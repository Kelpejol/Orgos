# =============================================================================
# agents/nl_search/compliance_search.py — Compliance register search
#
# Handles compliance-intent queries: rules, ownership, status, gaps, schedules.
# Does NOT use the vector store — queries structured SharePoint registers directly.
#
# Retrieval strategy — three tiers per register, applied in order:
#
#   Tier 1 — OData exact filter
#     When the query specifies an exact field value (status="Closed", severity=
#     "Critical", standard="ISO 27001"), use OData $filter=fields/X eq 'Y'.
#     Works reliably for short structured columns (choice/text fields ≤5,000 rows).
#     Real-time — newly created items appear immediately.
#
#   Tier 2 — Graph Search API (two-stage)
#     For keyword queries that must search inside multi-line text columns
#     (ControlStatement, Finding, Description, Treatment) — OData contains()
#     silently fails on these. Graph Search uses SharePoint's full-text engine.
#     Stage 1: POST /search/query → returns matching item IDs.
#     Stage 2: get_list_item() in parallel for each ID → full field data.
#
#   Tier 3 — Python substring fallback
#     Used when Graph Search is unavailable (network error, wrong region) or
#     returns 0 hits. Fetches all items via OData and filters in Python.
#     Also used as a supplement after Tier 1 to apply keyword sub-filtering.
#
# No arbitrary data caps — every function returns ALL matching items.
# The response_generator decides how many to include in the LLM context, but
# always reports TOTAL COUNTS so the LLM can answer quantity questions correctly.
# The complete result set is always returned to the frontend via compliance_data.
# =============================================================================

import asyncio
import json
import logging
import re
from typing import Optional

from agents.llm_client import llm_generate
from agents.nl_search.vector_store import search_controls
from config import settings
from graph.auth import get_graph_access_token
from graph.client import get_client, get_list_items, get_list_item, resolve_user

logger = logging.getLogger(__name__)

# =============================================================================
#  Constants
# =============================================================================

_CONTROLS_ENRICH_LIMIT = 8    # Controls to enrich with evidence (N+1 guard)
_EVIDENCE_PER_CONTROL  = 5    # Evidence items per control in LLM context
_VECTOR_RESULTS        = 8    # ChromaDB hits before distance filtering

# Graph Search: if search returns more than this many IDs, the entire list
# basically matches — fall through to OData fetch-all instead of fetching each
# item individually. Keeps API call count bounded.
_GRAPH_SEARCH_MAX_IDS  = 40

_GRAPH_SEARCH_URL = "https://graph.microsoft.com/v1.0/search/query"

# Status value normalization — maps user language to exact SharePoint column values.
# The LLM extracts status_filter but may use phrasing that doesn't match exactly.
_STATUS_NORMALIZE: dict[str, str] = {
    "closed":            "Closed",
    "close":             "Closed",
    "accepted":          "Accepted risk",
    "accepted risk":     "Accepted risk",
    "accepted by excos": "Accepted risk",
    "excos accepted":    "Accepted risk",
    "open":              "Open",
    "in progress":       "In progress",
    "inprogress":        "In progress",
    "in-progress":       "In progress",
    "active":            "Active",
    "under review":      "Under Review",
    "underreview":       "Under Review",
    "overdue":           "Overdue",
    "due soon":          "Due Soon",
    "upcoming":          "Upcoming",
    "completed":         "Completed",
    "expired":           "Expired",
    "expiring soon":     "Expiring Soon",
    "terminated":        "Terminated",
    "withdrawn":         "Withdrawn",
    "superseded":        "Superseded",
}

_SEVERITY_NORMALIZE: dict[str, str] = {
    "critical": "Critical",
    "major":    "Major",
    "minor":    "Minor",
}


# =============================================================================
#  Utilities
# =============================================================================

def _date_only(val) -> str:
    """
    Return just the YYYY-MM-DD part of any date or datetime value.
    Strips timezone/time suffix so the LLM never outputs "at 07:00:00 (UTC)" noise.
    """
    if not val:
        return ""
    return str(val)[:10]


def _site_path() -> str:
    """SharePoint site URL used for Graph Search path: scoping."""
    return settings.sharepoint_site_url.rstrip("/")


