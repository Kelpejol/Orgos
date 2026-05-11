# =============================================================================
# queue/router.py — AI Review Queue API endpoints
# GET  /api/v1/queue/items            — list queue items, filterable by type
# GET  /api/v1/queue/items/{id}       — get single item
# PATCH /api/v1/queue/items/{id}/decide — record a decision with rationale
# Depends on: graph/client.py, auth/validator.py, config.py
# =============================================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth.validator import CurrentUser, get_current_user
from config import settings
from graph.client import (
    get_list_items,
    get_list_item,
    update_list_item,
)
from graph.exceptions import (
    GraphAPIError,
    GraphNotFoundError,
    SharePointListNotConfiguredError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/queue", tags=["AI Review Queue"])

_LIST_NAME = "AI Review Queue"


def _get_list_id() -> str:
    return settings.ai_review_queue_list_id


def _sp_item_to_queue_item(item: dict) -> dict:
    """Convert a SharePoint list item to a clean queue item dict."""
    fields = item.get("fields", {})
    return {
        "id":                      str(item["id"]),
        "Title":                   fields.get("Title", ""),
        "ItemType":                fields.get("ItemType", "Extraction"),
        "SourceDocumentUrl": fields.get("SourceDocumentUrl", ""),
        "ExtractionCategory":      fields.get("ExtractionCategory", ""),
        "DocumentType":            fields.get("DocumentType", ""),
        "SourceDocumentCode":      fields.get("SourceDocumentCode", ""),
        "SourceClause":            fields.get("SourceClause", ""),
        "ControlStatement":        fields.get("ControlStatement", ""),
        "RiskStatement":           fields.get("RiskStatement", ""),
        "ControlType":             fields.get("ControlType", ""),
        "ProposedOwnerRole":       fields.get("ProposedOwnerRole", ""),
        "ISOClause":               fields.get("ISOClause", ""),
        "SourceType":              fields.get("SourceType", ""),
        "CompletenessFlag":        fields.get("CompletenessFlag", ""),
        "DeficiencyReason":        fields.get("DeficiencyReason", ""),
        "EvidenceType":            fields.get("EvidenceType", ""),
        "EvidenceDescription":     fields.get("EvidenceDescription", ""),
        "EvidenceSourceSystem":    fields.get("EvidenceSourceSystem", ""),
        "EvidenceFormat":          fields.get("EvidenceFormat", ""),
        "EvidenceFrequency":       fields.get("EvidenceFrequency", ""),
        "EvidenceCollectionMethod":fields.get("EvidenceCollectionMethod", ""),
        "EvidenceOwnerRole":       fields.get("EvidenceOwnerRole", ""),
        "EvidenceValidationCriteria": fields.get("EvidenceValidationCriteria", ""),
        "EvidenceUndefined":       fields.get("EvidenceUndefined", False),
        "EvidenceUndefinedReason": fields.get("EvidenceUndefinedReason", ""),
        "OrphanDirection":         fields.get("OrphanDirection", ""),
        "ResponsibilityStatement": fields.get("ResponsibilityStatement", ""),
        "OrphanClassification":    fields.get("OrphanClassification", ""),
        "OrphanReason":            fields.get("OrphanReason", ""),
        "FindingType":             fields.get("FindingType", ""),
        "Severity":                fields.get("Severity", ""),
        "StandardReference":       fields.get("StandardReference", ""),
        "GapType":                 fields.get("GapType", ""),
        "RemediationRequired":     fields.get("RemediationRequired", ""),
        "TriggersDocumentLifecycle": fields.get("TriggersDocumentLifecycle", False),
        "IsRepeatedFinding":       fields.get("IsRepeatedFinding", False),
        "Authority":               fields.get("Authority", ""),
        "ObligationDeadline":      fields.get("ObligationDeadline", ""),
        "ObligationRecurrence":    fields.get("ObligationRecurrence", ""),
        "PenaltyIfMissed":         fields.get("PenaltyIfMissed", ""),
        "ConfidenceScore":         fields.get("ConfidenceScore", 0.0),
        "ReviewStatus":            fields.get("ReviewStatus", "Pending Review"),
        "Decision":                fields.get("Decision", ""),
        "DecisionRationale":       fields.get("DecisionRationale", ""),
        "RoutingRule":             fields.get("RoutingRule", ""),
        "AssignedTo":              fields.get("AssignedTo", ""),
    }


def _handle_error(exc: Exception, context: str):
    if isinstance(exc, SharePointListNotConfiguredError):
        raise HTTPException(status_code=503, detail=str(exc))
    elif isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    else:
        logger.exception(f"Unexpected error: {context}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {context}")


class DecisionRequest(BaseModel):
    """Body for PATCH /queue/items/{id}/decide"""
    decision: str = Field(
        description="One of: Accept, Edit and Accept, Reject, Route to Owner, Mark False Positive, Request Second Review"
    )
    rationale: str = Field(
        min_length=5,
        description="Mandatory rationale for this decision. Minimum 5 characters."
    )


@router.get(
    "/items",
    summary="List AI Review Queue items",
)
async def list_queue_items(
    item_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """
    Returns all items in the AI Review Queue.
    Fetches all items and filters in Python — avoids SharePoint index requirement.
    """
    try:
        items = await get_list_items(
            _get_list_id(),
            _LIST_NAME,
        )

        queue_items = [_sp_item_to_queue_item(i) for i in items]

        # Filter in Python — no SharePoint index needed
        if item_type:
            queue_items = [
                i for i in queue_items
                if i.get("ItemType", "").lower() == item_type.lower()
            ]
        if status_filter:
            queue_items = [
                i for i in queue_items
                if i.get("ReviewStatus", "").lower() == status_filter.lower()
            ]

        # Sort: pending first, then by confidence ascending
        queue_items.sort(
            key=lambda x: (
                0 if x["ReviewStatus"] == "Pending Review" else 1,
                x["ConfidenceScore"] or 0,
            )
        )

        return queue_items

    except Exception as exc:
        _handle_error(exc, "list queue items")
        
@router.get(
    "/items/{item_id}",
    summary="Get a single queue item",
)
async def get_queue_item(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        return _sp_item_to_queue_item(item)
    except Exception as exc:
        _handle_error(exc, f"get queue item {item_id}")


@router.patch(
    "/items/{item_id}/decide",
    summary="Record a decision on a queue item",
)
async def decide_on_item(
    item_id: str,
    body: DecisionRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Record a human decision on an AI Review Queue item.
    Rationale is mandatory — every decision must be explained.
    Only Compliance Lead or OrgOS Admin can make decisions.

    Valid decisions:
    Accept | Edit and Accept | Reject | Route to Owner |
    Mark False Positive | Request Second Review
    """
    # Permission check — compliance team only
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compliance Lead or OrgOS Admin role required to make queue decisions",
        )

    valid_decisions = {
        "Accept", "Edit and Accept", "Reject",
        "Route to Owner", "Mark False Positive", "Request Second Review"
    }
    if body.decision not in valid_decisions:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decision. Must be one of: {', '.join(sorted(valid_decisions))}",
        )

    # Map decision to review status
    status_map = {
        "Accept":               "Accepted",
        "Edit and Accept":      "Edited and Accepted",
        "Reject":               "Rejected",
        "Route to Owner":       "Routed",
        "Mark False Positive":  "False Positive",
        "Request Second Review":"Second Review Requested",
    }

    fields = {
        "ReviewStatus":    status_map[body.decision],
        "Decision":        body.decision,
        "DecisionRationale": body.rationale,
        "ReviewedByEntraId": user.oid,
    }

    try:
        await update_list_item(_get_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_get_list_id(), _LIST_NAME, item_id)
        logger.info(
            f"Queue decision: item={item_id} decision='{body.decision}' "
            f"by={user.name} ({user.oid})"
        )
        return _sp_item_to_queue_item(updated)
    except Exception as exc:
        _handle_error(exc, f"decide on queue item {item_id}")