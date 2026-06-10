# =============================================================================
# gap_analysis/router.py — Gap Analysis API
# GET    /api/v1/gap-analysis               — list all gap findings
# GET    /api/v1/gap-analysis/{id}          — get single finding
# POST   /api/v1/gap-analysis               — create finding (manual or from agent)
# PATCH  /api/v1/gap-analysis/{id}/status   — update status
# POST   /api/v1/gap-analysis/{id}/approve-remediation — approve package, create lifecycle
# POST   /api/v1/gap-analysis/{id}/accept-risk         — escalate to Strategic Risk Register
# Per DRG-AUTO-GUIDE-GRC-01-26 Phase 9
# Gap Analyzer amendment: findings include proposed_remediation package (Bobby's spec)
# =============================================================================

import json
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

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

# Canonical target dates per severity — Critical 30d, Major 60d, Minor 90d
SEVERITY_DAYS = {"Critical": 30, "Major": 60, "Minor": 90}

VALID_GAP_STATUSES = {"Open", "In progress", "Accepted risk", "Closed"}

# Risk score maps (shared with strategic_risks router — kept here for accept-risk logic)
_LIKELIHOOD_MAP = {"Low": 1, "Medium": 2, "High": 3}
_IMPACT_MAP     = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}


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
        "id":                   str(item["id"]),
        "GapId":                f.get("GapId", ""),
        "GapKey":               f.get("GapKey", ""),
        "Standard":             f.get("Standard", ""),
        "Clause":               f.get("Clause", ""),
        "ClauseTitle":          f.get("ClauseTitle", ""),
        "GapCategory":          f.get("GapCategory", ""),
        "Severity":             f.get("Severity", "Minor"),
        "Finding":              f.get("Finding", ""),
        "Impact":               f.get("Impact", ""),
        "RemediationHint":      f.get("RemediationHint", ""),
        "ProposedRemediation":  f.get("ProposedRemediation", ""),
        "Status":               f.get("Status", "Open"),
        "AssignedTo":           f.get("AssignedTo", ""),
        "AssignedToEntraId":    f.get("AssignedToEntraId", ""),
        "TargetDate":           f.get("TargetDate", ""),
        "VerificationMethod":   f.get("VerificationMethod", ""),
        "ResolutionNotes":      f.get("ResolutionNotes", ""),
        "LinkedRiskId":         f.get("LinkedRiskId", ""),
        "LinkedLifecycleId":    f.get("LinkedLifecycleId", ""),
        "AcceptedBy":           f.get("AcceptedBy", ""),
        "AcceptedDate":         f.get("AcceptedDate", ""),
        "created":              item.get("createdDateTime", ""),
        "modified":             item.get("lastModifiedDateTime", ""),
    }


async def _generate_risk_id() -> str:
    """Generate RSK-{YY}-{NNN} for a risk created through gap acceptance."""
    year_short = date.today().strftime("%y")
    prefix     = f"RSK-{year_short}-"
    try:
        items = await get_list_items(
            settings.strategic_risk_register_list_id, "Strategic Risk Register"
        )
        count = sum(
            1 for i in items
            if i.get("fields", {}).get("RiskId", "").startswith(prefix)
        )
        return f"{prefix}{count + 1:03d}"
    except Exception:
        import time
        return f"{prefix}{int(time.time()) % 1000:03d}"


async def _next_gap_id(standard: str) -> str:
    """
    Generate the next sequential GapId for this standard and year.
    Format: GAP-{STANDARD}-{YY}-{NNN}
    Example: GAP-ISO27001-26-003
    """
    year_short = date.today().strftime("%y")
    std_code   = standard.replace(" ", "").replace("-", "") or "GEN"
    prefix     = f"GAP-{std_code}-{year_short}-"
    try:
        items = await get_list_items(_list_id(), _LIST_NAME)
        count = sum(
            1 for i in items
            if i.get("fields", {}).get("GapId", "").startswith(prefix)
        )
        return f"{prefix}{count + 1:03d}"
    except Exception:
        # If we can't read the list, use a timestamp-based fallback that is still unique
        import time
        return f"{prefix}{int(time.time()) % 1000:03d}"


# =============================================================================
#  Schemas
# =============================================================================

