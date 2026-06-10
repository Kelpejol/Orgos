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

from auth.validator import CurrentUser, get_current_user
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
_RR_LIST_NAME = "Role Register"


def _list_id() -> str:
    return settings.evidence_tracker_list_id


def _rr_list_id() -> str:
    return settings.role_register_list_id


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

def _split_terms(value: str) -> list[str]:
    terms: list[str] = []
    for raw in (value or "").replace("\n", ",").split(","):
        term = raw.strip()
        if term and term.lower() not in {t.lower() for t in terms}:
            terms.append(term)
    return terms


async def _role_owner_map() -> dict[str, dict]:
    """Return normalised role/variant term -> canonical title and holder Entra ID."""
    try:
        roles = await get_list_items(_rr_list_id(), _RR_LIST_NAME)
    except Exception as exc:
        logger.warning(f"Could not fetch Role Register for evidence owner sync: {exc}")
        return {}

    owners: dict[str, dict] = {}
    for role in roles:
        fields = role.get("fields", {})
        title = fields.get("Title", "")
        if not title:
            continue
        holder_oid = (
            fields.get("CurrentHolderEntraId", "")
            or fields.get("CurrentHolderId", "")
            or ""
        )
        owner = {"title": title, "holder_oid": holder_oid}
        owners[" ".join(title.strip().lower().split())] = owner
        for term in _split_terms(fields.get("VariantTerms", "")):
            owners[" ".join(term.strip().lower().split())] = owner
    return owners


async def _sync_evidence_owner_ids(items: list[dict]) -> list[dict]:
    """
    Repair stale Evidence Tracker ownership after role harmonisation.
    Evidence Status is workflow state, so only OwnerRole/OwnerEntraId are synced.
    """
    role_owners = await _role_owner_map()
    if not role_owners:
        return items

    synced: list[dict] = []
    for item in items:
        fields = dict(item.get("fields", {}))
        owner_role = fields.get("OwnerRole", "")
        if not owner_role:
            synced.append(item)
            continue

        role_owner = role_owners.get(" ".join(owner_role.strip().lower().split()))
        if not role_owner:
            synced.append(item)
            continue

        canonical_role = role_owner["title"]
        holder_oid = role_owner["holder_oid"]
        updates = {}
        if fields.get("OwnerRole", "") != canonical_role:
            updates["OwnerRole"] = canonical_role
        if fields.get("OwnerEntraId", "") != holder_oid:
            updates["OwnerEntraId"] = holder_oid

        if updates:
            try:
                await update_list_item(
                    _list_id(),
                    _LIST_NAME,
                    str(item["id"]),
                    updates,
                )
                fields.update(updates)
                item = {**item, "fields": fields}
            except Exception as exc:
                logger.warning(f"Could not sync owner for evidence {item.get('id')}: {exc}")

        synced.append(item)
    return synced

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
        items = await _sync_evidence_owner_ids(items)
        evds  = [_sp_to_evd(i) for i in items]

        if owner_oid:
            evds = [e for e in evds if e["OwnerEntraId"] == owner_oid]
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
        item = (await _sync_evidence_owner_ids([item]))[0]
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
    upload_path = f"EVID-{item_id}-{_safe_filename(filename)}"
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
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Compliance team verifies a submitted evidence item.
    Accept → status becomes Accepted.
    Reject → status returns to Pending with rejection note visible to owner.
    """
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Compliance Lead or OrgOS Admin required to verify evidence.",
        )

    if not body.accepted and not body.rejection_note:
        raise HTTPException(
            status_code=422,
            detail="rejection_note is required when rejecting evidence.",
        )

    try:
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
