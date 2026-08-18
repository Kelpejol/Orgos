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
from config import MIN_RATIONALE_CHARS, settings
from graph.client import (
    create_list_item,
    get_list_item,
    get_list_items,
    update_list_item,
)
from graph.exceptions import GraphAPIError, GraphNotFoundError

logger = logging.getLogger(__name__)


class CascadeError(Exception):
    """
    A required cascade step failed. Carries what completed before the failure
    so the queue item can be marked Blocked ("Cascade failed") per DINT §7.5
    instead of silently entering registers in a partial state.
    """

    def __init__(self, step: str, completed: list[str], original: Exception):
        self.step = step
        self.completed = completed
        self.original = original
        super().__init__(f"Cascade failed at step '{step}': {original}")


def _require_rationale(rationale: str) -> str:
    cleaned = (rationale or "").strip()
    if len(cleaned) < MIN_RATIONALE_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Rationale is required (min {MIN_RATIONALE_CHARS} characters).",
        )
    return cleaned

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


async def _mark_cascade_failed(
    item_id: str,
    zone: str,
    decision: str,
    rationale: str,
    user: CurrentUser,
    err: "CascadeError",
) -> None:
    """
    DINT §7.5 — a failed cascade must not leave the queue item looking decided.
    Marks the item Blocked with a "Cascade failed" note recording the failed
    step and any partial writes, and logs the failure to the Audit Log.
    """
    failure_note = (
        f"CASCADE FAILED at step '{err.step}': {err.original}. "
        f"Completed before failure: {'; '.join(err.completed) if err.completed else 'nothing'}. "
        f"Retry the decision or escalate to the System Admin."
    )
    try:
        await update_list_item(_q_id(), _Q_LIST, item_id, {
            "ReviewStatus":      "Blocked",
            "Decision":          decision,
            "DecisionRationale": rationale,
            "ReviewedByEntraId": user.oid,
            "CascadeResult":     failure_note[:4000],
        })
    except Exception as exc:
        logger.error(f"Could not mark queue item {item_id} as cascade-failed: {exc}")

    try:
        await create_list_item(_al_id(), _AL_LIST, {
            "Title":              f"Zone {zone} CASCADE FAILED — {decision}",
            "Action":             f"Zone {zone}: {decision} (cascade failed)",
            "ReviewerEntraId":    user.oid,
            "ReviewerName":       user.name,
            "Decision":           decision,
            "Rationale":          rationale,
            "CascadeResult":      failure_note[:4000],
            "Timestamp":          datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.error(f"Could not audit-log cascade failure for {item_id}: {exc}")


def _cascade_failed_http(err: "CascadeError") -> HTTPException:
    return HTTPException(
        status_code=502,
        detail=(
            f"Cascade failed at step '{err.step}'. The item has been marked Blocked "
            f"and did not fully enter the registers. "
            f"Completed before failure: {'; '.join(err.completed) if err.completed else 'nothing'}. "
            f"You can retry the decision."
        ),
    )


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

# A queue item may only be decided from a non-terminal state. Deciding an
# already-decided item is blocked (409) so a double-click / retry cannot re-run
# a cascade and create duplicate downstream records. "Blocked" is included so a
# genuinely failed cascade can be retried; "Pending Second Review" so a second
# reviewer can still act.
_DECIDABLE_STATUSES = {"", "Pending Review", "Pending Second Review", "Blocked"}


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

    # 1. Control Register — required step; failure aborts the cascade
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
        raise CascadeError("Control Register", created, exc)

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
            # Compensate — withdraw the control so registers don't hold a
            # half-created chain (SharePoint has no transactions; soft-rollback).
            try:
                await update_list_item(_cr_id(), _CR_LIST, cr_id, {
                    "Status": "Withdrawn",
                    "DecisionRationale": "Rolled back — evidence cascade step failed.",
                })
                created.append(f"Control Register {cr_id}: rolled back (Withdrawn)")
            except Exception as undo_exc:
                logger.error(f"Rollback of control {cr_id} also failed: {undo_exc}")
            raise CascadeError("Evidence Tracker", created, exc)

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
        logger.error(f"AUDIT TRAIL GAP — Zone 1 Audit Log write failed for {item.get('id', '')}: {exc}")
        # Non-silent: record the gap on the item itself (persisted to
        # CascadeResult) so the missing audit record is visible, not just logged.
        created.append("⚠ AUDIT LOG NOT WRITTEN — decision not recorded in the audit trail (see server logs)")

    # 4. NL Search index — embed control for semantic search (non-blocking)
    if cr_id and control_stmt:
        try:
            from agents.nl_search.vector_store import embed_and_store_control
            embed_meta = {
                "document_code": item.get("SourceDocumentCode", ""),
                "iso_clause":    iso_clause or "",
                "control_type":  control_type or "",
                "owner_oid":     user.oid,
            }
            await embed_and_store_control(cr_id, control_stmt, embed_meta)
            created.append("NL Search: indexed")
        except Exception as exc:
            logger.warning(f"NL Search index step failed (non-fatal): {exc}")

    return " | ".join(created)


def _split_terms(value: str) -> list[str]:
    """Parse comma/newline separated terms while preserving order."""
    terms: list[str] = []
    for raw in (value or "").replace("\n", ",").split(","):
        term = raw.strip()
        if term and term.lower() not in {t.lower() for t in terms}:
            terms.append(term)
    return terms


def _join_variant_terms(terms: list[str]) -> str:
    """Store Role Register VariantTerms as one term per line."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for term in terms:
        value = str(term or "").strip()
        key = value.lower()
        if value and key not in seen:
            cleaned.append(value)
            seen.add(key)
    return "\n".join(cleaned)


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
            "VariantTerms":     _join_variant_terms(variant_terms),
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
        {"VariantTerms": _join_variant_terms(merged_terms)},
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
    rationale = _require_rationale(body.rationale)

    try:
        item = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))

        # Idempotency guard — only decide from a non-terminal state. Without this
        # a double-click / retry re-runs the accept cascade and creates DUPLICATE
        # Control + Evidence + Audit records. (Mirrors control_register.accept_control.)
        current_status = (item.get("ReviewStatus") or "").strip()
        if current_status not in _DECIDABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This item already has a decision (status '{current_status}'). "
                    "Refresh the queue — re-deciding is blocked to prevent duplicate "
                    "Control/Evidence records."
                ),
            )

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
            "DecisionRationale": rationale,
            "ReviewedByEntraId": user.oid,
        }

        cascade_result = ""
        if body.decision in ("Accept", "Edit and Accept"):
            overrides = {
                "rationale":                    rationale,
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
            try:
                cascade_result = await _zone1_accept_cascade(item, user, overrides)
            except CascadeError as ce:
                await _mark_cascade_failed(item_id, "1", body.decision, rationale, user, ce)
                raise _cascade_failed_http(ce)
            try:
                from agents.classifier.service import run_classifier
                await run_classifier(triggered_by=f"system: zone1 {body.decision} by {user.name or user.oid}")
            except Exception as exc:
                logger.warning(f"Automatic classifier run after Zone 1 decision failed: {exc}")
            updates["CascadeResult"] = cascade_result

        try:
            await update_list_item(_q_id(), _Q_LIST, item_id, updates)
        except Exception as exc:
            # If the create-cascade already ran, the Control/Evidence/Audit
            # records exist but the queue item's status is now stale. Do NOT let
            # the caller retry (the guard above keys off ReviewStatus, still
            # non-terminal here) — a retry would duplicate everything.
            if cascade_result:
                logger.error(
                    f"Zone 1 {item_id}: cascade succeeded but final queue update failed "
                    f"({exc}). Records exist; status is stale — needs manual reconciliation."
                )
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Decision applied — the Control and Evidence records were created — "
                        "but the queue item could not be updated. Do NOT retry (it would create "
                        "duplicates). The records exist; an admin should reconcile this item's status."
                    ),
                )
            raise
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
            raise CascadeError("Document Lifecycle", created, exc)

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
            raise CascadeError("Document Lifecycle", created, exc)

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
            raise CascadeError("Document Lifecycle", created, exc)

    elif decision == "Reassign control":
        role = target_role or item.get("ProposedOwnerRole", "")
        if role:
            try:
                created.append(await _update_matching_control_owner(item, role))
                created.append(await _update_matching_evidence_owner(item, role))
            except Exception as exc:
                raise CascadeError("Control/Evidence reassignment", created, exc)
        else:
            created.append("Control reassignment requires a target role.")

    elif decision == "Create new role":
        role = target_role or item.get("ProposedOwnerRole", "")
        if role:
            try:
                created.append(await _create_role_if_missing(role, item, rationale))
            except Exception as exc:
                raise CascadeError("Role Register", created, exc)
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
            raise CascadeError("Document Lifecycle", created, exc)

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
            raise CascadeError("Document Lifecycle", created, exc)

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
            raise CascadeError("Document Lifecycle", created, exc)

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
            raise CascadeError("Document Lifecycle", created, exc)

    elif decision == "Escalate to ExCo":
        try:
            created.append(await _create_strategic_risk_from_zone2(item, rationale, user))
        except Exception as exc:
            raise CascadeError("Strategic Risk Register", created, exc)

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
        logger.error(f"AUDIT TRAIL GAP — Zone 2 Audit Log write failed: {exc}")
        created.append("⚠ AUDIT LOG NOT WRITTEN — decision not recorded in the audit trail (see server logs)")

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
    rationale = _require_rationale(body.rationale)

    try:
        item = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))

        current_status = (item.get("ReviewStatus") or "").strip()
        if current_status not in _DECIDABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This item already has a decision (status '{current_status}'). "
                    "Refresh the queue — re-deciding is blocked to prevent duplicate records."
                ),
            )

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

        try:
            cascade_result = await _zone2_cascade(
                item, body.decision, rationale,
                user, body.linked_doc_code, body.target_role,
                {
                    "oid": body.reviewer_oid,
                    "name": body.reviewer_name,
                    "email": body.reviewer_email,
                } if body.reviewer_oid or body.reviewer_name or body.reviewer_email else None,
            )
        except CascadeError as ce:
            await _mark_cascade_failed(item_id, "2", body.decision, rationale, user, ce)
            raise _cascade_failed_http(ce)

        updates = {
            "ReviewStatus":      status_map[body.decision],
            "Decision":          body.decision,
            "DecisionRationale": rationale,
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

    source_doc2 = item.get("SourceDocumentCode2", "")

    if decision in ("Merge", "Rename and standardise") and canonical_name:
        created.append(f"Canonical name confirmed: '{canonical_name}'")
        if is_role_harmonisation:
            try:
                created.append(await _append_role_variants(canonical_name, variant_terms))
                created.append(await _update_control_owner_variants(canonical_name, variant_terms))
                created.append(await _update_evidence_owner_variants(canonical_name, variant_terms))
            except Exception as exc:
                raise CascadeError("Role harmonisation", created, exc)
        else:
            shared_notes = (
                f"Created from Zone 3 Harmonisation decision.\n"
                f"Decision: {decision}\n"
                f"Canonical control/name: {canonical_name}\n"
                f"Variant/control terms:\n{item.get('VariantTerms', '')[:1500]}\n"
                f"Rationale: {rationale}"
            )
            for doc_code in filter(None, [source_doc, source_doc2]):
                try:
                    lifecycle_id = await _create_lifecycle_task(
                        title=f"Harmonisation fix — standardise control in {doc_code}: {item.get('Title', '')[:140]}",
                        trigger="Harmonisation Fix",
                        document_code=doc_code,
                        document_type="Policy",
                        notes=shared_notes,
                        user=user,
                    )
                    created.append(f"Document Lifecycle ({doc_code}): {lifecycle_id}")
                except Exception as exc:
                    raise CascadeError(f"Document Lifecycle ({doc_code})", created, exc)

    elif decision == "Partial merge" and canonical_name:
        created.append(f"Partial merge — canonical name '{canonical_name}' confirmed for overlapping variants.")
        if is_role_harmonisation:
            try:
                created.append(await _append_role_variants(canonical_name, variant_terms))
                created.append(await _update_control_owner_variants(canonical_name, variant_terms))
                created.append(await _update_evidence_owner_variants(canonical_name, variant_terms))
                created.append("Remaining variants require manual review.")
            except Exception as exc:
                raise CascadeError("Role harmonisation", created, exc)
        else:
            shared_notes = (
                f"Created from Zone 3 partial merge decision.\n"
                f"Canonical control/name: {canonical_name}\n"
                f"Variant/control terms:\n{item.get('VariantTerms', '')[:1500]}\n"
                f"Rationale: {rationale}"
            )
            for doc_code in filter(None, [source_doc, source_doc2]):
                try:
                    lifecycle_id = await _create_lifecycle_task(
                        title=f"Harmonisation fix — partial merge in {doc_code}: {item.get('Title', '')[:140]}",
                        trigger="Harmonisation Fix",
                        document_code=doc_code,
                        document_type="Policy",
                        notes=shared_notes,
                        user=user,
                    )
                    created.append(f"Document Lifecycle ({doc_code}): {lifecycle_id}")
                except Exception as exc:
                    raise CascadeError(f"Document Lifecycle ({doc_code})", created, exc)

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
        logger.error(f"AUDIT TRAIL GAP — Zone 3 Audit Log write failed: {exc}")
        created.append("⚠ AUDIT LOG NOT WRITTEN — decision not recorded in the audit trail (see server logs)")

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
    rationale = _require_rationale(body.rationale)

    try:
        item = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))

        current_status = (item.get("ReviewStatus") or "").strip()
        if current_status not in _DECIDABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This item already has a decision (status '{current_status}'). "
                    "Refresh the queue — re-deciding is blocked to prevent duplicate records."
                ),
            )

        status_map = {
            "Merge":                   "Accepted",
            "Partial merge":           "Accepted",
            "Keep separate":           "Accepted",
            "Rename and standardise":  "Accepted",
        }

        try:
            cascade_result = await _zone3_cascade(
                item, body.decision, rationale,
                body.canonical_name, user,
            )
        except CascadeError as ce:
            await _mark_cascade_failed(item_id, "3", body.decision, rationale, user, ce)
            raise _cascade_failed_http(ce)

        updates = {
            "ReviewStatus":      status_map[body.decision],
            "Decision":          body.decision,
            "DecisionRationale": rationale,
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


# =============================================================================
#  Cascade impact preview (dry-run) — DINT §2.4 "Decision cascade hints" and
#  the pre-decision cascade impact screen. Read-only: computes what a decision
#  WOULD create/update without writing anything.
# =============================================================================

def _impact_shell(zone: str, decision: str) -> dict:
    return {
        "action":   decision,
        "zone":     zone,
        "summary":  "",
        "creates":  [],
        "updates":  [],
        "flags":    [],
        "warnings": [],
        "blocked":  False,
        "blocked_reason": None,
    }


async def _count_owner_variant_matches(canonical_name: str, variant_terms: list[str]) -> tuple[int, int]:
    """Read-only counts of controls/evidence whose OwnerRole is one of the variants."""
    variants = {_normalise(v) for v in variant_terms if v}
    variants.add(_normalise(canonical_name))

    control_count = 0
    try:
        for control in await get_list_items(_cr_id(), _CR_LIST):
            owner_role = control.get("fields", {}).get("OwnerRole", "")
            if owner_role and _normalise(owner_role) in variants:
                control_count += 1
    except Exception as exc:
        logger.warning(f"Impact preview could not scan Control Register: {exc}")

    evidence_count = 0
    try:
        for evidence in await get_list_items(_ev_id(), _EV_LIST):
            owner_role = evidence.get("fields", {}).get("OwnerRole", "")
            if owner_role and _normalise(owner_role) in variants:
                evidence_count += 1
    except Exception as exc:
        logger.warning(f"Impact preview could not scan Evidence Tracker: {exc}")

    return control_count, evidence_count


async def _count_reassign_matches(item: dict) -> tuple[int, int]:
    """Read-only counts matching the Reassign-control cascade predicates."""
    stmt = item.get("ControlStatement", "")
    source_doc = item.get("SourceDocumentCode", "")
    current_role = item.get("ProposedOwnerRole", "")

    control_count = 0
    try:
        for control in await get_list_items(_cr_id(), _CR_LIST):
            fields = control.get("fields", {})
            same_statement = _normalise(fields.get("ControlStatement", "")) == _normalise(stmt)
            same_source = not source_doc or fields.get("SourceDocument", "") == source_doc
            if stmt and same_statement and same_source:
                control_count += 1
    except Exception as exc:
        logger.warning(f"Impact preview could not scan Control Register: {exc}")

    evidence_count = 0
    try:
        for evidence in await get_list_items(_ev_id(), _EV_LIST):
            fields = evidence.get("fields", {})
            same_source = not source_doc or fields.get("SourceDocument", "") == source_doc
            same_role = not current_role or _normalise(fields.get("OwnerRole", "")) == _normalise(current_role)
            same_control = not stmt or stmt[:180].lower() in (fields.get("Title", "") + " " + fields.get("EvidenceDescription", "")).lower()
            if same_source and (same_role or same_control):
                evidence_count += 1
    except Exception as exc:
        logger.warning(f"Impact preview could not scan Evidence Tracker: {exc}")

    return control_count, evidence_count


async def _zone1_impact(item: dict, decision: str, impact: dict) -> dict:
    status_map = {
        "Accept":                "Accepted",
        "Edit and Accept":       "Accepted",
        "Reject":                "Rejected",
        "Mark False Positive":   "False Positive",
        "Request Second Review": "Pending Second Review",
        "Route to Owner":        "Routed to Owner",
    }
    new_status = status_map.get(decision, "Accepted")

    if decision in ("Accept", "Edit and Accept"):
        control_stmt = item.get("ControlStatement", "")
        if not control_stmt:
            impact["blocked"] = True
            impact["blocked_reason"] = "Cannot accept — the queue item has no control statement."
            return impact

        owner_role = item.get("ProposedOwnerRole", "")
        holder_oid = ""
        if owner_role:
            role = await _find_role_by_title(owner_role)
            if role:
                fields = role.get("fields", {})
                holder_oid = fields.get("CurrentHolderEntraId", "") or fields.get("CurrentHolderId", "") or ""

        control_state = "Active" if (owner_role and holder_oid) else "Blocked"
        impact["creates"].append({
            "register": "Control Register",
            "detail": (
                f"{item.get('ControlType') or 'Control'} — “{control_stmt[:140]}"
                f"{'…' if len(control_stmt) > 140 else ''}”, owner: {owner_role or 'Unknown'}, "
                f"status: {control_state}"
            ),
        })

        evidence_type = item.get("EvidenceType", "")
        if evidence_type:
            impact["creates"].append({
                "register": "Evidence Tracker",
                "detail": (
                    f"{evidence_type} evidence — {item.get('EvidenceDescription', '')[:120] or 'per Evidence Taxonomy'}, "
                    f"frequency: {item.get('EvidenceFrequency') or 'not set'}, status: Pending"
                ),
            })
        else:
            impact["warnings"].append(
                "No evidence type is defined — no Evidence Tracker entry will be created. "
                "The control chain will be incomplete until evidence is designed."
            )

        impact["creates"].append({
            "register": "Audit Log",
            "detail": "Decision record — reviewer, rationale, cascade result.",
        })
        impact["updates"].append({
            "register": "AI Review Queue",
            "detail": f"Item → {new_status}.",
        })

        iso_clause = item.get("ISOClause", "")
        if iso_clause:
            impact["updates"].append({
                "register": "Standards Map",
                "detail": f"Clause {iso_clause} traffic light recalculates with the new control.",
            })
        else:
            impact["warnings"].append("No ISO clause mapped — the control will show as Unmapped on the Standards Map.")

        if not owner_role:
            impact["warnings"].append("No owner role proposed — the control will be created as Blocked (unassigned owner).")
        elif not holder_oid:
            impact["warnings"].append(
                f"Owner role “{owner_role}” has no current holder in the Role Register — "
                "the control will be created as Blocked until the role is assigned."
            )

        impact["summary"] = (
            f"Accepting creates {len(impact['creates'])} record(s) and updates the queue item."
        )
    else:
        impact["updates"].append({
            "register": "AI Review Queue",
            "detail": f"Item → {new_status}. No register entries are created.",
        })
        impact["creates"].append({
            "register": "Audit Log",
            "detail": "Decision record — reviewer, rationale.",
        })
        if decision in ("Reject", "Mark False Positive"):
            impact["flags"].append({
                "register": "Extractor / Classifier",
                "detail": "Rejection is recorded for model improvement.",
            })
        impact["summary"] = f"“{decision}” updates the queue item only — nothing enters the registers."

    return impact


async def _zone2_impact(item: dict, decision: str, impact: dict,
                        target_role: Optional[str], linked_doc_code: Optional[str]) -> dict:
    stmt = (item.get("ResponsibilityStatement") or item.get("ControlStatement") or item.get("Title", ""))[:120]
    source_doc = item.get("SourceDocumentCode", "")

    lifecycle_decisions = {
        "Create new document":       f"New document task: “{stmt}” (trigger: Gap Remediation).",
        "Add to existing policy":    f"Revision task for policy {linked_doc_code or '— select a policy'}.",
        "Add to existing JD":        f"Revision task for JD {linked_doc_code or source_doc}.",
        "Remove from policy":        f"Revision task to remove the reference from {source_doc}.",
        "Remove from JD":            f"Revision task to remove the responsibility from JD {source_doc}.",
        "Select governing document": f"Conflict-resolution task for {linked_doc_code or 'the selected governing document'}.",
        "Merge":                     f"Merge-requirements task for {linked_doc_code or source_doc}.",
    }

    if decision in lifecycle_decisions:
        impact["creates"].append({
            "register": "Document Lifecycle",
            "detail": lifecycle_decisions[decision] + " Enters at the Review stage.",
        })

    elif decision == "Reassign control":
        role = target_role or item.get("ProposedOwnerRole", "")
        if not role:
            impact["blocked"] = True
            impact["blocked_reason"] = "Reassign control requires a target role."
            return impact
        control_count, evidence_count = await _count_reassign_matches(item)
        holder_role = await _find_role_by_title(role)
        holder_oid = ""
        if holder_role:
            rf = holder_role.get("fields", {})
            holder_oid = rf.get("CurrentHolderEntraId", "") or rf.get("CurrentHolderId", "") or ""
        impact["updates"].append({
            "register": "Control Register",
            "detail": f"{control_count} matching control(s) reassigned to “{role}” ({'Active' if holder_oid else 'Blocked'}).",
        })
        impact["updates"].append({
            "register": "Evidence Tracker",
            "detail": f"{evidence_count} matching evidence item(s) reassigned to “{role}”.",
        })
        if not holder_oid:
            impact["warnings"].append(
                f"Role “{role}” has no current holder — reassigned controls will be Blocked until the role is assigned."
            )

    elif decision == "Create new role":
        role = target_role or item.get("ProposedOwnerRole", "")
        if not role:
            impact["blocked"] = True
            impact["blocked_reason"] = "Create new role requires a role title."
            return impact
        existing = await _find_role_by_title(role)
        if existing:
            impact["warnings"].append(f"Role “{role}” already exists in the Role Register — no new role will be created.")
        else:
            impact["creates"].append({
                "register": "Role Register",
                "detail": f"New role “{role}”, status: Unassigned (Blocked until a person is assigned).",
            })
            impact["flags"].append({
                "register": "Work Hub",
                "detail": "Compliance is surfaced: “New role requires person assignment.”",
            })

    elif decision == "Escalate to ExCo":
        impact["creates"].append({
            "register": "Strategic Risk Register",
            "detail": f"ExCo escalation risk entry — “{stmt}”, treatment: Mitigate, review in 90 days.",
        })

    elif decision == "Intentional":
        impact["updates"].append({
            "register": "AI Review Queue",
            "detail": "Gap accepted as intentional — decision and rationale logged, available for audit.",
        })

    status_map = {
        "Create new document": "Accepted", "Add to existing policy": "Accepted",
        "Add to existing JD": "Accepted", "Reassign control": "Accepted",
        "Create new role": "Accepted", "Remove from policy": "Rejected",
        "Intentional": "Accepted", "Remove from JD": "Rejected",
        "Mark False Positive": "False Positive", "Request Second Review": "Pending Second Review",
        "Select governing document": "Accepted", "Escalate to ExCo": "Pending Second Review",
        "Merge": "Accepted",
    }
    impact["updates"].append({
        "register": "AI Review Queue",
        "detail": f"Item → {status_map.get(decision, 'Accepted')}.",
    })
    impact["creates"].append({
        "register": "Audit Log",
        "detail": "Decision record — reviewer, rationale, cascade result.",
    })
    impact["summary"] = (
        f"“{decision}” creates {len(impact['creates'])} record(s) "
        f"and updates {len(impact['updates'])} register(s)."
    )
    return impact


async def _zone3_impact(item: dict, decision: str, impact: dict, canonical_name: Optional[str]) -> dict:
    variant_terms = _split_terms(item.get("VariantTerms", ""))
    canonical = canonical_name or item.get("CanonicalName", "")
    is_role_harmonisation = not item.get("ControlStatement")
    source_docs = [d for d in [item.get("SourceDocumentCode", ""), item.get("SourceDocumentCode2", "")] if d]

    if decision == "Keep separate":
        impact["updates"].append({
            "register": "AI Review Queue",
            "detail": "Items confirmed as genuinely different — all entries remain; the classifier learns to distinguish them.",
        })
    elif decision in ("Merge", "Partial merge", "Rename and standardise"):
        if not canonical:
            impact["blocked"] = True
            impact["blocked_reason"] = "A canonical name is required for this decision."
            return impact

        if is_role_harmonisation:
            control_count, evidence_count = await _count_owner_variant_matches(canonical, variant_terms)
            existing_role = await _find_role_by_title(canonical)
            holder_oid = ""
            if existing_role:
                rf = existing_role.get("fields", {})
                holder_oid = rf.get("CurrentHolderEntraId", "") or rf.get("CurrentHolderId", "") or ""
                impact["updates"].append({
                    "register": "Role Register",
                    "detail": f"Role “{canonical}” absorbs {len(variant_terms)} variant term(s).",
                })
            else:
                impact["creates"].append({
                    "register": "Role Register",
                    "detail": f"New canonical role “{canonical}” (Unassigned) holding the variant terms.",
                })
            impact["updates"].append({
                "register": "Control Register",
                "detail": f"{control_count} control(s) whose owner matches a variant are re-pointed to “{canonical}”.",
            })
            impact["updates"].append({
                "register": "Evidence Tracker",
                "detail": f"{evidence_count} evidence item(s) re-pointed to “{canonical}”.",
            })
            if not holder_oid:
                impact["warnings"].append(
                    f"“{canonical}” has no current holder — re-pointed controls will be Blocked until the role is assigned."
                )
            if decision == "Partial merge":
                impact["warnings"].append("Partial merge: remaining variants stay separate and require manual review.")
        else:
            for doc_code in source_docs:
                impact["creates"].append({
                    "register": "Document Lifecycle",
                    "detail": f"Harmonisation-fix revision task for {doc_code} (standardise to “{canonical}”).",
                })
            if not source_docs:
                impact["warnings"].append("No source document codes on this item — no lifecycle revision tasks will be created.")

    impact["updates"].append({
        "register": "AI Review Queue",
        "detail": "Item → Accepted" + (f"; canonical name set to “{canonical}”." if canonical else "."),
    })
    impact["creates"].append({
        "register": "Audit Log",
        "detail": "Decision record — reviewer, rationale, cascade result.",
    })
    impact["summary"] = (
        f"“{decision}” creates {len(impact['creates'])} record(s) "
        f"and updates {len(impact['updates'])} register(s)."
    )
    return impact


@router.get("/items/{item_id}/impact")
async def decision_impact(
    item_id: str,
    zone: str,
    decision: str,
    target_role:     Optional[str] = None,
    linked_doc_code: Optional[str] = None,
    canonical_name:  Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Read-only cascade impact preview for a queue decision.
    Returns {creates, updates, flags, warnings, blocked} so the UI can show
    the full downstream effect before the reviewer confirms.
    """
    if zone not in ("1", "2", "3"):
        raise HTTPException(status_code=422, detail="zone must be '1', '2' or '3'.")

    valid = {"1": ZONE1_DECISIONS, "2": ZONE2_DECISIONS, "3": ZONE3_DECISIONS}[zone]
    if decision not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid Zone {zone} decision. Must be one of: {', '.join(sorted(valid))}",
        )

    try:
        item = _sp_to_item(await get_list_item(_q_id(), _Q_LIST, item_id))
        impact = _impact_shell(zone, decision)

        if item.get("ReviewStatus") == "Blocked":
            impact["warnings"].append(
                "A previous cascade for this item failed — confirming will retry the decision. "
                f"Previous result: {item.get('CascadeResult', '')[:300]}"
            )

        if zone == "1":
            return await _zone1_impact(item, decision, impact)
        if zone == "2":
            return await _zone2_impact(item, decision, impact, target_role, linked_doc_code)
        return await _zone3_impact(item, decision, impact, canonical_name)

    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"decision impact {item_id}")
