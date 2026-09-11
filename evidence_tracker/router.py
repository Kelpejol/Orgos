# =============================================================================
# evidence_tracker/router.py
# GET  /api/v1/evidence              — list all evidence items
# GET  /api/v1/evidence/{id}         — get single item
# PATCH /api/v1/evidence/{id}/submit — owner submits evidence with link
# PATCH /api/v1/evidence/{id}/verify — compliance verifies submission
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

router = APIRouter(tags=["Evidence Tracker"])

_LIST_NAME = "Evidence Tracker"


def _list_id() -> str:
    return settings.evidence_tracker_list_id


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.exception(f"Error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


def _sp_to_evd(item: dict) -> dict:
    f = item.get("fields", {})
    return {
        "id":                  str(item["id"]),
        "Title":               f.get("Title", ""),
        "EvidenceDescription": f.get("EvidenceDescription", ""),
        "EvidenceType":        f.get("EvidenceType", ""),
        "SourceSystem":        f.get("SourceSystem", ""),
        "EvidenceFormat":      f.get("EvidenceFormat", ""),
        "Frequency":           f.get("Frequency", ""),
        "CollectionMethod":    f.get("CollectionMethod", ""),
        "OwnerRole":           f.get("OwnerRole", ""),
        "OwnerEntraId":        f.get("OwnerEntraId", ""),
        "ValidationCriteria":  f.get("ValidationCriteria", ""),
        "EvidenceLink":        f.get("EvidenceLink", ""),
        "EvidenceUrl":         f.get("EvidenceLink", ""),
        "evidenceUrl":         f.get("EvidenceLink", ""),
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

@router.get("/api/v1/evidence")
async def list_evidence(
    owner_oid:  Optional[str] = None,
    status:     Optional[str] = None,
    control_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """
    List evidence items. Filterable by owner OID, status, or linked control.
    """
    try:
        items = await get_list_items(_list_id(), _LIST_NAME)
        evds  = [_sp_to_evd(i) for i in items]

        # Ownership is a ROLE (job title / group / alias) — OwnerEntraId is
        # never populated. Resolve once and stamp each item so the UI can gate
        # actions without re-deriving membership client-side.
        try:
            from ownership.resolver import get_ownership_index
            ownership = await get_ownership_index()
            for e in evds:
                res = ownership.resolve(e["OwnerRole"])
                e["OwnedByMe"]    = ownership.owns(e["OwnerRole"], user.oid)
                e["OwnerKind"]    = res["kind"]           # group | job_title | unresolved
                e["OwnerPeople"]  = res["people"]
                e["OwnerResolved"] = res["resolved"]
                e["OwnerCanonical"] = res["canonical"]
                e["OwnerViaAlias"]  = res["via_alias"]
        except Exception as exc:
            logger.warning(f"Could not resolve evidence ownership: {exc}")
            for e in evds:
                e.setdefault("OwnedByMe", False)
                e.setdefault("OwnerKind", "unresolved")
                e.setdefault("OwnerPeople", [])
                e.setdefault("OwnerResolved", False)

        if owner_oid:
            # Filter by who actually holds the owning role.
            evds = [e for e in evds
                    if any((p.get("oid") or "") == owner_oid for p in e.get("OwnerPeople", []))]
        if status:
            evds = [e for e in evds if e["Status"] == status]
        if control_id:
            evds = [e for e in evds if e["LinkedControlId"] == control_id]

        # Sort: overdue and due soon first
        status_order = {
            "Overdue": 0, "Due Soon": 1, "Submitted": 2,
            "Pending": 3, "Rejected": 4, "Accepted": 5,
        }
        evds.sort(key=lambda e: status_order.get(e["Status"], 9))
        return evds
    except Exception as exc:
        _handle(exc, "list evidence")


@router.get("/api/v1/evidence/{item_id}")
async def get_evidence(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_evd(item)
    except Exception as exc:
        _handle(exc, f"get evidence {item_id}")


class SubmitEvidence(BaseModel):
    evidence_link:    str   # Mandatory — link to the actual artefact
    submission_notes: Optional[str] = None


class VerifyEvidence(BaseModel):
    accepted:      bool
    rejection_note: Optional[str] = None  # Required if accepted=False


def _safe_filename(filename: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in (" ", ".", "-", "_") else "_" for c in filename)
    return cleaned.strip(" .") or "evidence-file"


async def _upload_evidence_to_sharepoint(
    item_id: str,
    filename: str,
    file_bytes: bytes,
) -> str:
    """
    Upload evidence to SharePoint and return the source webUrl.
    Path: /EVID-{item_id}-{filename}
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
    logger.info(f"Uploaded evidence '{filename}' for item {item_id}: {web_url}")
    return web_url


@router.patch("/api/v1/evidence/{item_id}/submit")
async def submit_evidence(
    item_id: str,
    body: SubmitEvidence,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Owner submits collected evidence with a mandatory link to the artefact.
    Sets status to Submitted for Compliance team verification.
    """
    if not body.evidence_link.strip():
        raise HTTPException(
            status_code=422,
            detail="evidence_link is mandatory. Paste the URL to the artefact in SharePoint, Intune, GitHub, or the relevant source system.",
        )

    try:
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        if ((current.get("fields", {}) or {}).get("Status", "") or "") == "Accepted":
            raise HTTPException(
                status_code=409,
                detail="This evidence is already Accepted. Someone with the Compliance role "
                       "must reopen it (reject) before new evidence can be submitted.",
            )

        fields: dict = {
            "EvidenceLink":   body.evidence_link.strip(),
            "Status":         "Submitted",
            "LastCollected":  date.today().isoformat(),
            "RejectionNote":  "",  # Clear any previous rejection
        }
        if body.submission_notes:
            fields["SubmissionNotes"] = body.submission_notes

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_evd(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"submit evidence {item_id}")


@router.post("/api/v1/evidence/{item_id}/upload")
async def upload_evidence(
    item_id: str,
    file: UploadFile = File(...),
    submission_notes: Optional[str] = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Owner uploads collected evidence to SharePoint.
    The returned SharePoint webUrl is stored as the evidence source URL.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Evidence file is required.")

    filename = file.filename or f"evidence_{item_id}"

    try:
        evidence_url = await _upload_evidence_to_sharepoint(item_id, filename, file_bytes)
    except Exception as exc:
        logger.exception(f"SharePoint evidence upload failed for {item_id}")
        raise HTTPException(status_code=503, detail=f"SharePoint upload failed: {exc}")

    try:
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        if ((current.get("fields", {}) or {}).get("Status", "") or "") == "Accepted":
            raise HTTPException(
                status_code=409,
                detail="This evidence is already Accepted. Someone with the Compliance role "
                       "must reopen it (reject) before new evidence can be uploaded.",
            )

        fields: dict = {
            "EvidenceLink":   evidence_url,
            "Status":         "Submitted",
            "LastCollected":  date.today().isoformat(),
            "RejectionNote":  "",
        }
        if submission_notes:
            fields["SubmissionNotes"] = submission_notes

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_evd(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"save uploaded evidence {item_id}")


@router.patch("/api/v1/evidence/{item_id}/verify")
async def verify_evidence(
    item_id: str,
    body: VerifyEvidence,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Compliance team verifies a submitted evidence item.
    Accept → status becomes Accepted.
    Reject → status returns to Pending with rejection note visible to owner.
    """
    if not body.accepted and not body.rejection_note:
        raise HTTPException(
            status_code=422,
            detail="rejection_note is required when rejecting evidence.",
        )

    try:
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        cur_status = (current.get("fields", {}) or {}).get("Status", "") or ""
        if cur_status != "Submitted":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Only submitted evidence can be verified (current status: "
                    f"'{cur_status or 'Pending'}'). The owner must submit the evidence first."
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
        return _sp_to_evd(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"verify evidence {item_id}")


class ReassignEvidenceOwner(BaseModel):
    owner_role: str


@router.patch("/api/v1/evidence/{item_id}/reassign-owner")
async def reassign_evidence_owner(
    item_id: str,
    body: ReassignEvidenceOwner,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Reassign the evidence owner role to a (real) job title. Compliance only.
    """
    owner = (body.owner_role or "").strip()
    if not owner:
        raise HTTPException(status_code=422, detail="owner_role is required.")
    try:
        await update_list_item(_list_id(), _LIST_NAME, item_id, {"OwnerRole": owner})
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_evd(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"reassign evidence owner {item_id}")