class CreateGap(BaseModel):
    standard:             str
    clause:               str
    clause_title:         str = ""
    gap_category:         str
    severity:             str
    finding:              str
    impact:               str = ""
    remediation_hint:     str = ""
    proposed_remediation: Optional[str] = None
    assigned_to:          Optional[str] = None
    assigned_to_entra_id: Optional[str] = None
    target_date:          Optional[str] = None
    verification_method:  Optional[str] = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in ("Critical", "Major", "Minor"):
            raise ValueError("severity must be Critical, Major, or Minor")
        return v

    @field_validator("gap_category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid = {
            "Missing artefact", "Control gap", "Evidence gap",
            "Ownership gap", "Standards misalignment", "Obligation gap",
        }
        if v not in valid:
            raise ValueError(f"gap_category must be one of: {', '.join(sorted(valid))}")
        return v


class UpdateGapStatus(BaseModel):
    status:               str
    resolution_notes:     Optional[str] = None
    assigned_to:          Optional[str] = None
    assigned_to_entra_id: Optional[str] = None
    target_date:          Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_GAP_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(VALID_GAP_STATUSES))}"
            )
        return v


class ApproveRemediation(BaseModel):
    reviewer_notes: Optional[str] = None


class AcceptRisk(BaseModel):
    rationale: str

    @field_validator("rationale")
    @classmethod
    def rationale_min_length(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("Rationale must be at least 20 characters.")
        return v.strip()


# =============================================================================
#  Endpoints
# =============================================================================

@router.get("")
async def list_gaps(
    severity:      Optional[str] = None,
    status_filter: Optional[str] = None,
    standard:      Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """List all gap findings, sorted Critical → Major → Minor then by clause."""
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
    Create a gap finding manually or from an external tool.
    Auto-generates a sequential GapId (GAP-{STANDARD}-{YY}-{NNN}) and
    sets a default target date based on severity.
    """
    gap_id = await _next_gap_id(body.standard)
    gap_key = f"{body.standard}|{body.clause}|{body.gap_category}"

    target = (
        body.target_date
        or (date.today() + timedelta(days=SEVERITY_DAYS.get(body.severity, 90))).isoformat()
    )

    fields: dict = {
        "Title":        body.finding[:255],
        "GapId":        gap_id,
        "GapKey":       gap_key,
        "Standard":     body.standard,
        "Clause":       body.clause,
        "ClauseTitle":  body.clause_title,
        "GapCategory":  body.gap_category,
        "Severity":     body.severity,
        "Finding":      body.finding,
        "Impact":       body.impact,
        "RemediationHint": body.remediation_hint,
        "Status":       "Open",
        "TargetDate":   target,
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
    """Update gap status, assignee, or resolution notes."""
    try:
        fields: dict = {"Status": body.status}
        if body.resolution_notes:     fields["ResolutionNotes"]   = body.resolution_notes
        if body.assigned_to:          fields["AssignedTo"]        = body.assigned_to
        if body.assigned_to_entra_id: fields["AssignedToEntraId"] = body.assigned_to_entra_id
        if body.target_date:          fields["TargetDate"]        = body.target_date

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_gap(updated)
    except Exception as exc:
        _handle(exc, f"update gap status {item_id}")


@router.post("/{item_id}/approve-remediation")
async def approve_remediation(
    item_id: str,
    body: ApproveRemediation,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Compliance Lead approves the proposed remediation package for a gap.
    If the package includes a document action, creates a Document Lifecycle entry
    and links it back to the gap.
    Sets gap status to 'In progress'.
    """
    if "OrgOS.Admin" not in user.roles and "Compliance.Lead" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Compliance Lead or OrgOS Admin required to approve remediation.",
        )

    try:
        gap = _sp_to_gap(await get_list_item(_list_id(), _LIST_NAME, item_id))

        if gap["Status"] not in ("Open", "In progress"):
            raise HTTPException(
                status_code=422,
                detail=f"Cannot approve remediation for a gap with status '{gap['Status']}'.",
            )

        if gap["LinkedLifecycleId"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A lifecycle entry ({gap['LinkedLifecycleId']}) already exists for this gap. "
                    "Approve the existing lifecycle item or close it before creating a new one."
                ),
            )

        # Parse the proposed remediation package
        pkg = None
        if gap["ProposedRemediation"]:
            try:
                pkg = json.loads(gap["ProposedRemediation"])
            except Exception:
                pkg = None

        lifecycle_id = ""

        # Create Document Lifecycle entry if the package has a document action
        if pkg and pkg.get("document") and settings.is_list_configured(
            settings.document_lifecycle_list_id
        ):
            doc_title = pkg["document"][:255]
            notes_parts = [f"Gap remediation for {gap['Standard']} {gap['Clause']}."]
            if body.reviewer_notes:
                notes_parts.append(f"Reviewer notes: {body.reviewer_notes}")

            lifecycle_fields: dict = {
                "Title":            doc_title,
                "Stage":            "Review",
                "Trigger":          "Gap Remediation",
                "AIGenerated":      False,
                "OwnerEntraId":     user.oid,
                "LinkedGapId":      gap["GapId"] or item_id,
                "Notes":            " ".join(notes_parts),
            }
            if pkg.get("standards_mapping"):
                lifecycle_fields["StandardsMapping"] = pkg["standards_mapping"]

            try:
                lc_item     = await create_list_item(
                    settings.document_lifecycle_list_id,
                    "Document Lifecycle",
                    lifecycle_fields,
                )
                lifecycle_id = str(lc_item.get("id", ""))
                logger.info(
                    f"Lifecycle entry {lifecycle_id} created for gap {item_id} "
                    f"({gap['Standard']} {gap['Clause']})"
                )
            except Exception as exc:
                logger.error(f"Failed to create lifecycle entry for gap {item_id}: {exc}")

        # Update the gap
        resolution = "Remediation package approved."
        if body.reviewer_notes:
            resolution += f" Notes: {body.reviewer_notes}"

        gap_updates: dict = {
            "Status":          "In progress",
            "ResolutionNotes": resolution,
        }
        if lifecycle_id:
            gap_updates["LinkedLifecycleId"] = lifecycle_id

        await update_list_item(_list_id(), _LIST_NAME, item_id, gap_updates)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)

        result = {
            "gap":         _sp_to_gap(updated),
            "lifecycle_id": lifecycle_id,
            "message":     (
                "Remediation package approved. Gap marked In progress."
                + (f" Document Lifecycle entry {lifecycle_id} created." if lifecycle_id else "")
            ),
        }
        return result

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"approve remediation for gap {item_id}")


