# =============================================================================
# strategic_risks/router.py — Strategic Risk Register API
# Manual-first register. No AI extraction. ExCo-curated only.
# Three entry paths: direct ExCo input, gap acceptance, incident escalation.
# Per Bobby's spec note on Strategic Risk Register.
# =============================================================================

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from auth.validator import CurrentUser, get_current_user, require_admin
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

# Valid statuses — enforced on all updates
VALID_STATUSES = {"Open", "Under treatment", "Accepted", "Transferred", "Avoided", "Closed"}

# Legal forward transitions — backend mirror of the frontend STATUS_TRANSITIONS map
# Prevents e.g. Closed → Open which would corrupt the lifecycle audit trail
VALID_TRANSITIONS: dict[str, set[str]] = {
    "Open":            {"Under treatment", "Accepted", "Transferred", "Avoided"},
    "Under treatment": {"Accepted", "Transferred", "Avoided", "Closed"},
    "Accepted":        {"Closed"},
    "Transferred":     {"Closed"},
    "Avoided":         {"Closed"},
    "Closed":          set(),   # terminal — no transitions out
}


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
    """Score bands: 1-3 Low, 4-6 Medium, 7-9 High, 10-12 Critical."""
    if score <= 3:  return "Low"
    if score <= 6:  return "Medium"
    if score <= 9:  return "High"
    return "Critical"


def _score_color(score: int) -> str:
    if score <= 3:  return "#1D9E75"
    if score <= 6:  return "#BA7517"
    if score <= 9:  return "#D85A30"
    return "#A32D2D"


def _sp_to_risk(item: dict) -> dict:
    f           = item.get("fields", {})
    likelihood  = f.get("Likelihood", "Low")
    impact      = f.get("Impact", "Low")
    score       = _score(likelihood, impact)
    review_date = f.get("ReviewDate", "")
    risk_status = f.get("Status", "Open")

    review_overdue = (
        bool(review_date)
        and risk_status not in ("Closed",)
        and review_date < date.today().isoformat()
    )

    return {
        "id":               str(item["id"]),
        "RiskId":           f.get("RiskId", ""),
        "Title":            f.get("Title", ""),
        "Description":      f.get("Description", ""),
        "Category":         f.get("Category", ""),
        "Source":           f.get("Source", "ExCo assessment"),
        "Likelihood":       likelihood,
        "Impact":           impact,
        "RiskScore":        score,
        "RiskScoreLabel":   _score_label(score),
        "RiskScoreColor":   _score_color(score),
        "OwnerEntraId":     f.get("OwnerEntraId", ""),
        "OwnerName":        f.get("Owner", ""),
        "Treatment":        f.get("Treatment", "Mitigate"),
        "TreatmentActions": f.get("TreatmentActions", ""),
        "Status":           risk_status,
        "ReviewOverdue":    review_overdue,
        "DateIdentified":   f.get("DateIdentified", ""),
        "ReviewDate":       review_date,
        "LastReviewed":     f.get("LastReviewed", ""),
        "AcceptedBy":       f.get("AcceptedBy", ""),
        "AcceptedDate":     f.get("AcceptedDate", ""),
        "RelatedGapId":     f.get("RelatedGapId", ""),
        "RelatedIncidentId":f.get("RelatedIncidentId", ""),
        "EscalationNote":   f.get("EscalationNote", ""),
        "Notes":            f.get("Notes", ""),
        "created":          item.get("createdDateTime", ""),
        "modified":         item.get("lastModifiedDateTime", ""),
    }


async def _next_risk_id() -> str:
    """
    Generate the next sequential RiskId for the current year.
    Format: RSK-{YY}-{NNN}
    Example: RSK-26-003
    """
    year_short = date.today().strftime("%y")
    prefix     = f"RSK-{year_short}-"
    try:
        items = await get_list_items(_list_id(), _LIST_NAME)
        count = sum(
            1 for i in items
            if i.get("fields", {}).get("RiskId", "").startswith(prefix)
        )
        return f"{prefix}{count + 1:03d}"
    except Exception:
        import time
        return f"{prefix}{int(time.time()) % 1000:03d}"


# =============================================================================
#  Schemas
# =============================================================================

