# =============================================================================
# review_queue/router.py — AI Review Queue API
# Three zone decide endpoints, each with correct decisions and cascade logic.
#
# Zone 1 — Extraction Review
#   Decisions: Accept, Edit and Accept, Reject, Mark False Positive,
#              Request Second Review, Route to Owner
#   Cascade on Accept: creates Control Register + Evidence Tracker + Audit Log
#
# Zone 2 — Assignment & Ownership (orphans from JD extraction)
#   Decisions: Create new document, Add to existing policy, Intentional,
#              Remove from JD, Mark False Positive, Request Second Review
#   Cascade: Create new document → Document Lifecycle entry
#
# Zone 3 — Harmonisation (variant terms, near-duplicate controls)
#   Decisions: Merge, Partial merge, Keep separate, Rename and standardise
#   Cascade: Merge → update CanonicalName in AI Review Queue item
# =============================================================================

import logging
from datetime import date, timezone, datetime, timedelta
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/queue", tags=["AI Review Queue"])

_Q_LIST  = "AI Review Queue"
_CR_LIST = "Control Register"
_EV_LIST = "Evidence Tracker"
_AL_LIST = "Audit Log"
_DL_LIST = "Document Lifecycle"
_RR_LIST = "Role Register"
_SR_LIST = "Strategic Risk Register"