@router.post("/{item_id}/accept-risk")
async def accept_risk(
    item_id: str,
    body: AcceptRisk,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    ExCo accepts the risk rather than remediating.
    Creates a Strategic Risk Register entry linked to this gap.
    Updates gap status to 'Accepted risk' with acceptor and date recorded.
    Per DRG-QI-REF-DINT-01-26 Section 4.11.
    """
    if "OrgOS.Admin" not in user.roles and "Compliance.Lead" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Compliance Lead or OrgOS Admin required to accept risk.",
        )

    try:
        gap = _sp_to_gap(await get_list_item(_list_id(), _LIST_NAME, item_id))

        if gap["Status"] == "Accepted risk":
            raise HTTPException(
                status_code=409,
                detail="This gap has already been accepted as risk.",
            )

        # Derive risk parameters from gap severity
        likelihood = "Medium"
        impact     = "High" if gap["Severity"] == "Critical" else "Medium"
        risk_score = _LIKELIHOOD_MAP[likelihood] * _IMPACT_MAP[impact]
        today      = date.today()
        risk_id    = await _generate_risk_id()

        risk_fields = {
            "RiskId":         risk_id,
            "Title":          f"Accepted risk: {gap['Finding'][:200]}",
            "Description":    gap["Finding"],
            "Category":       "SWOT — Threat",
            "Source":         "Gap acceptance",
            "Likelihood":     likelihood,
            "Impact":         impact,
            "RiskScore":      risk_score,
            "OwnerEntraId":   user.oid,
            "Owner":          user.name,
            "Treatment":      "Accept",
            "Status":         "Accepted",
            "DateIdentified": today.isoformat(),
            "ReviewDate":     (today + timedelta(days=90)).isoformat(),
            "RelatedGapId":   gap["GapId"] or item_id,
            "Notes":          f"ExCo rationale: {body.rationale}",
            "AcceptedBy":     user.name,
            "AcceptedDate":   today.isoformat(),
            "LastReviewed":   today.isoformat(),
        }

        await create_list_item(
            settings.strategic_risk_register_list_id,
            "Strategic Risk Register",
            risk_fields,
        )

        await update_list_item(_list_id(), _LIST_NAME, item_id, {
            "Status":          "Accepted risk",
            "LinkedRiskId":    risk_id,      # human-readable RSK-YY-NNN — shown on the gap card
            "AcceptedBy":      user.name,
            "AcceptedDate":    today.isoformat(),
            "ResolutionNotes": (
                f"Risk accepted by {user.name} on {today.isoformat()}. "
                f"Rationale: {body.rationale}"
            ),
        })

        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return {
            "gap":     _sp_to_gap(updated),
            "risk_id": risk_id,
            "message": (
                "Gap marked as accepted risk. "
                "Strategic Risk Register entry created."
            ),
        }

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"accept risk for gap {item_id}")
