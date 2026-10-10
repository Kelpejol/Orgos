# =============================================================================
# record_tracker/router.py
# GET  /api/v1/records              — list all record items
# GET  /api/v1/records/{id}         — get single item
# PATCH /api/v1/records/{id}/submit — owner submits a record with link
# PATCH /api/v1/records/{id}/verify — compliance verifies submission
#
# NOTE — naming: this module was renamed from "Evidence Tracker" to "Record
# Tracker" (OrgOS's own feature/API naming only). The underlying SharePoint
# list is still literally named "Evidence Tracker" with columns like
# EvidenceDescription/EvidenceType/EvidenceLink — those are NOT renamed here
# (OrgOS cannot rename SharePoint columns). The 16-code "Evidence Type"
# taxonomy (DRG-QI-REF-EVTX-01-26) also keeps its name throughout — it is a
# separate, formally documented standard, distinct from this tracker feature.
# =============================================================================

import logging
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from config import settings
from graph.auth import get_graph_access_token
from graph.client import (
    create_list_item,
    get_list_item,
    get_list_items,
    update_list_item,
)
from graph.exceptions import GraphAPIError, GraphNotFoundError
from graph.client import resolve_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Record Tracker"])

# The real SharePoint list name — unchanged (see module note above).
_LIST_NAME = "Evidence Tracker"


