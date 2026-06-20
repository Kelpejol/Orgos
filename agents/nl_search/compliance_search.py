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


def _date_only(val) -> str:
    """
    Return just the YYYY-MM-DD part of any date or datetime value.
    Handles ISO strings ("2026-06-10T07:00:00Z"), date-only strings,
    and None/empty safely. Strips the time portion so the LLM never
    outputs "at 07:00:00 (UTC)" noise.
    """
    if not val:
        return ""
    return str(val)[:10]


# =============================================================================
#  Entity extraction from question
# =============================================================================

_ENTITY_PROMPT = """\
Extract search entities from a GRC compliance question. Return JSON only.

Rules:
- If the question covers multiple topics, extract keywords covering ALL of them.
- If the question is short, vague, or uses references like "this control", "the above",
  "the same", "it", or asks about a property (owner, risk, evidence, status, gap) without
  naming the subject — use the recent conversation context to derive the actual topic.
- Combine keywords from the current question AND the context when the question alone
  is not self-contained.

{context_block}Question: {question}

Fields:
  "keywords": up to 6 topic keywords identifying the subject (control, policy, obligation, gap, document, risk)
  "iso_clause": ISO 27001/9001 clause if explicitly mentioned (e.g. "A.5.17") or null
  "standard": "ISO 27001" | "ISO 9001" | "NDPA" or null
  "is_personal_query": true if asking about "my" items, "my overdue", "assigned to me"
  "document_code": exact Dragnet document code if present in the question (e.g. "DRG-HR-POL-01-26") or null

JSON:"""


def _build_entity_context(question: str, recent_history: list[dict] | None) -> str:
    """
    Build a context block for entity extraction from recent user messages.
    Only uses user messages (not assistant answers) — assistant text is long and noisy.
    Excludes the current question itself to avoid repetition.

    History is skipped for long questions (> 20 words): a question that long is
    self-contained and contains its own topic signal. Injecting prior history for
    a long question causes the LLM to mix keywords from different topics, breaking
    the match against the correct control.
    """
    if not recent_history or len(question.split()) > 20:
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
                "document_code":     data.get("document_code"),
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
        "keywords":          [w for w in words if w not in stop][:6],
        "iso_clause":        None,
        "standard":          None,
        "is_personal_query": False,
        "document_code":     None,
    }


# =============================================================================
#  Register queries
# =============================================================================

async def _search_controls(
    keywords: list[str],
    iso_clause: Optional[str],
    question: str = "",
) -> list[dict]:
    """Query Control Register for controls matching keywords or ISO clause.

    Fetches all controls from SharePoint and filters in Python.
    OData contains() is not used for text matching because ControlStatement is
    not indexed in SharePoint — unindexed columns cause contains() to return 404.
    ISO clause exact-match still uses OData since ISOClause is a short fixed value.

    Matching strategy (OR logic — any hit returns the control):
      1. Keyword substring match in ControlStatement or RiskImplication
      2. Verbatim match — control statement or risk text appears in the user's question
         (handles the common pattern where users paste the control statement into
         their question, e.g. "what is the risk for 'All staff SHALL engage...'")
    """
    list_id = settings.control_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    # Use OData only for exact ISO clause match (short value, reliable).
    odata_filter = f"fields/ISOClause eq '{iso_clause}'" if iso_clause else None

    try:
        items = await get_list_items(
            list_id=list_id,
            list_name="Control Register",
            odata_filter=odata_filter,
            top=500,
        )
    except Exception as exc:
        logger.warning(f"compliance_search: control query failed: {exc}")
        return []

    active = [i for i in items if i.get("fields", {}).get("Status") == "Active"]
    if not active:
        return []

    q_lower = question.lower() if question else ""

    def _matches(item: dict) -> bool:
        stmt = (item.get("fields", {}).get("ControlStatement", "") or "").lower()
        risk = (item.get("fields", {}).get("RiskImplication", "") or "").lower()

        # 1. Keyword match in control statement or risk (handles extracted keywords)
        if keywords:
            haystack = stmt + " " + risk
            if any(kw.lower() in haystack for kw in keywords):
                return True

        # 2. Verbatim match — first 40 chars of control statement appear in question.
        #    Handles users who paste the control/risk text directly into their question.
        if q_lower:
            if stmt and len(stmt) > 15 and stmt[:40] in q_lower:
                return True
            if risk and len(risk) > 15 and risk[:40] in q_lower:
                return True

        return False

    if keywords or q_lower:
        active = [i for i in active if _matches(i)]

    return [_map_control(i) for i in active[:_CONTROLS_FETCH_TOP]]


