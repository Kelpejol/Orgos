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
from datetime import date, timezone, datetime
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


def _q_id():  return settings.ai_review_queue_list_id
def _cr_id(): return settings.control_register_list_id
def _ev_id(): return settings.evidence_tracker_list_id
def _al_id(): return settings.audit_log_list_id
def _dl_id(): return settings.document_lifecycle_list_id


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
    control_type = overrides.get("control_type")      or item.get("ControlType", "Directive")
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
    if evidence_type and not item.get("EvidenceUndefined"):
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
    "Intentional",
    "Remove from JD",
    "Mark False Positive",
    "Request Second Review",
}


class Zone2DecideBody(BaseModel):
    decision:          str
    rationale:         str
    linked_doc_code:   Optional[str] = None  # For "Add to existing policy"


async def _zone2_cascade(
    item: dict,
    decision: str,
    rationale: str,
    user: CurrentUser,
    linked_doc_code: Optional[str] = None,
) -> str:
    created = []

    if decision == "Create new document":
        # Create a Document Lifecycle entry — Gap Remediation trigger
        try:
            stmt = item.get("ResponsibilityStatement") or item.get("ControlStatement") or item.get("Title", "")
            dl_fields = {
                "Title":          f"Gap Remediation: {stmt[:200]}",
                "Stage":          "Review",
                "Trigger":        "Gap Remediation",
                "AIGenerated":    False,
                "Revised":        False,
                "OwnerEntraId":   user.oid,
                "Notes": (
                    f"Created from Zone 2 Assignment decision.\n"
                    f"Source: {item.get('SourceDocumentCode', '')}\n"
                    f"Responsibility: {stmt[:300]}\n"
                    f"Rationale: {rationale}"
                ),
            }
            dl_item = await create_list_item(_dl_id(), _DL_LIST, dl_fields)
            created.append(f"Document Lifecycle: {dl_item['id']}")
        except Exception as exc:
            logger.error(f"Zone 2 Document Lifecycle cascade failed: {exc}")

    elif decision == "Add to existing policy":
        # Log the document that needs updating
        if linked_doc_code:
            created.append(f"Document '{linked_doc_code}' flagged for revision to include this responsibility.")
        else:
            created.append("No document code provided — reviewer must manually update the relevant policy.")

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
            "Intentional":          "Accepted",
            "Remove from JD":       "Rejected",
            "Mark False Positive":  "False Positive",
            "Request Second Review":"Pending Second Review",
        }

        cascade_result = await _zone2_cascade(
            item, body.decision, body.rationale.strip(),
            user, body.linked_doc_code,
        )

        updates = {
            "ReviewStatus":      status_map[body.decision],
            "Decision":          body.decision,
            "DecisionRationale": body.rationale.strip(),
            "ReviewedByEntraId": user.oid,
            "CascadeResult":     cascade_result,
        }

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

    if decision in ("Merge", "Rename and standardise") and canonical_name:
        # Update the queue item with the confirmed canonical name
        # In production, this would also update the Role Register
        created.append(f"Canonical name confirmed: '{canonical_name}'")
        created.append("Role Register update required — set all variant terms to map to this canonical name.")

    elif decision == "Partial merge" and canonical_name:
        created.append(f"Partial merge — canonical name '{canonical_name}' confirmed for overlapping variants.")
        created.append("Review remaining variants manually — some may be genuinely different roles.")

    elif decision == "Keep separate":
        created.append("Confirmed as separate items — no merge required.")

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