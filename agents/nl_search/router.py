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
from pydantic import BaseModel, Field, field_validator
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
from agents.nl_search.response_generator import generate_chat_response
from agents.nl_search.embedder import check_embed_connectivity
from agents.nl_search.vector_store import get_collection_stats, embed_and_store_control

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/nl-search", tags=["NL Search"])


def _conversational_fallback(question: str) -> str:
    """
    Generates a natural conversational reply when the LLM gateway is unavailable.
    Picks up time-of-day greetings, acknowledgements, and follow-up requests so
    the user always gets a coherent response rather than a robotic one-liner.
    """
    q = question.lower().strip()

    # Time-of-day greetings
    if any(w in q for w in ("good evening", "evening")):
        return "Good evening! I'm your OrgOS compliance assistant. Ask me anything about Dragnet's policies, controls, or HR procedures."
    if any(w in q for w in ("good morning", "morning")):
        return "Good morning! I'm your OrgOS compliance assistant. What can I help you with today — policies, controls, or procedures?"
    if any(w in q for w in ("good afternoon", "afternoon")):
        return "Good afternoon! I'm your OrgOS compliance assistant. Ask me about Dragnet's GRC policies or how-to procedures."

    # "how are you"
    if "how are you" in q or "how are u" in q:
        return "I'm doing great, thanks for asking! What can I help you with — a policy question, evidence requirement, or a how-to procedure?"

    # Thank-you acknowledgement
    if any(w in q for w in ("thank", "thanks")):
        return "You're welcome! Feel free to ask any other questions about Dragnet's policies, controls, or procedures."

    # Follow-up / elaboration request with no prior LLM context
    if any(w in q for w in ("explain", "elaborate", "clarify", "more detail", "tell me more")):
        return "I'd be happy to elaborate — could you ask a specific question about the policy, control, or procedure you're interested in?"

    # Generic greeting or short social phrase
    return "Hi! I'm your OrgOS GRC assistant. Ask me about Dragnet's compliance policies, controls, evidence requirements, or how-to procedures."


# =============================================================================
#  Schemas
# =============================================================================

class NLSearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    session_id: Optional[str] = None  # Informational — stored by frontend in IndexedDB
    conversation_history: list[dict] = Field(default_factory=list)

    @field_validator("conversation_history")
    @classmethod
    def _clean_history(cls, v: list[dict]) -> list[dict]:
        # Strip to role+content only, keep last 10 messages, reject unknown roles
        clean = [
            {"role": m.get("role", ""), "content": (m.get("content") or "")[:500]}
            for m in v
            if m.get("role") in ("user", "assistant")
        ]
        return clean[-10:]


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

    # Classify intent — LLM at temp=0, sees last conversation turn for follow-up context
    intent = await classify_intent(question, request.conversation_history)
    logger.info(f"NL Search | user={user.oid} | intent={intent} | q='{question[:80]}'")

    # 2. Route to search pipelines + generate RAG answer
    try:
        if intent == "conversational":
            # No ChromaDB search — LLM responds from conversation history alone.
            llm_ans = await generate_chat_response(
                question, "conversational", {}, request.conversation_history
            )
            return NLSearchResponse(
                mode="general",
                answer=llm_ans or _conversational_fallback(question),
                sources=[],
                intent="conversational",
            )

        elif intent == "compliance":
            # Multi-topic handling is done inside search_compliance via all-keyword
            # OData OR filters — no question splitting needed at the router level.
            result    = await search_compliance(question, user_oid=user.oid)
            formatted = format_compliance_response(result)
            llm_ans   = await generate_chat_response(
                question, "compliance", result, request.conversation_history
            )

        elif intent == "procedural":
            result    = await search_procedural(question)
            formatted = format_procedural_response(result)
            llm_ans   = await generate_chat_response(
                question, "procedural", result, request.conversation_history
            )

        else:  # "both"
            comp_result, proc_result = await asyncio.gather(
                search_compliance(question, user_oid=user.oid),
                search_procedural(question),
            )
            formatted = format_combined_response(comp_result, proc_result)
            llm_ans   = await generate_chat_response(
                question, "both", {},
                request.conversation_history,
                compliance_result=comp_result,
                procedural_result=proc_result,
            )

    except Exception as exc:
        logger.error(f"NL Search pipeline error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Search pipeline error. Please try again.",
        )

    # LLM answer is primary; fall back to structured formatter if LLM failed
    answer = llm_ans if llm_ans else formatted["answer"]

    return NLSearchResponse(
        mode=formatted["mode"],
        answer=answer,
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
#  Seed endpoint — insert test data for development/demo without SharePoint
# =============================================================================

_SEED_CONTROLS = [
    {
        "id":        "seed-ctrl-001",
        "statement": "All staff must complete information security awareness training within 30 days of joining and annually thereafter.",
        "meta":      {"document_code": "DRG-ISMS-POL-SEC-01-26", "iso_clause": "A.6.3", "control_type": "Directive", "owner_oid": ""},
    },
    {
        "id":        "seed-ctrl-002",
        "statement": "Access to production systems must be reviewed and re-approved by the system owner every 90 days.",
        "meta":      {"document_code": "DRG-ISMS-POL-ACP-01-26", "iso_clause": "A.5.18", "control_type": "Detective", "owner_oid": ""},
    },
    {
        "id":        "seed-ctrl-003",
        "statement": "All vendor contracts must include a data processing agreement (DPA) before any personal data is shared.",
        "meta":      {"document_code": "DRG-LEGAL-POL-VND-01-26", "iso_clause": "A.5.19", "control_type": "Preventive", "owner_oid": ""},
    },
    {
        "id":        "seed-ctrl-004",
        "statement": "Incident response team must be notified within 1 hour of detecting a potential data breach.",
        "meta":      {"document_code": "DRG-ISMS-POL-INC-01-26", "iso_clause": "A.5.24", "control_type": "Corrective", "owner_oid": ""},
    },
    {
        "id":        "seed-ctrl-005",
        "statement": "Privileged accounts must use multi-factor authentication (MFA) and must not be used for day-to-day activities.",
        "meta":      {"document_code": "DRG-ISMS-POL-ACP-01-26", "iso_clause": "A.5.17", "control_type": "Preventive", "owner_oid": ""},
    },
    {
        "id":        "seed-ctrl-006",
        "statement": "All personal data processed under NDPA must be documented in the data register maintained by the DPO.",
        "meta":      {"document_code": "DRG-LEGAL-POL-DPO-01-26", "iso_clause": "S.26", "control_type": "Directive", "owner_oid": ""},
    },
    {
        "id":        "seed-ctrl-007",
        "statement": "Business continuity plans must be tested at least once per year through a tabletop exercise or full simulation.",
        "meta":      {"document_code": "DRG-OPS-POL-BCP-01-26", "iso_clause": "A.5.30", "control_type": "Detective", "owner_oid": ""},
    },
]

_SEED_PROCEDURES = [
    {
        "id":   "seed-proc-001",
        "text": "Step 1 — Submit a new joiner request via the AAMP portal at least 3 days before the start date.",
        "meta": {"document_code": "DRG-HR-PRO-JNR-01-26", "document_title": "New Joiner Onboarding Procedure", "process_name": "New Employee Onboarding", "step_number": "1", "roles_involved": "HR Officer, IT Admin", "forms_referenced": "FM-HR-001", "section_ref": "4.1"},
    },
    {
        "id":   "seed-proc-002",
        "text": "Step 2 — IT Admin provisions accounts in Entra ID and assigns the correct licence and role group based on the approved JD.",
        "meta": {"document_code": "DRG-HR-PRO-JNR-01-26", "document_title": "New Joiner Onboarding Procedure", "process_name": "New Employee Onboarding", "step_number": "2", "roles_involved": "IT Admin", "forms_referenced": "", "section_ref": "4.2"},
    },
    {
        "id":   "seed-proc-003",
        "text": "Step 1 — Staff member completes Leave Request Form (FM-HR-003) and submits to line manager via SeamlessHR.",
        "meta": {"document_code": "DRG-HR-PRO-LVE-01-26", "document_title": "Leave Application Procedure", "process_name": "Leave Application", "step_number": "1", "roles_involved": "Staff, Line Manager", "forms_referenced": "FM-HR-003", "section_ref": "3.1"},
    },
    {
        "id":   "seed-proc-004",
        "text": "Step 2 — Line manager approves or rejects within 3 working days. Rejections must include a written reason.",
        "meta": {"document_code": "DRG-HR-PRO-LVE-01-26", "document_title": "Leave Application Procedure", "process_name": "Leave Application", "step_number": "2", "roles_involved": "Line Manager", "forms_referenced": "", "section_ref": "3.2"},
    },
    {
        "id":   "seed-proc-005",
        "text": "Step 1 — Raise a change request in the ITSM portal with business justification, risk assessment, and rollback plan at least 5 days before the planned change.",
        "meta": {"document_code": "DRG-ISMS-PRO-CHG-01-26", "document_title": "Change Management Procedure", "process_name": "IT Change Request", "step_number": "1", "roles_involved": "Change Requestor, IT Manager", "forms_referenced": "FM-IT-005", "section_ref": "5.1"},
    },
    {
        "id":   "seed-proc-006",
        "text": "Step 2 — Change Advisory Board (CAB) reviews the request every Thursday. Standard changes are approved within 24 hours; significant changes require CISO sign-off.",
        "meta": {"document_code": "DRG-ISMS-PRO-CHG-01-26", "document_title": "Change Management Procedure", "process_name": "IT Change Request", "step_number": "2", "roles_involved": "CAB, CISO", "forms_referenced": "", "section_ref": "5.2"},
    },
]


@router.post("/index/seed", status_code=200)
async def seed_index(
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Insert hardcoded test controls and procedural steps into ChromaDB.
    Use for development and demos when SharePoint lists are not yet populated.
    Safe to call multiple times — upserts, so no duplicates.
    """
    from agents.nl_search.vector_store import embed_and_store_control, embed_and_store_procedural_step

    controls_ok = 0
    procedures_ok = 0
    errors = []

    for ctrl in _SEED_CONTROLS:
        ok = await embed_and_store_control(ctrl["id"], ctrl["statement"], ctrl["meta"])
        if ok:
            controls_ok += 1
        else:
            errors.append(f"Failed to embed control {ctrl['id']}")

    for step in _SEED_PROCEDURES:
        ok = await embed_and_store_procedural_step(step["id"], step["text"], step["meta"])
        if ok:
            procedures_ok += 1
        else:
            errors.append(f"Failed to embed step {step['id']}")

    return {
        "controls_seeded":   controls_ok,
        "procedures_seeded": procedures_ok,
        "errors":            errors,
    }


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