def _map_control(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":               str(item.get("id", "")),
        "control_statement":f.get("ControlStatement") or f.get("Title", ""),
        "control_type":     f.get("ControlType", ""),
        "iso_clause":       f.get("ISOClause", ""),
        "owner_role_title": f.get("OwnerRole", ""),     # role title string (always present)
        "owner_oid":        f.get("OwnerEntraId", ""),  # Entra OID → resolved to person name
        "source_document":  f.get("SourceDocument", ""),
        "risk_statement":   f.get("RiskImplication", ""),
        "status":           f.get("Status", ""),
    }


async def _get_all_evidence() -> list[dict]:
    """
    Fetch all Evidence Tracker items in one batch and filter per control in Python.

    OData filtering on LinkedControlId is unreliable — SharePoint may store the
    value as a Number or Text column depending on how the cascade wrote it, and
    a type-mismatch causes a silent 404 that returns [] even when evidence exists.
    One batch fetch + Python comparison avoids this entirely and also reduces
    round-trips when enriching multiple controls in the same request.
    """
    list_id = settings.evidence_tracker_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(
            list_id=list_id,
            list_name="Evidence Tracker",
            top=500,
        )
        return [_map_evidence(i) for i in items]
    except Exception as exc:
        logger.warning(f"compliance_search: evidence batch fetch failed: {exc}")
        return []


def _map_evidence(item: dict) -> dict:
    f = item.get("fields", item)
    # "Last collected" may live in different columns depending on how the router wrote it.
    # Try all candidates; the first non-empty value wins. _date_only strips the time part.
    last_collected = _date_only(
        f.get("LastCollected") or f.get("CollectionDate") or
        f.get("SubmissionDate") or f.get("DateCollected") or
        item.get("lastModifiedDateTime", "")
    )
    return {
        "id":                 str(item.get("id", "")),
        "linked_control_id":  str(f.get("LinkedControlId") or ""),
        "description":        f.get("EvidenceDescription", ""),
        "type":               f.get("EvidenceType", ""),
        "format":             f.get("EvidenceFormat", ""),
        "status":             f.get("Status", "Pending"),
        "due_date":           _date_only(f.get("DueDate", "")),
        "last_collected":     last_collected,
        "link":               (f.get("EvidenceLink") or "").strip(),
        "source_system":      f.get("SourceSystem", ""),
        "collection_method":  f.get("CollectionMethod", ""),
        "frequency":          f.get("Frequency", ""),
        "owner_role":         f.get("OwnerRole", ""),
        "owner_oid":          f.get("OwnerEntraId", ""),
        "reviewer_oid":       f.get("ReviewerEntraId", ""),
        "reviewer_notes":     f.get("ReviewerNotes", ""),
        "submission_notes":   f.get("SubmissionNotes", ""),
        "validation_criteria":f.get("ValidationCriteria", ""),
        # reviewer_name populated later after OID resolution in search_compliance()
        "reviewer_name":      "",
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
    """Search compliance calendar for relevant obligations.

    Fetches all obligations and filters in Python across multiple fields
    (Title, Authority, ObligationType) — Authority and Type are not indexed
    in SharePoint so contains() OData filters would fail on them.
    """
    list_id = settings.compliance_calendar_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(
            list_id=list_id,
            list_name="Compliance Calendar",
            top=200,
        )
        if not keywords:
            return [_map_obligation(i) for i in items[:5]]
        kw_lower = [k.lower() for k in keywords]
        matched = []
        for i in items:
            f = i.get("fields", {})
            # CAL_FIELDS maps: obligation_name→Title, type→ObligationType, notes→ObligationNotes
            # There is no "ObligationName" column — Title IS the obligation name.
            haystack = " ".join([
                (f.get("Title") or ""),
                (f.get("Authority") or ""),
                (f.get("ObligationType") or ""),
                (f.get("ObligationNotes") or ""),
            ]).lower()
            if any(kw in haystack for kw in kw_lower):
                matched.append(i)
        return [_map_obligation(i) for i in matched[:5]]
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
        "due_date":   _date_only(f.get("DueDate", "")),
        "recurrence": f.get("Recurrence", ""),
        # CAL_FIELDS["notes"] = "ObligationNotes" (not "Notes")
        "notes":      f.get("ObligationNotes", ""),
        # CAL_FIELDS["owner_id"] = "OwnerId" (not "OwnerEntraId")
        "owner_oid":  f.get("OwnerId", ""),
    }


