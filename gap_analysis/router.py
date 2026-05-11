# =============================================================================
# gap_analysis/router.py — Gap Analysis API
# GET  /api/v1/gap-analysis               — list all gap findings
# GET  /api/v1/gap-analysis/{id}          — get single finding
# POST /api/v1/gap-analysis               — create finding (used by Gap Analyzer agent)
# PATCH /api/v1/gap-analysis/{id}/status  — update status (accept, close, etc)
# POST /api/v1/gap-analysis/{id}/accept-risk — escalate to Strategic Risk Register
# Per DRG-AUTO-GUIDE-GRC-01-26 Phase 9
# Gap Analyzer amendment: findings include proposed_remediation package (Bobby's spec)
# =============================================================================

import logging
from datetime import date, timedelta
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

router = APIRouter(prefix="/api/v1/gap-analysis", tags=["Gap Analysis"])

_LIST_NAME = "Gap Analysis"

SEVERITY_ORDER = {"Critical": 0, "Major": 1, "Minor": 2}
SEVERITY_DAYS  = {"Critical": 56, "Major": 28, "Minor": 90}  # target date offsets


def _list_id() -> str:
    return settings.gap_analysis_list_id


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.exception(f"Error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


def _sp_to_gap(item: dict) -> dict:
    f = item.get("fields", {})
    return {
        "id":                 str(item["id"]),
        "GapId":              f.get("GapId", ""),
        "Standard":           f.get("Standard", ""),
        "Clause":             f.get("Clause", ""),
        "ClauseTitle":        f.get("ClauseTitle", ""),
        "GapCategory":        f.get("GapCategory", ""),
        "Severity":           f.get("Severity", "Minor"),
        "Finding":            f.get("Finding", ""),
        "Impact":             f.get("Impact", ""),
        "RemediationHint":    f.get("RemediationHint", ""),
        "ProposedRemediation":f.get("ProposedRemediation", ""),  # Bobby's amendment — full package JSON
        "Status":             f.get("Status", "Open"),
        "AssignedTo":         f.get("AssignedTo", ""),
        "AssignedToEntraId":  f.get("AssignedToEntraId", ""),
        "TargetDate":         f.get("TargetDate", ""),
        "VerificationMethod": f.get("VerificationMethod", ""),
        "ResolutionNotes":    f.get("ResolutionNotes", ""),
        "LinkedRiskId":       f.get("LinkedRiskId", ""),
        "created":            item.get("createdDateTime", ""),
        "modified":           item.get("lastModifiedDateTime", ""),
    }


# =============================================================================
#  Schemas
# =============================================================================

class CreateGap(BaseModel):
    standard:           str
    clause:             str
    clause_title:       str = ""
    gap_category:       str
    severity:           str
    finding:            str
    impact:             str = ""
    remediation_hint:   str = ""
    proposed_remediation: Optional[str] = None  # JSON string of full package
    assigned_to:        Optional[str] = None
    assigned_to_entra_id: Optional[str] = None
    target_date:        Optional[str] = None
    verification_method: Optional[str] = None


class UpdateGapStatus(BaseModel):
    status:           str
    resolution_notes: Optional[str] = None
    assigned_to:      Optional[str] = None
    assigned_to_entra_id: Optional[str] = None
    target_date:      Optional[str] = None


class AcceptRisk(BaseModel):
    rationale: str  # ExCo rationale for accepting the risk


# =============================================================================
#  Endpoints
# =============================================================================

@router.get("")
async def list_gaps(
    severity:  Optional[str] = None,
    status_filter: Optional[str] = None,
    standard:  Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """
    List all gap findings. Sorted by severity (Critical first) then by clause.
    """
    try:
        items = await get_list_items(_list_id(), _LIST_NAME)
        gaps  = [_sp_to_gap(i) for i in items]

        if severity:
            gaps = [g for g in gaps if g["Severity"] == severity]
        if status_filter:
            gaps = [g for g in gaps if g["Status"] == status_filter]
        if standard:
            gaps = [g for g in gaps if g["Standard"] == standard]

        gaps.sort(key=lambda g: (
            SEVERITY_ORDER.get(g["Severity"], 9),
            g["Standard"],
            g["Clause"],
        ))
        return gaps
    except Exception as exc:
        _handle(exc, "list gaps")


@router.get("/{item_id}")
async def get_gap(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_gap(item)
    except Exception as exc:
        _handle(exc, f"get gap {item_id}")


@router.post("", status_code=201)
async def create_gap(
    body: CreateGap,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Create a gap finding. Called by the Gap Analyzer agent or manually.
    Auto-generates GapId and sets a default target date based on severity.
    """
    today      = date.today()
    year       = today.year
    month_day  = today.strftime("%m%d")
    gap_id     = f"GAP-{year}-{month_day}"

    target = (
        body.target_date
        or (today + timedelta(days=SEVERITY_DAYS.get(body.severity, 90))).isoformat()
    )

    fields: dict = {
        "Title":              body.finding[:255],
        "GapId":              gap_id,
        "Standard":           body.standard,
        "Clause":             body.clause,
        "ClauseTitle":        body.clause_title,
        "GapCategory":        body.gap_category,
        "Severity":           body.severity,
        "Finding":            body.finding,
        "Impact":             body.impact,
        "RemediationHint":    body.remediation_hint,
        "Status":             "Open",
        "TargetDate":         target,
    }
    if body.proposed_remediation:
        fields["ProposedRemediation"] = body.proposed_remediation
    if body.assigned_to:
        fields["AssignedTo"] = body.assigned_to
    if body.assigned_to_entra_id:
        fields["AssignedToEntraId"] = body.assigned_to_entra_id
    if body.verification_method:
        fields["VerificationMethod"] = body.verification_method

    try:
        item = await create_list_item(_list_id(), _LIST_NAME, fields)
        return _sp_to_gap(item)
    except Exception as exc:
        _handle(exc, "create gap")


@router.patch("/{item_id}/status")
async def update_gap_status(
    item_id: str,
    body: UpdateGapStatus,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Update status, assign to someone, add resolution notes."""
    valid_statuses = {"Open", "In progress", "Accepted risk", "Closed"}
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Status must be one of: {', '.join(sorted(valid_statuses))}",
        )

    try:
        fields: dict = {"Status": body.status}
        if body.resolution_notes:  fields["ResolutionNotes"]   = body.resolution_notes
        if body.assigned_to:       fields["AssignedTo"]        = body.assigned_to
        if body.assigned_to_entra_id: fields["AssignedToEntraId"] = body.assigned_to_entra_id
        if body.target_date:       fields["TargetDate"]        = body.target_date

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_gap(updated)
    except Exception as exc:
        _handle(exc, f"update gap status {item_id}")


@router.post("/{item_id}/accept-risk")
async def accept_risk(
    item_id: str,
    body: AcceptRisk,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    ExCo accepts the risk rather than remediating.
    Creates a Strategic Risk Register entry linked to this gap.
    Updates gap status to Accepted risk.
    Per DRG-QI-REF-DINT-01-26 Section 4.11.
    """
    if "OrgOS.Admin" not in user.roles and "Compliance.Lead" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Compliance Lead or OrgOS Admin required to accept risk.",
        )

    try:
        gap = _sp_to_gap(await get_list_item(_list_id(), _LIST_NAME, item_id))

        # Create Strategic Risk Register entry
        risk_fields = {
            "Title":          f"Accepted risk: {gap['Finding'][:200]}",
            "Description":    gap["Finding"],
            "Category":       "SWOT — Threat",
            "Source":         "Gap acceptance",
            "Likelihood":     "Medium",
            "Impact":         "High" if gap["Severity"] == "Critical" else "Medium",
            "RiskScore":      6 if gap["Severity"] == "Critical" else 4,
            "OwnerEntraId":   user.oid,
            "Treatment":      "Accept",
            "Status":         "Accepted",
            "DateIdentified": date.today().isoformat(),
            "ReviewDate":     (date.today() + timedelta(days=90)).isoformat(),
            "RelatedGapId":   gap["GapId"] or item_id,
            "Notes":          f"ExCo rationale: {body.rationale}",
        }

        risk_item = await create_list_item(
            settings.strategic_risk_register_list_id,
            "Strategic Risk Register",
            risk_fields,
        )
        risk_id = str(risk_item["id"])

        # Update gap status
        await update_list_item(_list_id(), _LIST_NAME, item_id, {
            "Status":          "Accepted risk",
            "LinkedRiskId":    risk_id,
            "ResolutionNotes": f"Risk accepted by {user.name}. Rationale: {body.rationale}",
        })

        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return {
            "gap":     _sp_to_gap(updated),
            "risk_id": risk_id,
            "message": "Gap marked as accepted risk. Strategic Risk Register entry created.",
        }

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"accept risk for gap {item_id}")