def _q_id():  return settings.ai_review_queue_list_id
def _cr_id(): return settings.control_register_list_id
def _ev_id(): return settings.evidence_tracker_list_id
def _al_id(): return settings.audit_log_list_id
def _dl_id(): return settings.document_lifecycle_list_id
def _rr_id(): return settings.role_register_list_id
def _sr_id(): return settings.strategic_risk_register_list_id


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.exception(f"Error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


def _sp_to_item(item: dict) -> dict:
    f = item.get("fields", {})
    return {
        "id":                       str(item["id"]),
        "Title":                    f.get("Title", ""),
        "ItemType":                 f.get("ItemType", ""),
        "DocumentType":             f.get("DocumentType", ""),
        "SourceDocumentCode":       f.get("SourceDocumentCode", ""),
        "SourceDocumentUrl":        f.get("SourceDocumentUrl", ""),
        "SourceClause":             f.get("SourceClause", ""),
        "ControlStatement":         f.get("ControlStatement", ""),
        "ControlType":              f.get("ControlType", ""),
        "RiskStatement":            f.get("RiskStatement", ""),
        "ProposedOwnerRole":        f.get("ProposedOwnerRole", ""),
        "ISOClause":                f.get("ISOClause", ""),
        "EvidenceType":             f.get("EvidenceType", ""),
        "EvidenceDescription":      f.get("EvidenceDescription", ""),
        "EvidenceSourceSystem":     f.get("EvidenceSourceSystem", ""),
        "EvidenceFormat":           f.get("EvidenceFormat", ""),
        "EvidenceFrequency":        f.get("EvidenceFrequency", ""),
        "EvidenceCollectionMethod": f.get("EvidenceCollectionMethod", ""),
        "EvidenceOwnerRole":        f.get("EvidenceOwnerRole", ""),
        "EvidenceValidationCriteria":f.get("EvidenceValidationCriteria", ""),
        "EvidenceUndefined":        f.get("EvidenceUndefined", False),
        "EvidenceUndefinedReason":  f.get("EvidenceUndefinedReason", ""),
        "CompletenessFlag":         f.get("CompletenessFlag", ""),
        "DeficiencyReason":         f.get("DeficiencyReason", ""),
        "ConfidenceScore":          f.get("ConfidenceScore", 0.0),
        "ReviewStatus":             f.get("ReviewStatus", "Pending Review"),
        "Decision":                 f.get("Decision", ""),
        "DecisionRationale":        f.get("DecisionRationale", ""),
        "ReviewedByEntraId":        f.get("ReviewedByEntraId", ""),
        "CascadeResult":            f.get("CascadeResult", ""),
        # Orphan fields
        "ResponsibilityStatement":  f.get("ResponsibilityStatement", ""),
        "OrphanDirection":          f.get("OrphanDirection", ""),
        "OrphanClassification":     f.get("OrphanClassification", ""),
        "OrphanReason":             f.get("OrphanReason", ""),
        # Harmonisation fields
        "VariantTerms":             f.get("VariantTerms", ""),
        "CanonicalName":            f.get("CanonicalName", ""),
        "VariantFrequency":         f.get("VariantFrequency", ""),
        "SourceDocumentCode2":      f.get("SourceDocumentCode2", ""),
    }


# =============================================================================
#  List endpoint — fetch queue items with optional item_type filter
# =============================================================================

@router.get("/items")
async def list_queue_items(
    item_type:    Optional[str] = None,
    review_status:Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    try:
        raw   = await get_list_items(_q_id(), _Q_LIST)
        items = [_sp_to_item(i) for i in raw]

        # Python-side filtering (SharePoint OData filtering on unindexed fields causes 400)
        if item_type:
            items = [i for i in items if i["ItemType"].lower() == item_type.lower()]
        if review_status:
            items = [i for i in items if i["ReviewStatus"].lower() == review_status.lower()]

        return items
    except Exception as exc:
        _handle(exc, "list queue items")


@router.get("/items/{item_id}")
async def get_queue_item(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_q_id(), _Q_LIST, item_id)
        return _sp_to_item(item)
    except Exception as exc:
        _handle(exc, f"get queue item {item_id}")


# =============================================================================
#  Zone 1 — Extraction Review decide
# =============================================================================

ZONE1_DECISIONS = {
    "Accept",
    "Edit and Accept",
    "Reject",
    "Mark False Positive",
    "Request Second Review",
    "Route to Owner",
}


class Zone1DecideBody(BaseModel):
    decision:          str
    rationale:         str
    # Edit and Accept overrides
    control_statement: Optional[str] = None
    control_type:      Optional[str] = None
    proposed_owner:    Optional[str] = None
    iso_clause:        Optional[str] = None
    evidence_type:     Optional[str] = None
    evidence_description:         Optional[str] = None
    evidence_source_system:       Optional[str] = None
    evidence_frequency:           Optional[str] = None
    evidence_collection_method:   Optional[str] = None
    evidence_owner_role:          Optional[str] = None
    evidence_validation_criteria: Optional[str] = None


async def _zone1_accept_cascade(item: dict, user: CurrentUser, overrides: dict) -> str:
    """
    Accept cascade — creates:
      1. Control Register entry
      2. Evidence Tracker entry (if evidence defined)
      3. Audit Log record
    Returns a summary string for CascadeResult.
    """
    created = []

    control_stmt = overrides.get("control_statement") or item.get("ControlStatement", "")
    control_type = overrides.get("control_type")      or item.get("ControlType", "")
    owner_role   = overrides.get("proposed_owner")    or item.get("ProposedOwnerRole", "")
    iso_clause   = overrides.get("iso_clause")        or item.get("ISOClause", "")
    evidence_type= overrides.get("evidence_type")     or item.get("EvidenceType", "")
    evd_desc     = overrides.get("evidence_description") or item.get("EvidenceDescription", "")

    # 1. Control Register
    try:
        cr_fields = {
            "Title":            control_stmt[:255],
            "ControlStatement": control_stmt,
            "ControlType":      control_type,
            "OwnerRole":        owner_role,
            "OwnerEntraId":     "",
            "ISOClause":        iso_clause,
            "SourceDocument":   item.get("SourceDocumentCode", ""),
            "SourceClause":     item.get("SourceClause", ""),
            "RiskImplication":  item.get("RiskStatement", "")[:500],
            "Status":           "Active" if owner_role else "Blocked",
            "ConfirmedByEntraId": user.oid,
            "ConfirmedDate":    date.today().isoformat(),
            "DecisionRationale": overrides.get("rationale", ""),
        }
        cr_item = await create_list_item(_cr_id(), _CR_LIST, cr_fields)
        cr_id   = str(cr_item["id"])
        created.append(f"Control Register: {cr_id}")
    except Exception as exc:
        logger.error(f"Control Register cascade failed: {exc}")
        cr_id = None

    # 2. Evidence Tracker — only if evidence is defined
    ev_id = None
    evidence_undefined = item.get("EvidenceUndefined")
    if isinstance(evidence_undefined, str):
        evidence_undefined = evidence_undefined.lower() == "true"
    evidence_undefined = bool(evidence_undefined)
    if evidence_type and evidence_undefined and item.get("EvidenceType"):
        evidence_undefined = False

    if evidence_type and not evidence_undefined:
        try:
            ev_fields = {
                "Title":               evd_desc[:255] if evd_desc else f"Evidence for: {control_stmt[:200]}",
                "EvidenceDescription": evd_desc,
                "EvidenceType":        evidence_type,
                "SourceSystem":        overrides.get("evidence_source_system") or item.get("EvidenceSourceSystem", ""),
                "Frequency":           overrides.get("evidence_frequency")     or item.get("EvidenceFrequency", ""),
                "CollectionMethod":    overrides.get("evidence_collection_method") or item.get("EvidenceCollectionMethod", ""),
                "OwnerRole":           overrides.get("evidence_owner_role")    or item.get("EvidenceOwnerRole", owner_role),
                "ValidationCriteria":  overrides.get("evidence_validation_criteria") or item.get("EvidenceValidationCriteria", ""),
                "Status":              "Pending",
                "LinkedControlId":     cr_id or "",
                "SourceDocument":      item.get("SourceDocumentCode", ""),
            }
            ev_item = await create_list_item(_ev_id(), _EV_LIST, ev_fields)
            ev_id   = str(ev_item["id"])
            created.append(f"Evidence Tracker: {ev_id}")
        except Exception as exc:
            logger.error(f"Evidence Tracker cascade failed: {exc}")

    # 3. Audit Log
    try:
        al_fields = {
            "Title":             f"Zone 1 Accept — {item.get('SourceDocumentCode', '')}",
            "Action":            "Zone 1 Accept",
            "ReviewerEntraId":   user.oid,
            "ReviewerName":      user.name,
            "Decision":          "Accept",
            "Rationale":         overrides.get("rationale", ""),
            "SourceDocumentCode":item.get("SourceDocumentCode", ""),
            "ControlStatement":  control_stmt[:500],
            "ControlRegisterId": cr_id or "",
            "EvidenceTrackerId": ev_id  or "",
            "Timestamp":         datetime.now(timezone.utc).isoformat(),
        }
        await create_list_item(_al_id(), _AL_LIST, al_fields)
        created.append("Audit Log: 1 record")
    except Exception as exc:
        logger.error(f"Audit Log cascade failed: {exc}")

    return " | ".join(created) if created else "Cascade failed — check logs"


def _split_terms(value: str) -> list[str]:
    """Parse comma/newline separated terms while preserving order."""
    terms: list[str] = []
    for raw in (value or "").replace("\n", ",").split(","):
        term = raw.strip()
        if term and term.lower() not in {t.lower() for t in terms}:
            terms.append(term)
    return terms


def _normalise(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


async def _create_lifecycle_task(
    *,
    title: str,
    trigger: str,
    notes: str,
    user: CurrentUser,
    document_code: Optional[str] = None,
    document_type: Optional[str] = None,
    department: Optional[str] = None,
    sharepoint_file_url: Optional[str] = None,
) -> str:
    fields: dict = {
        "Title":        title[:255],
        "Stage":        "Review",
        "Trigger":      trigger,
        "AIGenerated":  False,
        "Revised":      False,
        "OwnerEntraId": user.oid,
        "Owner":        user.name or user.oid,
        "Notes":        notes[:4000],
    }
    if document_code:
        fields["DocumentCode"] = document_code
    if document_type:
        fields["DocumentType"] = document_type
    if department:
        fields["Department"] = department
    if sharepoint_file_url:
        fields["SharePointFileUrl"] = sharepoint_file_url

    dl_item = await create_list_item(_dl_id(), _DL_LIST, fields)
    return str(dl_item["id"])


async def _find_role_by_title(role_title: str) -> Optional[dict]:
    if not role_title:
        return None
    try:
        roles = await get_list_items(_rr_id(), _RR_LIST)
    except Exception as exc:
        logger.warning(f"Could not fetch Role Register: {exc}")
        return None

    target = _normalise(role_title)
    for role in roles:
        fields = role.get("fields", {})
        title = fields.get("Title", "")
        if _normalise(title) == target:
            return role
    return None


async def _control_owner_update_fields(owner_role: str) -> dict:
    """
    Build the ownership fields for a Control Register update.
    A control is Active only when the canonical role has a current holder.
    """
    role = await _find_role_by_title(owner_role)
    holder_oid = ""
    if role:
        fields = role.get("fields", {})
        holder_oid = (
            fields.get("CurrentHolderEntraId", "")
            or fields.get("CurrentHolderId", "")
            or ""
        )
    return {
        "OwnerRole": owner_role,
        "OwnerEntraId": holder_oid,
        "Status": "Active" if holder_oid else "Blocked",
    }


async def _evidence_owner_update_fields(owner_role: str) -> dict:
    """
    Build ownership fields for Evidence Tracker.
    Evidence Status is workflow state, so do not overwrite it here.
    """
    role = await _find_role_by_title(owner_role)
    holder_oid = ""
    if role:
        fields = role.get("fields", {})
        holder_oid = (
            fields.get("CurrentHolderEntraId", "")
            or fields.get("CurrentHolderId", "")
            or ""
        )
    return {
        "OwnerRole": owner_role,
        "OwnerEntraId": holder_oid,
    }


async def _create_role_if_missing(role_title: str, item: dict, rationale: str) -> str:
    existing = await _find_role_by_title(role_title)
    if existing:
        return f"Role already exists: {existing.get('id')}"

    fields = {
        "Title":            role_title[:255],
        "Department":       item.get("Department") or "Unassigned",
        "JDReference":      item.get("SourceDocumentCode") or "",
        "SourceSystem":     "Manual",
        "AssignmentStatus": "Unassigned",
        "VariantTerms":     item.get("ProposedOwnerRole", "") if item.get("ProposedOwnerRole") != role_title else "",
    }
    role = await create_list_item(_rr_id(), _RR_LIST, fields)
    return f"Role Register: created '{role_title}' ({role['id']})"


async def _append_role_variants(canonical_name: str, variant_terms: list[str]) -> str:
    role = await _find_role_by_title(canonical_name)
    if not role:
        fields = {
            "Title":            canonical_name[:255],
            "Department":       "Unassigned",
            "JDReference":      "",
            "SourceSystem":     "Manual",
            "AssignmentStatus": "Unassigned",
            "VariantTerms":     ", ".join(variant_terms),
        }
        created = await create_list_item(_rr_id(), _RR_LIST, fields)
        return f"Role Register: created canonical role '{canonical_name}' ({created['id']})"

    fields = role.get("fields", {})
    existing_terms = _split_terms(fields.get("VariantTerms", ""))
    merged_terms = existing_terms[:]
    for term in variant_terms:
        if term and _normalise(term) != _normalise(canonical_name):
            if term.lower() not in {t.lower() for t in merged_terms}:
                merged_terms.append(term)

    await update_list_item(
        _rr_id(),
        _RR_LIST,
        str(role["id"]),
        {"VariantTerms": ", ".join(merged_terms)},
    )
    return f"Role Register: updated variants for '{canonical_name}'"


async def _update_control_owner_variants(canonical_name: str, variant_terms: list[str]) -> str:
    try:
        controls = await get_list_items(_cr_id(), _CR_LIST)
    except Exception as exc:
        logger.warning(f"Could not fetch Control Register: {exc}")
        return "Control Register update skipped"

    variants = {_normalise(v) for v in variant_terms if v}
    variants.add(_normalise(canonical_name))
    update_fields = await _control_owner_update_fields(canonical_name)
    updated = 0
    for control in controls:
        fields = control.get("fields", {})
        owner_role = fields.get("OwnerRole", "")
        needs_refresh = (
            owner_role != canonical_name
            or fields.get("OwnerEntraId", "") != update_fields["OwnerEntraId"]
            or fields.get("Status", "") != update_fields["Status"]
        )
        if owner_role and _normalise(owner_role) in variants and needs_refresh:
            await update_list_item(
                _cr_id(),
                _CR_LIST,
                str(control["id"]),
                update_fields,
            )
            updated += 1
    return (
        f"Control Register: {updated} owner role(s) standardised"
        f" ({update_fields['Status']})"
    )


async def _update_evidence_owner_variants(canonical_name: str, variant_terms: list[str]) -> str:
    try:
        evidence_items = await get_list_items(_ev_id(), _EV_LIST)
    except Exception as exc:
        logger.warning(f"Could not fetch Evidence Tracker: {exc}")
        return "Evidence Tracker update skipped"

    variants = {_normalise(v) for v in variant_terms if v}
    variants.add(_normalise(canonical_name))
    update_fields = await _evidence_owner_update_fields(canonical_name)
    updated = 0
    for evidence in evidence_items:
        fields = evidence.get("fields", {})
        owner_role = fields.get("OwnerRole", "")
        needs_refresh = (
            owner_role != canonical_name
            or fields.get("OwnerEntraId", "") != update_fields["OwnerEntraId"]
        )
        if owner_role and _normalise(owner_role) in variants and needs_refresh:
            await update_list_item(
                _ev_id(),
                _EV_LIST,
                str(evidence["id"]),
                update_fields,
            )
            updated += 1
    return f"Evidence Tracker: {updated} owner role(s) standardised"


async def _update_matching_control_owner(item: dict, target_role: str) -> str:
    stmt = item.get("ControlStatement", "")
    if not stmt or not target_role:
        return "Control reassignment skipped — missing control statement or target role"

    try:
        controls = await get_list_items(_cr_id(), _CR_LIST)
    except Exception as exc:
        logger.warning(f"Could not fetch Control Register: {exc}")
        return "Control reassignment skipped"

    updated = 0
    source_doc = item.get("SourceDocumentCode", "")
    update_fields = await _control_owner_update_fields(target_role)
    for control in controls:
        fields = control.get("fields", {})
        same_statement = _normalise(fields.get("ControlStatement", "")) == _normalise(stmt)
        same_source = not source_doc or fields.get("SourceDocument", "") == source_doc
        if same_statement and same_source:
            await update_list_item(
                _cr_id(),
                _CR_LIST,
                str(control["id"]),
                update_fields,
            )
            updated += 1
    return (
        f"Control Register: {updated} matching control(s) reassigned to '{target_role}'"
        f" ({update_fields['Status']})"
    )


async def _update_matching_evidence_owner(item: dict, target_role: str) -> str:
    stmt = item.get("ControlStatement", "")
    if not stmt and not target_role:
        return "Evidence reassignment skipped — missing control statement or target role"

    try:
        evidence_items = await get_list_items(_ev_id(), _EV_LIST)
    except Exception as exc:
        logger.warning(f"Could not fetch Evidence Tracker: {exc}")
        return "Evidence reassignment skipped"

    updated = 0
    source_doc = item.get("SourceDocumentCode", "")
    current_role = item.get("ProposedOwnerRole", "")
    update_fields = await _evidence_owner_update_fields(target_role)
    for evidence in evidence_items:
        fields = evidence.get("fields", {})
        same_source = not source_doc or fields.get("SourceDocument", "") == source_doc
        same_role = not current_role or _normalise(fields.get("OwnerRole", "")) == _normalise(current_role)
        same_control = not stmt or stmt[:180].lower() in (fields.get("Title", "") + " " + fields.get("EvidenceDescription", "")).lower()
        if same_source and (same_role or same_control):
            await update_list_item(
                _ev_id(),
                _EV_LIST,
                str(evidence["id"]),
                update_fields,
            )
            updated += 1
    return f"Evidence Tracker: {updated} matching item(s) reassigned to '{target_role}'"


async def _create_strategic_risk_from_zone2(
    item: dict,
    rationale: str,
    user: CurrentUser,
) -> str:
    stmt = item.get("ResponsibilityStatement") or item.get("ControlStatement") or item.get("Title", "")
    fields = {
        "Title":          f"ExCo escalation: {stmt[:200]}",
        "Description":    (
            f"Assignment/ownership conflict requires ExCo decision.\n\n"
            f"Source: {item.get('SourceDocumentCode', '')}\n"
            f"Statement: {stmt}\n"
            f"Reason: {item.get('OrphanReason', '')}"
        )[:4000],
        "Category":       "SWOT — Threat",
        "Source":         "Zone 2 Assignment escalation",
        "Likelihood":     "Medium",
        "Impact":         "High",
        "RiskScore":      6,
        "OwnerEntraId":   user.oid,
        "Treatment":      "Mitigate",
        "TreatmentActions": "ExCo to confirm governing requirement, accountable owner, and required document changes.",
        "Status":         "Open",
        "DateIdentified": date.today().isoformat(),
        "ReviewDate":     (date.today() + timedelta(days=90)).isoformat(),
        "EscalationNote": rationale,
        "Notes":          f"Queue item escalated by {user.name or user.oid}.",
    }
    risk = await create_list_item(_sr_id(), _SR_LIST, fields)
    return f"Strategic Risk Register: {risk['id']}"


@router.patch("/items/{item_id}/decide")
async def zone1_decide(
    item_id: str,
    body: Zone1DecideBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if body.decision not in ZONE1_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decision for Zone 1. Must be one of: {', '.join(sorted(ZONE1_DECISIONS))}",
        )
    if not body.rationale or len(body.rationale.strip()) < 5:
        raise HTTPException(status_code=422, detail="Rationale is required (min 5 characters).")

    try:
        item = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))

        status_map = {
            "Accept":               "Accepted",
            "Edit and Accept":      "Accepted",
            "Reject":               "Rejected",
            "Mark False Positive":  "False Positive",
            "Request Second Review":"Pending Second Review",
            "Route to Owner":       "Routed to Owner",
        }

        updates = {
            "ReviewStatus":      status_map[body.decision],
            "Decision":          body.decision,
            "DecisionRationale": body.rationale.strip(),
            "ReviewedByEntraId": user.oid,
        }

        cascade_result = ""
        if body.decision in ("Accept", "Edit and Accept"):
            overrides = {
                "rationale":                    body.rationale,
                "control_statement":            body.control_statement,
                "control_type":                 body.control_type,
                "proposed_owner":               body.proposed_owner,
                "iso_clause":                   body.iso_clause,
                "evidence_type":                body.evidence_type,
                "evidence_description":         body.evidence_description,
                "evidence_source_system":       body.evidence_source_system,
                "evidence_frequency":           body.evidence_frequency,
                "evidence_collection_method":   body.evidence_collection_method,
                "evidence_owner_role":          body.evidence_owner_role,
                "evidence_validation_criteria": body.evidence_validation_criteria,
            }
            cascade_result = await _zone1_accept_cascade(item, user, overrides)
            updates["CascadeResult"] = cascade_result

        await update_list_item(_q_id(), _Q_LIST, item_id, updates)
        updated = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))
        return {"item": updated, "cascade_result": cascade_result}

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"zone1 decide {item_id}")