def _list_id() -> str:
    # Unchanged config attribute — renaming it would require a matching
    # production .env update; not worth the deploy-coordination risk for an
    # internal-only name. See module note above.
    return settings.evidence_tracker_list_id


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.exception(f"Error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


def _sp_to_record(item: dict) -> dict:
    f = item.get("fields", {})
    return {
        "id":                  str(item["id"]),
        "Title":               f.get("Title", ""),
        "RecordDescription":   f.get("EvidenceDescription", ""),
        "EvidenceType":        f.get("EvidenceType", ""),
        "SourceSystem":        f.get("SourceSystem", ""),
        "RecordFormat":        f.get("EvidenceFormat", ""),
        "Frequency":           f.get("Frequency", ""),
        "CollectionMethod":    f.get("CollectionMethod", ""),
        "OwnerRole":           f.get("OwnerRole", ""),
        "OwnerEntraId":        f.get("OwnerEntraId", ""),
        "ValidationCriteria":  f.get("ValidationCriteria", ""),
        "RecordLink":          f.get("EvidenceLink", ""),
        "RecordUrl":           f.get("EvidenceLink", ""),
        "recordUrl":           f.get("EvidenceLink", ""),
        "Status":              f.get("Status", "Pending"),
        "LinkedControlId":     f.get("LinkedControlId", ""),
        "NextDue":             f.get("NextDue", ""),
        "LastCollected":       f.get("LastCollected", ""),
        "SubmissionNotes":     f.get("SubmissionNotes", ""),
        "RejectionNote":       f.get("RejectionNote", ""),
        "VerifiedBy":          f.get("VerifiedBy", ""),
        "created":             item.get("createdDateTime", ""),
        "modified":            item.get("lastModifiedDateTime", ""),
    }


# =============================================================================
#  Endpoints
# =============================================================================

@router.get("/api/v1/records")
async def list_records(
    owner_oid:  Optional[str] = None,
    status:     Optional[str] = None,
    control_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """
    List record items. Filterable by owner OID, status, or linked control.
    """
    try:
        items = await get_list_items(_list_id(), _LIST_NAME)
        records = [_sp_to_record(i) for i in items]

        # Ownership is a ROLE (job title / group / alias) — OwnerEntraId is
        # never populated. Resolve once and stamp each item so the UI can gate
        # actions without re-deriving membership client-side.
        try:
            from ownership.resolver import get_ownership_index
            ownership = await get_ownership_index()
            for r in records:
                res = ownership.resolve(r["OwnerRole"])
                r["OwnedByMe"]    = ownership.owns(r["OwnerRole"], user.oid)
                r["OwnerKind"]    = res["kind"]           # group | job_title | unresolved
                r["OwnerPeople"]  = res["people"]
                r["OwnerResolved"] = res["resolved"]
                r["OwnerCanonical"] = res["canonical"]
                r["OwnerViaAlias"]  = res["via_alias"]
        except Exception as exc:
            logger.warning(f"Could not resolve record ownership: {exc}")
            for r in records:
                r.setdefault("OwnedByMe", False)
                r.setdefault("OwnerKind", "unresolved")
                r.setdefault("OwnerPeople", [])
                r.setdefault("OwnerResolved", False)

        if owner_oid:
            # Filter by who actually holds the owning role.
            records = [r for r in records
                       if any((p.get("oid") or "") == owner_oid for p in r.get("OwnerPeople", []))]
        if status:
            records = [r for r in records if r["Status"] == status]
        if control_id:
            records = [r for r in records if r["LinkedControlId"] == control_id]

        # Sort: overdue and due soon first
        status_order = {
            "Overdue": 0, "Due Soon": 1, "Submitted": 2,
            "Pending": 3, "Rejected": 4, "Accepted": 5,
        }
        records.sort(key=lambda r: status_order.get(r["Status"], 9))
        return records
    except Exception as exc:
        _handle(exc, "list records")


@router.get("/api/v1/records/{item_id}")
async def get_record(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(item)
    except Exception as exc:
        _handle(exc, f"get record {item_id}")


class SubmitRecord(BaseModel):
    record_link:      str   # Mandatory — link to the actual artefact
    submission_notes: Optional[str] = None


class VerifyRecord(BaseModel):
    accepted:      bool
    rejection_note: Optional[str] = None  # Required if accepted=False


def _safe_filename(filename: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in (" ", ".", "-", "_") else "_" for c in filename)
    return cleaned.strip(" .") or "record-file"


async def _upload_record_to_sharepoint(
    item_id: str,
    filename: str,
    file_bytes: bytes,
) -> str:
    """
    Upload a record file to SharePoint and return the source webUrl.
    Path: /EVID-{item_id}-{filename} — kept as-is, matches the already-
    uploaded files' naming convention on the live drive.
    """
    token = await get_graph_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    upload_path = f"Evidence/EVID-{item_id}-{_safe_filename(filename)}"
    upload_url = (
        f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
        f"/drive/root:/{upload_path}:/content"
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.put(upload_url, headers=headers, content=file_bytes)
        resp.raise_for_status()

    web_url = resp.json().get("webUrl", "")
    logger.info(f"Uploaded record '{filename}' for item {item_id}: {web_url}")
    return web_url


@router.patch("/api/v1/records/{item_id}/submit")
async def submit_record(
    item_id: str,
    body: SubmitRecord,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Owner submits a collected record with a mandatory link to the artefact.
    Sets status to Submitted for Compliance team verification.
    """
    if not body.record_link.strip():
        raise HTTPException(
            status_code=422,
            detail="record_link is mandatory. Paste the URL to the artefact in SharePoint, Intune, GitHub, or the relevant source system.",
        )

    try:
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        if ((current.get("fields", {}) or {}).get("Status", "") or "") == "Accepted":
            raise HTTPException(
                status_code=409,
                detail="This record is already Accepted. Someone with the Compliance role "
                       "must reopen it (reject) before a new record can be submitted.",
            )

        fields: dict = {
            "EvidenceLink":   body.record_link.strip(),
            "Status":         "Submitted",
            "LastCollected":  date.today().isoformat(),
            "RejectionNote":  "",  # Clear any previous rejection
        }
        if body.submission_notes:
            fields["SubmissionNotes"] = body.submission_notes

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"submit record {item_id}")


@router.post("/api/v1/records/{item_id}/upload")
async def upload_record(
    item_id: str,
    file: UploadFile = File(...),
    submission_notes: Optional[str] = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Owner uploads a collected record to SharePoint.
    The returned SharePoint webUrl is stored as the record's source URL.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Record file is required.")

    filename = file.filename or f"record_{item_id}"

    try:
        record_url = await _upload_record_to_sharepoint(item_id, filename, file_bytes)
    except Exception as exc:
        logger.exception(f"SharePoint record upload failed for {item_id}")
        raise HTTPException(status_code=503, detail=f"SharePoint upload failed: {exc}")

    try:
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        if ((current.get("fields", {}) or {}).get("Status", "") or "") == "Accepted":
            raise HTTPException(
                status_code=409,
                detail="This record is already Accepted. Someone with the Compliance role "
                       "must reopen it (reject) before a new record can be uploaded.",
            )

        fields: dict = {
            "EvidenceLink":   record_url,
            "Status":         "Submitted",
            "LastCollected":  date.today().isoformat(),
            "RejectionNote":  "",
        }
        if submission_notes:
            fields["SubmissionNotes"] = submission_notes

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"save uploaded record {item_id}")


@router.patch("/api/v1/records/{item_id}/verify")
async def verify_record(
    item_id: str,
    body: VerifyRecord,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Compliance team verifies a submitted record item.
    Accept → status becomes Accepted.
    Reject → status returns to Pending with rejection note visible to owner.
    """
    if not body.accepted and not body.rejection_note:
        raise HTTPException(
            status_code=422,
            detail="rejection_note is required when rejecting a record.",
        )

    try:
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        cur_status = (current.get("fields", {}) or {}).get("Status", "") or ""
        if cur_status != "Submitted":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Only submitted records can be verified (current status: "
                    f"'{cur_status or 'Pending'}'). The owner must submit the record first."
                ),
            )

        fields: dict = {
            "Status":     "Accepted" if body.accepted else "Pending",
            "VerifiedBy": user.name or user.oid,
        }
        if not body.accepted and body.rejection_note:
            fields["RejectionNote"] = body.rejection_note

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"verify record {item_id}")


class ReassignRecordOwner(BaseModel):
    owner_role: str


@router.patch("/api/v1/records/{item_id}/reassign-owner")
async def reassign_record_owner(
    item_id: str,
    body: ReassignRecordOwner,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Reassign the record owner role to a (real) job title. Compliance only.
    """
    owner = (body.owner_role or "").strip()
    if not owner:
        raise HTTPException(status_code=422, detail="owner_role is required.")
    try:
        await update_list_item(_list_id(), _LIST_NAME, item_id, {"OwnerRole": owner})
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"reassign record owner {item_id}")