def _normalize_statuses(raw: list | str | None) -> list[str]:
    """
    Normalize LLM-extracted status values to exact SharePoint column values.
    Accepts a list, a single string, or None. Returns a deduplicated list.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    normalized = []
    for s in raw:
        s_lower = s.strip().lower()
        canonical = _STATUS_NORMALIZE.get(s_lower)
        if canonical and canonical not in normalized:
            normalized.append(canonical)
        elif s.strip() and s.strip() not in normalized:
            # Pass through as-is if not in map — OData will simply return 0 results
            normalized.append(s.strip())
    return normalized


def _normalize_severity(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    return _SEVERITY_NORMALIZE.get(raw.strip().lower())


def _odata_status_filter(statuses: list[str]) -> Optional[str]:
    """Build an OData $filter expression for a list of status values."""
    if not statuses:
        return None
    if len(statuses) == 1:
        return f"fields/Status eq '{statuses[0]}'"
    clauses = " or ".join(f"fields/Status eq '{s}'" for s in statuses)
    return f"({clauses})"


# =============================================================================
#  Graph Search — Tier 2
# =============================================================================

async def _graph_search_list(
    list_id: str,
    list_name: str,
    kql_query: str,
    size: int = 500,
) -> list[dict]:
    """
    Two-stage Graph Search for full-text keyword matching on a SharePoint list.

    Stage 1 — POST /search/query:
      Sends a KQL query to the Graph Search API scoped to the OrgOS SharePoint site.
      Returns matching item IDs. SharePoint's full-text engine searches ALL column
      types including multi-line text (Finding, Description, ControlStatement) which
      OData contains() cannot filter on.

    Stage 2 — get_list_item() in parallel for each ID:
      Fetches complete field data for each hit. This bypasses the managed-property
      limitation of Graph Search responses — all custom column values are returned.
      Items from other lists on the same site will 404 and be dropped silently.

    Returns items in {id, fields} shape — compatible with get_list_items() output.
    Returns [] on any failure; callers always have a Python OData fallback.
    """
    if not settings.is_list_configured(list_id):
        return []

    site_path = _site_path()
    full_kql = f'({kql_query}) AND path:"{site_path}"'

    payload = {
        "requests": [{
            "entityTypes": ["listItem"],
            "query": {"queryString": full_kql},
            "region": settings.graph_search_region,
            "size": min(size, 500),
        }]
    }

    try:
        token = await get_graph_access_token()
        client = get_client()

        resp = await client.post(
            _GRAPH_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15.0,
        )

        if resp.status_code != 200:
            logger.warning(
                f"Graph Search {list_name}: HTTP {resp.status_code} — "
                f"falling back to Python. Response: {resp.text[:300]}"
            )
            return []

        data = resp.json()
        containers = (data.get("value") or [{}])[0].get("hitsContainers") or []
        if not containers:
            return []

        hits = containers[0].get("hits") or []
        if not hits:
            logger.debug(f"Graph Search {list_name}: 0 hits for '{kql_query[:80]}'")
            return []

        # Extract item IDs from hits
        item_ids: list[str] = []
        for hit in hits:
            resource = hit.get("resource") or {}
            item_id = resource.get("id") or hit.get("hitId") or ""
            if item_id:
                item_ids.append(str(item_id))

        if not item_ids:
            return []

        # If search returns more than the threshold, the whole list basically matches.
        # Caller will use OData fetch-all which is more efficient.
        if len(item_ids) > _GRAPH_SEARCH_MAX_IDS:
            logger.info(
                f"Graph Search {list_name}: {len(item_ids)} hits > threshold "
                f"{_GRAPH_SEARCH_MAX_IDS} — caller should use OData fetch-all"
            )
            return []

        logger.info(f"Graph Search {list_name}: {len(item_ids)} hits — fetching full items")

        # Stage 2: fetch full field data for each matched item in parallel
        tasks = [get_list_item(list_id, list_name, iid) for iid in item_ids]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        items = []
        for r in raw_results:
            if isinstance(r, dict) and r.get("fields"):
                items.append(r)

        logger.info(
            f"Graph Search {list_name}: {len(items)}/{len(item_ids)} items retrieved"
        )
        return items

    except Exception as exc:
        logger.warning(f"Graph Search {list_name} error: {exc} — falling back to Python")
        return []


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
- For status_filter: capture ONLY status-like values the user wants to filter by.
  Use the EXACT case-sensitive values listed below. Return a list (may be multiple).
  Gap/Risk statuses:       "Open" | "In progress" | "Accepted risk" | "Closed"
  Control/Document:        "Active" | "Under Review" | "Superseded" | "Withdrawn"
  Compliance Calendar:     "Overdue" | "Due Soon" | "Upcoming" | "Completed"
  Contracts:               "Active" | "Expired" | "Expiring Soon" | "Terminated"
  Examples:
    "show me all closed gaps"                → ["Closed"]
    "gaps accepted by excos"                 → ["Accepted risk"]
    "closed and accepted gaps"               → ["Closed", "Accepted risk"]
    "overdue obligations"                    → ["Overdue"]
    "active controls"                        → ["Active"]
    "list all gaps" (no status qualifier)    → []
- For severity_filter: capture severity if explicitly mentioned.
  Values: "Critical" | "Major" | "Minor"
  Return null if not mentioned.

{context_block}Question: {question}

Fields:
  "keywords": up to 6 topic keywords identifying the subject (e.g. "access", "vendor", "training")
              Do NOT include status words like "closed", "active" here — those go in status_filter.
  "iso_clause": ISO 27001/9001 clause if explicitly mentioned (e.g. "A.5.17") or null
  "standard": "ISO 27001" | "ISO 9001" | "NDPA" or null
  "status_filter": list of exact status values (see rules above), or []
  "severity_filter": "Critical" | "Major" | "Minor" or null
  "is_personal_query": true if asking about "my" items, "my overdue", "assigned to me"
  "document_code": exact Dragnet document code if present (e.g. "DRG-HR-POL-01-26") or null

JSON:"""