# =============================================================================
#  Zone 2 — Assignment & Ownership decide
# =============================================================================

ZONE2_DECISIONS = {
    "Create new document",
    "Add to existing policy",
    "Add to existing JD",
    "Reassign control",
    "Create new role",
    "Remove from policy",
    "Intentional",
    "Remove from JD",
    "Mark False Positive",
    "Request Second Review",
    "Select governing document",
    "Escalate to ExCo",
    "Merge",
}


class Zone2DecideBody(BaseModel):
    decision:          str
    rationale:         str
    linked_doc_code:   Optional[str] = None
    target_role:       Optional[str] = None
    reviewer_oid:      Optional[str] = None
    reviewer_name:     Optional[str] = None
    reviewer_email:    Optional[str] = None


async def _zone2_cascade(
    item: dict,
    decision: str,
    rationale: str,
    user: CurrentUser,
    linked_doc_code: Optional[str] = None,
    target_role: Optional[str] = None,
    reviewer: Optional[dict] = None,
) -> str:
    created = []
    stmt = item.get("ResponsibilityStatement") or item.get("ControlStatement") or item.get("Title", "")
    source_doc = item.get("SourceDocumentCode", "")
    source_url = item.get("SourceDocumentUrl", "")

    def notes(action: str) -> str:
        return (
            f"Created from Zone 2 Assignment & Ownership decision.\n"
            f"Decision: {decision}\n"
            f"Action required: {action}\n"
            f"Source: {source_doc}\n"
            f"Statement: {stmt[:700]}\n"
            f"Rationale: {rationale}"
        )

    if decision == "Create new document":
        try:
            lifecycle_id = await _create_lifecycle_task(
                title=f"New governing document needed: {stmt[:180]}",
                trigger="Gap Remediation",
                document_type="Policy",
                notes=notes("Create a new policy/procedure to govern this responsibility."),
                user=user,
            )
            created.append(f"Document Lifecycle: {lifecycle_id}")
        except Exception as exc:
            logger.error(f"Zone 2 Document Lifecycle cascade failed: {exc}")

    elif decision == "Add to existing policy":
        try:
            lifecycle_id = await _create_lifecycle_task(
                title=f"Revise policy {linked_doc_code or source_doc}: {stmt[:160]}",
                trigger="Gap Remediation",
                document_code=linked_doc_code,
                document_type="Policy",
                notes=notes("Revise existing policy/procedure to include this responsibility."),
                user=user,
            )
            created.append(f"Document Lifecycle: {lifecycle_id}")
        except Exception as exc:
            logger.error(f"Zone 2 existing policy cascade failed: {exc}")

    elif decision == "Add to existing JD":
        try:
            lifecycle_id = await _create_lifecycle_task(
                title=f"Revise JD {linked_doc_code or source_doc}: {stmt[:180]}",
                trigger="Gap Remediation",
                document_code=linked_doc_code or source_doc,
                document_type="JobDescription",
                sharepoint_file_url=source_url,
                notes=notes("Revise the relevant JD to include this policy/control responsibility."),
                user=user,
            )
            created.append(f"Document Lifecycle: {lifecycle_id}")
        except Exception as exc:
            logger.error(f"Zone 2 JD revision cascade failed: {exc}")

    elif decision == "Reassign control":
        role = target_role or item.get("ProposedOwnerRole", "")
        if role:
            created.append(await _update_matching_control_owner(item, role))
            created.append(await _update_matching_evidence_owner(item, role))
        else:
            created.append("Control reassignment requires a target role.")

    elif decision == "Create new role":
        role = target_role or item.get("ProposedOwnerRole", "")
        if role:
            try:
                created.append(await _create_role_if_missing(role, item, rationale))
            except Exception as exc:
                logger.error(f"Zone 2 role creation cascade failed: {exc}")
        else:
            created.append("Role creation requires a role title.")

    elif decision == "Remove from policy":
        try:
            lifecycle_id = await _create_lifecycle_task(
                title=f"Remove role/control from policy {source_doc}: {stmt[:160]}",
                trigger="Gap Remediation",
                document_code=source_doc,
                document_type=item.get("DocumentType") or "Policy",
                sharepoint_file_url=source_url,
                notes=notes("Revise the source policy/procedure to remove or correct this role/control reference."),
                user=user,
            )
            created.append(f"Document Lifecycle: {lifecycle_id}")
        except Exception as exc:
            logger.error(f"Zone 2 remove-from-policy cascade failed: {exc}")

    elif decision == "Remove from JD":
        try:
            lifecycle_id = await _create_lifecycle_task(
                title=f"Remove responsibility from JD {source_doc}: {stmt[:160]}",
                trigger="Gap Remediation",
                document_code=source_doc,
                document_type="JobDescription",
                sharepoint_file_url=source_url,
                notes=notes("Revise the JD to remove a responsibility that should not sit with this role."),
                user=user,
            )
            created.append(f"Document Lifecycle: {lifecycle_id}")
        except Exception as exc:
            logger.error(f"Zone 2 remove-from-JD cascade failed: {exc}")

    elif decision == "Select governing document":
        try:
            lifecycle_id = await _create_lifecycle_task(
                title=f"Conflict resolution for governing document: {stmt[:160]}",
                trigger="Gap Remediation",
                document_code=linked_doc_code,
                document_type="Policy",
                notes=notes("Confirm the governing document and revise conflicting document(s)."),
                user=user,
            )
            created.append(f"Document Lifecycle: {lifecycle_id}")
        except Exception as exc:
            logger.error(f"Zone 2 governing-document cascade failed: {exc}")

    elif decision == "Merge":
        try:
            lifecycle_id = await _create_lifecycle_task(
                title=f"Merge conflicting requirements: {stmt[:180]}",
                trigger="Gap Remediation",
                document_code=linked_doc_code or source_doc,
                document_type="Policy",
                notes=notes("Merge conflicting requirements into one approved requirement."),
                user=user,
            )
            created.append(f"Document Lifecycle: {lifecycle_id}")
        except Exception as exc:
            logger.error(f"Zone 2 merge-conflict cascade failed: {exc}")

    elif decision == "Escalate to ExCo":
        try:
            created.append(await _create_strategic_risk_from_zone2(item, rationale, user))
        except Exception as exc:
            logger.error(f"Zone 2 ExCo escalation failed: {exc}")
            created.append("ExCo escalation recorded, but Strategic Risk Register write failed.")

    elif decision == "Intentional":
        created.append("Intentional accountability gap accepted with rationale.")

    elif decision == "Mark False Positive":
        created.append("False positive recorded for classifier tuning.")

    elif decision == "Request Second Review":
        if reviewer and (reviewer.get("name") or reviewer.get("email")):
            label = reviewer.get("name") or reviewer.get("email")
            email = reviewer.get("email", "")
            created.append(f"Second review requested from {label}{f' ({email})' if email and email != label else ''}.")
        else:
            created.append("Second review requested.")

    # Audit Log for all decisions
    try:
        al_fields = {
            "Title":              f"Zone 2 {decision} — {item.get('SourceDocumentCode', '')}",
            "Action":             f"Zone 2: {decision}",
            "ReviewerEntraId":    user.oid,
            "ReviewerName":       user.name,
            "Decision":           decision,
            "Rationale":          rationale,
            "SourceDocumentCode": item.get("SourceDocumentCode", ""),
            "ControlStatement":   (item.get("ResponsibilityStatement") or item.get("ControlStatement", ""))[:500],
            "Timestamp":          datetime.now(timezone.utc).isoformat(),
        }
        await create_list_item(_al_id(), _AL_LIST, al_fields)
        created.append("Audit Log: 1 record")
    except Exception as exc:
        logger.error(f"Zone 2 Audit Log failed: {exc}")

    return " | ".join(created) if created else "Decision recorded"


