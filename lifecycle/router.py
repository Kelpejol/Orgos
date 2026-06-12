# =============================================================================
# lifecycle/router.py — Document Lifecycle API
# Handles all five entry types: Manual, CDI Fix, Scheduled Review,
# Gap Remediation, NC Corrective Action, Harmonisation Fix.
# File upload/download wired to SharePoint via Graph API.
# =============================================================================

import asyncio
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx
from fastapi import (
    APIRouter, Depends, File, HTTPException,
    UploadFile, status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user
from agents.cdi_checker.service import DOC_CODE_PATTERN, run_cdi_check
from agents.extractor.service import run_extraction_from_file
from config import settings
from graph.auth import get_graph_access_token
from graph.client import (
    create_list_item,
    download_file_from_sharepoint,
    get_list_item,
    get_list_items,
    resolve_sp_user_lookup_id,
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
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return (
            value.get("displayName")
            or value.get("DisplayName")
            or value.get("LookupValue")    # Person/Group field from Graph API
            or value.get("lookupValue")
            or value.get("title")
            or value.get("Title")
            or ""
        ).strip()
    return str(value).strip()


def _filename_from_sharepoint_url(url: str, content_type: str = "") -> str:
    """Best-effort filename for extraction based on SharePoint URL/content type."""
    path_name = unquote(urlparse(url or "").path.rsplit("/", 1)[-1])
    if "." in path_name:
        return path_name
    if "pdf" in (content_type or "").lower():
        return f"{path_name or 'document'}.pdf"
    if "text" in (content_type or "").lower():
        return f"{path_name or 'document'}.txt"
    return f"{path_name or 'document'}.docx"


def _extractor_type_for_lifecycle(document_type: str) -> Optional[str]:
    """
    Map lifecycle/register document types to extractor document types.
    Procedure/SOP/Guidelines are controlled-document sources, so extract them
    with the policy control extractor. Forms do not usually contain controls.
    """
    normalized = (document_type or "").strip().lower()
    if normalized in {"policy", "procedure", "sop", "guidelines"}:
        return "Policy"
    return None


async def _extract_approved_document_to_review_queue(doc: dict) -> dict:
    """Run the approved document into the AI Review Queue extraction pipeline."""
    file_url = doc.get("SharePointFileUrl")
    doc_code = doc.get("DocumentCode")
    if not file_url or not doc_code:
        return {
            "started": False,
            "written_to_sharepoint": False,
            "reason": "Missing SharePointFileUrl or DocumentCode.",
        }

    extractor_type = _extractor_type_for_lifecycle(doc.get("DocumentType", ""))
    if not extractor_type:
        return {
            "started": False,
            "written_to_sharepoint": False,
            "reason": f"Document type '{doc.get('DocumentType', '')}' is not an extraction target.",
        }

    file_bytes, content_type = await download_file_from_sharepoint(file_url)
    filename = _filename_from_sharepoint_url(file_url, content_type)
    result = await run_extraction_from_file(
        file_bytes=file_bytes,
        filename=filename,
        doc_code=doc_code,
        write_to_sharepoint=True,
        folder_path=doc.get("Department", ""),
        web_url=file_url,
        document_type_override=extractor_type,
    )

    return {
        "started": True,
        "document_type": result.document_type,
        "total_extracted": result.total_extracted,
        "written_to_sharepoint": result.written_to_sharepoint,
        "skipped_reason": result.skipped_reason,
    }


async def _resolve_display_name(entra_oid: str, fallback: str = "") -> str:
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
    owner_name = await _resolve_display_name(owner_oid, fallback)
    if owner_name and item_id and settings.is_list_configured(_get_list_id()):
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, {"Owner": owner_name})
    return owner_name


async def _sp_to_doc(item: dict) -> dict:
    """Convert a SharePoint list item into a clean lifecycle document dict."""
    f = item.get("fields", {})

    item_id   = str(item.get("id", ""))
    list_id   = _get_list_id()
    writeback: dict = {}

    # Owner
    owner_name = _field_text(f.get("Owner"))
    owner_oid  = f.get("OwnerEntraId", "")
    if not owner_name and owner_oid:
        owner_name = await _resolve_display_name(owner_oid)
        if owner_name:
            try:
                await _write_owner_text_field(item_id, owner_oid, owner_name)
            except Exception as exc:
                logger.warning(f"Could not backfill lifecycle Owner text field for item {item_id}: {exc}")

    # Approver
    approver_name = _field_text(f.get("Approver"))
    approver_oid  = f.get("ApproverEntraId", "")
    if not approver_name and approver_oid:
        approver_name = await _resolve_display_name(approver_oid)
        if approver_name:
            writeback["Approver"] = approver_name

    if writeback and item_id and settings.is_list_configured(list_id):
        try:
            await update_list_item(list_id, _LIST_NAME, item_id, writeback)
        except Exception as exc:
            logger.warning(f"Could not backfill lifecycle owner/approver names for item {item_id}: {exc}")

    # Parse stakeholders JSON
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
        "id":                       item_id,
        "Title":                    f.get("Title", ""),
        "DocumentCode":             f.get("DocumentCode", ""),
        "DocumentType":             f.get("DocumentType", ""),
        "Department":               f.get("Department", ""),
        "Stage":                    f.get("Stage", "Review"),
        "Trigger":                  f.get("Trigger", "Manual"),
        "AIGenerated":              f.get("AIGenerated", False),
        "CDIStatus":                f.get("CDIStatus", "Pending"),
        "Revised":                  f.get("Revised", False),
        "DaysInStage":              _days_since(item.get("lastModifiedDateTime")),
        "OwnerEntraId":             owner_oid,
        "OwnerName":                owner_name,
        "Notes":                    f.get("Notes", ""),
        "ApprovalStatus":           f.get("ApprovalStatus", ""),
        "ApproverEntraId":          approver_oid,
        "ApproverName":             approver_name,
        "SubmittedForApproval":     f.get("SubmittedForApproval", ""),
        "ApprovedDate":             f.get("ApprovedDate", ""),
        "RejectionReason":          f.get("RejectionReason", ""),
        "RejectionCount":           int(f.get("RejectionCount", 0) or 0),
        "SharePointFileUrl":        f.get("SharePointFileUrl", ""),
        "CDIFailures":              f.get("CDIFailures", ""),
        "LinkedGapId":              f.get("LinkedGapId", ""),
        "LinkedNCId":               f.get("LinkedNCId", ""),
        "StandardsMapping":         f.get("StandardsMapping", ""),
        "LinkedDocumentRegisterItem": f.get("LinkedDocumentRegisterItem", ""),
        "SensitisationFeedback":    f.get("SensitisationFeedback", ""),
        "SensitisationDeadline":    f.get("SensitisationDeadline", ""),
        "StakeholderResponseCount": int(f.get("StakeholderResponseCount", 0) or 0),
        "Stakeholders":             stakeholders,
        "created":                  item.get("createdDateTime", ""),
        "modified":                 item.get("lastModifiedDateTime", ""),
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
    cdi_failures:    Optional[str] = None
    linked_gap_id:   Optional[str] = None
    linked_nc_id:    Optional[str] = None
    standards_mapping: Optional[str] = None
    sharepoint_file_url: Optional[str] = None


class ProgressDoc(BaseModel):
    current_stage:    str
    skip_stakeholders: Optional[bool] = False   # Review → Sensitisation without stakeholders
    skip_approver:     Optional[bool] = False   # Sensitisation → Approval without approver
    rejection_reason: Optional[str] = None
    # Review → Sensitisation
    stakeholders:        Optional[list[dict]] = None
    sensitisation_deadline: Optional[str] = None   # ISO date string "YYYY-MM-DD"
    # Sensitisation → Approval
    approver_id:      Optional[str] = None
    approver_name:    Optional[str] = None
    approver_email:   Optional[str] = None   # UPN — required to write the Person/Group column


class ReassignDoc(BaseModel):
    owner_id:   str
    owner_name: Optional[str] = None


class ApproveDoc(BaseModel):
    notes: Optional[str] = None


class RejectDoc(BaseModel):
    rejection_reason: str


class ExtendDeadlineBody(BaseModel):
    new_deadline: str   # ISO date string "YYYY-MM-DD"


class FeedbackSubmitBody(BaseModel):
    text:     str
    category: str = "General"   # Concern | Suggestion | Factual error | Approval | General


class FeedbackBody(BaseModel):
    feedback: str


# =============================================================================
#  Ollama helper for lifecycle AI features
# =============================================================================

async def _ollama_generate(prompt: str) -> str:
    """Generic Ollama text generation. Returns empty string on failure."""
    try:
        payload = {
            "model":   settings.ollama_model,
            "prompt":  prompt,
            "stream":  False,
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.warning(f"Ollama generate failed: {exc}")
        return ""


def _extract_json_payload(text: str):
    """Parse model JSON even when wrapped in fences or short explanatory text."""
    if not text:
        return None

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    candidates = [cleaned]
    array_match = re.search(r"\[[\s\S]*\]", cleaned)
    if array_match:
        candidates.append(array_match.group(0))
    object_match = re.search(r"\{[\s\S]*\}", cleaned)
    if object_match:
        candidates.append(object_match.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _normalise_cdi_suggestions(payload, fallback_text: str = "") -> list[dict]:
    """Return UI-safe {check, finding, suggestion} rows from model output."""
    if isinstance(payload, dict):
        for key in ("suggestions", "fixes", "items", "data"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]

    if isinstance(payload, str):
        nested = _extract_json_payload(payload)
        if nested is not None and nested != payload:
            return _normalise_cdi_suggestions(nested, fallback_text)
        return [{"check": "General", "finding": "See AI suggestion", "suggestion": payload}]

    if not isinstance(payload, list):
        return [{"check": "General", "finding": "See AI suggestion", "suggestion": fallback_text}] if fallback_text else []

    rows: list[dict] = []
    for item in payload:
        if isinstance(item, str):
            nested = _extract_json_payload(item)
            if nested is not None and nested != item:
                rows.extend(_normalise_cdi_suggestions(nested))
            elif item.strip():
                rows.append({"check": "General", "finding": "See AI suggestion", "suggestion": item.strip()})
            continue
        if not isinstance(item, dict):
            continue

        suggestion = item.get("suggestion") or item.get("fix") or item.get("proposed_fix") or item.get("action") or ""
        if isinstance(suggestion, (list, dict)):
            nested_rows = _normalise_cdi_suggestions(suggestion)
            if nested_rows:
                rows.extend(nested_rows)
                continue
            suggestion = json.dumps(suggestion)

        rows.append({
            "check": str(item.get("check") or item.get("check_id") or item.get("id") or "CDI").strip(),
            "finding": str(item.get("finding") or item.get("detail") or item.get("problem") or "").strip(),
            "suggestion": str(suggestion).strip(),
        })

    return [row for row in rows if row.get("finding") or row.get("suggestion")]


async def _get_document_text(doc: dict) -> str:
    """Download the lifecycle document from SharePoint and extract its text."""
    url = doc.get("SharePointFileUrl")
    if not url:
        return ""
    try:
        from agents.extractor.service import extract_text_from_docx, extract_text_from_pdf
        from graph.client import download_file_from_sharepoint
        file_bytes, filename = await download_file_from_sharepoint(url)
        name = (filename or "").lower()
        if name.endswith(".pdf"):
            return extract_text_from_pdf(file_bytes)
        return extract_text_from_docx(file_bytes)
    except Exception as exc:
        logger.warning(f"Could not extract document text from SharePoint: {exc}")
        return ""


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
        docs  = list(await asyncio.gather(*[_sp_to_doc(i) for i in items]))

        if stage:
            docs = [d for d in docs if d["Stage"] == stage]
        if trigger:
            docs = [d for d in docs if d["Trigger"] == trigger]

        docs.sort(
            key=lambda d: (
                d.get("modified") or d.get("created") or "",
                int(d.get("id") or 0) if str(d.get("id") or "").isdigit() else 0,
            ),
            reverse=True,
        )
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
    owner_name = await _resolve_display_name(user.oid, user.name)

    fields: dict = {
        "Title":        body.title,
        "Stage":        "Review",
        "Trigger":      body.trigger,
        "AIGenerated":  body.ai_generated,
        "Revised":      False,
        "OwnerEntraId": user.oid,
        "Owner":        owner_name,
        "RejectionCount": 0,
        "StakeholderResponseCount": 0,
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
                logger.warning(f"Lifecycle item {item_id} created, but Owner text field could not be populated: {exc}")
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
      Review → Sensitisation: requires at least one stakeholder + uploaded file + CDI pass.
      Sensitisation → Approval: requires a named approver who is not the document owner.
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
            has_file = doc.get("Revised") or doc.get("SharePointFileUrl")
            if not has_file:
                raise HTTPException(
                    status_code=422,
                    detail="Upload a file before progressing from Review.",
                )
            # CDI gate temporarily disabled: keep CDI results visible, but do not
            # block Review -> Sensitisation while onboarding legacy documents.
            # if doc.get("CDIStatus") == "Failed":
            #     raise HTTPException(
            #         status_code=422,
            #         detail="CDI check failed — fix the listed failures and re-upload before progressing.",
            #     )
            if not body.stakeholders and not body.skip_stakeholders:
                raise HTTPException(
                    status_code=422,
                    detail="Add at least one stakeholder or skip stakeholders to progress to Sensitisation.",
                )

        if body.current_stage == "Sensitisation":
            if not body.approver_id and not body.skip_approver:
                raise HTTPException(
                    status_code=422,
                    detail="Select an approver or skip to progress to Approval.",
                )
            # TODO: re-enable once role separation is enforced in production
            # if body.approver_id == doc.get("OwnerEntraId"):
            #     raise HTTPException(
            #         status_code=422,
            #         detail="The approver cannot be the same person as the document owner.",
            #     )

        next_stage = NEXT_STAGE.get(body.current_stage)
        if not next_stage:
            raise HTTPException(
                status_code=422,
                detail="Document is in Approval stage — use the Approve action to complete.",
            )

        fields: dict = {"Stage": next_stage}

        if body.current_stage == "Review" and body.stakeholders:
            fields["Stakeholders"] = json.dumps(body.stakeholders)
            if body.sensitisation_deadline:
                fields["SensitisationDeadline"] = body.sensitisation_deadline

        _approver_email_pg: str = ""   # saved for best-effort Person/Group write below
        if body.current_stage == "Sensitisation":
            fields["SubmittedForApproval"] = date.today().isoformat()
            fields["ApprovalStatus"]       = "Pending"
            fields["ApproverEntraId"]      = body.approver_id   # text column — OID
            _approver_email_pg = (body.approver_email or "").strip()

        # ── Critical write — text columns always succeed ───────────────────────
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)

        # ── Best-effort: write the Person/Group column in a separate PATCH ─────
        # Person/Group columns require the SP site user lookup ID (integer), not
        # a string. A failed lookup must NOT contaminate the critical write above.
        if _approver_email_pg:
            try:
                sp_uid = await resolve_sp_user_lookup_id(_approver_email_pg)
                if sp_uid is not None:
                    await update_list_item(
                        _get_list_id(), _LIST_NAME, item_id, {"ApproverLookupId": sp_uid}
                    )
            except Exception as exc:
                logger.warning(f"Could not set Approver Person/Group column for item {item_id}: {exc}")
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"progress document {item_id}")


@router.patch("/documents/{item_id}/claim")
async def claim_doc(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Claim an unowned lifecycle document — sets the current user as the owner."""
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)
        if doc.get("OwnerEntraId"):
            raise HTTPException(status_code=409, detail="Document already has an owner.")
        owner_name = await _resolve_display_name(user.oid, user.name)
        fields = {"OwnerEntraId": user.oid, "Owner": owner_name}
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"claim lifecycle document {item_id}")


@router.post("/documents/{item_id}/approve")
async def approve_doc(
    item_id: str,
    body: ApproveDoc,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Mark a document as Approved and create a Document Register entry.
    Only the designated approver may call this. Owner cannot approve their own document.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if doc["Stage"] != "Approval":
            raise HTTPException(
                status_code=422,
                detail=f"Document must be in Approval stage to approve (currently '{doc['Stage']}').",
            )
        if doc.get("ApprovalStatus") == "Approved" and doc.get("LinkedDocumentRegisterItem"):
            raise HTTPException(
                status_code=409,
                detail="Document is already approved and linked to the Document Register.",
            )

        # Enforce: only the designated approver can approve
        approver_oid = doc.get("ApproverEntraId", "")
        if approver_oid and user.oid != approver_oid:
            raise HTTPException(
                status_code=403,
                detail="Only the designated approver can approve this document.",
            )

        # TODO: re-enable once role separation is enforced in production
        # Enforce: owner cannot approve their own document
        # if user.oid == doc.get("OwnerEntraId", ""):
        #     raise HTTPException(
        #         status_code=403,
        #         detail="The document owner cannot approve their own document.",
        #     )

        approver_resolved  = await resolve_user(user.oid)
        approver_email_val = approver_resolved.get("email", "")

        if not settings.is_list_configured(settings.document_register_list_id):
            raise HTTPException(
                status_code=503,
                detail="Document Register list is not configured; approval cannot publish this document.",
            )

        effective_date = date.today()
        if not DOC_CODE_PATTERN.match(str(doc.get("DocumentCode", "")).strip().upper()):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Document code '{doc.get('DocumentCode', '')}' is invalid. "
                    "Fix the document code before approving/publishing."
                ),
            )

        dr_fields: dict = {
            "Title":               doc["Title"],
            "DocumentCode":        doc["DocumentCode"],
            "DocumentType":        doc["DocumentType"],
            "Department":          doc["Department"],
            "Status":              "Active",
            "OwnerId":             doc.get("OwnerEntraId", ""),
            "Owner":               doc.get("OwnerName", ""),
            "CurrentVersion":      "R01",
            "EffectiveDate":       effective_date.isoformat(),
            "ApplicableStandards": doc.get("StandardsMapping", ""),
            "LinkedControlsCount": 0,
        }
        if doc.get("SensitisationDeadline"):
            dr_fields["NextReviewDate"] = doc["SensitisationDeadline"]

        try:
            register_item = await create_list_item(
                settings.document_register_list_id,
                "Document Register",
                dr_fields,
            )
        except Exception as exc:
            logger.exception(f"Lifecycle {item_id} approval could not publish Document Register entry")
            raise HTTPException(
                status_code=502,
                detail=f"Document approval failed: could not create Document Register entry ({exc}).",
            )

        register_item_id = str(register_item.get("id", ""))
        logger.info(
            f"Document Register entry {register_item_id} created for approved lifecycle "
            f"{item_id}: {doc['DocumentCode']}"
        )

        # Optional trace fields. Some deployed registers may have these columns;
        # the provisioned baseline may not, so do not let this block approval.
        optional_dr_fields: dict = {}
        if doc.get("SharePointFileUrl"):
            optional_dr_fields["SharePointUrl"] = doc["SharePointFileUrl"]
        optional_dr_fields["Source"] = "Document Lifecycle"
        if optional_dr_fields and register_item_id:
            try:
                await update_list_item(
                    settings.document_register_list_id,
                    "Document Register",
                    register_item_id,
                    optional_dr_fields,
                )
            except Exception as exc:
                logger.warning(f"Document Register optional trace fields were not written: {exc}")

        fields: dict = {
            "ApprovalStatus":             "Approved",
            "ApprovedDate":               effective_date.isoformat(),
            "ApproverEntraId":            user.oid,
            "LinkedDocumentRegisterItem": register_item_id,
        }
        if body.notes:
            fields["Notes"] = (doc.get("Notes") or "") + f"\n\nApproval note: {body.notes}"

        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)

        # ── Best-effort: Person/Group column in a separate PATCH ──────────────
        if approver_email_val:
            try:
                sp_uid = await resolve_sp_user_lookup_id(approver_email_val)
                if sp_uid is not None:
                    await update_list_item(
                        _get_list_id(), _LIST_NAME, item_id, {"ApproverLookupId": sp_uid}
                    )
            except Exception as exc:
                logger.warning(f"Could not set Approver Person/Group column on approve for item {item_id}: {exc}")

        extraction_result: dict = {}
        try:
            extraction_result = await _extract_approved_document_to_review_queue(doc)
            logger.info(
                f"Approved lifecycle {item_id} extraction result: {extraction_result}"
            )
            if register_item_id and extraction_result.get("total_extracted") is not None:
                try:
                    await update_list_item(
                        settings.document_register_list_id,
                        "Document Register",
                        register_item_id,
                        {"LinkedControlsCount": extraction_result.get("total_extracted", 0)},
                    )
                except Exception as exc:
                    logger.warning(f"Could not update Document Register extraction count: {exc}")
        except Exception as exc:
            logger.exception(f"Approved lifecycle {item_id} extraction failed")
            extraction_result = {
                "started": True,
                "written_to_sharepoint": False,
                "error": str(exc),
            }

        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        result = await _sp_to_doc(updated)
        result["DocumentRegisterItemId"] = register_item_id
        result["ExtractionResult"] = extraction_result
        return result

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"approve document {item_id}")


@router.post("/documents/{item_id}/reject")
async def reject_doc(
    item_id: str,
    body: RejectDoc,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Reject a document and return it to Review stage.
    Only the designated approver may reject. Rejection reason is mandatory (min 20 chars).
    Increments RejectionCount. Resets Revised = false so owner must re-upload.
    """
    if not body.rejection_reason or len(body.rejection_reason.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Rejection reason must be at least 20 characters.",
        )
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if doc["Stage"] != "Approval":
            raise HTTPException(
                status_code=422,
                detail=f"Document must be in Approval stage to reject (currently '{doc['Stage']}').",
            )

        # Enforce: only the designated approver can reject
        approver_oid = doc.get("ApproverEntraId", "")
        if approver_oid and user.oid != approver_oid:
            raise HTTPException(
                status_code=403,
                detail="Only the designated approver can reject this document.",
            )

        new_rejection_count = doc.get("RejectionCount", 0) + 1

        fields: dict = {
            "Stage":           "Review",
            "ApprovalStatus":  "Rejected",
            "RejectionReason": body.rejection_reason.strip(),
            "RejectionCount":  new_rejection_count,
            "Revised":         False,          # Owner must re-upload after addressing rejection
            "CDIStatus":       "Pending",      # Reset CDI so re-upload triggers fresh check
        }
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"reject document {item_id}")


@router.post("/documents/{item_id}/recall")
async def recall_doc(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Owner recalls a document from Approval back to Sensitisation.
    Only the document owner can recall (not the approver).
    Clears the approver so a new one must be selected when re-progressing.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if doc["Stage"] != "Approval":
            raise HTTPException(
                status_code=422,
                detail=f"Document must be in Approval stage to recall (currently '{doc['Stage']}').",
            )

        if user.oid != doc.get("OwnerEntraId", ""):
            raise HTTPException(
                status_code=403,
                detail="Only the document owner can recall a document from Approval.",
            )

        fields: dict = {
            "Stage":               "Sensitisation",
            "ApprovalStatus":      "",
            "ApproverEntraId":     "",
            "Approver":            "",
            "SubmittedForApproval": "",
        }
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"recall document {item_id}")


@router.patch("/documents/{item_id}/deadline")
async def extend_deadline(
    item_id: str,
    body: ExtendDeadlineBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Extend the sensitisation feedback deadline. Owner only."""
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if doc["Stage"] != "Sensitisation":
            raise HTTPException(
                status_code=422,
                detail="Deadline can only be extended while in Sensitisation stage.",
            )
        if user.oid != doc.get("OwnerEntraId", ""):
            raise HTTPException(
                status_code=403,
                detail="Only the document owner can extend the sensitisation deadline.",
            )

        await update_list_item(_get_list_id(), _LIST_NAME, item_id,
                               {"SensitisationDeadline": body.new_deadline})
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"extend deadline {item_id}")


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
            logger.warning(f"Lifecycle item {item_id} reassigned, but Owner text field could not be populated: {exc}")
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
    """
    file_bytes = await file.read()
    filename   = file.filename or f"document_{item_id}.docx"

    try:
        file_url = await _upload_to_sharepoint(item_id, filename, file_bytes)
    except Exception as exc:
        logger.exception(f"SharePoint upload failed for lifecycle {item_id}")
        raise HTTPException(status_code=503, detail=f"SharePoint upload failed: {exc}")

    cdi_status   = "Pending"
    cdi_failures = ""
    try:
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

        try:
            item_data = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
            doc_code  = item_data.get("fields", {}).get("DocumentCode", "")
        except Exception:
            doc_code = ""

        cdi_result = await run_cdi_check(file_bytes, filename, doc_code, role_titles)

        if cdi_result.get("error"):
            cdi_status   = "Error"
            cdi_failures = json.dumps([{
                "check":  "CDI",
                "detail": cdi_result["error"],
                "fix":    "Resolve the issue above, then re-upload the document.",
            }])
            logger.warning(f"CDI check error for lifecycle {item_id}: {cdi_result['error']}")
        elif cdi_result["passed"]:
            cdi_status   = "Passed"
            cdi_failures = ""
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
        logger.info(f"CDI check for lifecycle {item_id}: {cdi_status} — {cdi_result.get('fail_count', 0)} failures")
    except Exception as exc:
        logger.warning(f"CDI check failed to run for {item_id}: {exc}")
        cdi_status   = "Error"
        cdi_failures = ""

    fields: dict = {
        "SharePointFileUrl": file_url,
        "Revised":           True,
        "CDIStatus":         cdi_status,
        "CDIFailures":       cdi_failures,
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
    """Redirect the client to the SharePoint file URL for direct download."""
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
#  Feedback endpoints
# =============================================================================

class FeedbackBody(BaseModel):
    feedback: str


@router.patch("/documents/{item_id}/feedback")
async def update_feedback(
    item_id: str,
    body: FeedbackBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Bulk-replace the sensitisation feedback field (owner use — used internally).
    For structured per-stakeholder submissions, use POST /feedback/submit.
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


@router.post("/documents/{item_id}/feedback/submit")
async def submit_feedback(
    item_id: str,
    body: FeedbackSubmitBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Stakeholder submits a structured feedback entry.
    Appends to the existing feedback array and increments StakeholderResponseCount.
    Accepts submissions from any authenticated user (not restricted to the stakeholders list).
    """
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=422, detail="Feedback text cannot be empty.")

    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if doc["Stage"] != "Sensitisation":
            raise HTTPException(
                status_code=422,
                detail="Feedback can only be submitted while the document is in Sensitisation stage.",
            )

        # Parse existing feedback array
        existing: list[dict] = []
        raw = doc.get("SensitisationFeedback", "")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    existing = parsed
            except Exception:
                pass

        # Resolve user name
        submitter_name = await _resolve_display_name(user.oid, user.name)

        new_entry = {
            "text":        body.text.strip(),
            "category":    body.category,
            "submittedBy": submitter_name or user.name or user.oid,
            "submittedAt": datetime.now(timezone.utc).isoformat(),
            "stakeholderOid": user.oid,
        }
        updated_feedback = existing + [new_entry]

        # Determine if this is the first time this user submitted — increment counter
        already_submitted = any(
            e.get("stakeholderOid") == user.oid for e in existing
        )
        new_count = doc.get("StakeholderResponseCount", 0)
        if not already_submitted:
            new_count += 1

        await update_list_item(_get_list_id(), _LIST_NAME, item_id, {
            "SensitisationFeedback":    json.dumps(updated_feedback),
            "StakeholderResponseCount": new_count,
        })
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return await _sp_to_doc(updated)

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"submit feedback {item_id}")


# =============================================================================
#  AI endpoints
# =============================================================================

@router.post("/documents/{item_id}/cdi-fix-suggestions")
async def cdi_fix_suggestions(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Generate AI suggestions for fixing CDI failures in the current document.
    Returns a list of {check, finding, suggestion} dicts.
    The owner downloads and applies fixes manually — nothing is auto-overwritten.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        cdi_failures_raw = doc.get("CDIFailures", "")
        if not cdi_failures_raw:
            raise HTTPException(status_code=422, detail="No CDI failures recorded for this document.")

        try:
            cdi_failures = json.loads(cdi_failures_raw)
        except Exception:
            cdi_failures = [{"check": "CDI", "detail": cdi_failures_raw}]

        doc_text = await _get_document_text(doc)
        doc_context = (doc_text[:3000] + "...") if len(doc_text) > 3000 else doc_text

        failures_text = "\n".join(
            f"- {f.get('check', '')}: {f.get('detail', '')} | Fix hint: {f.get('fix', '')}"
            for f in cdi_failures
        )

        prompt = f"""You are a document quality expert. A controlled document has CDI (Controlled Document Interface) failures that need to be fixed.

Document title: {doc.get('Title', 'Unknown')}
Document type: {doc.get('DocumentType', 'Unknown')}

Current CDI failures:
{failures_text}

Document excerpt (first 3000 characters):
{doc_context}

For each CDI failure listed above, provide a specific, actionable suggestion for how to fix it in the document.
Return a JSON array where each item has:
- "check": the CDI check ID (e.g. "CDI-03")
- "finding": the problem found
- "suggestion": the specific text change or action to take (be concrete, e.g. "Add 'Version: 1.0' to the document header on the first page")

Return only the JSON array, no other text."""

        response_text = await _ollama_generate(prompt)
        suggestions = _normalise_cdi_suggestions(
            _extract_json_payload(response_text),
            fallback_text=response_text,
        )

        return {
            "document_id": item_id,
            "title":       doc.get("Title", ""),
            "cdi_failures": cdi_failures,
            "suggestions":  suggestions,
        }

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"cdi-fix-suggestions {item_id}")


@router.post("/documents/{item_id}/feedback/ai-suggestions")
async def feedback_ai_suggestions(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Generate AI revision suggestions based on stakeholder feedback.
    Returns a list of {section, current_text, suggested_text, based_on_feedback_from}.
    The owner decides which suggestions to incorporate.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        if not doc.get("SensitisationFeedback"):
            raise HTTPException(status_code=422, detail="No stakeholder feedback recorded yet.")

        try:
            feedback_list = json.loads(doc["SensitisationFeedback"])
            if not isinstance(feedback_list, list):
                feedback_list = []
        except Exception:
            feedback_list = [{"text": doc["SensitisationFeedback"], "submittedBy": "Unknown"}]

        doc_text    = await _get_document_text(doc)
        doc_context = (doc_text[:3000] + "...") if len(doc_text) > 3000 else doc_text

        feedback_text = "\n".join(
            f"- [{f.get('category', 'General')}] {f.get('submittedBy', 'Unknown')}: {f.get('text', '')}"
            for f in feedback_list
        )

        prompt = f"""You are a document improvement expert. A controlled document has been reviewed by stakeholders who have left feedback. Your task is to translate that feedback into specific document revision suggestions.

Document title: {doc.get('Title', 'Unknown')}
Document type: {doc.get('DocumentType', 'Unknown')}

Stakeholder feedback received:
{feedback_text}

Document excerpt (first 3000 characters):
{doc_context}

Based on the feedback, provide specific revision suggestions. For each suggestion:
- Identify which section or area of the document it affects
- State what is currently there (or what is missing)
- Suggest the specific change
- Note which feedback item it addresses

Return a JSON array where each item has:
- "section": the section or area (e.g. "Section 5.1" or "Introduction" or "Missing section")
- "current_text": what the document currently says (brief, or "Not present")
- "suggested_text": what it should say or what should be added
- "based_on_feedback_from": the stakeholder who raised this concern

Return only the JSON array, no other text."""

        response_text = await _ollama_generate(prompt)

        suggestions = []
        try:
            suggestions = json.loads(response_text)
            if not isinstance(suggestions, list):
                suggestions = []
        except Exception:
            suggestions = [{"section": "General", "current_text": "", "suggested_text": response_text, "based_on_feedback_from": "AI"}] if response_text else []

        return {
            "document_id":    item_id,
            "title":          doc.get("Title", ""),
            "feedback_count": len(feedback_list),
            "suggestions":    suggestions,
        }

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"feedback ai-suggestions {item_id}")


@router.post("/documents/{item_id}/ai-assessment")
async def ai_assessment(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Generate an AI assessment of the document for the approver review page.
    Checks whether stakeholder feedback concerns appear to be addressed in the document.
    Returns structured assessment with coverage analysis.
    """
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        doc  = await _sp_to_doc(item)

        feedback_list: list[dict] = []
        if doc.get("SensitisationFeedback"):
            try:
                parsed = json.loads(doc["SensitisationFeedback"])
                if isinstance(parsed, list):
                    feedback_list = parsed
            except Exception:
                pass

        doc_text    = await _get_document_text(doc)
        doc_context = (doc_text[:4000] + "...") if len(doc_text) > 4000 else doc_text

        feedback_summary = "\n".join(
            f"- [{f.get('category', 'General')}] {f.get('submittedBy', 'Unknown')}: {f.get('text', '')}"
            for f in feedback_list
        ) or "No stakeholder feedback recorded."

        prompt = f"""You are a document compliance assessor. A document has been through stakeholder review and is now at the approval stage. Assess whether it is ready for approval.

Document title: {doc.get('Title', 'Unknown')}
Document type: {doc.get('DocumentType', 'Unknown')}
Standards mapped to: {doc.get('StandardsMapping', 'Not specified')}
CDI status: {doc.get('CDIStatus', 'Unknown')}
Rejection count: {doc.get('RejectionCount', 0)}

Stakeholder feedback received:
{feedback_summary}

Document excerpt (first 4000 characters):
{doc_context}

Provide an approval readiness assessment. Return a JSON object with:
- "ready_for_approval": true or false
- "confidence": "High" | "Medium" | "Low"
- "cdi_note": brief note on CDI status
- "standards_coverage": brief note on whether the document appears to address the mapped standards
- "feedback_addressed": array of objects with "concern" and "addressed" (true/false) and "note" for each concern raised
- "unresolved_concerns": array of concern strings not reflected in the document
- "approver_note": a one or two sentence summary for the approver

Return only the JSON object, no other text."""

        response_text = await _ollama_generate(prompt)

        assessment = {}
        try:
            assessment = json.loads(response_text)
            if not isinstance(assessment, dict):
                assessment = {}
        except Exception:
            assessment = {"approver_note": response_text} if response_text else {}

        return {
            "document_id":    item_id,
            "title":          doc.get("Title", ""),
            "feedback_count": len(feedback_list),
            "assessment":     assessment,
        }

    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc, f"ai-assessment {item_id}")


# =============================================================================
#  SharePoint file upload
# =============================================================================

async def _upload_to_sharepoint(
    item_id: str, filename: str, file_bytes: bytes
) -> str:
    token   = await get_graph_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/octet-stream",
    }
    base    = settings.graph_base_url
    site_id = settings.sharepoint_site_id

    upload_path = f"Lifecycle Documents/{item_id}/{filename}"
    upload_url  = f"{base}/sites/{site_id}/drive/root:/{upload_path}:/content"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.put(upload_url, headers=headers, content=file_bytes)
        resp.raise_for_status()

    web_url = resp.json().get("webUrl", "")
    logger.info(f"Uploaded '{filename}' for lifecycle {item_id} → {web_url}")
    return web_url
