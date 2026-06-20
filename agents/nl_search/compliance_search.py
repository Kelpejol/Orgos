# =============================================================================
# agents/nl_search/compliance_search.py — Compliance register search
#
# Handles compliance-intent queries: rules, ownership, status, gaps, schedules.
# Does NOT use the vector store — queries structured SharePoint registers directly
# using OData filters derived from entity extraction.
#
# Strategy:
#   1. Extract entities from the question (topic keyword, ISO clause, standard hint)
#      using a lightweight LLM call.
#   2. Run targeted OData queries against the relevant registers.
#   3. Collect controls + evidence items + owner info + standards status.
#   4. Return a structured result dict for response_formatter.py.
# =============================================================================

import asyncio
import logging
import re
from typing import Optional

from agents.llm_client import llm_generate
from agents.nl_search.vector_store import search_controls
from config import settings
from graph.client import get_list_items, resolve_user

logger = logging.getLogger(__name__)


# =============================================================================
#  Entity extraction from question
# =============================================================================

_ENTITY_PROMPT = """\
Extract search entities from a compliance question. Return JSON only.

Fields:
  "keywords": list of 1-3 topic keywords (e.g. ["password", "access control"])
  "iso_clause": ISO 27001/9001 clause if mentioned (e.g. "A.5.17") or null
  "standard": "ISO 27001" | "ISO 9001" | "NDPA" or null
  "is_personal_query": true if asking about "my" items, "my overdue", "assigned to me"

Question: {question}

JSON:"""


async def _extract_entities(question: str) -> dict:
    prompt = _ENTITY_PROMPT.format(question=question)
    raw = await llm_generate(prompt, tier="light", max_tokens=150, temperature=0.0, json_mode=True)
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        import json
        data = json.loads(raw)
        return {
            "keywords":         data.get("keywords") or [],
            "iso_clause":       data.get("iso_clause"),
            "standard":         data.get("standard"),
            "is_personal_query":bool(data.get("is_personal_query", False)),
        }
    except Exception:
        # Fallback: extract keywords from the question directly
        words = re.findall(r'\b[a-zA-Z]{4,}\b', question.lower())
        stop = {"what", "when", "where", "which", "that", "this", "with", "from",
                "have", "does", "your", "their", "show", "give", "tell", "about"}
        return {
            "keywords":         [w for w in words if w not in stop][:3],
            "iso_clause":       None,
            "standard":         None,
            "is_personal_query":False,
        }


# =============================================================================
#  Register queries
# =============================================================================

async def _search_controls(keywords: list[str], iso_clause: Optional[str]) -> list[dict]:
    """Query Control Register for controls matching keywords or ISO clause."""
    list_id = settings.control_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    filters = []
    if iso_clause:
        filters.append(f"fields/ISOClause eq '{iso_clause}'")
    elif keywords:
        # OData: substringof is not universally available; use contains where supported
        kw = keywords[0]
        filters.append(
            f"(contains(fields/ControlStatement, '{kw}') "
            f"or contains(fields/RiskStatement, '{kw}'))"
        )

    odata_filter = " and ".join(filters) if filters else None

    try:
        items = await get_list_items(
            list_id=list_id,
            list_name="Control Register",
            odata_filter=odata_filter,
            select_fields=(
                "id,fields/Title,fields/ControlStatement,fields/ControlType,"
                "fields/ISOClause,fields/OwnerRoleEntraId,fields/SourceDocumentCode,"
                "fields/RiskStatement,fields/Status"
            ),
            top=10,
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
        "owner_oid":        f.get("OwnerRoleEntraId", ""),
        "source_document":  f.get("SourceDocumentCode", ""),
        "risk_statement":   f.get("RiskStatement", ""),
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
        kw = keywords[0] if keywords else ""
        odata_filter = f"contains(fields/Title, '{kw}')" if kw else None
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

_VECTOR_DISTANCE_THRESHOLD = 0.6  # cosine distance — lower = more similar


async def _vector_search_controls(question: str) -> list[dict]:
    """
    Semantic search over controls_v1 ChromaDB collection.
    Used as a fallback when SharePoint Control Register is not configured or empty.
    Returns controls in the same dict shape as _search_controls().
    """
    try:
        hits = await search_controls(question, n_results=5)
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

async def search_compliance(question: str, user_oid: Optional[str] = None) -> dict:
    """
    Run a compliance search for the given question.
    Returns a structured dict consumed by response_formatter.format_compliance_response().

    Shape:
    {
      "question": str,
      "entities": { keywords, iso_clause, standard, is_personal_query },
      "controls": [ { id, control_statement, control_type, iso_clause,
                       owner, source_document, risk_statement,
                       evidence: [...] } ],
      "obligations": [ ... ],
      "standards_hint": { clause, note } | None,
      "found": bool,
    }
    """
    entities = await _extract_entities(question)
    keywords     = entities.get("keywords") or []
    iso_clause   = entities.get("iso_clause")

    # Run control search and calendar search in parallel
    controls_raw, obligations = await asyncio.gather(
        _search_controls(keywords, iso_clause),
        _search_compliance_calendar(keywords),
    )

    # If SharePoint returned nothing, fall back to ChromaDB vector search
    if not controls_raw:
        controls_raw = await _vector_search_controls(question)

    # Enrich controls with evidence items (parallel per control, capped at 5)
    async def _enrich(ctrl: dict) -> dict:
        evidence = await _get_evidence_for_control(ctrl["id"])
        ctrl["evidence"] = evidence
        return ctrl

    enriched_controls = []
    if controls_raw:
        enriched_controls = await asyncio.gather(*[_enrich(c) for c in controls_raw[:5]])
        enriched_controls = list(enriched_controls)

    # Resolve all owner OIDs in one batch
    all_oids = (
        [c["owner_oid"] for c in enriched_controls if c.get("owner_oid")] +
        [o["owner_oid"] for o in obligations if o.get("owner_oid")]
    )
    owners = await _resolve_owners(all_oids)

    # Attach resolved owner to controls
    for ctrl in enriched_controls:
        oid = ctrl.get("owner_oid", "")
        ctrl["owner"] = owners.get(oid, {"display_name": ctrl.get("owner_oid", ""), "email": ""})

    # Attach resolved owner to obligations
    for ob in obligations:
        oid = ob.get("owner_oid", "")
        ob["owner"] = owners.get(oid, {"display_name": ob.get("owner_oid", ""), "email": ""})

    standards_hint = await _get_standards_status(iso_clause)

    return {
        "question":       question,
        "entities":       entities,
        "controls":       enriched_controls,
        "obligations":    obligations,
        "standards_hint": standards_hint,
        "found":          bool(enriched_controls or obligations),
    }