@router.patch("/items/{item_id}/zone2-decide")
async def zone2_decide(
    item_id: str,
    body: Zone2DecideBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if body.decision not in ZONE2_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid Zone 2 decision. Must be one of: {', '.join(sorted(ZONE2_DECISIONS))}",
        )
    if not body.rationale or len(body.rationale.strip()) < 5:
        raise HTTPException(status_code=422, detail="Rationale is required.")

    try:
        item = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))

        status_map = {
            "Create new document":  "Accepted",
            "Add to existing policy":"Accepted",
            "Add to existing JD":    "Accepted",
            "Reassign control":      "Accepted",
            "Create new role":       "Accepted",
            "Remove from policy":    "Rejected",
            "Intentional":          "Accepted",
            "Remove from JD":       "Rejected",
            "Mark False Positive":  "False Positive",
            "Request Second Review":"Pending Second Review",
            "Select governing document": "Accepted",
            "Escalate to ExCo":      "Pending Second Review",
            "Merge":                 "Accepted",
        }

        cascade_result = await _zone2_cascade(
            item, body.decision, body.rationale.strip(),
            user, body.linked_doc_code, body.target_role,
            {
                "oid": body.reviewer_oid,
                "name": body.reviewer_name,
                "email": body.reviewer_email,
            } if body.reviewer_oid or body.reviewer_name or body.reviewer_email else None,
        )

        updates = {
            "ReviewStatus":      status_map[body.decision],
            "Decision":          body.decision,
            "DecisionRationale": body.rationale.strip(),
            "ReviewedByEntraId": user.oid,
            "CascadeResult":     cascade_result,
        }
        if body.target_role:
            updates["ProposedOwnerRole"] = body.target_role

        await update_list_item(_q_id(), _Q_LIST, item_id, updates)
        updated = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))
        return {"item": updated, "cascade_result": cascade_result}

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"zone2 decide {item_id}")


