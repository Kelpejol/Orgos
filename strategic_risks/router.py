# =============================================================================
# strategic_risks/router.py — Strategic Risk Register API
# Manual-first register. No AI extraction. ExCo-curated only.
# Three entry paths: direct ExCo input, gap acceptance, incident escalation.
# Per Bobby's spec note on Strategic Risk Register.
# =============================================================================

import logging
from datetime import date, datetime, timedelta
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

router = APIRouter(prefix="/api/v1/risks", tags=["Strategic Risk Register"])

_LIST_NAME = "Strategic Risk Register"

# Risk score matrix: Likelihood (Low=1, Medium=2, High=3) × Impact (Low=1, Medium=2, High=3, Critical=4)
LIKELIHOOD_MAP = {"Low": 1, "Medium": 2, "High": 3}
IMPACT_MAP     = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}


def _list_id() -> str:
    return settings.strategic_risk_register_list_id


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.exception(f"Error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


def _score(likelihood: str, impact: str) -> int:
    return LIKELIHOOD_MAP.get(likelihood, 1) * IMPACT_MAP.get(impact, 1)


def _score_label(score: int) -> str:
    if score <= 2:   return "Low"
    if score <= 4:   return "Medium"
    if score <= 6:   return "High"
    return "Critical"


def _score_color(score: int) -> str:
    if score <= 2:   return "#1D9E75"
    if score <= 4:   return "#BA7517"
    if score <= 6:   return "#D85A30"
    return "#A32D2D"


def _sp_to_risk(item: dict) -> dict:
    f = item.get("fields", {})
    likelihood = f.get("Likelihood", "Low")
    impact     = f.get("Impact", "Low")
    score      = _score(likelihood, impact)
    return {
        "id":                  str(item["id"]),
        "RiskId":              f.get("RiskId", ""),
        "Title":               f.get("Title", ""),
        "Description":         f.get("Description", ""),
        "Category":            f.get("Category", ""),
        "Source":              f.get("Source", "ExCo assessment"),
        "Likelihood":          likelihood,
        "Impact":              impact,
        "RiskScore":           score,
        "RiskScoreLabel":      _score_label(score),
        "RiskScoreColor":      _score_color(score),
        "OwnerEntraId":        f.get("OwnerEntraId", ""),
        "OwnerName":           f.get("Owner", ""),
        "Treatment":           f.get("Treatment", "Mitigate"),
        "TreatmentActions":    f.get("TreatmentActions", ""),
        "Status":              f.get("Status", "Open"),
        "DateIdentified":      f.get("DateIdentified", ""),
        "ReviewDate":          f.get("ReviewDate", ""),
        "LastReviewed":        f.get("LastReviewed", ""),
        "RelatedGapId":        f.get("RelatedGapId", ""),
        "RelatedIncidentId":   f.get("RelatedIncidentId", ""),
        "EscalationNote":      f.get("EscalationNote", ""),
        "Notes":               f.get("Notes", ""),
        "created":             item.get("createdDateTime", ""),
        "modified":            item.get("lastModifiedDateTime", ""),
    }


# =============================================================================
#  Schemas
# =============================================================================

class CreateRisk(BaseModel):
    description:       str
    category:          str   # SWOT-Strength/Weakness/Opportunity/Threat | PESTLE-Political/etc
    source:            str = "ExCo assessment"
    likelihood:        str = "Medium"
    impact:            str = "Medium"
    treatment:         str = "Mitigate"
    treatment_actions: Optional[str] = None
    escalation_note:   Optional[str] = None
    notes:             Optional[str] = None
    related_gap_id:    Optional[str] = None
    related_incident_id: Optional[str] = None


class UpdateRisk(BaseModel):
    likelihood:        Optional[str] = None
    impact:            Optional[str] = None
    treatment:         Optional[str] = None
    treatment_actions: Optional[str] = None
    status:            Optional[str] = None
    escalation_note:   Optional[str] = None
    notes:             Optional[str] = None
    review_date:       Optional[str] = None


# =============================================================================
#  Endpoints
# =============================================================================

@router.get("")
async def list_risks(
    status_filter: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """List all strategic risks, sorted by score descending (highest risk first)."""
    try:
        items = await get_list_items(_list_id(), _LIST_NAME)
        risks = [_sp_to_risk(i) for i in items]

        if status_filter:
            risks = [r for r in risks if r["Status"] == status_filter]

        risks.sort(key=lambda r: r["RiskScore"], reverse=True)
        return risks
    except Exception as exc:
        _handle(exc, "list risks")


@router.get("/{item_id}")
async def get_risk(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_risk(item)
    except Exception as exc:
        _handle(exc, f"get risk {item_id}")


@router.post("", status_code=201)
async def create_risk(
    body: CreateRisk,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Create a new strategic risk entry.
    All three entry paths use this endpoint.
    Gap acceptance and incident escalation pass related_gap_id or related_incident_id.
    """
    score = _score(body.likelihood, body.impact)
    today = date.today()

    fields: dict = {
        "Title":           body.description[:255],
        "Description":     body.description,
        "Category":        body.category,
        "Source":          body.source,
        "Likelihood":      body.likelihood,
        "Impact":          body.impact,
        "RiskScore":       score,
        "OwnerEntraId":    user.oid,
        "Treatment":       body.treatment,
        "Status":          "Open",
        "DateIdentified":  today.isoformat(),
        # Review date: 90 days for new risks per spec
        "ReviewDate":      (today + timedelta(days=90)).isoformat(),
    }

    if body.treatment_actions:
        fields["TreatmentActions"] = body.treatment_actions
    if body.escalation_note:
        fields["EscalationNote"] = body.escalation_note
    if body.notes:
        fields["Notes"] = body.notes
    if body.related_gap_id:
        fields["RelatedGapId"] = body.related_gap_id
    if body.related_incident_id:
        fields["RelatedIncidentId"] = body.related_incident_id

    try:
        item = await create_list_item(_list_id(), _LIST_NAME, fields)
        return _sp_to_risk(item)
    except Exception as exc:
        _handle(exc, "create risk")


@router.patch("/{item_id}")
async def update_risk(
    item_id: str,
    body: UpdateRisk,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Update a risk — treatment, status, notes, review date."""
    try:
        updates: dict = {}
        if body.likelihood:
            updates["Likelihood"] = body.likelihood
        if body.impact:
            updates["Impact"] = body.impact
        if body.likelihood or body.impact:
            # Fetch current values to recalculate score
            current = await get_list_item(_list_id(), _LIST_NAME, item_id)
            f = current.get("fields", {})
            l = body.likelihood or f.get("Likelihood", "Low")
            i = body.impact     or f.get("Impact", "Low")
            updates["RiskScore"] = _score(l, i)

        if body.treatment:         updates["Treatment"]        = body.treatment
        if body.treatment_actions: updates["TreatmentActions"] = body.treatment_actions
        if body.status:            updates["Status"]           = body.status
        if body.escalation_note:   updates["EscalationNote"]   = body.escalation_note
        if body.notes:             updates["Notes"]            = body.notes
        if body.review_date:       updates["ReviewDate"]       = body.review_date

        if body.status in ("Accepted", "Closed"):
            updates["LastReviewed"] = date.today().isoformat()

        await update_list_item(_list_id(), _LIST_NAME, item_id, updates)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_risk(updated)
    except Exception as exc:
        _handle(exc, f"update risk {item_id}")