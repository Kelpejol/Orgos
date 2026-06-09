# =============================================================================
# lifecycle/router.py — Document Lifecycle API
# Handles all five entry types: Manual, CDI Fix, Scheduled Review,
# Gap Remediation, NC Corrective Action.
# File upload/download wired to SharePoint via Graph API.
# =============================================================================

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from fastapi import (
    APIRouter, Depends, File, HTTPException,
    UploadFile, status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user
from agents.cdi_checker.service import run_cdi_check
from config import settings
from graph.auth import get_graph_access_token
from graph.client import (
    create_list_item,
    get_list_item,
    get_list_items,
    resolve_user,
    update_list_item,
)
from graph.exceptions import GraphAPIError, GraphNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/lifecycle", tags=["Document Lifecycle"])

_LIST_NAME  = "Document Lifecycle"
STAGE_ORDER = ["Review", "Sensitisation", "Approval"]
NEXT_STAGE  = {"Review": "Sensitisation", "Sensitisation": "Approval", "Approval": None}


def _get_list_id() -> str:
    return settings.document_lifecycle_list_id


def _handle_error(exc: Exception, context: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    else:
        logger.exception(f"Unexpected error: {context}")
        raise HTTPException(status_code=500, detail=f"Error: {context}")


def _days_since(dt_str: Optional[str]) -> int:
    if not dt_str:
        return 0
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return 0


def _field_text(value) -> str:
    """Return a displayable string from a SharePoint text/person field."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return (
            value.get("displayName")
            or value.get("DisplayName")
            or value.get("title")
            or value.get("Title")
            or ""
        ).strip()
    return str(value).strip()


async def _resolve_display_name(entra_oid: str, fallback: str = "") -> str:
    """Resolve an Entra ID object ID into a display name for SharePoint text fields."""
    fallback = _field_text(fallback)
    if not entra_oid:
        return fallback
    try:
        resolved = await resolve_user(entra_oid)
        return _field_text(resolved.get("display_name")) or fallback
    except Exception as exc:
        logger.warning(f"Could not resolve display name for Entra ID {entra_oid}: {exc}")
        return fallback


async def _write_owner_text_field(item_id: str, owner_oid: str, fallback: str = "") -> str:
    """
    Resolve OwnerEntraId and populate SharePoint's Owner text field.
    OwnerEntraId remains the stable ID; Owner is the human-readable name.
    """
    owner_name = await _resolve_display_name(owner_oid, fallback)
    if owner_name and item_id and settings.is_list_configured(_get_list_id()):
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, {"Owner": owner_name})
    return owner_name


async def _sp_to_doc(item: dict) -> dict:
    """Convert a SharePoint list item into a clean lifecycle document dict.

    Resolves OwnerEntraId → display name via Graph API (cached) when the
    Owner text column is blank — covers records created before the name was
    written, and records created via the OID-only path.
    """
    f = item.get("fields", {})

    item_id   = str(item.get("id", ""))
    list_id   = _get_list_id()
    writeback: dict = {}   # collected fields to write back when SP columns are empty

    # Owner — prefer stored name, fall back to OID resolution, write back if empty
    owner_name = _field_text(f.get("Owner"))
    owner_oid  = f.get("OwnerEntraId", "")
    if not owner_name and owner_oid:
        owner_name = await _resolve_display_name(owner_oid)
        if owner_name:
            try:
                await _write_owner_text_field(item_id, owner_oid, owner_name)
            except Exception as exc:
                logger.warning(
                    f"Could not backfill lifecycle Owner text field for item {item_id}: {exc}"
                )

    # Approver — same pattern
    approver_name = _field_text(f.get("Approver"))
    approver_oid  = f.get("ApproverEntraId", "")
    if not approver_name and approver_oid:
        approver_name = await _resolve_display_name(approver_oid)
        if approver_name:
            writeback["Approver"] = approver_name

    # Write back resolved approver names so SharePoint columns are not left empty.
    # Owner is a Person/Group field and is handled separately above.
    if writeback and item_id and settings.is_list_configured(list_id):
        try:
            await update_list_item(list_id, _LIST_NAME, item_id, writeback)
        except Exception as exc:
            logger.warning(
                f"Could not backfill lifecycle owner/approver names for item {item_id}: {exc}"
            )

    # Parse stakeholders (JSON array in multi-line text column)
    stakeholders: list[dict] = []
    raw_stakeholders = f.get("Stakeholders", "")
    if raw_stakeholders:
        try:
            stakeholders = json.loads(raw_stakeholders)
            if not isinstance(stakeholders, list):
                stakeholders = []
        except Exception:
            stakeholders = []

    return {
        "id":               item_id,
        "Title":            f.get("Title", ""),
        "DocumentCode":     f.get("DocumentCode", ""),
        "DocumentType":     f.get("DocumentType", ""),
        "Department":       f.get("Department", ""),
        "Stage":            f.get("Stage", "Review"),
        "Trigger":          f.get("Trigger", "Manual"),
        "AIGenerated":      f.get("AIGenerated", False),
        "CDIStatus":        f.get("CDIStatus", "Pending"),
        "Revised":          f.get("Revised", False),
        "DaysInStage":      _days_since(item.get("lastModifiedDateTime")),
        "OwnerEntraId":     owner_oid,
        "OwnerName":        owner_name,
        "Notes":            f.get("Notes", ""),
        "ApprovalStatus":   f.get("ApprovalStatus", ""),
        "ApproverEntraId":  approver_oid,
        "ApproverName":     approver_name,
        "SubmittedForApproval": f.get("SubmittedForApproval", ""),
        "ApprovedDate":     f.get("ApprovedDate", ""),
        "RejectionReason":  f.get("RejectionReason", ""),
        "SharePointFileUrl":f.get("SharePointFileUrl", ""),
        "CDIFailures":      f.get("CDIFailures", ""),
        "LinkedGapId":      f.get("LinkedGapId", ""),
        "LinkedNCId":       f.get("LinkedNCId", ""),
        "StandardsMapping": f.get("StandardsMapping", ""),
        "LinkedDocumentRegisterItem": f.get("LinkedDocumentRegisterItem", ""),
        "SensitisationFeedback": f.get("SensitisationFeedback", ""),
        "Stakeholders":     stakeholders,
        "created":          item.get("createdDateTime", ""),
        "modified":         item.get("lastModifiedDateTime", ""),
    }


# =============================================================================
#  Request schemas
# =============================================================================

class CreateDoc(BaseModel):
    title:           str
    document_code:   Optional[str] = None
    document_type:   Optional[str] = None
    department:      Optional[str] = None
    trigger:         str = "Manual"
    ai_generated:    bool = False
    notes:           Optional[str] = None
    # CDI Fix — JSON string of specific failures, e.g. '[{"check":"CDI-10","detail":"..."}]'
    cdi_failures:    Optional[str] = None
    # Traceability
    linked_gap_id:   Optional[str] = None
    linked_nc_id:    Optional[str] = None
    standards_mapping: Optional[str] = None
    # For CDI Fix and Scheduled Review — carry the existing file URL
    sharepoint_file_url: Optional[str] = None


class ProgressDoc(BaseModel):
    current_stage:    str
    rejection_reason: Optional[str] = None
    # Review → Sensitisation: list of [{oid, name, email}, ...]
    stakeholders:     Optional[list[dict]] = None
    # Sensitisation → Approval
    approver_id:      Optional[str] = None
    approver_name:    Optional[str] = None


class ReassignDoc(BaseModel):
    owner_id:   str
    owner_name: Optional[str] = None


class ApproveDoc(BaseModel):
    notes: Optional[str] = None


# =============================================================================
#  Endpoints
# =============================================================================

@router.get("/documents")
async def list_docs(
    stage:   Optional[str] = None,
    trigger: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """List all lifecycle documents, optionally filtered by stage or trigger type."""
    try:
        items = await get_list_items(_get_list_id(), _LIST_NAME)
        # Resolve all owner names concurrently — resolve_user is cached so this is fast
        docs = list(await asyncio.gather(*[_sp_to_doc(i) for i in items]))

        if stage:
            docs = [d for d in docs if d["Stage"] == stage]
        if trigger:
            docs = [d for d in docs if d["Trigger"] == trigger]

        # Newest first — most recently created item at the top of each column
        docs.sort(key=lambda d: d.get("created", ""), reverse=True)
        return docs
    except Exception as exc:
        _handle_error(exc, "list lifecycle documents")


@router.get("/documents/{item_id}")
async def get_doc(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(item)
    except Exception as exc:
        _handle_error(exc, f"get lifecycle document {item_id}")


@router.post("/documents", status_code=201)
async def create_doc(
    body: CreateDoc,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Create a new lifecycle entry. All five trigger types are handled.
    CDI Fix entries carry the CDI failures so the card shows exactly what to fix.
    Gap Remediation and NC entries carry their source IDs for traceability.
    """
    owner_name = await _resolve_display_name(user.oid, user.name)

    fields: dict = {
        "Title":        body.title,
        "Stage":        "Review",
        "Trigger":      body.trigger,
        "AIGenerated":  body.ai_generated,
        "Revised":      False,
        "OwnerEntraId": user.oid,
        "Owner":        owner_name,
    }
    for attr, col in [
        ("document_code",       "DocumentCode"),
        ("document_type",       "DocumentType"),
        ("department",          "Department"),
        ("notes",               "Notes"),
        ("cdi_failures",        "CDIFailures"),
        ("linked_gap_id",       "LinkedGapId"),
        ("linked_nc_id",        "LinkedNCId"),
        ("standards_mapping",   "StandardsMapping"),
        ("sharepoint_file_url", "SharePointFileUrl"),
    ]:
        val = getattr(body, attr)
        if val:
            fields[col] = val

    try:
        item = await create_list_item(_get_list_id(), _LIST_NAME, fields)
        item_id = str(item.get("id", ""))
        if item_id:
            try:
                await _write_owner_text_field(item_id, user.oid, owner_name)
            except Exception as exc:
                logger.warning(
                    f"Lifecycle item {item_id} created, but Owner text field "
                    f"could not be populated: {exc}"
                )
            item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(item)
    except Exception as exc:
        _handle_error(exc, "create lifecycle document")


@router.patch("/documents/{item_id}/progress")
async def progress_doc(
    item_id: str,
    body: ProgressDoc,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Advance a document to the next stage with stage-specific validation.
      Review → Sensitisation: requires at least one stakeholder + uploaded file.
      Sensitisation → Approval: requires an approver.
      Approval: blocked — use POST /approve to complete.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if doc["Stage"] != body.current_stage:
            raise HTTPException(
                status_code=409,
                detail=(f"Stage mismatch: document is in '{doc['Stage']}', "
                        f"not '{body.current_stage}'."),
            )

        if body.current_stage == "Review":
            if not doc.get("Revised"):
                raise HTTPException(
                    status_code=422,
                    detail="Upload a revised version before progressing from Review.",
                )
            if not body.stakeholders:
                raise HTTPException(
                    status_code=422,
                    detail="At least one stakeholder must be selected before progressing to Sensitisation.",
                )

        if body.current_stage == "Sensitisation":
            if not body.approver_id:
                raise HTTPException(
                    status_code=422,
                    detail="An approver must be selected before progressing to Approval.",
                )

        next_stage = NEXT_STAGE.get(body.current_stage)
        if not next_stage:
            raise HTTPException(
                status_code=422,
                detail="Document is in Approval stage — use the Approve action to complete.",
            )

        fields: dict = {"Stage": next_stage}

        if body.current_stage == "Review" and body.stakeholders:
            fields["Stakeholders"] = json.dumps(body.stakeholders)

        if body.current_stage == "Sensitisation":
            approver_name = await _resolve_display_name(
                body.approver_id,
                body.approver_name or "",
            )
            fields["SubmittedForApproval"] = date.today().isoformat()
            fields["ApprovalStatus"]       = "Pending"
            fields["ApproverEntraId"]      = body.approver_id
            if approver_name:
                fields["Approver"] = approver_name

        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"progress document {item_id}")


@router.post("/documents/{item_id}/approve")
async def approve_doc(
    item_id: str,
    body: ApproveDoc,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Mark a document as Approved and create a Document Register entry.
    Only valid when the document is in Approval stage.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if doc["Stage"] != "Approval":
            raise HTTPException(
                status_code=422,
                detail=f"Document must be in Approval stage to approve (currently '{doc['Stage']}').",
            )

        # Mark approved
        approver_name = await _resolve_display_name(user.oid, user.name)

        fields: dict = {
            "ApprovalStatus": "Approved",
            "ApprovedDate":   date.today().isoformat(),
            "ApproverEntraId": user.oid,
            "Approver":        approver_name,
        }
        if body.notes:
            fields["Notes"] = (doc.get("Notes") or "") + f"\n\nApproval note: {body.notes}"

        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)

        # Create Document Register entry
        if settings.is_list_configured(settings.document_register_list_id):
            dr_fields: dict = {
                "Title":              doc["Title"],
                "DocumentCode":       doc["DocumentCode"],
                "DocumentType":       doc["DocumentType"],
                "Department":         doc["Department"],
                "Status":             "Active",
                "OwnerEntraId":       doc["OwnerEntraId"],
                "Owner":              doc["OwnerName"],
                "EffectiveDate":      date.today().isoformat(),
                "ApplicableStandards": doc["StandardsMapping"],
                "Source":             "Document Lifecycle",
            }
            if doc["SharePointFileUrl"]:
                dr_fields["SharePointUrl"] = doc["SharePointFileUrl"]
            try:
                await create_list_item(
                    settings.document_register_list_id,
                    "Document Register",
                    dr_fields,
                )
                logger.info(
                    f"Document Register entry created for approved lifecycle "
                    f"{item_id}: {doc['DocumentCode']}"
                )
            except Exception as exc:
                logger.warning(
                    f"Lifecycle {item_id} approved but Document Register write failed: {exc}"
                )

        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"approve document {item_id}")


@router.patch("/documents/{item_id}/reassign")
async def reassign_doc(
    item_id: str,
    body: ReassignDoc,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        owner_name = await _resolve_display_name(body.owner_id, body.owner_name or "")
        fields: dict = {"OwnerEntraId": body.owner_id}
        if owner_name:
            fields["Owner"] = owner_name
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        try:
            await _write_owner_text_field(item_id, body.owner_id, owner_name)
        except Exception as exc:
            logger.warning(
                f"Lifecycle item {item_id} reassigned, but Owner text field "
                f"could not be populated: {exc}"
            )
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)
    except Exception as exc:
        _handle_error(exc, f"reassign document {item_id}")


@router.post("/documents/{item_id}/upload")
async def upload_doc_file(
    item_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Upload a revised document to SharePoint, link it to the lifecycle item,
    set Revised=True, then automatically run the CDI Checker.
    If CDI passes: sets CDIStatus=Passed, Progress button unlocks.
    If CDI fails: sets CDIStatus=Failed, CDIFailures populated,
                  Progress button stays locked.
    """
    file_bytes = await file.read()
    filename   = file.filename or f"document_{item_id}.docx"

    # Upload to SharePoint
    try:
        file_url = await _upload_to_sharepoint(item_id, filename, file_bytes)
    except Exception as exc:
        logger.exception(f"SharePoint upload failed for lifecycle {item_id}")
        raise HTTPException(status_code=503, detail=f"SharePoint upload failed: {exc}")

    # Run CDI check automatically.
    # Each fetch is wrapped independently so a misconfigured list ID or network
    # blip on a supporting call never blocks the check from running.
    cdi_status   = "Pending"
    cdi_failures = ""
    try:
        # Role titles for CDI-07/16 — gracefully skip if list not configured yet
        try:
            role_items  = await get_list_items(settings.role_register_list_id, "Role Register")
            role_titles = [
                i.get("fields", {}).get("Title", "")
                for i in role_items
                if i.get("fields", {}).get("Title")
            ]
        except Exception as exc:
            logger.debug(f"Role Register unavailable for CDI check ({exc}); proceeding without role validation")
            role_titles = []

        # Doc code for CDI-01 — gracefully fall back to empty string
        try:
            item_data = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
            doc_code  = item_data.get("fields", {}).get("DocumentCode", "")
        except Exception:
            doc_code = ""

        cdi_result = await run_cdi_check(file_bytes, filename, doc_code, role_titles)

        if cdi_result.get("error"):
            cdi_status   = "Error"
            # Store the reason in CDIFailures so it surfaces in the UI
            cdi_failures = json.dumps([{
                "check":  "CDI",
                "detail": cdi_result["error"],
                "fix":    "Resolve the issue above, then re-upload the document.",
            }])
            logger.warning(f"CDI check error for lifecycle {item_id}: {cdi_result['error']}")
        elif cdi_result["passed"]:
            cdi_status   = "Passed"
            cdi_failures = ""          # clear any failures from a previous upload
        else:
            cdi_status   = "Failed"
            cdi_failures = json.dumps([
                {
                    "check":  c["check_id"],
                    "detail": c["finding"],
                    "fix":    c.get("proposed_fix", ""),
                }
                for c in cdi_result["checks"] if c["result"] == "FAIL"
            ])
        logger.info(
            f"CDI check for lifecycle {item_id}: "
            f"{cdi_status} — {cdi_result.get('fail_count', 0)} failures"
        )
    except Exception as exc:
        logger.warning(f"CDI check failed to run for {item_id}: {exc}")
        cdi_status   = "Error"
        cdi_failures = ""

    # Update lifecycle item — always write CDIFailures so stale failures from a
    # previous upload are cleared when the re-upload passes CDI.
    fields: dict = {
        "SharePointFileUrl": file_url,
        "Revised":           True,
        "CDIStatus":         cdi_status,
        "CDIFailures":       cdi_failures,   # empty string clears old failures on pass
    }

    try:
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)
    except Exception as exc:
        _handle_error(exc, f"update lifecycle item after upload {item_id}")


@router.get("/documents/{item_id}/download")
async def download_doc_file(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Redirect the client to the SharePoint file URL for direct download.
    Returns 404 if no file has been uploaded yet.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)
        url  = doc.get("SharePointFileUrl")
        if not url:
            raise HTTPException(
                status_code=404,
                detail="No file has been uploaded for this lifecycle item yet.",
            )
        return RedirectResponse(url=url, status_code=302)
    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"download lifecycle document {item_id}")


# =============================================================================
#  SharePoint file upload
# =============================================================================

class FeedbackBody(BaseModel):
    feedback: str  # JSON string of feedback items array


@router.patch("/documents/{item_id}/feedback")
async def update_feedback(
    item_id: str,
    body: FeedbackBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Append sensitisation feedback to a lifecycle document.
    Feedback is stored as a JSON array in the SensitisationFeedback field.
    Any team member can submit feedback during the Sensitisation stage.
    """
    try:
        await update_list_item(
            _get_list_id(), _LIST_NAME, item_id,
            {"SensitisationFeedback": body.feedback},
        )
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)
    except Exception as exc:
        _handle_error(exc, f"update feedback {item_id}")


async def _upload_to_sharepoint(
    item_id: str, filename: str, file_bytes: bytes
) -> str:
    """
    Upload a file to the OrgOs SharePoint site using the Graph API simple upload.
    Path: /Lifecycle Documents/{item_id}/{filename}
    Returns the webUrl of the uploaded file.
    Simple upload supports files up to 4MB. Chunked upload needed beyond that.
    """
    token   = await get_graph_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/octet-stream",
    }
    base    = settings.graph_base_url
    site_id = settings.sharepoint_site_id

    # Store under the default Documents drive in a Lifecycle Documents folder
    upload_path = f"Lifecycle Documents/{item_id}/{filename}"
    upload_url  = f"{base}/sites/{site_id}/drive/root:/{upload_path}:/content"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.put(upload_url, headers=headers, content=file_bytes)
        resp.raise_for_status()

    web_url = resp.json().get("webUrl", "")
    logger.info(f"Uploaded '{filename}' for lifecycle {item_id} → {web_url}")
    return web_url
