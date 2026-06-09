# =============================================================================
# control_register/router.py
# GET  /api/v1/controls              — list all controls
# GET  /api/v1/controls/{id}         — get single control
# POST /api/v1/queue/items/{id}/accept-control  — Zone 1 accept cascade
# POST /api/v1/queue/items/{id}/reject          — Zone 1 reject
# POST /api/v1/queue/items/{id}/edit-accept     — Zone 1 edit and accept
# Per DRG-QI-REF-DINT-01-26 Section 4.1 cascade spec
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Control Register"])

_CR_LIST_NAME  = "Control Register"
_EVD_LIST_NAME = "Evidence Tracker"
_LOG_LIST_NAME = "Audit Log"
_Q_LIST_NAME   = "AI Review Queue"


def _cr_list_id()  -> str: return settings.control_register_list_id
def _evd_list_id() -> str: return settings.evidence_tracker_list_id
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


# =============================================================================
#  Decision cascade schemas
# =============================================================================

class AcceptControl(BaseModel):
    rationale: str
    # Optional edits — if provided these override the AI-extracted values
    control_statement: Optional[str] = None
    control_type:      Optional[str] = None
    iso_clause:        Optional[str] = None
    owner_role:        Optional[str] = None
    risk_implication:  Optional[str] = None
    escalation_note:   Optional[str] = None
    evidence_type:          Optional[str] = None
    evidence_description:   Optional[str] = None
    evidence_source_system: Optional[str] = None
    evidence_format:        Optional[str] = None
    evidence_frequency:     Optional[str] = None


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
) -> None:
    """Write an audit log entry. Per DINT Section 8 — every decision logged."""
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
    except Exception as exc:
        # Audit log failure must not block the cascade — log and continue
        logger.error(f"Audit log write failed: {exc}")


async def _get_queue_item(item_id: str) -> dict:
    """Fetch a queue item and return its fields."""
    item = await get_list_item(_q_list_id(), _Q_LIST_NAME, item_id)
    return item.get("fields", {})


async def _resolve_owner_entra_id(owner_role: str) -> str:
    """
    Look up the current holder of a role in the Role Register.
    Returns the Entra ID OID of the current holder, or empty string if unassigned.
    """
    try:
        from config import settings as s
        items = await get_list_items(
            s.role_register_list_id,
            "Role Register",
        )
        for item in items:
            f = item.get("fields", {})
            title = f.get("Title", "").strip().lower()
            if title == owner_role.strip().lower():
                return f.get("CurrentHolderEntraId", "")
        return ""
    except Exception as exc:
        logger.warning(f"Could not resolve owner for role '{owner_role}': {exc}")
        return ""


# =============================================================================
#  Zone 1 — Accept Control (full cascade per DINT 4.1)
# =============================================================================

