# =============================================================================
# control_register/router.py
# GET  /api/v1/controls              — list all controls
# GET  /api/v1/controls/{id}         — get single control
# POST /api/v1/queue/items/{id}/reject          — Zone 1 reject
# POST /api/v1/queue/items/{id}/request-second-review
# The live Zone 1 accept cascade is review_queue/router.py's
# PATCH /api/v1/queue/items/{id}/decide — this file's own accept-control
# endpoint was dead/unused code and has been removed.
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from config import MIN_RATIONALE_CHARS, settings
from graph.client import (
    create_list_item,
    get_list_item,
    get_list_items,
    update_list_item,
)
from graph.exceptions import GraphAPIError, GraphNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Control Register"])

_CR_LIST_NAME  = "Control Register"
_LOG_LIST_NAME = "Audit Log"
_Q_LIST_NAME   = "AI Review Queue"


def _cr_list_id()  -> str: return settings.control_register_list_id
def _log_list_id() -> str: return settings.audit_log_list_id
def _q_list_id()   -> str: return settings.ai_review_queue_list_id


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.exception(f"Error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


def _sp_to_control(item: dict) -> dict:
    f = item.get("fields", {})
    return {
        "id":               str(item["id"]),
        "Title":            f.get("Title", ""),
        "ControlStatement": f.get("ControlStatement", ""),
        "ControlType":      f.get("ControlType", ""),
        "SourceDocument":   f.get("SourceDocument", ""),
        "SourceClause":     f.get("SourceClause", ""),
        "ISOClause":        f.get("ISOClause", ""),
        "OwnerRole":        f.get("OwnerRole", ""),
        "OwnerEntraId":     f.get("OwnerEntraId", ""),
        "RiskImplication":  f.get("RiskImplication", ""),
        "EscalationNote":   f.get("EscalationNote", ""),
        "Status":           f.get("Status", "Active"),
        "ConfidenceScore":  f.get("ConfidenceScore", 0.0),
        "QueueItemId":      f.get("QueueItemId", ""),
        "created":          item.get("createdDateTime", ""),
        "modified":         item.get("lastModifiedDateTime", ""),
    }


# =============================================================================
#  Control Register endpoints
# =============================================================================

@router.get("/api/v1/controls")
async def list_controls(
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    try:
        items = await get_list_items(_cr_list_id(), _CR_LIST_NAME)
        controls = [_sp_to_control(i) for i in items]
        controls.sort(key=lambda c: c["created"], reverse=True)
        return controls
    except Exception as exc:
        _handle(exc, "list controls")


@router.get("/api/v1/controls/{item_id}")
async def get_control(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_cr_list_id(), _CR_LIST_NAME, item_id)
        return _sp_to_control(item)
    except Exception as exc:
        _handle(exc, f"get control {item_id}")


class ReassignControlOwner(BaseModel):
    owner_role: str


@router.patch("/api/v1/controls/{item_id}/reassign-owner")
async def reassign_control_owner(
    item_id: str,
    body: ReassignControlOwner,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Reassign a control's owner to a real job title or OrgOS group.
    A control is Blocked while its role resolves to nobody, so this also
    re-derives Status: Active once the new role has real holders.
    """
    owner_role = (body.owner_role or "").strip()
    if not owner_role:
        raise HTTPException(status_code=422, detail="owner_role is required.")
    try:
        # Only activate if the role actually resolves to someone.
        resolved = False
        try:
            from ownership.resolver import get_ownership_index
            resolved = (await get_ownership_index()).has_owner(owner_role)
        except Exception as exc:
            logger.warning(f"Could not resolve '{owner_role}' while reassigning {item_id}: {exc}")
            resolved = True  # don't block the edit if resolution is unavailable

        await update_list_item(_cr_list_id(), _CR_LIST_NAME, item_id, {
            "OwnerRole": owner_role,
            "Status":    "Active" if resolved else "Blocked",
        })
        updated = await get_list_item(_cr_list_id(), _CR_LIST_NAME, item_id)
        result = _sp_to_control(updated)
        result["OwnerResolved"] = resolved
        return result
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"reassign control owner {item_id}")


# =============================================================================
#  Decision cascade schemas
# =============================================================================

class RejectItem(BaseModel):
    rationale:   str
    reject_type: str = "Reject"  # "Reject" or "Mark False Positive"


class RequestSecondReview(BaseModel):
    rationale: str
    reviewer_oid: Optional[str] = None
    reviewer_name: Optional[str] = None
    reviewer_email: Optional[str] = None


# =============================================================================
#  Cascade helpers
# =============================================================================

async def _write_audit_log(
    reviewer: CurrentUser,
    item_id: str,
    item_type: str,
    zone: str,
    ai_confidence: float,
    decision: str,
    rationale: str,
    cascade_result: str,
    state_from: str,
    state_to: str,
) -> bool:
    """
    Write an audit log entry. Per DINT Section 8 — every decision logged.

    Returns True if the audit record was written, False otherwise. An audit
    failure must NOT block or roll back the cascade (the decision already
    applied), but it must not be silent either: on failure we record a visible
    marker on the decided item's CascadeResult so the audit gap is discoverable
    where the decision lives, not only in server logs.
    """
    try:
        await create_list_item(_log_list_id(), _LOG_LIST_NAME, {
            "Title":         f"{decision} — {item_id[:20]}",
            "ReviewerOID":   reviewer.oid,
            "ReviewerName":  reviewer.name,
            "ItemId":        item_id,
            "ItemType":      item_type,
            "Zone":          zone,
            "AIConfidence":  ai_confidence,
            "Decision":      decision,
            "Rationale":     rationale,
            "CascadeResult": cascade_result,
            "StateFrom":     state_from,
            "StateTo":       state_to,
        })
        return True
    except Exception as exc:
        logger.error(f"AUDIT TRAIL GAP — audit log write failed for item {item_id}: {exc}")
        # Non-silent fallback: append a gap marker to the decided item.
        try:
            existing = await get_list_item(_q_list_id(), _Q_LIST_NAME, item_id)
            current = (existing.get("fields", {}) or {}).get("CascadeResult", "") or ""
            if "AUDIT LOG NOT WRITTEN" not in current:
                marker = " | ⚠ AUDIT LOG NOT WRITTEN — decision not recorded in the audit trail (see server logs)"
                await update_list_item(
                    _q_list_id(), _Q_LIST_NAME, item_id,
                    {"CascadeResult": (current + marker)[:4000]},
                )
        except Exception as exc2:
            logger.error(f"Could not record audit-gap marker on item {item_id}: {exc2}")
        return False


async def _get_queue_item(item_id: str) -> dict:
    """Fetch a queue item and return its fields."""
    item = await get_list_item(_q_list_id(), _Q_LIST_NAME, item_id)
    return item.get("fields", {})


async def _mark_queue_cascade_failed(
    item_id: str,
    q_fields: dict,
    decision: str,
    rationale: str,
    user: CurrentUser,
    step: str,
    error: Exception,
    completed: list[str],
) -> None:
    """
    DINT §7.5 — a failed cascade must not leave the item looking decided or
    silently half-applied. Mark the queue item Blocked ("Cascade failed"),
    record the failed step and partial writes, and audit-log the failure.
    """
    failure_note = (
        f"CASCADE FAILED at step '{step}': {error}. "
        f"Completed before failure: {'; '.join(completed) if completed else 'nothing'}. "
        f"Retry the decision or escalate to the System Admin."
    )
    try:
        await update_list_item(_q_list_id(), _Q_LIST_NAME, item_id, {
            "ReviewStatus":      "Blocked",
            "Decision":          decision,
            "DecisionRationale": rationale,
            "ReviewedByEntraId": user.oid,
            "CascadeResult":     failure_note[:4000],
        })
    except Exception as exc:
        logger.error(f"Could not mark queue item {item_id} as cascade-failed: {exc}")

    await _write_audit_log(
        reviewer=user,
        item_id=item_id,
        item_type=q_fields.get("ItemType", "Extraction"),
        zone="1",
        ai_confidence=float(q_fields.get("ConfidenceScore") or 0),
        decision=f"{decision} (cascade failed)",
        rationale=rationale,
        cascade_result=failure_note,
        state_from=q_fields.get("ReviewStatus") or "Pending Review",
        state_to="Blocked",
    )


# =============================================================================
#  Zone 1 — Reject / Mark False Positive
# =============================================================================

@router.post("/api/v1/queue/items/{item_id}/reject")
async def reject_item(
    item_id: str,
    body: RejectItem,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """Reject a queue item or mark it as a false positive."""
    if len(body.rationale.strip()) < MIN_RATIONALE_CHARS:
        raise HTTPException(status_code=422, detail=f"Rationale must be at least {MIN_RATIONALE_CHARS} characters.")

    valid = {"Reject", "Mark False Positive"}
    if body.reject_type not in valid:
        raise HTTPException(status_code=422, detail=f"reject_type must be one of: {valid}")

    try:
        q_fields = await _get_queue_item(item_id)
        new_status = "Rejected" if body.reject_type == "Reject" else "False Positive"

        await update_list_item(_q_list_id(), _Q_LIST_NAME, item_id, {
            "ReviewStatus":      new_status,
            "Decision":          body.reject_type,
            "DecisionRationale": body.rationale,
            "ReviewedByEntraId": user.oid,
        })

        await _write_audit_log(
            reviewer=user,
            item_id=item_id,
            item_type=q_fields.get("ItemType", "Extraction"),
            zone="1",
            ai_confidence=float(q_fields.get("ConfidenceScore") or 0),
            decision=body.reject_type,
            rationale=body.rationale,
            cascade_result="No downstream cascade — item rejected.",
            state_from="Pending Review",
            state_to=new_status,
        )

        return {"status": new_status.lower().replace(" ", "_"), "item_id": item_id}

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"reject item {item_id}")


# =============================================================================
#  Zone 1 — Request Second Review
# =============================================================================

@router.post("/api/v1/queue/items/{item_id}/request-second-review")
async def request_second_review(
    item_id: str,
    body: RequestSecondReview,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    if len(body.rationale.strip()) < MIN_RATIONALE_CHARS:
        raise HTTPException(status_code=422, detail=f"Rationale must be at least {MIN_RATIONALE_CHARS} characters.")

    try:
        q_fields = await _get_queue_item(item_id)
        await update_list_item(_q_list_id(), _Q_LIST_NAME, item_id, {
            "ReviewStatus":      "Second Review Requested",
            "Decision":          "Request Second Review",
            "DecisionRationale": body.rationale,
            "ReviewedByEntraId": user.oid,
        })

        reviewer_summary = ""
        if body.reviewer_name or body.reviewer_email:
            reviewer_summary = " Requested reviewer: " + (
                f"{body.reviewer_name} ({body.reviewer_email})" if body.reviewer_name and body.reviewer_email
                else body.reviewer_name or body.reviewer_email
            )

        await _write_audit_log(
            reviewer=user,
            item_id=item_id,
            item_type=q_fields.get("ItemType", "Extraction"),
            zone="1",
            ai_confidence=float(q_fields.get("ConfidenceScore") or 0),
            decision="Request Second Review",
            rationale=body.rationale,
            cascade_result="Flagged for second reviewer." + reviewer_summary,
            state_from="Pending Review",
            state_to="Second Review Requested",
        )

        return {"status": "second_review_requested", "item_id": item_id}

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"request second review {item_id}")