def _build_entity_context(question: str, recent_history: list[dict] | None) -> str:
    """
    Build a context block for entity extraction from recent user messages.
    Only uses user messages (not assistant answers) — assistant text is long and noisy.
    Excludes the current question itself to avoid repetition.
    Skipped for long questions (>20 words) — they are self-contained.
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
        for m in prior_user[-2:]
    ]
    return "Recent conversation context:\n" + "\n".join(lines) + "\n\n"


async def _extract_entities(question: str, recent_history: list[dict] | None = None) -> dict:
    """
    Extract search keywords, ISO clause, standard, status filter, severity filter,
    query type, and document code from a compliance question.

    status_filter: list of exact status values for OData filtering (e.g. ["Closed", "Accepted risk"])
    severity_filter: single severity value or None (e.g. "Critical")
    """
    context_block = _build_entity_context(question, recent_history)
    prompt = _ENTITY_PROMPT.format(question=question, context_block=context_block)
    raw = await llm_generate(prompt, tier="light", max_tokens=250, temperature=0.0, json_mode=True)
    raw = raw.strip()

    json_match = re.search(r'\{.*?\}', raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return {
                "keywords":          data.get("keywords") or [],
                "iso_clause":        data.get("iso_clause"),
                "standard":          data.get("standard"),
                "status_filter":     _normalize_statuses(data.get("status_filter")),
                "severity_filter":   _normalize_severity(data.get("severity_filter")),
                "is_personal_query": bool(data.get("is_personal_query", False)),
                "document_code":     data.get("document_code"),
            }
        except Exception:
            pass

    # Fallback: derive keywords from question + context when JSON parse fails
    all_text = question
    if recent_history:
        for m in recent_history[-4:]:
            if m.get("role") == "user":
                all_text += " " + (m.get("content") or "")
    words = re.findall(r'\b[a-zA-Z]{4,}\b', all_text.lower())
    stop = {"what", "when", "where", "which", "that", "this", "with", "from",
            "have", "does", "your", "their", "show", "give", "tell", "about",
            "many", "much", "long", "often", "must", "should", "would", "could",
            "role", "owner", "risk", "type", "more", "same", "above", "control",
            "closed", "open", "active", "status", "accepted"}
    return {
        "keywords":          [w for w in words if w not in stop][:6],
        "iso_clause":        None,
        "standard":          None,
        "status_filter":     [],
        "severity_filter":   None,
        "is_personal_query": False,
        "document_code":     None,
    }


# =============================================================================
#  Register queries — Control Register
# =============================================================================

async def _search_controls(
    keywords: list[str],
    iso_clause: Optional[str],
    question: str = "",
    status_filter: Optional[list[str]] = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    """
    Search Control Register. Returns ALL matching active controls — no cap.

    Tier 1: OData exact filter for ISO clause and known status values.
    Tier 2: Graph Search for keyword matches in ControlStatement / RiskImplication.
    Tier 3: Python fallback — fetch all active controls and filter locally.
    Personal query: adds owner OID filter when is_personal_query=True.
    """
    list_id = settings.control_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    # Build OData filter parts
    odata_parts: list[str] = []
    if iso_clause:
        odata_parts.append(f"fields/ISOClause eq '{iso_clause}'")

    # Controls are always filtered to Active unless the user specified otherwise
    active_statuses = (
        [s for s in (status_filter or []) if s in ("Active", "Under Review", "Superseded", "Withdrawn")]
        or ["Active"]
    )
    if len(active_statuses) == 1:
        odata_parts.append(f"fields/Status eq '{active_statuses[0]}'")
    else:
        clauses = " or ".join(f"fields/Status eq '{s}'" for s in active_statuses)
        odata_parts.append(f"({clauses})")

    if is_personal_query and user_oid:
        odata_parts.append(f"fields/OwnerEntraId eq '{user_oid}'")

    odata_filter = " and ".join(odata_parts) if odata_parts else None

    # Tier 1: No keywords — pure OData filter (exact matches only)
    if not keywords and not question:
        try:
            items = await get_list_items(
                list_id=list_id, list_name="Control Register",
                odata_filter=odata_filter, top=500,
            )
            return [_map_control(i) for i in items]
        except Exception as exc:
            logger.warning(f"compliance_search: control OData failed: {exc}")
            return []

    # Tier 2: Graph Search for keyword content matching
    kql_parts = [" ".join(keywords)] if keywords else []
    if iso_clause:
        kql_parts.append(f'"{iso_clause}"')
    if kql_parts:
        kql = " AND ".join(kql_parts)
        search_items = await _graph_search_list(list_id, "Control Register", kql)
        if search_items:
            # Apply active status filter in Python (search may return inactive items)
            search_items = [
                i for i in search_items
                if i.get("fields", {}).get("Status") in active_statuses
            ]
            if is_personal_query and user_oid:
                search_items = [
                    i for i in search_items
                    if i.get("fields", {}).get("OwnerEntraId") == user_oid
                ]
            return [_map_control(i) for i in search_items]

    # Tier 3: Python fallback
    try:
        items = await get_list_items(
            list_id=list_id, list_name="Control Register",
            odata_filter=odata_filter, top=500,
        )
    except Exception as exc:
        logger.warning(f"compliance_search: control fallback failed: {exc}")
        return []

    q_lower = question.lower() if question else ""

    def _matches(item: dict) -> bool:
        stmt = (item.get("fields", {}).get("ControlStatement", "") or "").lower()
        risk = (item.get("fields", {}).get("RiskImplication", "") or "").lower()
        haystack = stmt + " " + risk
        if keywords and any(kw.lower() in haystack for kw in keywords):
            return True
        if q_lower:
            if stmt and len(stmt) > 15 and stmt[:40] in q_lower:
                return True
            if risk and len(risk) > 15 and risk[:40] in q_lower:
                return True
        return False

    if keywords or q_lower:
        matched = [i for i in items if _matches(i)]
        items = matched if matched else items

    return [_map_control(i) for i in items]


def _map_control(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":               str(item.get("id", "")),
        "control_statement":f.get("ControlStatement") or f.get("Title", ""),
        "control_type":     f.get("ControlType", ""),
        "iso_clause":       f.get("ISOClause", ""),
        "owner_role_title": f.get("OwnerRole", ""),
        "owner_oid":        f.get("OwnerEntraId", ""),
        "source_document":  f.get("SourceDocument", ""),
        "risk_statement":   f.get("RiskImplication", ""),
        "status":           f.get("Status", ""),
    }


async def _get_all_evidence() -> list[dict]:
    """
    Fetch ALL evidence items in one batch — avoids per-control OData queries and
    the LinkedControlId column-type bug (SP may store as Number or Text).
    Python groupby in search_compliance() matches evidence to controls.
    """
    list_id = settings.evidence_tracker_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(
            list_id=list_id, list_name="Evidence Tracker", top=500,
        )
        return [_map_evidence(i) for i in items]
    except Exception as exc:
        logger.warning(f"compliance_search: evidence batch fetch failed: {exc}")
        return []


def _map_evidence(item: dict) -> dict:
    f = item.get("fields", item)
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
        "reviewer_name":      "",
    }


async def _get_standards_status(iso_clause: Optional[str]) -> Optional[dict]:
    if not iso_clause:
        return None
    return {"clause": iso_clause, "note": "See Standards Map for live traffic light"}


# =============================================================================
#  Register queries — Compliance Calendar
# =============================================================================

async def _search_compliance_calendar(
    keywords: list[str],
    status_filter: Optional[list[str]] = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    """
    Search Compliance Calendar. Returns ALL matching obligations — no cap.

    Tier 1: OData exact filter for known status values.
    Tier 2: Graph Search for keyword content in Title/Authority/Notes.
    Tier 3: Python fallback.
    """
    list_id = settings.compliance_calendar_list_id
    if not settings.is_list_configured(list_id):
        return []

    # Calendar uses OwnerId not OwnerEntraId
    odata_parts: list[str] = []
    valid_cal_statuses = {"Overdue", "Due Soon", "Upcoming", "Completed"}
    cal_statuses = [s for s in (status_filter or []) if s in valid_cal_statuses]
    if cal_statuses:
        sf = _odata_status_filter(cal_statuses)
        if sf:
            odata_parts.append(sf)
    if is_personal_query and user_oid:
        odata_parts.append(f"fields/OwnerId eq '{user_oid}'")

    odata_filter = " and ".join(odata_parts) if odata_parts else None

    # Tier 1: structured filter only (no keyword)
    if not keywords:
        try:
            items = await get_list_items(
                list_id=list_id, list_name="Compliance Calendar",
                odata_filter=odata_filter, top=500,
            )
            return [_map_obligation(i) for i in items]
        except Exception as exc:
            logger.warning(f"compliance_search: calendar OData failed: {exc}")
            return []

    # Tier 2: Graph Search
    kql = " ".join(keywords)
    search_items = await _graph_search_list(list_id, "Compliance Calendar", kql)
    if search_items:
        if cal_statuses:
            search_items = [
                i for i in search_items
                if i.get("fields", {}).get("Status") in cal_statuses
            ]
        if is_personal_query and user_oid:
            search_items = [
                i for i in search_items
                if i.get("fields", {}).get("OwnerId") == user_oid
            ]
        return [_map_obligation(i) for i in search_items]

    # Tier 3: Python fallback
    try:
        items = await get_list_items(
            list_id=list_id, list_name="Compliance Calendar",
            odata_filter=odata_filter, top=500,
        )
    except Exception as exc:
        logger.warning(f"compliance_search: calendar fallback failed: {exc}")
        return []

    kw_lower = [k.lower() for k in keywords]
    matched = []
    for i in items:
        f = i.get("fields", {})
        haystack = " ".join([
            (f.get("Title") or ""),
            (f.get("Authority") or ""),
            (f.get("ObligationType") or ""),
            (f.get("ObligationNotes") or ""),
        ]).lower()
        if any(kw in haystack for kw in kw_lower):
            matched.append(i)

    return [_map_obligation(i) for i in (matched if matched else items)]


def _map_obligation(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":         str(item.get("id", "")),
        "name":       f.get("Title", ""),
        "type":       f.get("ObligationType", ""),
        "authority":  f.get("Authority", ""),
        "due_date":   _date_only(f.get("DueDate", "")),
        "recurrence": f.get("Recurrence", ""),
        "notes":      f.get("ObligationNotes", ""),
        "owner_oid":  f.get("OwnerId", ""),
    }


# =============================================================================
#  Register queries — Gap Analysis
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


async def _search_gap_analysis(
    keywords: list[str],
    question: str = "",
    status_filter: Optional[list[str]] = None,
    severity_filter: Optional[str] = None,
    standard_filter: Optional[str] = None,
    iso_clause: Optional[str] = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    """
    Search Gap Analysis. Returns ALL matching gaps — no cap.

    Tier 1: OData exact filter for status/severity/standard/clause.
    Tier 2: Graph Search for keyword content in Finding/Standard/Clause text.
    Tier 3: Python fallback — always includes all items when no filter matches.
    """
    list_id = settings.gap_analysis_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid_gap_statuses = {"Open", "In progress", "Accepted risk", "Closed"}
    gap_statuses = [s for s in (status_filter or []) if s in valid_gap_statuses]

    odata_parts: list[str] = []
    if gap_statuses:
        sf = _odata_status_filter(gap_statuses)
        if sf:
            odata_parts.append(sf)
    if severity_filter:
        odata_parts.append(f"fields/Severity eq '{severity_filter}'")
    if standard_filter:
        odata_parts.append(f"fields/Standard eq '{standard_filter}'")
    if iso_clause:
        odata_parts.append(
            f"(fields/ClauseReference eq '{iso_clause}' or "
            f"fields/ISOClause eq '{iso_clause}')"
        )
    if is_personal_query and user_oid:
        odata_parts.append(f"fields/OwnerEntraId eq '{user_oid}'")

    odata_filter = " and ".join(odata_parts) if odata_parts else None

    # Tier 1: Pure structured filter — known exact values, no keyword search needed
    if odata_filter and not keywords and not question:
        try:
            items = await get_list_items(
                list_id=list_id, list_name="Gap Analysis",
                odata_filter=odata_filter, top=500,
            )
            logger.info(f"Gap Analysis Tier 1 (OData): {len(items)} items")
            return [_map_gap(i) for i in items]
        except Exception as exc:
            logger.warning(f"Gap Analysis OData filter failed: {exc} — falling through")

    # Tier 2: Graph Search for keyword content
    if keywords:
        kql_parts = [" ".join(keywords)]
        if standard_filter:
            kql_parts.append(f'"{standard_filter}"')
        if iso_clause:
            kql_parts.append(f'"{iso_clause}"')
        # Add status terms to KQL — helps when managed properties are mapped
        for s in gap_statuses:
            kql_parts.append(f'"{s}"')
        kql = " AND ".join(kql_parts)

        search_items = await _graph_search_list(list_id, "Gap Analysis", kql)
        if search_items:
            # Post-filter: apply structured filters in Python (Search may return extras)
            if gap_statuses:
                search_items = [i for i in search_items
                                if i.get("fields", {}).get("Status") in gap_statuses]
            if severity_filter:
                search_items = [i for i in search_items
                                if i.get("fields", {}).get("Severity") == severity_filter]
            if is_personal_query and user_oid:
                search_items = [i for i in search_items
                                if i.get("fields", {}).get("OwnerEntraId") == user_oid]
            if search_items:
                logger.info(f"Gap Analysis Tier 2 (Graph Search): {len(search_items)} items")
                return [_map_gap(i) for i in search_items]

    # Tier 3: Python fallback — fetch (with OData filter if any) + Python substring
    try:
        items = await get_list_items(
            list_id=list_id, list_name="Gap Analysis",
            odata_filter=odata_filter, top=500,
        )
    except Exception as exc:
        logger.warning(f"Gap Analysis Python fallback failed: {exc}")
        return []

    logger.info(f"Gap Analysis Tier 3 (Python): {len(items)} fetched")

    if not keywords and not question:
        return [_map_gap(i) for i in items]

    kw_lower = [k.lower() for k in keywords]
    q_lower  = question.lower() if question else ""
    matched = []
    for i in items:
        f = i.get("fields", {})
        haystack = " ".join([
            f.get("Finding", "") or f.get("Title", ""),
            f.get("Standard", ""),
            f.get("ClauseReference", "") or f.get("ISOClause", ""),
            f.get("Severity", ""),
            f.get("Status", ""),
            f.get("ProposedRemediation", "")[:200],
        ]).lower()
        if kw_lower and any(kw in haystack for kw in kw_lower):
            matched.append(i)
            continue
        if q_lower:
            for text in [f.get("Finding", ""), f.get("Standard", "")]:
                t = (text or "").lower()
                if t and len(t) > 15 and t[:40] in q_lower:
                    matched.append(i)
                    break

    # For broad "list all" queries with no keyword match, return everything
    return [_map_gap(i) for i in (matched if matched else items)]


# =============================================================================
#  Register queries — Document Register
# =============================================================================

def _map_document(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":                  str(item.get("id", "")),
        "document_code":       f.get("DocumentCode", ""),
        "title":               f.get("Title", ""),
        "type":                f.get("DocumentType", ""),
        "department":          f.get("Department", ""),
        "status":              f.get("Status", ""),
        "current_version":     f.get("CurrentVersion", ""),
        "effective_date":      _date_only(f.get("EffectiveDate", "")),
        "next_review_date":    _date_only(f.get("NextReviewDate", "")),
        "applicable_standards":f.get("ApplicableStandards", ""),
        "sharepoint_url":      f.get("SharePointUrl", ""),
        "owner_oid":           f.get("OwnerId", ""),
    }


async def _search_document_register(
    keywords: list[str],
    question: str = "",
    document_code: Optional[str] = None,
    status_filter: Optional[list[str]] = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    """
    Search Document Register. Returns ALL matching documents — no cap.

    Document code exact match → OData Tier 1.
    Keywords → Graph Search Tier 2 → Python fallback Tier 3.
    Active-only by default unless status_filter specifies otherwise.
    """
    list_id = settings.document_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid_doc_statuses = {"Active", "Under Review", "Superseded", "Withdrawn"}
    doc_statuses = [s for s in (status_filter or []) if s in valid_doc_statuses]
    # Default: exclude Withdrawn unless explicitly requested
    if not doc_statuses:
        doc_statuses = ["Active", "Under Review"]

    odata_parts: list[str] = []
    sf = _odata_status_filter(doc_statuses)
    if sf:
        odata_parts.append(sf)
    if is_personal_query and user_oid:
        odata_parts.append(f"fields/OwnerId eq '{user_oid}'")

    odata_filter = " and ".join(odata_parts) if odata_parts else None

    # Document code exact match (Tier 1 variant)
    if document_code:
        dc_norm = document_code.lower().replace(" ", "-").replace("_", "-")
        try:
            items = await get_list_items(
                list_id=list_id, list_name="Document Register", top=500,
            )
            active = [i for i in items
                      if i.get("fields", {}).get("Status") in doc_statuses
                      or i.get("fields", {}).get("Status") != "Withdrawn"]
            code_matched = [
                i for i in active
                if dc_norm in (i.get("fields", {}).get("DocumentCode") or "").lower().replace(" ", "-")
                or (i.get("fields", {}).get("DocumentCode") or "").lower().replace(" ", "-") in dc_norm
            ]
            if code_matched:
                return [_map_document(i) for i in code_matched]
            # Code not found — enrich keywords with tokens from code
            dc_tokens = [
                t for t in re.split(r'[-_\s]+', dc_norm)
                if len(t) > 2 and t not in {"drg", "the", "and", "for",
                                              "01", "02", "03", "04", "05", "06",
                                              "24", "25", "26", "27"}
            ]
            keywords = list(dict.fromkeys(list(keywords) + dc_tokens))
        except Exception as exc:
            logger.warning(f"Document register code match failed: {exc}")

    if not keywords and not question:
        try:
            items = await get_list_items(
                list_id=list_id, list_name="Document Register",
                odata_filter=odata_filter, top=500,
            )
            return [_map_document(i) for i in items]
        except Exception as exc:
            logger.warning(f"Document register OData failed: {exc}")
            return []

    # Tier 2: Graph Search
    kql = " ".join(keywords)
    search_items = await _graph_search_list(list_id, "Document Register", kql)
    if search_items:
        search_items = [i for i in search_items
                        if i.get("fields", {}).get("Status") in doc_statuses]
        if is_personal_query and user_oid:
            search_items = [i for i in search_items
                            if i.get("fields", {}).get("OwnerId") == user_oid]
        if search_items:
            return [_map_document(i) for i in search_items]

    # Tier 3: Python fallback
    try:
        items = await get_list_items(
            list_id=list_id, list_name="Document Register",
            odata_filter=odata_filter, top=500,
        )
    except Exception as exc:
        logger.warning(f"Document register Python fallback failed: {exc}")
        return []

    kw_lower = [k.lower() for k in keywords]
    q_lower  = question.lower() if question else ""
    matched = []
    for i in items:
        f = i.get("fields", {})
        haystack = " ".join([
            f.get("Title", ""),
            f.get("DocumentCode", ""),
            f.get("Department", ""),
            f.get("DocumentType", ""),
            f.get("ApplicableStandards", ""),
        ]).lower()
        if kw_lower and any(kw in haystack for kw in kw_lower):
            matched.append(i)
            continue
        if q_lower:
            for text in [f.get("Title", ""), f.get("DocumentCode", "")]:
                t = (text or "").lower()
                if t and len(t) > 15 and t[:40] in q_lower:
                    matched.append(i)
                    break

    return [_map_document(i) for i in (matched if matched else items)]


# =============================================================================
#  Register queries — Strategic Risk Register
# =============================================================================

_LIKELIHOOD_MAP = {"Low": 1, "Medium": 2, "High": 3}
_IMPACT_MAP     = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}


def _map_risk(item: dict) -> dict:
    f = item.get("fields", item)
    likelihood = f.get("Likelihood") or "Low"
    impact     = f.get("Impact") or "Low"
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


async def _search_strategic_risks(
    keywords: list[str],
    question: str = "",
    status_filter: Optional[list[str]] = None,
    severity_filter: Optional[str] = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    """
    Search Strategic Risk Register. Returns ALL matching risks — no cap.

    Tier 1: OData filter for status/risk_level.
    Tier 2: Graph Search for keywords in Description/Category/Treatment.
    Tier 3: Python fallback.
    """
    list_id = settings.strategic_risk_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid_risk_statuses = {"Open", "In progress", "Accepted risk", "Closed"}
    risk_statuses = [s for s in (status_filter or []) if s in valid_risk_statuses]

    odata_parts: list[str] = []
    if risk_statuses:
        sf = _odata_status_filter(risk_statuses)
        if sf:
            odata_parts.append(sf)
    if is_personal_query and user_oid:
        odata_parts.append(f"fields/OwnerEntraId eq '{user_oid}'")

    odata_filter = " and ".join(odata_parts) if odata_parts else None

    # Tier 1: structured filter only
    if odata_filter and not keywords and not question:
        try:
            items = await get_list_items(
                list_id=list_id, list_name="Strategic Risk Register",
                odata_filter=odata_filter, top=500,
            )
            logger.info(f"Strategic Risks Tier 1 (OData): {len(items)} items")
            return [_map_risk(i) for i in items]
        except Exception as exc:
            logger.warning(f"Strategic Risks OData failed: {exc}")

    # Tier 2: Graph Search
    if keywords:
        kql = " ".join(keywords)
        search_items = await _graph_search_list(list_id, "Strategic Risk Register", kql)
        if search_items:
            if risk_statuses:
                search_items = [i for i in search_items
                                if i.get("fields", {}).get("Status") in risk_statuses]
            if is_personal_query and user_oid:
                search_items = [i for i in search_items
                                if i.get("fields", {}).get("OwnerEntraId") == user_oid]
            if severity_filter:
                # Risk level is computed, not stored — filter after mapping
                mapped = [_map_risk(i) for i in search_items]
                return [r for r in mapped if r.get("risk_level") == severity_filter]
            if search_items:
                logger.info(f"Strategic Risks Tier 2 (Graph Search): {len(search_items)} items")
                return [_map_risk(i) for i in search_items]

    # Tier 3: Python fallback
    try:
        items = await get_list_items(
            list_id=list_id, list_name="Strategic Risk Register",
            odata_filter=odata_filter, top=500,
        )
    except Exception as exc:
        logger.warning(f"Strategic Risks Python fallback failed: {exc}")
        return []

    if not keywords and not question:
        mapped = [_map_risk(i) for i in items]
        if severity_filter:
            mapped = [r for r in mapped if r.get("risk_level") == severity_filter]
        return mapped

    kw_lower = [k.lower() for k in keywords]
    q_lower  = question.lower() if question else ""
    matched = []
    for i in items:
        f = i.get("fields", {})
        haystack = " ".join([
            f.get("Description", "") or f.get("Title", ""),
            f.get("Category", ""),
            f.get("Treatment", "")[:200],
            f.get("Status", ""),
        ]).lower()
        if kw_lower and any(kw in haystack for kw in kw_lower):
            matched.append(i)
            continue
        if q_lower:
            text = (f.get("Description") or "").lower()
            if text and len(text) > 15 and text[:40] in q_lower:
                matched.append(i)

    result = [_map_risk(i) for i in (matched if matched else items)]
    if severity_filter:
        result = [r for r in result if r.get("risk_level") == severity_filter]
    return result


# =============================================================================
#  Owner resolution
# =============================================================================

async def _resolve_owners(oids: list[str]) -> dict[str, dict]:
    """Resolve a list of Entra OIDs to {display_name, email} dicts in parallel."""
    unique_oids = list({o for o in oids if o})
    resolved: dict[str, dict] = {}
    tasks = [resolve_user(oid) for oid in unique_oids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for oid, result in zip(unique_oids, results):
        if isinstance(result, dict):
            resolved[oid] = result
    return resolved


# =============================================================================
#  ChromaDB vector search fallback (controls only)
# =============================================================================

_VECTOR_DISTANCE_THRESHOLD = 0.42


async def _vector_search_controls(question: str) -> list[dict]:
    """
    Semantic search over controls_v1 ChromaDB collection.
    Used only when SharePoint Control Register is not configured or returns nothing.
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
                "owner_role_title": meta.get("owner_role", ""),
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
    user_oid: str = "",
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Run a compliance search across ALL GRC registers for the given question.

    All five registers are searched in parallel. No arbitrary item caps — each
    register function returns ALL matching items. The response_generator decides
    how many to include in the LLM context (with count summaries so the LLM
    always knows the total), and the full result set is passed to the frontend
    via the compliance_data field in the API response.

    Retrieval tiers (per register):
      Tier 1 — OData exact filter (known status/severity/standard values)
      Tier 2 — Graph Search API (full-text keyword search in multi-line text)
      Tier 3 — Python fallback (fetch-all + substring match)

    Returns a structured dict with keys:
      controls, obligations, gaps, documents, risks — each a complete list.
      entities — extracted query metadata for debugging.
      found — True if any register returned results.
    """
    entities = await _extract_entities(question, recent_history=conversation_history)
    keywords        = entities.get("keywords") or []
    iso_clause      = entities.get("iso_clause")
    standard_filter = entities.get("standard")
    status_filter   = entities.get("status_filter") or []
    severity_filter = entities.get("severity_filter")
    document_code   = entities.get("document_code")
    is_personal     = bool(entities.get("is_personal_query"))

    logger.info(
        f"compliance_search: entities={entities} | user_oid={user_oid[:8] if user_oid else '—'}"
    )

    # Run all five register searches in parallel
    (
        controls_raw,
        obligations,
        gaps,
        documents,
        risks,
    ) = await asyncio.gather(
        _search_controls(
            keywords, iso_clause, question=question,
            status_filter=status_filter,
            user_oid=user_oid, is_personal_query=is_personal,
        ),
        _search_compliance_calendar(
            keywords,
            status_filter=status_filter,
            user_oid=user_oid, is_personal_query=is_personal,
        ),
        _search_gap_analysis(
            keywords, question=question,
            status_filter=status_filter,
            severity_filter=severity_filter,
            standard_filter=standard_filter,
            iso_clause=iso_clause,
            user_oid=user_oid, is_personal_query=is_personal,
        ),
        _search_document_register(
            keywords, question=question,
            document_code=document_code,
            status_filter=status_filter,
            user_oid=user_oid, is_personal_query=is_personal,
        ),
        _search_strategic_risks(
            keywords, question=question,
            status_filter=status_filter,
            severity_filter=severity_filter,
            user_oid=user_oid, is_personal_query=is_personal,
        ),
    )

    # ChromaDB vector fallback — only if SharePoint controls returned nothing
    if not controls_raw:
        controls_raw = await _vector_search_controls(question)

    # Enrich controls with evidence — single batch fetch, Python-side matching
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

    # Resolve ALL person OIDs across all registers in a single Graph API batch
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

    # Stamp reviewer names onto evidence items
    for ctrl in enriched_controls:
        for ev in ctrl.get("evidence", []):
            roid = ev.get("reviewer_oid", "")
            if roid and roid in owners:
                ev["reviewer_name"] = owners[roid].get("display_name", "")

    # Attach owner objects to every entity across every register
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

    logger.info(
        f"compliance_search results: controls={len(enriched_controls)}, "
        f"obligations={len(obligations)}, gaps={len(gaps)}, "
        f"documents={len(documents)}, risks={len(risks)}"
    )

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
#  Debug pipeline — exposes every intermediate step for a given question
# =============================================================================

async def debug_compliance_pipeline(question: str) -> dict:
    """
    Run the full compliance search pipeline and return every intermediate result.
    Shows: extracted entities (including status_filter/severity_filter), which tier
    was used per register, raw item counts, and the final LLM context block.
    """
    result: dict = {"question": question, "stages": {}}

    # Stage 1: Entity extraction
    try:
        entities = await _extract_entities(question)
        result["stages"]["1_entity_extraction"] = {
            "status":   "ok",
            "entities": entities,
        }
    except Exception as exc:
        result["stages"]["1_entity_extraction"] = {"status": "error", "error": str(exc)}
        return result

    keywords        = entities.get("keywords") or []
    iso_clause      = entities.get("iso_clause")
    status_filter   = entities.get("status_filter") or []
    severity_filter = entities.get("severity_filter")

    # Stage 2: Retrieval strategy summary
    result["stages"]["2_retrieval_strategy"] = {
        "tier_1_odata": {
            "applicable": bool(status_filter or severity_filter or iso_clause),
            "status_filter": status_filter,
            "severity_filter": severity_filter,
            "iso_clause": iso_clause,
        },
        "tier_2_graph_search": {
            "applicable": bool(keywords),
            "kql_keywords": " ".join(keywords),
            "region": settings.graph_search_region,
            "site_scope": _site_path(),
        },
        "tier_3_python": {
            "applicable": True,
            "note": "Always available as fallback",
        },
    }

    # Stage 3: Control Register query
    ctrl_list_id = settings.control_register_list_id
    if not settings.is_list_configured(ctrl_list_id):
        result["stages"]["3_control_register"] = {
            "status": "skipped", "reason": "list not configured",
        }
    else:
        try:
            controls = await _search_controls(keywords, iso_clause, question=question,
                                               status_filter=status_filter)
            result["stages"]["3_control_register"] = {
                "status":  "ok",
                "count":   len(controls),
                "sample":  [{"id": c["id"], "statement": c["control_statement"][:120]}
                            for c in controls[:3]],
            }
        except Exception as exc:
            result["stages"]["3_control_register"] = {"status": "error", "error": str(exc)}

    # Stage 4: Gap Analysis query
    gap_list_id = settings.gap_analysis_list_id
    if not settings.is_list_configured(gap_list_id):
        result["stages"]["4_gap_analysis"] = {
            "status": "skipped", "reason": "list not configured",
        }
    else:
        try:
            gaps = await _search_gap_analysis(
                keywords, question=question,
                status_filter=status_filter,
                severity_filter=severity_filter,
                standard_filter=entities.get("standard"),
                iso_clause=iso_clause,
            )
            result["stages"]["4_gap_analysis"] = {
                "status": "ok",
                "count":  len(gaps),
                "sample": [{"id": g["id"], "gap_id": g["gap_id"],
                            "status": g["status"], "severity": g["severity"]}
                           for g in gaps[:5]],
            }
        except Exception as exc:
            result["stages"]["4_gap_analysis"] = {"status": "error", "error": str(exc)}

    # Stage 5: Graph Search connectivity check
    try:
        token = await get_graph_access_token()
        client = get_client()
        test_resp = await client.post(
            _GRAPH_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "requests": [{
                    "entityTypes": ["listItem"],
                    "query": {"queryString": "test"},
                    "region": settings.graph_search_region,
                    "size": 1,
                }]
            },
            timeout=10.0,
        )
        result["stages"]["5_graph_search_connectivity"] = {
            "status": "ok" if test_resp.status_code == 200 else "error",
            "http_status": test_resp.status_code,
            "region": settings.graph_search_region,
        }
    except Exception as exc:
        result["stages"]["5_graph_search_connectivity"] = {
            "status": "error", "error": str(exc),
        }

    # Stage 6: What the LLM actually sees
    try:
        from agents.nl_search.response_generator import _context_from_compliance
        compliance_result = await search_compliance(question, conversation_history=[])
        ctx = _context_from_compliance(compliance_result)
        result["stages"]["6_llm_context"] = {
            "controls_found":    len(compliance_result.get("controls", [])),
            "documents_found":   len(compliance_result.get("documents", [])),
            "gaps_found":        len(compliance_result.get("gaps", [])),
            "risks_found":       len(compliance_result.get("risks", [])),
            "obligations_found": len(compliance_result.get("obligations", [])),
            "entities":          compliance_result.get("entities", {}),
            "context_sent_to_llm": ctx if ctx else "(empty — LLM will say no info)",
        }
    except Exception as exc:
        result["stages"]["6_llm_context"] = {"status": "error", "error": str(exc)}

    return result