@router.post("/api/v1/queue/items/{item_id}/accept-control")
async def accept_control(
    item_id: str,
    body: AcceptControl,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Zone 1 Accept cascade — per DRG-QI-REF-DINT-01-26 Section 4.1.
    Steps:
    1. Validate rationale (min 10 chars)
    2. Fetch queue item
    3. Resolve owner via Role Register
    4. Create Control Register entry
    5. Create Evidence Tracker entry linked to control
    6. Update queue item status to Accepted
    7. Write audit log
    8. Return created control
    """
    # Permission check
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Compliance Lead or OrgOS Admin role required.",
        )

    if len(body.rationale.strip()) < 10:
        raise HTTPException(
            status_code=422,
            detail="Rationale must be at least 10 characters.",
        )

    try:
        # Step 1 — fetch queue item
        q_fields = await _get_queue_item(item_id)

        if q_fields.get("ReviewStatus") not in (None, "", "Pending Review"):
            raise HTTPException(
                status_code=409,
                detail=f"Item has already been reviewed: {q_fields.get('ReviewStatus')}",
            )

        # Use edited values if provided, otherwise use AI-extracted values
        control_statement = body.control_statement or q_fields.get("ControlStatement", "")
        control_type      = body.control_type      or q_fields.get("ControlType", "")
        iso_clause        = body.iso_clause        or q_fields.get("ISOClause", "")
        owner_role        = body.owner_role        or q_fields.get("ProposedOwnerRole", "")
        risk_implication  = body.risk_implication  or q_fields.get("RiskStatement", "")
        escalation_note   = body.escalation_note   or ""
        source_document   = q_fields.get("SourceDocumentCode", "")
        source_clause     = q_fields.get("SourceClause", "")
        confidence        = float(q_fields.get("ConfidenceScore") or 0)

        if not control_statement:
            raise HTTPException(
                status_code=422,
                detail="Cannot accept — no control statement found in queue item.",
            )

        # Step 2 — resolve owner via Role Register
        owner_oid = await _resolve_owner_entra_id(owner_role)
        control_status = "Active" if owner_oid else "Blocked"
        if not owner_oid:
            logger.warning(
                f"Owner role '{owner_role}' not found in Role Register — "
                f"control will be created as Blocked."
            )

        # Step 3 — create Control Register entry
        control_fields = {
            "Title":            control_statement[:255],
            "ControlStatement": control_statement,
            "ControlType":      control_type,
            "SourceDocument":   source_document,
            "SourceClause":     source_clause,
            "ISOClause":        iso_clause,
            "OwnerRole":        owner_role,
            "OwnerEntraId":     owner_oid,
            "RiskImplication":  risk_implication,
            "Status":           control_status,
            "ConfidenceScore":  confidence,
            "QueueItemId":      item_id,
        }
        if escalation_note:
            control_fields["EscalationNote"] = escalation_note

        control_item = await create_list_item(
            _cr_list_id(), _CR_LIST_NAME, control_fields
        )
        control_id = str(control_item["id"])
        logger.info(f"Control Register entry created: {control_id}")

        # Step 4 — create Evidence Tracker entry (if evidence fields present)
        evd_id = ""
        evd_type   = body.evidence_type          or q_fields.get("EvidenceType", "")
        evd_desc   = body.evidence_description   or q_fields.get("EvidenceDescription", "")
        evd_sys    = body.evidence_source_system or q_fields.get("EvidenceSourceSystem", "")
        evd_format = body.evidence_format        or q_fields.get("EvidenceFormat", "")
        evd_freq   = body.evidence_frequency     or q_fields.get("EvidenceFrequency", "")
        evd_method = q_fields.get("EvidenceCollectionMethod", "")
        evd_owner  = q_fields.get("EvidenceOwnerRole", "") or owner_role
        evd_crit   = q_fields.get("EvidenceValidationCriteria", "")
        is_edit_accept = any([
            body.control_statement,
            body.control_type,
            body.iso_clause,
            body.owner_role,
            body.risk_implication,
            body.escalation_note,
            body.evidence_type,
            body.evidence_description,
            body.evidence_source_system,
            body.evidence_format,
            body.evidence_frequency,
        ])

        if evd_type:
            evd_owner_oid = await _resolve_owner_entra_id(evd_owner)
            evd_title = evd_desc[:255] if evd_desc else f"Evidence for: {control_statement[:200]}"
            evd_fields = {
                "Title":               evd_title,
                "EvidenceDescription": evd_desc,
                "EvidenceType":        evd_type,
                "SourceSystem":        evd_sys,
                "EvidenceFormat":      evd_format,
                "Frequency":           evd_freq,
                "CollectionMethod":    evd_method,
                "OwnerRole":           evd_owner,
                "OwnerEntraId":        evd_owner_oid,
                "ValidationCriteria":  evd_crit,
                "Status":              "Pending",
                "LinkedControlId":     control_id,
            }
            evd_item = await create_list_item(
                _evd_list_id(), _EVD_LIST_NAME, evd_fields
            )
            evd_id = str(evd_item["id"])
            logger.info(f"Evidence Tracker entry created: {evd_id}")
        else:
            logger.info(
                f"No evidence type on queue item {item_id} — "
                "Evidence Tracker entry skipped."
            )

        # Step 5 — update queue item to Accepted
        cascade_summary = (
            f"Control Register: {control_id}"
            + (f" | Evidence Tracker: {evd_id}" if evd_id else "")
            + (f" | Status: Blocked — owner '{owner_role}' unassigned" if control_status == "Blocked" else "")
        )

        queue_updates = {
            "ReviewStatus":    "Accepted",
            "Decision":        "Edit and Accept" if is_edit_accept else "Accept",
            "DecisionRationale": body.rationale,
            "ReviewedByEntraId": user.oid,
            "CascadeResult":   cascade_summary,
        }
        edited_field_updates = {
            "ControlStatement": body.control_statement,
            "ControlType": body.control_type,
            "ISOClause": body.iso_clause,
            "ProposedOwnerRole": body.owner_role,
            "RiskStatement": body.risk_implication,
            "EvidenceType": body.evidence_type,
            "EvidenceDescription": body.evidence_description,
            "EvidenceSourceSystem": body.evidence_source_system,
            "EvidenceFormat": body.evidence_format,
            "EvidenceFrequency": body.evidence_frequency,
        }
        queue_updates.update({
            field: value
            for field, value in edited_field_updates.items()
            if value
        })
        if control_type and evd_type:
            queue_updates["CompletenessFlag"] = "COMPLETE"
            queue_updates["DeficiencyReason"] = ""
            queue_updates["EvidenceUndefined"] = False

        await update_list_item(_q_list_id(), _Q_LIST_NAME, item_id, queue_updates)

        # Step 6 — write audit log
        await _write_audit_log(
            reviewer=user,
            item_id=item_id,
            item_type=q_fields.get("ItemType", "Extraction"),
            zone="1",
            ai_confidence=confidence,
            decision="Edit and Accept" if is_edit_accept else "Accept",
            rationale=body.rationale,
            cascade_result=cascade_summary,
            state_from="Pending Review",
            state_to="Accepted",
        )

        return {
            "status":      "accepted",
            "control_id":  control_id,
            "evidence_id": evd_id,
            "control_status": control_status,
            "message": (
                "Control created and is Active." if control_status == "Active"
                else f"Control created but BLOCKED — role '{owner_role}' is unassigned in the Role Register. Assign the role to activate."
            ),
        }

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"accept control {item_id}")


# =============================================================================
#  Zone 1 — Reject / Mark False Positive
# =============================================================================

@router.post("/api/v1/queue/items/{item_id}/reject")
async def reject_item(
    item_id: str,
    body: RejectItem,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Reject a queue item or mark it as a false positive."""
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Compliance Lead or OrgOS Admin required.")

    if len(body.rationale.strip()) < 10:
        raise HTTPException(status_code=422, detail="Rationale must be at least 10 characters.")

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
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Compliance Lead or OrgOS Admin required.")

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
