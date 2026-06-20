# =============================================================================
# agents/nl_search/compliance_search.py — Compliance register search
#
# Handles compliance-intent queries: rules, ownership, status, gaps, schedules.
# Does NOT use the vector store — queries structured SharePoint registers directly
# using OData filters derived from entity extraction.
#
# Strategy:
#   1. Extract entities from the question (topic keywords, ISO clause, standard hint)
#      using a lightweight LLM call. All extracted keywords are used in the filter
#      with OR logic so multi-topic questions match across all relevant controls.
#   2. Run targeted OData queries against the relevant registers.
#   3. Collect controls + evidence items + owner info + standards status.
#   4. Return a structured result dict for response_formatter.py.
# =============================================================================

import asyncio
import json
import logging
import re
from typing import Optional

from agents.llm_client import llm_generate
from agents.nl_search.vector_store import search_controls
from config import settings
from graph.client import get_list_items, resolve_user

logger = logging.getLogger(__name__)

# Fetch limits — named so they are easy to tune without hunting the code.
_CONTROLS_FETCH_TOP    = 20   # OData top — how many raw rows SharePoint returns
_CONTROLS_ENRICH_LIMIT = 8    # Max controls we enrich with evidence (N+1 guard)
_EVIDENCE_PER_CONTROL  = 5    # Max evidence items per control
_VECTOR_RESULTS        = 8    # ChromaDB hits before distance filtering


# =============================================================================
#  Entity extraction from question
# =============================================================================

_ENTITY_PROMPT = """\
Extract search entities from a GRC compliance question. Return JSON only.

Rules:
- If the question covers multiple topics, extract keywords covering ALL of them.
- If the question is short, vague, or uses references like "this control", "the above",
  "the same", "it", or asks about a property (owner, risk, evidence, status) without
  naming the subject — use the recent conversation context to derive the actual topic.
- Combine keywords from the current question AND the context when the question alone
  is not self-contained.

{context_block}Question: {question}

Fields:
  "keywords": up to 5 topic keywords that identify the subject (control, policy, obligation)
  "iso_clause": ISO 27001/9001 clause if explicitly mentioned (e.g. "A.5.17") or null
  "standard": "ISO 27001" | "ISO 9001" | "NDPA" or null
  "is_personal_query": true if asking about "my" items, "my overdue", "assigned to me"

JSON:"""


def _build_entity_context(question: str, recent_history: list[dict] | None) -> str:
    """
    Build a context block for entity extraction from recent user messages.
    Only uses user messages (not assistant answers) — assistant text is long and noisy.
    Excludes the current question itself to avoid repetition.
    """
    if not recent_history:
        return ""
    prior_user = [
        m for m in recent_history
        if m.get("role") == "user"
        and (m.get("content") or "").strip() != question.strip()
    ]
    if not prior_user:
        return ""
    lines = [
        f"- {(m.get('content') or '').strip()[:200]}"
        for m in prior_user[-2:]  # at most 2 prior user messages
    ]
    return "Recent conversation context:\n" + "\n".join(lines) + "\n\n"