class CreateRisk(BaseModel):
    description:        str
    category:           str
    source:             str = "ExCo assessment"
    likelihood:         str = "Medium"
    impact:             str = "Medium"
    treatment:          str = "Mitigate"
    treatment_actions:  Optional[str] = None
    escalation_note:    Optional[str] = None
    notes:              Optional[str] = None
    related_gap_id:     Optional[str] = None
    related_incident_id: Optional[str] = None

    @field_validator("likelihood")
    @classmethod
    def validate_likelihood(cls, v: str) -> str:
        if v not in LIKELIHOOD_MAP:
            raise ValueError(f"likelihood must be one of: {', '.join(LIKELIHOOD_MAP)}")
        return v

    @field_validator("impact")
    @classmethod
    def validate_impact(cls, v: str) -> str:
        if v not in IMPACT_MAP:
            raise ValueError(f"impact must be one of: {', '.join(IMPACT_MAP)}")
        return v

    @field_validator("treatment")
    @classmethod
    def validate_treatment(cls, v: str) -> str:
        valid = {"Mitigate", "Accept", "Transfer", "Avoid"}
        if v not in valid:
            raise ValueError(f"treatment must be one of: {', '.join(sorted(valid))}")
        return v


class UpdateRisk(BaseModel):
    likelihood:         Optional[str] = None
    impact:             Optional[str] = None
    treatment:          Optional[str] = None
    treatment_actions:  Optional[str] = None
    status:             Optional[str] = None
    escalation_note:    Optional[str] = None
    notes:              Optional[str] = None
    review_date:        Optional[str] = None

    @field_validator("likelihood")
    @classmethod
    def validate_likelihood(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in LIKELIHOOD_MAP:
            raise ValueError(f"likelihood must be one of: {', '.join(LIKELIHOOD_MAP)}")
        return v

    @field_validator("impact")
    @classmethod
    def validate_impact(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in IMPACT_MAP:
            raise ValueError(f"impact must be one of: {', '.join(IMPACT_MAP)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )
        return v

    @field_validator("treatment")
    @classmethod
    def validate_treatment(cls, v: Optional[str]) -> Optional[str]:
        valid = {"Mitigate", "Accept", "Transfer", "Avoid"}
        if v is not None and v not in valid:
            raise ValueError(f"treatment must be one of: {', '.join(sorted(valid))}")
        return v


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
    user: CurrentUser = Depends(require_admin),
) -> dict:
    """
    Create a new strategic risk entry.
    All three entry paths use this endpoint.
    Gap acceptance and incident escalation pass related_gap_id or related_incident_id.
    """
    score     = _score(body.likelihood, body.impact)
    today     = date.today()
    risk_id   = await _next_risk_id()

    fields: dict = {
        "RiskId":         risk_id,
        "Title":          body.description[:255],
        "Description":    body.description,
        "Category":       body.category,
        "Source":         body.source,
        "Likelihood":     body.likelihood,
        "Impact":         body.impact,
        "RiskScore":      score,
        "OwnerEntraId":   user.oid,
        "Owner":          user.name,
        "Treatment":      body.treatment,
        "Status":         "Open",
        "DateIdentified": today.isoformat(),
        "ReviewDate":     (today + timedelta(days=90)).isoformat(),
    }

    if body.treatment_actions:  fields["TreatmentActions"] = body.treatment_actions
    if body.escalation_note:    fields["EscalationNote"]   = body.escalation_note
    if body.notes:              fields["Notes"]            = body.notes
    if body.related_gap_id:     fields["RelatedGapId"]     = body.related_gap_id
    if body.related_incident_id: fields["RelatedIncidentId"] = body.related_incident_id

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

        # Always fetch current item — needed for both score recalculation and transition guard
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        f_current = current.get("fields", {})
        current_status = f_current.get("Status", "Open")

        # Validate status transition before touching anything else
        if body.status and body.status != current_status:
            allowed = VALID_TRANSITIONS.get(current_status, set())
            if body.status not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Cannot move risk from '{current_status}' to '{body.status}'. "
                        f"Allowed transitions from '{current_status}': "
                        f"{', '.join(sorted(allowed)) or 'none (terminal state)'}."
                    ),
                )

        if body.likelihood: updates["Likelihood"] = body.likelihood
        if body.impact:     updates["Impact"]     = body.impact

        # Recalculate score if either component changed
        if body.likelihood or body.impact:
            lh = body.likelihood or f_current.get("Likelihood", "Low")
            im = body.impact     or f_current.get("Impact", "Low")
            updates["RiskScore"] = _score(lh, im)

        if body.treatment:         updates["Treatment"]        = body.treatment
        if body.treatment_actions: updates["TreatmentActions"] = body.treatment_actions
        if body.status:            updates["Status"]           = body.status
        if body.escalation_note:   updates["EscalationNote"]   = body.escalation_note
        if body.notes:             updates["Notes"]            = body.notes
        if body.review_date:       updates["ReviewDate"]       = body.review_date

        # Stamp LastReviewed whenever a meaningful status change occurs
        if body.status:
            updates["LastReviewed"] = date.today().isoformat()
            if body.status == "Accepted":
                updates["AcceptedBy"]   = user.name
                updates["AcceptedDate"] = date.today().isoformat()

        await update_list_item(_list_id(), _LIST_NAME, item_id, updates)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_risk(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"update risk {item_id}")
