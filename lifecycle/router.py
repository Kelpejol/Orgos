# =============================================================================
# lifecycle/router.py — Document Lifecycle API
# Handles all five entry types: Manual, CDI Fix, Scheduled Review,
# Gap Remediation, NC Corrective Action.
# File upload/download wired to SharePoint via Graph API.
# =============================================================================

import asyncio
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


async def _sp_to_doc(item: dict) -> dict:
    """Convert a SharePoint list item into a clean lifecycle document dict.

    Resolves OwnerEntraId → display name via Graph API (cached) when the
    Owner text column is blank — covers records created before the name was
    written, and records created via the OID-only path.
    """
    f = item.get("fields", {})

    # Owner — prefer stored name, fall back to OID resolution
    owner_name = (f.get("Owner") or "").strip()
    owner_oid  = f.get("OwnerEntraId", "")
    if not owner_name and owner_oid:
        try:
            u = await resolve_user(owner_oid)
            owner_name = u.get("display_name", "")
        except Exception:
            pass

    # Approver — same pattern
    approver_name = (f.get("Approver") or "").strip()
    approver_oid  = f.get("ApproverEntraId", "")
    if not approver_name and approver_oid:
        try:
            u = await resolve_user(approver_oid)
            approver_name = u.get("display_name", "")
        except Exception:
            pass

    return {
        "id":               str(item["id"]),
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


class ReassignDoc(BaseModel):
    owner_id:   str
    owner_name: Optional[str] = None


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
    fields: dict = {
        "Title":        body.title,
        "Stage":        "Review",
        "Trigger":      body.trigger,
        "AIGenerated":  body.ai_generated,
        "Revised":      False,
        "OwnerEntraId": user.oid,
        "Owner":        user.name,  # store display name so reads don't need OID resolution
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
    Advance a document to the next stage.
    Blocks progression from Review if no file has been uploaded (Revised = False).
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

        next_stage = NEXT_STAGE.get(body.current_stage)
        if not next_stage:
            raise HTTPException(
                status_code=422,
                detail="Document is in Approval stage. Use the Teams approval flow to complete.",
            )

        fields: dict = {"Stage": next_stage}
        if next_stage == "Approval":
            fields["SubmittedForApproval"] = date.today().isoformat()
            fields["ApprovalStatus"]       = "Pending"

        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"progress document {item_id}")


@router.patch("/documents/{item_id}/reassign")
async def reassign_doc(
    item_id: str,
    body: ReassignDoc,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        fields: dict = {"OwnerEntraId": body.owner_id}
        if body.owner_name:
            fields["Owner"] = body.owner_name
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
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

    # Run CDI check automatically
    cdi_status   = "Pending"
    cdi_failures = ""
    try:
        from agents.cdi_checker.service import run_cdi_check
        from graph.client import get_list_items
        # Fetch role titles for CDI-07 check
        role_items  = await get_list_items(
            settings.role_register_list_id, "Role Register"
        )
        role_titles = [
            i.get("fields", {}).get("Title", "")
            for i in role_items
            if i.get("fields", {}).get("Title")
        ]
        item_data = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc_code  = item_data.get("fields", {}).get("DocumentCode", "")
        cdi_result = await run_cdi_check(file_bytes, filename, doc_code, role_titles)

        if cdi_result.get("error"):
            cdi_status = "Error"
        elif cdi_result["passed"]:
            cdi_status   = "Passed"
            cdi_failures = ""
        else:
            import json
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
        cdi_status = "Error"

    # Update lifecycle item
    fields: dict = {
        "SharePointFileUrl": file_url,
        "Revised":           True,
        "CDIStatus":         cdi_status,
    }
    if cdi_failures:
        fields["CDIFailures"] = cdi_failures

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