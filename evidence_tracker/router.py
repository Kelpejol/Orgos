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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user
from config import settings
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
        return _sp_to_evd(item)
    except Exception as exc:
        _handle(exc, f"get evidence {item_id}")


class SubmitEvidence(BaseModel):
    evidence_link:    str   # Mandatory — link to the actual artefact
    submission_notes: Optional[str] = None


class VerifyEvidence(BaseModel):
    accepted:      bool
    rejection_note: Optional[str] = None  # Required if accepted=False


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