# =============================================================================
#  Gap Analysis search
# =============================================================================

def _map_gap(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":                   str(item.get("id", "")),
        "gap_id":               f.get("GapId", "") or f.get("Title", ""),
        "finding":              f.get("Finding", "") or f.get("GapFinding", "") or f.get("Title", ""),
        "standard":             f.get("Standard", ""),
        "clause":               (f.get("ClauseReference") or f.get("ISOClause") or
                                 f.get("StandardClause") or ""),
        "severity":             f.get("Severity", ""),
        "status":               f.get("Status", ""),
        "proposed_remediation": (f.get("ProposedRemediation") or "")[:400],
        "target_date":          _date_only(f.get("TargetDate", "")),
        "source":               f.get("Source", ""),
        "owner_oid":            f.get("OwnerEntraId", ""),
    }


def _py_match(items: list, keywords: list[str], question: str,
              *field_getters) -> list:
    """
    Filter a list of SharePoint item dicts in Python using keyword OR verbatim matching.
    field_getters: callables (item -> str) for each field to search in.
    Returns matched items preserving order.
    """
    kw_lower = [k.lower() for k in keywords]
    q_lower  = question.lower() if question else ""
    matched  = []
    for item in items:
        texts = [g(item) for g in field_getters]
        haystack = " ".join(t.lower() for t in texts if t)
        if kw_lower and any(kw in haystack for kw in kw_lower):
            matched.append(item)
            continue
        if q_lower:
            for text in texts:
                t = text.lower()
                if t and len(t) > 15 and t[:40] in q_lower:
                    matched.append(item)
                    break
    return matched


async def _search_gap_analysis(keywords: list[str], question: str = "") -> list[dict]:
    """Search Gap Analysis list. Python-side filtering across all text fields."""
    list_id = settings.gap_analysis_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(list_id=list_id, list_name="Gap Analysis", top=200)
        if not keywords and not question:
            return [_map_gap(i) for i in items[:5]]
        matched = _py_match(
            items, keywords, question,
            lambda i: i.get("fields", {}).get("Finding", "") or i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("Standard", ""),
            lambda i: i.get("fields", {}).get("ClauseReference", "") or i.get("fields", {}).get("ISOClause", ""),
            lambda i: i.get("fields", {}).get("Severity", ""),
            lambda i: i.get("fields", {}).get("Status", ""),
        )
        return [_map_gap(i) for i in matched[:5]]
    except Exception as exc:
        logger.warning(f"compliance_search: gap analysis query failed: {exc}")
        return []


# =============================================================================
#  Document Register search
# =============================================================================

def _map_document(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":                  str(item.get("id", "")),
        "document_code":       f.get("DocumentCode", ""),
        "title":               f.get("Title", ""),
        "type":                f.get("DocumentType", ""),
        "department":          f.get("Department", ""),
        # DOC_FIELDS["status"] = "Status" (not "DocumentStatus")
        "status":              f.get("Status", ""),
        "current_version":     f.get("CurrentVersion", ""),
        "effective_date":      _date_only(f.get("EffectiveDate", "")),
        "next_review_date":    _date_only(f.get("NextReviewDate", "")),
        "applicable_standards":f.get("ApplicableStandards", ""),
        # DOC_FIELDS["sharepoint_url"] = "SharePointUrl"
        "sharepoint_url":      f.get("SharePointUrl", ""),
        # DOC_FIELDS["owner_id"] = "OwnerId" (not "OwnerEntraId")
        "owner_oid":           f.get("OwnerId", ""),
    }


