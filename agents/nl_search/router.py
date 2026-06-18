# =============================================================================
# agents/nl_search/router.py — NL Search API endpoints
#
# POST /api/v1/nl-search/query      — Main query endpoint (chat UI calls this)
# POST /api/v1/nl-search/index/rebuild  — Full re-index from SharePoint data
# GET  /api/v1/nl-search/health     — ChromaDB + embed model status
# =============================================================================

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from agents.nl_search.intent_classifier import classify_intent
from agents.nl_search.compliance_search import search_compliance
from agents.nl_search.procedural_search import search_procedural
from agents.nl_search.response_formatter import (
    format_compliance_response,
    format_procedural_response,
    format_combined_response,
)
from agents.nl_search.embedder import check_embed_connectivity
from agents.nl_search.vector_store import get_collection_stats, embed_and_store_control

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/nl-search", tags=["NL Search"])


# =============================================================================
#  Schemas
# =============================================================================

class NLSearchRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    session_id: Optional[str] = None  # Informational — stored by frontend in IndexedDB


class NLSearchResponse(BaseModel):
    mode:             str           # "compliance" | "procedural" | "combined"
    answer:           str           # Markdown text for the chat bubble
    sources:          list[dict]    # [{title, document_code, clause, link}]
    compliance_data:  Optional[dict] = None
    procedural_data:  Optional[dict] = None
    intent:           str = ""      # Echoes the classified intent


class RebuildRequest(BaseModel):
    confirm: bool = Field(
        default=False,
        description="Must be True to execute the rebuild. Prevents accidental triggers."
    )


# =============================================================================
#  Query endpoint
# =============================================================================

@router.post("/query", response_model=NLSearchResponse)
async def nl_search_query(
    request: NLSearchRequest,
    user: CurrentUser = Depends(get_current_user),
) -> NLSearchResponse:
    """
    Main dual-mode search endpoint. Classifies intent, searches appropriate
    indexes, and returns a formatted response for the chat UI.
    """
    question = request.question.strip()

    # 1. Classify intent
    intent = await classify_intent(question)
    logger.info(f"NL Search | user={user.oid} | intent={intent} | q='{question[:80]}'")

    # 2. Route to search pipelines
    try:
        if intent == "compliance":
            result = search_compliance(question, user_oid=user.oid)
            result = await result
            formatted = format_compliance_response(result)

        elif intent == "procedural":
            result = await search_procedural(question)
            formatted = format_procedural_response(result)

        else:  # "both"
            comp_result, proc_result = await asyncio.gather(
                search_compliance(question, user_oid=user.oid),
                search_procedural(question),
            )
            formatted = format_combined_response(comp_result, proc_result)

    except Exception as exc:
        logger.error(f"NL Search pipeline error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Search pipeline error. Please try again.",
        )

    return NLSearchResponse(
        mode=formatted["mode"],
        answer=formatted["answer"],
        sources=formatted.get("sources", []),
        compliance_data=formatted.get("compliance_data"),
        procedural_data=formatted.get("procedural_data"),
        intent=intent,
    )


# =============================================================================
#  Index a single control (called from Zone 1 accept cascade)
# =============================================================================

@router.post("/index/control/{control_id}", status_code=204)
async def index_single_control(
    control_id: str,
    body: dict,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """
    Embed and index a single accepted control into controls_v1.
    Called internally by review_queue/router.py after Zone 1 acceptance.
    Body: { control_statement: str, metadata: dict }
    """
    control_statement = body.get("control_statement", "")
    metadata          = body.get("metadata", {})
    if not control_statement:
        raise HTTPException(status_code=422, detail="control_statement required")
    await embed_and_store_control(control_id, control_statement, metadata)


# =============================================================================
#  Full index rebuild
# =============================================================================

@router.post("/index/rebuild")
async def rebuild_index(
    request: RebuildRequest,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Full rebuild of both ChromaDB collections from current SharePoint data.
    Use on initial setup or after a data migration.
    Requires Compliance Lead or Admin role.
    Returns counts of items indexed.
    """
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to execute the rebuild.",
        )

    from config import settings
    from graph.client import get_list_items
    from agents.nl_search.vector_store import embed_and_store_control, embed_and_store_procedural_step
    from agents.nl_search.procedures_service import get_all_steps_paginated

    results = {"controls_indexed": 0, "procedures_indexed": 0, "errors": []}

    # --- Rebuild controls_v1 ---
    ctrl_list_id = settings.control_register_list_id
    if settings.is_list_configured(ctrl_list_id):
        try:
            items = await get_list_items(
                list_id=ctrl_list_id,
                list_name="Control Register",
                odata_filter="fields/Status eq 'Active'",
                select_fields=(
                    "id,fields/ControlStatement,fields/ControlType,"
                    "fields/ISOClause,fields/OwnerRoleEntraId,fields/SourceDocumentCode"
                ),
                top=500,
            )
            for item in items:
                f = item.get("fields", item)
                stmt = f.get("ControlStatement", "")
                if not stmt:
                    continue
                meta = {
                    "document_code": f.get("SourceDocumentCode", ""),
                    "iso_clause":    f.get("ISOClause", ""),
                    "control_type":  f.get("ControlType", ""),
                    "owner_oid":     f.get("OwnerRoleEntraId", ""),
                }
                ok = await embed_and_store_control(str(item.get("id", "")), stmt, meta)
                if ok:
                    results["controls_indexed"] += 1
        except Exception as exc:
            results["errors"].append(f"Controls rebuild: {exc}")
            logger.error(f"Rebuild controls failed: {exc}")
    else:
        results["errors"].append("Control Register list not configured")

    # --- Rebuild procedures_v1 ---
    try:
        steps = await get_all_steps_paginated(top=500)
        for step in steps:
            step_id = step.get("id", "")
            text    = step.get("step_text", "")
            if not text or not step_id:
                continue
            meta = {
                "document_code": step.get("document_code", ""),
                "document_title":step.get("document_title", ""),
                "process_name":  step.get("process_name", ""),
                "step_number":   str(step.get("step_number", 0)),
                "section_ref":   step.get("section_ref", ""),
                "roles_involved":step.get("roles_involved", ""),
                "forms_referenced":step.get("forms_referenced", ""),
            }
            ok = await embed_and_store_procedural_step(step_id, text, meta)
            if ok:
                results["procedures_indexed"] += 1
    except Exception as exc:
        results["errors"].append(f"Procedures rebuild: {exc}")
        logger.error(f"Rebuild procedures failed: {exc}")

    logger.info(
        f"Index rebuild complete: {results['controls_indexed']} controls, "
        f"{results['procedures_indexed']} procedure steps"
    )
    return results


# =============================================================================
#  Health
# =============================================================================

@router.get("/health")
async def nl_search_health() -> dict:
    """
    Returns health of ChromaDB collections and embedding service.
    No auth required.
    """
    embed_status = await check_embed_connectivity()
    collection_stats = get_collection_stats()

    return {
        "status":      "ok" if embed_status.get("status") == "ok" else "degraded",
        "embed":       embed_status,
        "collections": collection_stats,
    }