async def _extract_entities(question: str, recent_history: list[dict] | None = None) -> dict:
    """
    Extract search keywords, ISO clause, standard, and query type from a question.

    When the question is short or referential (e.g. "who is the owner", "what is the risk",
    "show me more"), recent_history supplies the prior user messages so the LLM can
    derive the actual topic. This works for any follow-up question about any subject —
    not just ownership — because the extraction is principle-based, not hardcoded.
    """
    context_block = _build_entity_context(question, recent_history)
    prompt = _ENTITY_PROMPT.format(question=question, context_block=context_block)
    raw = await llm_generate(prompt, tier="light", max_tokens=200, temperature=0.0, json_mode=True)
    raw = raw.strip()

    # Try to find the JSON object anywhere in the response (handles fences and prose)
    json_match = re.search(r'\{.*?\}', raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return {
                "keywords":          data.get("keywords") or [],
                "iso_clause":        data.get("iso_clause"),
                "standard":          data.get("standard"),
                "is_personal_query": bool(data.get("is_personal_query", False)),
            }
        except Exception:
            pass

    # Fallback: derive keywords from question + recent context when JSON parse fails entirely.
    # Include prior user messages so short follow-ups still get meaningful keywords.
    all_text = question
    if recent_history:
        for m in recent_history[-4:]:
            if m.get("role") == "user":
                all_text += " " + (m.get("content") or "")
    words = re.findall(r'\b[a-zA-Z]{4,}\b', all_text.lower())
    stop = {"what", "when", "where", "which", "that", "this", "with", "from",
            "have", "does", "your", "their", "show", "give", "tell", "about",
            "many", "much", "long", "often", "must", "should", "would", "could",
            "role", "owner", "risk", "type", "more", "same", "above", "control"}
    return {
        "keywords":          [w for w in words if w not in stop][:5],
        "iso_clause":        None,
        "standard":          None,
        "is_personal_query": False,
    }


# =============================================================================
#  Register queries
# =============================================================================

async def _search_controls(keywords: list[str], iso_clause: Optional[str]) -> list[dict]:
    """Query Control Register for controls matching keywords or ISO clause.

    All extracted keywords are combined with OR so a multi-topic question (e.g.
    "training requirements and NDPA obligations") matches controls from every
    topic — not just the first keyword.
    """
    list_id = settings.control_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    filters = []
    if iso_clause:
        filters.append(f"fields/ISOClause eq '{iso_clause}'")
    elif keywords:
        # Build an OR clause across all keywords so multi-topic queries hit all relevant controls
        kw_parts = [
            f"(contains(fields/ControlStatement, '{kw}') or contains(fields/RiskImplication, '{kw}'))"
            for kw in keywords[:5]
        ]
        filters.append("(" + " or ".join(kw_parts) + ")")

    odata_filter = " and ".join(filters) if filters else None

    try:
        items = await get_list_items(
            list_id=list_id,
            list_name="Control Register",
            odata_filter=odata_filter,
            select_fields=(
                "id,fields/Title,fields/ControlStatement,fields/ControlType,"
                "fields/ISOClause,fields/OwnerRole,fields/OwnerEntraId,"
                "fields/SourceDocumentCode,fields/RiskImplication,fields/Status"
            ),
            top=_CONTROLS_FETCH_TOP,
        )
        return [_map_control(i) for i in items if i.get("fields", {}).get("Status") == "Active"]
    except Exception as exc:
        logger.warning(f"compliance_search: control query failed: {exc}")
        return []


def _map_control(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":               str(item.get("id", "")),
        "control_statement":f.get("ControlStatement") or f.get("Title", ""),
        "control_type":     f.get("ControlType", ""),
        "iso_clause":       f.get("ISOClause", ""),
        "owner_role_title": f.get("OwnerRole", ""),     # role title string (always present)
        "owner_oid":        f.get("OwnerEntraId", ""),  # Entra OID → resolved to person name
        "source_document":  f.get("SourceDocumentCode", ""),
        "risk_statement":   f.get("RiskImplication", ""),
        "status":           f.get("Status", ""),
    }


async def _get_evidence_for_control(control_id: str) -> list[dict]:
    """Fetch evidence items linked to a specific control."""
    list_id = settings.evidence_tracker_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(
            list_id=list_id,
            list_name="Evidence Tracker",
            odata_filter=f"fields/LinkedControlId eq '{control_id}'",
            select_fields=(
                "id,fields/EvidenceDescription,fields/EvidenceType,"
                "fields/Status,fields/DueDate,fields/EvidenceLink"
            ),
            top=5,
        )
        return [_map_evidence(i) for i in items]
    except Exception as exc:
        logger.warning(f"compliance_search: evidence query failed for {control_id}: {exc}")
        return []


def _map_evidence(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":          str(item.get("id", "")),
        "description": f.get("EvidenceDescription", ""),
        "type":        f.get("EvidenceType", ""),
        "status":      f.get("Status", "Pending"),
        "due_date":    f.get("DueDate", ""),
        "link":        f.get("EvidenceLink", ""),
    }


async def _get_standards_status(iso_clause: Optional[str]) -> Optional[dict]:
    """Fetch traffic light status for an ISO clause from Standards Map data."""
    if not iso_clause:
        return None
    list_id = settings.control_register_list_id
    if not settings.is_list_configured(list_id):
        return None
    # Standards Map is calculated dynamically — we just return the clause reference
    # The router will call the Standards Map endpoint if needed
    return {"clause": iso_clause, "note": "See Standards Map for live traffic light"}


async def _search_compliance_calendar(keywords: list[str]) -> list[dict]:
    """Search compliance calendar for relevant obligations."""
    list_id = settings.compliance_calendar_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        if keywords:
            kw_parts = [f"contains(fields/Title, '{kw}')" for kw in keywords[:5]]
            odata_filter = "(" + " or ".join(kw_parts) + ")"
        else:
            odata_filter = None
        items = await get_list_items(
            list_id=list_id,
            list_name="Compliance Calendar",
            odata_filter=odata_filter,
            select_fields=(
                "id,fields/Title,fields/ObligationType,fields/Authority,"
                "fields/DueDate,fields/Recurrence,fields/OwnerEntraId"
            ),
            top=5,
        )
        return [_map_obligation(i) for i in items]
    except Exception as exc:
        logger.warning(f"compliance_search: calendar query failed: {exc}")
        return []


def _map_obligation(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":         str(item.get("id", "")),
        "name":       f.get("Title", ""),
        "type":       f.get("ObligationType", ""),
        "authority":  f.get("Authority", ""),
        "due_date":   f.get("DueDate", ""),
        "recurrence": f.get("Recurrence", ""),
        "owner_oid":  f.get("OwnerEntraId", ""),
    }


# =============================================================================
#  Owner resolution
# =============================================================================

async def _resolve_owners(oids: list[str]) -> dict[str, dict]:
    """Resolve a list of Entra OIDs to {display_name, email} dicts."""
    unique_oids = list({o for o in oids if o})
    resolved: dict[str, dict] = {}
    tasks = [resolve_user(oid) for oid in unique_oids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for oid, result in zip(unique_oids, results):
        if isinstance(result, dict):
            resolved[oid] = result
    return resolved


# =============================================================================
#  ChromaDB vector search fallback
# =============================================================================

_VECTOR_DISTANCE_THRESHOLD = 0.42  # cosine distance — lower = more similar


async def _vector_search_controls(question: str) -> list[dict]:
    """
    Semantic search over controls_v1 ChromaDB collection.
    Used as a fallback when SharePoint Control Register is not configured or empty.
    Returns controls in the same dict shape as _search_controls().
    """
    try:
        hits = await search_controls(question, n_results=_VECTOR_RESULTS)
        controls = []
        for hit in hits:
            if hit.get("distance", 1.0) > _VECTOR_DISTANCE_THRESHOLD:
                continue
            meta = hit.get("metadata", {})
            controls.append({
                "id":               hit.get("id", ""),
                "control_statement":hit.get("document", ""),
                "control_type":     meta.get("control_type", ""),
                "iso_clause":       meta.get("iso_clause", ""),
                "owner_oid":        meta.get("owner_oid", ""),
                "source_document":  meta.get("document_code", ""),
                "risk_statement":   "",
                "status":           "Active",
            })
        logger.info(f"compliance_search: vector fallback returned {len(controls)} controls")
        return controls
    except Exception as exc:
        logger.warning(f"compliance_search: vector fallback failed: {exc}")
        return []


# =============================================================================
#  Public interface
# =============================================================================

async def search_compliance(
    question: str,
    user_oid: Optional[str] = None,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Run a compliance search for the given question.
    Returns a structured dict consumed by response_formatter.format_compliance_response().

    conversation_history: passed through to entity extraction so short or referential
    follow-up questions ("who is the owner", "what is the evidence status", "show more")
    are resolved to the actual topic from recent user messages — not just the 2-word query.

    Shape:
    {
      "question": str,
      "entities": { keywords, iso_clause, standard, is_personal_query },
      "controls": [ { id, control_statement, control_type, iso_clause,
                       owner_role_title, owner, source_document, risk_statement,
                       evidence: [...] } ],
      "obligations": [ ... ],
      "standards_hint": { clause, note } | None,
      "found": bool,
    }
    """
    entities = await _extract_entities(question, recent_history=conversation_history)
    keywords     = entities.get("keywords") or []
    iso_clause   = entities.get("iso_clause")

    # Run control search and calendar search in parallel
    controls_raw, obligations = await asyncio.gather(
        _search_controls(keywords, iso_clause),
        _search_compliance_calendar(keywords),
    )

    # If SharePoint returned nothing, fall back to ChromaDB vector search.
    # Pass the original question (not keywords) so semantic similarity works.
    if not controls_raw:
        controls_raw = await _vector_search_controls(question)

    # Enrich controls with evidence items (parallel per control, capped at limit)
    async def _enrich(ctrl: dict) -> dict:
        evidence = await _get_evidence_for_control(ctrl["id"])
        ctrl["evidence"] = evidence
        return ctrl

    enriched_controls = []
    if controls_raw:
        enriched_controls = await asyncio.gather(*[_enrich(c) for c in controls_raw[:_CONTROLS_ENRICH_LIMIT]])
        enriched_controls = list(enriched_controls)

    # Resolve all owner OIDs in one batch (parallel Graph API calls)
    all_oids = (
        [c["owner_oid"] for c in enriched_controls if c.get("owner_oid")] +
        [o["owner_oid"] for o in obligations if o.get("owner_oid")]
    )
    owners = await _resolve_owners(all_oids)

    # Attach owner to controls.
    # Resolution order: OID → person name (if OID present and resolves).
    # Fallback: role title string from OwnerRole column (always populated).
    # Never show a raw OID to the LLM — it's meaningless and confuses the model.
    for ctrl in enriched_controls:
        oid        = ctrl.get("owner_oid", "")
        role_title = ctrl.get("owner_role_title", "")
        if oid and oid in owners:
            ctrl["owner"] = owners[oid]
        else:
            ctrl["owner"] = {"display_name": role_title or "Unassigned", "email": ""}

    # Attach owner to obligations
    for ob in obligations:
        oid = ob.get("owner_oid", "")
        ob["owner"] = owners.get(oid, {"display_name": "Unassigned", "email": ""})

    standards_hint = await _get_standards_status(iso_clause)

    return {
        "question":       question,
        "entities":       entities,
        "controls":       enriched_controls,
        "obligations":    obligations,
        "standards_hint": standards_hint,
        "found":          bool(enriched_controls or obligations),
    }