async def _search_document_register(
    keywords: list[str],
    question: str = "",
    document_code: Optional[str] = None,
) -> list[dict]:
    """
    Search Document Register. Python-side filtering across title, code, department,
    standards. If a specific document_code was extracted, tries exact match first.
    """
    list_id = settings.document_register_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(list_id=list_id, list_name="Document Register", top=200)
        # Exclude withdrawn documents — DOC_FIELDS["status"] = "Status" (not "DocumentStatus")
        active = [i for i in items if i.get("fields", {}).get("Status") != "Withdrawn"]

        # Document code matching — normalized contains-check so spaces, hyphens,
        # underscores, and missing year suffixes all resolve to the right document.
        # "DRG HR FM Competency Map" and "DRG-HR-FM-COMPETENCY-MAP-01-26" both match.
        if document_code:
            dc_norm = document_code.lower().replace(" ", "-").replace("_", "-")
            code_matched = [
                i for i in active
                if dc_norm in (i.get("fields", {}).get("DocumentCode") or "").lower().replace(" ", "-")
                or (i.get("fields", {}).get("DocumentCode") or "").lower().replace(" ", "-") in dc_norm
            ]
            if code_matched:
                return [_map_document(i) for i in code_matched[:3]]
            # Code not found — enrich keywords with tokens from the code so keyword
            # matching below can still catch the document.
            dc_tokens = [
                t for t in re.split(r'[-_\s]+', dc_norm)
                if len(t) > 2 and t not in {"drg", "the", "and", "for", "01", "02", "03",
                                              "04", "05", "06", "24", "25", "26", "27"}
            ]
            keywords = list(dict.fromkeys(list(keywords) + dc_tokens))

        if not keywords and not question:
            return [_map_document(i) for i in active[:5]]

        matched = _py_match(
            active, keywords, question,
            lambda i: i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("DocumentCode", ""),
            lambda i: i.get("fields", {}).get("Department", ""),
            lambda i: i.get("fields", {}).get("DocumentType", ""),
            lambda i: i.get("fields", {}).get("ApplicableStandards", ""),
        )
        return [_map_document(i) for i in matched[:5]]
    except Exception as exc:
        logger.warning(f"compliance_search: document register query failed: {exc}")
        return []


# =============================================================================
#  Strategic Risk Register search
# =============================================================================

# Mirrors strategic_risks/router.py — Likelihood and Impact are stored as strings.
_LIKELIHOOD_MAP = {"Low": 1, "Medium": 2, "High": 3}
_IMPACT_MAP     = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}


def _map_risk(item: dict) -> dict:
    f = item.get("fields", item)
    likelihood = f.get("Likelihood") or "Low"
    impact     = f.get("Impact") or "Low"
    # Likelihood/Impact are stored as strings ("Low", "Medium", "High", "Critical").
    # int() would raise ValueError — use the same lookup maps as strategic_risks/router.py.
    score = _LIKELIHOOD_MAP.get(str(likelihood), 1) * _IMPACT_MAP.get(str(impact), 1)
    if score <= 3:
        level = "Low"
    elif score <= 6:
        level = "Medium"
    elif score <= 9:
        level = "High"
    else:
        level = "Critical"
    return {
        "id":             str(item.get("id", "")),
        "description":    f.get("Description", "") or f.get("Title", ""),
        "category":       f.get("Category", ""),
        "likelihood":     str(likelihood),
        "impact":         str(impact),
        "risk_score":     str(score),
        "risk_level":     level,
        "treatment":      (f.get("Treatment") or "")[:300],
        "status":         f.get("Status", ""),
        "related_gap_id": f.get("RelatedGapId", ""),
        "owner_oid":      f.get("OwnerEntraId", ""),
    }