# =============================================================================
#  Zone 3 — Harmonisation decide
# =============================================================================

ZONE3_DECISIONS = {
    "Merge",
    "Partial merge",
    "Keep separate",
    "Rename and standardise",
}


class Zone3DecideBody(BaseModel):
    decision:       str
    rationale:      str
    canonical_name: Optional[str] = None  # The one true name going forward


async def _zone3_cascade(
    item: dict,
    decision: str,
    rationale: str,
    canonical_name: Optional[str],
    user: CurrentUser,
) -> str:
    created = []
    variant_terms = _split_terms(item.get("VariantTerms", ""))
    if canonical_name:
        variant_terms.append(canonical_name)
    is_role_harmonisation = not item.get("ControlStatement")
    source_doc = item.get("SourceDocumentCode", "")

    if decision in ("Merge", "Rename and standardise") and canonical_name:
        created.append(f"Canonical name confirmed: '{canonical_name}'")
        if is_role_harmonisation:
            try:
                created.append(await _append_role_variants(canonical_name, variant_terms))
                created.append(await _update_control_owner_variants(canonical_name, variant_terms))
                created.append(await _update_evidence_owner_variants(canonical_name, variant_terms))
            except Exception as exc:
                logger.error(f"Zone 3 role harmonisation cascade failed: {exc}")
        else:
            try:
                lifecycle_id = await _create_lifecycle_task(
                    title=f"Standardise duplicate control: {item.get('Title', '')[:180]}",
                    trigger="Gap Remediation",
                    document_code=source_doc,
                    document_type="Policy",
                    notes=(
                        f"Created from Zone 3 Harmonisation decision.\n"
                        f"Decision: {decision}\n"
                        f"Canonical control/name: {canonical_name}\n"
                        f"Source: {source_doc}\n"
                        f"Variant/control terms:\n{item.get('VariantTerms', '')[:1500]}\n"
                        f"Rationale: {rationale}"
                    ),
                    user=user,
                )
                created.append(f"Document Lifecycle: {lifecycle_id}")
            except Exception as exc:
                logger.error(f"Zone 3 duplicate control lifecycle cascade failed: {exc}")

    elif decision == "Partial merge" and canonical_name:
        created.append(f"Partial merge — canonical name '{canonical_name}' confirmed for overlapping variants.")
        if is_role_harmonisation:
            try:
                created.append(await _append_role_variants(canonical_name, variant_terms))
                created.append(await _update_control_owner_variants(canonical_name, variant_terms))
                created.append(await _update_evidence_owner_variants(canonical_name, variant_terms))
                created.append("Remaining variants require manual review.")
            except Exception as exc:
                logger.error(f"Zone 3 partial role harmonisation failed: {exc}")
        else:
            try:
                lifecycle_id = await _create_lifecycle_task(
                    title=f"Partially merge duplicate controls: {item.get('Title', '')[:170]}",
                    trigger="Gap Remediation",
                    document_code=source_doc,
                    document_type="Policy",
                    notes=(
                        f"Created from Zone 3 partial merge decision.\n"
                        f"Canonical control/name: {canonical_name}\n"
                        f"Variant/control terms:\n{item.get('VariantTerms', '')[:1500]}\n"
                        f"Rationale: {rationale}"
                    ),
                    user=user,
                )
                created.append(f"Document Lifecycle: {lifecycle_id}")
            except Exception as exc:
                logger.error(f"Zone 3 partial duplicate lifecycle cascade failed: {exc}")

    elif decision == "Keep separate":
        created.append("Confirmed as separate items — future classifier runs should suppress this exact pair.")

    # Audit Log
    try:
        al_fields = {
            "Title":              f"Zone 3 {decision} — {item.get('SourceDocumentCode', '')}",
            "Action":             f"Zone 3: {decision}",
            "ReviewerEntraId":    user.oid,
            "ReviewerName":       user.name,
            "Decision":           decision,
            "Rationale":          rationale,
            "SourceDocumentCode": item.get("SourceDocumentCode", ""),
            "ControlStatement":   item.get("Title", "")[:500],
            "Timestamp":          datetime.now(timezone.utc).isoformat(),
        }
        await create_list_item(_al_id(), _AL_LIST, al_fields)
        created.append("Audit Log: 1 record")
    except Exception as exc:
        logger.error(f"Zone 3 Audit Log failed: {exc}")

    return " | ".join(created) if created else "Decision recorded"


@router.patch("/items/{item_id}/zone3-decide")
async def zone3_decide(
    item_id: str,
    body: Zone3DecideBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if body.decision not in ZONE3_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid Zone 3 decision. Must be one of: {', '.join(sorted(ZONE3_DECISIONS))}",
        )
    if not body.rationale or len(body.rationale.strip()) < 5:
        raise HTTPException(status_code=422, detail="Rationale is required.")

    try:
        item = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))

        status_map = {
            "Merge":                   "Accepted",
            "Partial merge":           "Accepted",
            "Keep separate":           "Accepted",
            "Rename and standardise":  "Accepted",
        }

        cascade_result = await _zone3_cascade(
            item, body.decision, body.rationale.strip(),
            body.canonical_name, user,
        )

        updates = {
            "ReviewStatus":      status_map[body.decision],
            "Decision":          body.decision,
            "DecisionRationale": body.rationale.strip(),
            "ReviewedByEntraId": user.oid,
            "CascadeResult":     cascade_result,
        }
        if body.canonical_name:
            updates["CanonicalName"] = body.canonical_name

        await update_list_item(_q_id(), _Q_LIST, item_id, updates)
        updated = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))
        return {"item": updated, "cascade_result": cascade_result}

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"zone3 decide {item_id}")