async def _search_strategic_risks(keywords: list[str], question: str = "") -> list[dict]:
    """Search Strategic Risk Register. Python-side filtering across description, category."""
    list_id = settings.strategic_risk_register_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(
            list_id=list_id, list_name="Strategic Risk Register", top=200
        )
        if not keywords and not question:
            return [_map_risk(i) for i in items[:5]]
        matched = _py_match(
            items, keywords, question,
            lambda i: i.get("fields", {}).get("Description", "") or i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("Category", ""),
            lambda i: i.get("fields", {}).get("Treatment", ""),
            lambda i: i.get("fields", {}).get("Status", ""),
        )
        return [_map_risk(i) for i in matched[:5]]
    except Exception as exc:
        logger.warning(f"compliance_search: strategic risks query failed: {exc}")
        return []


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
                "owner_role_title": meta.get("owner_role", ""),  # needed for ownership display
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
    Run a compliance search across ALL GRC registers for the given question.

    Searches in parallel: Control Register, Compliance Calendar, Gap Analysis,
    Document Register, and Strategic Risk Register. Every register uses Python-side
    filtering (keyword + verbatim match) — no OData contains() anywhere.
    Evidence is fetched in a single batch and matched per control in Python.
    All person OIDs across every register are resolved in one Graph API batch.

    Returns a structured dict with keys:
      controls, obligations, gaps, documents, risks — each a list of enriched dicts.
      found: True if any register returned results.
    """
    entities = await _extract_entities(question, recent_history=conversation_history)
    keywords      = entities.get("keywords") or []
    iso_clause    = entities.get("iso_clause")
    document_code = entities.get("document_code")

    # Run all five register searches in parallel.
    (
        controls_raw,
        obligations,
        gaps,
        documents,
        risks,
    ) = await asyncio.gather(
        _search_controls(keywords, iso_clause, question=question),
        _search_compliance_calendar(keywords),
        _search_gap_analysis(keywords, question=question),
        _search_document_register(keywords, question=question, document_code=document_code),
        _search_strategic_risks(keywords, question=question),
    )

    # ChromaDB vector fallback — only if SharePoint controls returned nothing.
    if not controls_raw:
        controls_raw = await _vector_search_controls(question)

    # Enrich controls with evidence — one batch fetch, Python-side matching.
    # Avoids per-control OData queries and the LinkedControlId column-type bug.
    enriched_controls = list(controls_raw[:_CONTROLS_ENRICH_LIMIT])
    if enriched_controls:
        all_evidence = await _get_all_evidence()
        ev_by_control: dict[str, list[dict]] = {}
        for ev in all_evidence:
            cid = ev.get("linked_control_id", "")
            if cid:
                ev_by_control.setdefault(cid, []).append(ev)
        for ctrl in enriched_controls:
            ctrl["evidence"] = ev_by_control.get(ctrl["id"], [])[:_EVIDENCE_PER_CONTROL]

    # Resolve ALL person OIDs across every register in a single Graph API batch.
    all_oids = (
        [c["owner_oid"] for c in enriched_controls if c.get("owner_oid")] +
        [ev.get("owner_oid", "") for ctrl in enriched_controls
         for ev in ctrl.get("evidence", []) if ev.get("owner_oid")] +
        [ev.get("reviewer_oid", "") for ctrl in enriched_controls
         for ev in ctrl.get("evidence", []) if ev.get("reviewer_oid")] +
        [o["owner_oid"] for o in obligations if o.get("owner_oid")] +
        [g["owner_oid"] for g in gaps if g.get("owner_oid")] +
        [d["owner_oid"] for d in documents if d.get("owner_oid")] +
        [r["owner_oid"] for r in risks if r.get("owner_oid")]
    )
    owners = await _resolve_owners(all_oids)

    def _person(oid: str, fallback: str = "Unassigned") -> dict:
        if oid and oid in owners:
            return owners[oid]
        return {"display_name": fallback or "Unassigned", "email": ""}

    # Stamp reviewer_name onto each evidence item.
    for ctrl in enriched_controls:
        for ev in ctrl.get("evidence", []):
            roid = ev.get("reviewer_oid", "")
            if roid and roid in owners:
                ev["reviewer_name"] = owners[roid].get("display_name", "")

    # Attach owner objects to every entity across every register.
    for ctrl in enriched_controls:
        role_title = ctrl.get("owner_role_title", "")
        ctrl["owner"] = _person(ctrl.get("owner_oid", ""), fallback=role_title)

    for ob in obligations:
        ob["owner"] = _person(ob.get("owner_oid", ""))

    for gap in gaps:
        gap["owner"] = _person(gap.get("owner_oid", ""))

    for doc in documents:
        doc["owner"] = _person(doc.get("owner_oid", ""))

    for risk in risks:
        risk["owner"] = _person(risk.get("owner_oid", ""))

    standards_hint = await _get_standards_status(iso_clause)

    return {
        "question":       question,
        "entities":       entities,
        "controls":       enriched_controls,
        "obligations":    obligations,
        "gaps":           gaps,
        "documents":      documents,
        "risks":          risks,
        "standards_hint": standards_hint,
        "found":          bool(enriched_controls or obligations or gaps or documents or risks),
    }


# =============================================================================
#  Debug pipeline — exposes every intermediate step for a given question.
#  Used by GET /api/v1/nl-search/debug?question=... to isolate failures.
# =============================================================================

async def debug_compliance_pipeline(question: str) -> dict:
    """
    Run the full compliance search pipeline and return every intermediate result.
    Shows: extracted entities, OData filter string, raw SharePoint items (before
    mapping), mapped controls, ChromaDB hits, and any errors. Use this to pinpoint
    exactly which stage is failing for a given question.
    """
    result: dict = {"question": question, "stages": {}}

    # Stage 1: Entity extraction
    try:
        entities = await _extract_entities(question)
        result["stages"]["1_entity_extraction"] = {
            "status": "ok",
            "entities": entities,
        }
    except Exception as exc:
        result["stages"]["1_entity_extraction"] = {"status": "error", "error": str(exc)}
        return result

    keywords  = entities.get("keywords") or []
    iso_clause = entities.get("iso_clause")

    # Stage 2: Show matching strategy (OData only for ISO clause; keywords matched in Python)
    odata_filter = f"fields/ISOClause eq '{iso_clause}'" if iso_clause else None
    result["stages"]["2_odata_filter"] = {
        "filter": odata_filter,
        "note": (
            "ISO clause exact-match via OData" if iso_clause
            else "No OData filter — keyword matching done in Python after fetch"
        ),
        "keywords_for_python_match": keywords,
    }

    # Stage 3: Raw SharePoint query + Python keyword filtering
    list_id = settings.control_register_list_id
    if not settings.is_list_configured(list_id):
        result["stages"]["3_sharepoint_query"] = {"status": "skipped", "reason": "list not configured"}
    else:
        try:
            raw_items = await get_list_items(
                list_id=list_id,
                list_name="Control Register",
                odata_filter=odata_filter,
                top=500,
            )
            active = [i for i in raw_items if i.get("fields", {}).get("Status") == "Active"]

            # Apply same matching logic as _search_controls (keyword + verbatim)
            q_lower = question.lower()

            def _debug_match(item: dict) -> bool:
                stmt = (item.get("fields", {}).get("ControlStatement", "") or "").lower()
                risk = (item.get("fields", {}).get("RiskImplication", "") or "").lower()
                if keywords:
                    haystack = stmt + " " + risk
                    if any(kw.lower() in haystack for kw in keywords):
                        return True
                if q_lower:
                    if stmt and len(stmt) > 15 and stmt[:40] in q_lower:
                        return True
                    if risk and len(risk) > 15 and risk[:40] in q_lower:
                        return True
                return False

            matched = [i for i in active if _debug_match(i)] if (keywords or q_lower) else active

            result["stages"]["3_sharepoint_query"] = {
                "status": "ok",
                "total_returned": len(raw_items),
                "active_count": len(active),
                "keyword_matched": len(matched),
                "sample": [
                    {
                        "id": str(i.get("id", "")),
                        "ControlStatement": (i.get("fields", {}).get("ControlStatement") or "")[:200],
                        "Status": i.get("fields", {}).get("Status", ""),
                        "OwnerRole": i.get("fields", {}).get("OwnerRole", ""),
                        "RiskImplication": (i.get("fields", {}).get("RiskImplication") or "")[:300],
                    }
                    for i in matched[:3]
                ],
            }
        except Exception as exc:
            result["stages"]["3_sharepoint_query"] = {"status": "error", "error": str(exc)}

    # Stage 4: ChromaDB vector search
    try:
        hits = await search_controls(question, n_results=_VECTOR_RESULTS)
        good_hits = [h for h in hits if h.get("distance", 1.0) <= _VECTOR_DISTANCE_THRESHOLD]
        result["stages"]["4_chromadb_search"] = {
            "status": "ok",
            "total_hits": len(hits),
            "good_hits": len(good_hits),
            "sample": [
                {
                    "id": h.get("id", ""),
                    "distance": round(h.get("distance", 1.0), 4),
                    "text": (h.get("document") or "")[:100],
                }
                for h in good_hits[:3]
            ],
        }
    except Exception as exc:
        result["stages"]["4_chromadb_search"] = {"status": "error", "error": str(exc)}

    # Stage 5: Compliance calendar
    try:
        obligations = await _search_compliance_calendar(keywords)
        result["stages"]["5_compliance_calendar"] = {
            "status": "ok",
            "count": len(obligations),
            "sample": [{"name": o.get("name", ""), "due_date": o.get("due_date", "")} for o in obligations[:3]],
        }
    except Exception as exc:
        result["stages"]["5_compliance_calendar"] = {"status": "error", "error": str(exc)}

    return result
