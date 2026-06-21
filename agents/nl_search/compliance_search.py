# =============================================================================
# agents/nl_search/compliance_search.py — Compliance register search
#
# Handles compliance-intent queries against six SharePoint registers:
#   Gap Analysis, Control Register, Strategic Risk Register,
#   Compliance Calendar, Document Register, Evidence Tracker.
#
# Retrieval approach:
#   All registers are fetched in full (no OData $filter) because:
#   (a) The lists are small (<100 items each at Dragnet's current scale).
#   (b) SharePoint's Status/Severity/Clause columns are not indexed, so any
#       OData $filter on them returns HTTP 400 "field cannot be referenced".
#   (c) Full-fetch + Python filter is reliable, fast for small lists, and
#       never silently drops rows due to filter failures.
#
#   For keyword text search, Graph Search API is tried first as an optional
#   enhancement. If it fails for any reason, Python substring matching is used
#   as the fallback. The chatbot always returns data — Graph Search failure
#   is never a blocker.
#
# No arbitrary result caps — every function returns ALL matching items.
# response_generator.py handles token budget via count summaries + compact
# rendering; the complete set is always returned to the frontend.
# =============================================================================

import asyncio
import json
import logging
import re
from typing import Optional

from agents.llm_client import llm_generate
from agents.nl_search.vector_store import search_controls as vector_search_controls
from config import settings
from graph.auth import get_graph_access_token
from graph.client import get_client, get_list_items, get_list_item, resolve_user

logger = logging.getLogger(__name__)

# =============================================================================
#  Constants
# =============================================================================

_CONTROLS_ENRICH_LIMIT = 8
_EVIDENCE_PER_CONTROL  = 5
_VECTOR_RESULTS        = 8
_VECTOR_DISTANCE_MAX   = 0.42

_GRAPH_SEARCH_URL     = "https://graph.microsoft.com/v1.0/search/query"
_GRAPH_SEARCH_MAX_IDS = 40

# =============================================================================
#  Confirmed SharePoint field names (verified from live data 2026-06-21)
# =============================================================================
# Gap Analysis:
#   Title, Standard, Clause, ClauseTitle, GapCategory, Severity, Finding,
#   Impact, Status, TargetDate, ResolutionNotes, LinkedRiskId, ProposedRemediation
#   Status values: "Open" | "In progress" | "Accepted risk" | "Closed"
#
# Control Register:
#   Title, ControlStatement, ControlType, SourceDocument, ISOClause, OwnerRole,
#   RiskImplication, Status, ConfidenceScore, QueueItemId
#   Status values: "Active" | "Blocked" | "Under Review" | "Superseded" | "Withdrawn"
#   NOTE: current live data has Status="Blocked" for all controls — do NOT pre-filter to Active only.
#
# Strategic Risk Register:
#   Title, Description, Category, Source, Likelihood, Impact, RiskScore (decimal string),
#   OwnerEntraId, Treatment, Status, DateIdentified, ReviewDate, RelatedGapId, Notes
#   Status values: "Open" | "Accepted" | "Closed" | "In progress"
#   NOTE: "Accepted" here = accepted by ExCo (NOT "Accepted risk").
#
# Compliance Calendar:
#   Title, ObligationType, Authority, DueDate, Recurrence, OwnerEntraId,
#   Status (optional — may be absent, calculated from DueDate),
#   CompletedByEntraId, CompletedDate, CompletionNotes, EscalatedGapId
#
# Document Register:
#   Title, DocumentCode, DocumentType, Department, OwnerEntraId,
#   CurrentVersion, EffectiveDate, NextReviewDate, ApplicableStandards, Status
#   Status values: "Active" | "Under Review" | "Superseded" | "Withdrawn"
#
# Evidence Tracker:
#   Title, EvidenceDescription, EvidenceType, SourceSystem, EvidenceFormat,
#   Frequency, OwnerRole, OwnerEntraId, EvidenceLink, Status, LinkedControlId,
#   LastCollected, VerifiedBy, SubmissionNotes
#   Status values: "Pending" | "Submitted" | "Accepted" | "Rejected"

# =============================================================================
#  Status normalization
# =============================================================================

# Maps user phrasing → list of exact SharePoint status values.
# One phrase can expand to multiple values (e.g. "accepted" means "Accepted risk"
# in Gap Analysis but "Accepted" in Strategic Risk Register).
_STATUS_NORMALIZE: dict[str, list[str]] = {
    "closed":             ["Closed"],
    "close":              ["Closed"],
    "accepted":           ["Accepted risk", "Accepted"],
    "accepted risk":      ["Accepted risk"],
    "accepted by excos":  ["Accepted risk", "Accepted"],
    "excos accepted":     ["Accepted risk", "Accepted"],
    "open":               ["Open"],
    "in progress":        ["In progress"],
    "inprogress":         ["In progress"],
    "active":             ["Active"],
    "blocked":            ["Blocked"],
    "under review":       ["Under Review"],
    "overdue":            ["Overdue"],
    "due soon":           ["Due Soon"],
    "upcoming":           ["Upcoming"],
    "completed":          ["Completed"],
    "expired":            ["Expired"],
    "terminated":         ["Terminated"],
    "withdrawn":          ["Withdrawn"],
    "superseded":         ["Superseded"],
    "submitted":          ["Submitted"],
    "rejected":           ["Rejected"],
    "pending":            ["Pending"],
}

_SEVERITY_NORMALIZE: dict[str, str] = {
    "critical": "Critical",
    "major":    "Major",
    "minor":    "Minor",
}


def _normalize_statuses(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    seen: set[str] = set()
    result: list[str] = []
    for s in raw:
        for canonical in _STATUS_NORMALIZE.get(s.strip().lower(), [s.strip()]):
            if canonical and canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
    return result


def _normalize_severity(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    return _SEVERITY_NORMALIZE.get(raw.strip().lower())


def _date_only(val) -> str:
    if not val:
        return ""
    return str(val)[:10]


def _site_path() -> str:
    return settings.sharepoint_site_url.rstrip("/")


# =============================================================================
#  Entity extraction
# =============================================================================

_ENTITY_PROMPT = """\
Extract search entities from a GRC compliance question. Return JSON only.

Rules:
- Combine keywords from the current question AND context when the question is
  not self-contained (references "this", "it", "the above").
- status_filter: list of EXACT SharePoint status values matching the question.
  Gap Analysis statuses:      "Open" | "In progress" | "Accepted risk" | "Closed"
  Strategic Risk statuses:    "Open" | "Accepted" | "Closed" | "In progress"
  Control/Document statuses:  "Active" | "Blocked" | "Under Review" | "Superseded" | "Withdrawn"
  Evidence statuses:          "Pending" | "Submitted" | "Accepted" | "Rejected"
  Examples:
    "closed gaps"              → ["Closed"]
    "accepted by excos"        → ["Accepted risk", "Accepted"]
    "closed and accepted gaps" → ["Closed", "Accepted risk", "Accepted"]
    "active controls"          → ["Active"]
    no status qualifier         → []
- severity_filter: "Critical" | "Major" | "Minor" or null.
- Do NOT put status/severity words in keywords.

{context_block}Question: {question}

Fields:
  "keywords":          up to 6 topic keywords (subject matter only, not status words)
  "iso_clause":        ISO 27001/9001 clause if mentioned (e.g. "A.5.25") or null
  "standard":          "ISO 27001" | "ISO 9001" | "NDPA" or null
  "status_filter":     list of exact status values or []
  "severity_filter":   "Critical" | "Major" | "Minor" or null
  "is_personal_query": true if asking about "my" items / "assigned to me"
  "document_code":     exact Dragnet document code if present or null

JSON:"""


def _build_entity_context(question: str, recent_history: list[dict] | None) -> str:
    if not recent_history or len(question.split()) > 20:
        return ""
    prior = [
        m for m in recent_history
        if m.get("role") == "user"
        and (m.get("content") or "").strip() != question.strip()
    ]
    if not prior:
        return ""
    lines = [f"- {(m.get('content') or '').strip()[:200]}" for m in prior[-2:]]
    return "Recent context:\n" + "\n".join(lines) + "\n\n"


async def _extract_entities(question: str, recent_history: list[dict] | None = None) -> dict:
    context_block = _build_entity_context(question, recent_history)
    prompt = _ENTITY_PROMPT.format(question=question, context_block=context_block)
    raw = await llm_generate(prompt, tier="light", max_tokens=250, temperature=0.0, json_mode=True)

    m = re.search(r'\{.*?\}', raw.strip(), re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
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

    # Fallback: simple keyword extraction
    words = re.findall(r'\b[a-zA-Z]{4,}\b', question.lower())
    stop = {"what", "when", "where", "which", "that", "this", "with", "from",
            "have", "does", "your", "their", "show", "give", "tell", "about",
            "many", "much", "long", "must", "should", "would", "could"}
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
#  Graph Search — optional keyword enhancement
# =============================================================================

async def _graph_search_list(
    list_id: str,
    list_name: str,
    kql_query: str,
) -> list[dict]:
    """
    Full-text search via Graph Search API.
    Returns [] on any failure — callers always fall back to Python substring match.
    """
    if not settings.is_list_configured(list_id):
        return []

    payload = {
        "requests": [{
            "entityTypes": ["listItem"],
            "query":       {"queryString": f'({kql_query}) AND path:"{_site_path()}"'},
            "region":      settings.graph_search_region,
            "size":        500,
        }]
    }

    try:
        token  = await get_graph_access_token()
        client = get_client()
        resp   = await client.post(
            _GRAPH_SEARCH_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15.0,
        )
        if resp.status_code != 200:
            return []

        containers = (resp.json().get("value") or [{}])[0].get("hitsContainers") or []
        if not containers:
            return []
        hits = containers[0].get("hits") or []
        item_ids = [
            str((h.get("resource") or {}).get("id") or h.get("hitId") or "")
            for h in hits
        ]
        item_ids = [i for i in item_ids if i]

        if not item_ids or len(item_ids) > _GRAPH_SEARCH_MAX_IDS:
            return []

        results = await asyncio.gather(
            *[get_list_item(list_id, list_name, iid) for iid in item_ids],
            return_exceptions=True,
        )
        return [r for r in results if isinstance(r, dict) and r.get("fields")]

    except Exception as exc:
        logger.debug(f"Graph Search {list_name}: {exc}")
        return []


# =============================================================================
#  Mappers — confirmed field names from live SharePoint data
# =============================================================================

def _map_gap(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":                   str(item.get("id", "")),
        "gap_id":               f.get("Title", ""),
        "finding":              f.get("Finding", "") or f.get("Title", ""),
        "standard":             f.get("Standard", ""),
        "clause":               f.get("Clause", ""),          # confirmed: "Clause" not "ISOClause"
        "clause_title":         f.get("ClauseTitle", ""),
        "severity":             f.get("Severity", ""),
        "status":               f.get("Status", ""),
        "impact":               f.get("Impact", ""),
        "proposed_remediation": (f.get("ProposedRemediation") or "")[:400],
        "resolution_notes":     f.get("ResolutionNotes", ""),
        "linked_risk_id":       f.get("LinkedRiskId", ""),
        "target_date":          _date_only(f.get("TargetDate", "")),
        "owner_oid":            f.get("OwnerEntraId", ""),
    }


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


def _map_risk(item: dict) -> dict:
    f = item.get("fields", item)
    try:
        score_num = float(f.get("RiskScore") or 0)
    except (ValueError, TypeError):
        score_num = 0.0
    score = int(score_num)
    level = "Low" if score <= 3 else "Medium" if score <= 6 else "High" if score <= 9 else "Critical"
    return {
        "id":             str(item.get("id", "")),
        "description":    f.get("Description", "") or f.get("Title", ""),
        "category":       f.get("Category", ""),
        "source":         f.get("Source", ""),
        "likelihood":     str(f.get("Likelihood") or "Low"),
        "impact":         str(f.get("Impact") or "Low"),
        "risk_score":     str(score),
        "risk_level":     level,
        "treatment":      (f.get("Treatment") or "")[:300],
        "status":         f.get("Status", ""),
        "notes":          (f.get("Notes") or "")[:300],
        "related_gap_id": f.get("RelatedGapId", ""),
        "date_identified":_date_only(f.get("DateIdentified", "")),
        "review_date":    _date_only(f.get("ReviewDate", "")),
        "owner_oid":      f.get("OwnerEntraId", ""),
    }


def _map_obligation(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":               str(item.get("id", "")),
        "name":             f.get("Title", ""),
        "type":             f.get("ObligationType", ""),
        "authority":        f.get("Authority", ""),
        "due_date":         _date_only(f.get("DueDate", "")),
        "recurrence":       f.get("Recurrence", ""),
        "status":           f.get("Status", ""),
        "completion_notes": f.get("CompletionNotes", ""),
        "owner_oid":        f.get("OwnerEntraId", ""),  # confirmed: OwnerEntraId not OwnerId
    }


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
        "sharepoint_url":      (f.get("SharePointUrl") or "").strip(),
        "owner_oid":           f.get("OwnerEntraId", ""),
    }


def _map_evidence(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":                str(item.get("id", "")),
        "linked_control_id": str(f.get("LinkedControlId") or ""),
        "description":       f.get("EvidenceDescription", "") or f.get("Title", ""),
        "type":              f.get("EvidenceType", ""),
        "format":            f.get("EvidenceFormat", ""),
        "status":            f.get("Status", "Pending"),
        "due_date":          _date_only(f.get("DueDate", "")),
        "last_collected":    _date_only(f.get("LastCollected", "")),
        "link":              (f.get("EvidenceLink") or "").strip(),
        "source_system":     f.get("SourceSystem", ""),
        "collection_method": f.get("CollectionMethod", ""),
        "frequency":         f.get("Frequency", ""),
        "owner_role":        f.get("OwnerRole", ""),
        "owner_oid":         f.get("OwnerEntraId", ""),
        "reviewer_name":     f.get("VerifiedBy", ""),   # confirmed: VerifiedBy not ReviewerName
        "submission_notes":  f.get("SubmissionNotes", ""),
        "validation_criteria": f.get("ValidationCriteria", ""),
    }


# =============================================================================
#  Python keyword filter
# =============================================================================

def _keyword_filter(items: list[dict], keywords: list[str], *field_getters) -> list[dict]:
    """
    Return items where any keyword appears in any field from field_getters.
    Returns the original list unchanged when no keyword matches — never drops everything.
    """
    if not keywords or not items:
        return items
    kw_lower = [k.lower() for k in keywords]
    matched = [
        i for i in items
        if any(
            kw in (getter(i) or "").lower()
            for kw in kw_lower
            for getter in field_getters
        )
    ]
    return matched if matched else items


def _status_filter(items: list[dict], status_values: list[str], getter) -> list[dict]:
    """Filter items to those whose status field matches one of status_values."""
    if not status_values:
        return items
    sv_set = set(status_values)
    filtered = [i for i in items if getter(i) in sv_set]
    return filtered if filtered else items  # never return empty due to status mismatch


# =============================================================================
#  Register search functions
# =============================================================================

async def _search_gap_analysis(
    keywords: list[str],
    question: str = "",
    status_filter: list[str] | None = None,
    severity_filter: str | None = None,
    standard_filter: str | None = None,
    iso_clause: str | None = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    list_id = settings.gap_analysis_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid = {"Open", "In progress", "Accepted risk", "Closed"}
    gap_statuses = [s for s in (status_filter or []) if s in valid]

    try:
        items = await get_list_items(list_id=list_id, list_name="Gap Analysis", top=500)
    except Exception as exc:
        logger.warning(f"Gap Analysis fetch: {exc}")
        return []

    if not items:
        return []

    # Status filter (Python)
    if gap_statuses:
        sv = set(gap_statuses)
        filtered = [i for i in items if i.get("fields", {}).get("Status", "") in sv]
        items = filtered if filtered else items   # keep all if no matches (safety)

    # Severity filter (Python)
    if severity_filter:
        filtered = [i for i in items if i.get("fields", {}).get("Severity", "") == severity_filter]
        items = filtered if filtered else items

    # Standard filter (Python)
    if standard_filter:
        std_lower = standard_filter.lower()
        filtered = [i for i in items
                    if std_lower in (i.get("fields", {}).get("Standard", "") or "").lower()]
        items = filtered if filtered else items

    # ISO clause filter (Python — field name is "Clause")
    if iso_clause:
        iso_up = iso_clause.upper().strip()
        filtered = [i for i in items
                    if (i.get("fields", {}).get("Clause", "") or "").upper().strip() == iso_up]
        items = filtered if filtered else items

    # Owner filter
    if is_personal_query and user_oid:
        filtered = [i for i in items if i.get("fields", {}).get("OwnerEntraId", "") == user_oid]
        items = filtered if filtered else items

    # Keyword filter — try Graph Search first for multi-line text, fall back to Python
    if keywords:
        content_kw = [k for k in keywords
                      if k.lower() not in {"gap", "analysis", "control", "risk", "standard",
                                           "clause", "finding", "list", "show", "all"}]
        if content_kw:
            search_hits = await _graph_search_list(list_id, "Gap Analysis", " ".join(content_kw))
            if search_hits:
                search_ids = {str(i.get("id")) for i in search_hits}
                matched = [i for i in items if str(i.get("id")) in search_ids]
                if matched:
                    items = matched

        # Python keyword fallback on Finding / Standard / Clause / ClauseTitle
        items = _keyword_filter(
            items, keywords,
            lambda i: i.get("fields", {}).get("Finding", "") or i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("Standard", ""),
            lambda i: i.get("fields", {}).get("Clause", ""),
            lambda i: i.get("fields", {}).get("ClauseTitle", ""),
        )

    logger.info(f"Gap Analysis: returning {len(items)} items")
    return [_map_gap(i) for i in items]


async def _search_strategic_risks(
    keywords: list[str],
    question: str = "",
    status_filter: list[str] | None = None,
    severity_filter: str | None = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    list_id = settings.strategic_risk_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid = {"Open", "Accepted", "Closed", "In progress"}
    risk_statuses = [s for s in (status_filter or []) if s in valid]

    try:
        items = await get_list_items(list_id=list_id, list_name="Strategic Risk Register", top=500)
    except Exception as exc:
        logger.warning(f"Strategic Risk fetch: {exc}")
        return []

    if not items:
        return []

    if risk_statuses:
        sv = set(risk_statuses)
        filtered = [i for i in items if i.get("fields", {}).get("Status", "") in sv]
        items = filtered if filtered else items

    if is_personal_query and user_oid:
        filtered = [i for i in items if i.get("fields", {}).get("OwnerEntraId", "") == user_oid]
        items = filtered if filtered else items

    if keywords:
        search_hits = await _graph_search_list(list_id, "Strategic Risk Register", " ".join(keywords))
        if search_hits:
            search_ids = {str(i.get("id")) for i in search_hits}
            matched = [i for i in items if str(i.get("id")) in search_ids]
            if matched:
                items = matched
        items = _keyword_filter(
            items, keywords,
            lambda i: i.get("fields", {}).get("Description", "") or i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("Category", ""),
            lambda i: i.get("fields", {}).get("Treatment", ""),
        )

    mapped = [_map_risk(i) for i in items]
    if severity_filter:
        filtered_m = [r for r in mapped if r.get("risk_level") == severity_filter]
        mapped = filtered_m if filtered_m else mapped

    logger.info(f"Strategic Risks: returning {len(mapped)} items")
    return mapped


async def _search_compliance_calendar(
    keywords: list[str],
    status_filter: list[str] | None = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    list_id = settings.compliance_calendar_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid = {"Overdue", "Due Soon", "Upcoming", "Completed", "Withdrawn"}
    cal_statuses = [s for s in (status_filter or []) if s in valid]

    try:
        items = await get_list_items(list_id=list_id, list_name="Compliance Calendar", top=500)
    except Exception as exc:
        logger.warning(f"Compliance Calendar fetch: {exc}")
        return []

    if not items:
        return []

    if cal_statuses:
        sv = set(cal_statuses)
        filtered = [i for i in items if i.get("fields", {}).get("Status", "") in sv]
        items = filtered if filtered else items

    if is_personal_query and user_oid:
        filtered = [i for i in items if i.get("fields", {}).get("OwnerEntraId", "") == user_oid]
        items = filtered if filtered else items

    if keywords:
        search_hits = await _graph_search_list(list_id, "Compliance Calendar", " ".join(keywords))
        if search_hits:
            search_ids = {str(i.get("id")) for i in search_hits}
            matched = [i for i in items if str(i.get("id")) in search_ids]
            if matched:
                items = matched
        items = _keyword_filter(
            items, keywords,
            lambda i: i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("Authority", ""),
            lambda i: i.get("fields", {}).get("ObligationType", ""),
        )

    logger.info(f"Compliance Calendar: returning {len(items)} items")
    return [_map_obligation(i) for i in items]


async def _search_document_register(
    keywords: list[str],
    question: str = "",
    document_code: str | None = None,
    status_filter: list[str] | None = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    list_id = settings.document_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid = {"Active", "Under Review", "Superseded", "Withdrawn"}
    doc_statuses = [s for s in (status_filter or []) if s in valid]
    if not doc_statuses:
        doc_statuses = ["Active", "Under Review"]  # default: skip Withdrawn

    try:
        items = await get_list_items(list_id=list_id, list_name="Document Register", top=500)
    except Exception as exc:
        logger.warning(f"Document Register fetch: {exc}")
        return []

    if not items:
        return []

    # Document code exact match
    if document_code:
        dc = document_code.lower().replace(" ", "").replace("-", "").replace("_", "")
        matched = [
            i for i in items
            if dc in (i.get("fields", {}).get("DocumentCode") or "").lower().replace("-", "").replace("_", "")
        ]
        if matched:
            return [_map_document(i) for i in matched]

    sv = set(doc_statuses)
    filtered = [i for i in items if i.get("fields", {}).get("Status", "") in sv]
    items = filtered if filtered else items

    if is_personal_query and user_oid:
        filtered = [i for i in items if i.get("fields", {}).get("OwnerEntraId", "") == user_oid]
        items = filtered if filtered else items

    if keywords:
        search_hits = await _graph_search_list(list_id, "Document Register", " ".join(keywords))
        if search_hits:
            search_ids = {str(i.get("id")) for i in search_hits}
            matched = [i for i in items if str(i.get("id")) in search_ids]
            if matched:
                items = matched
        items = _keyword_filter(
            items, keywords,
            lambda i: i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("DocumentCode", ""),
            lambda i: i.get("fields", {}).get("Department", ""),
            lambda i: i.get("fields", {}).get("ApplicableStandards", ""),
        )

    logger.info(f"Document Register: returning {len(items)} items")
    return [_map_document(i) for i in items]


async def _search_controls(
    keywords: list[str],
    iso_clause: str | None,
    question: str = "",
    status_filter: list[str] | None = None,
    user_oid: str = "",
    is_personal_query: bool = False,
) -> list[dict]:
    list_id = settings.control_register_list_id
    if not settings.is_list_configured(list_id):
        return []

    valid = {"Active", "Blocked", "Under Review", "Superseded", "Withdrawn"}
    ctrl_statuses = [s for s in (status_filter or []) if s in valid]
    # Default: include Active AND Blocked (live data shows all controls are "Blocked")
    # Only exclude Withdrawn explicitly
    if not ctrl_statuses:
        ctrl_statuses = ["Active", "Blocked", "Under Review", "Superseded"]

    try:
        items = await get_list_items(list_id=list_id, list_name="Control Register", top=500)
    except Exception as exc:
        logger.warning(f"Control Register fetch: {exc}")
        return []

    if not items:
        return []

    sv = set(ctrl_statuses)
    filtered = [i for i in items if i.get("fields", {}).get("Status", "") in sv]
    items = filtered if filtered else items

    if is_personal_query and user_oid:
        filtered = [i for i in items if i.get("fields", {}).get("OwnerEntraId", "") == user_oid]
        items = filtered if filtered else items

    # ISO clause filter (Python)
    if iso_clause:
        iso_up = iso_clause.upper().strip()
        exact = [i for i in items
                 if (i.get("fields", {}).get("ISOClause", "") or "").upper().strip() == iso_up]
        if exact:
            items = exact
        else:
            sub = [i for i in items
                   if iso_up in (i.get("fields", {}).get("ISOClause", "") or "").upper()]
            if sub:
                items = sub

    if keywords:
        search_hits = await _graph_search_list(list_id, "Control Register",
                                               " ".join(keywords) + (f' "{iso_clause}"' if iso_clause else ""))
        if search_hits:
            search_ids = {str(i.get("id")) for i in search_hits}
            matched = [i for i in items if str(i.get("id")) in search_ids]
            if matched:
                items = matched
        items = _keyword_filter(
            items, keywords,
            lambda i: i.get("fields", {}).get("ControlStatement", "") or i.get("fields", {}).get("Title", ""),
            lambda i: i.get("fields", {}).get("RiskImplication", ""),
            lambda i: i.get("fields", {}).get("ISOClause", ""),
            lambda i: i.get("fields", {}).get("OwnerRole", ""),
            lambda i: i.get("fields", {}).get("SourceDocument", ""),
        )

    logger.info(f"Control Register: returning {len(items)} items")
    return [_map_control(i) for i in items]


# =============================================================================
#  Evidence fetching
# =============================================================================

async def _get_all_evidence() -> list[dict]:
    list_id = settings.evidence_tracker_list_id
    if not settings.is_list_configured(list_id):
        return []
    try:
        items = await get_list_items(list_id=list_id, list_name="Evidence Tracker", top=500)
        return [_map_evidence(i) for i in items]
    except Exception as exc:
        logger.warning(f"Evidence fetch: {exc}")
        return []


# =============================================================================
#  Owner resolution
# =============================================================================

async def _resolve_owners(oids: list[str]) -> dict[str, dict]:
    unique = list({o for o in oids if o})
    if not unique:
        return {}
    results = await asyncio.gather(*[resolve_user(oid) for oid in unique], return_exceptions=True)
    return {oid: r for oid, r in zip(unique, results) if isinstance(r, dict)}


# =============================================================================
#  Vector fallback for controls
# =============================================================================

async def _vector_search_controls(question: str) -> list[dict]:
    try:
        hits = await vector_search_controls(question, n_results=_VECTOR_RESULTS)
        controls = []
        for hit in hits:
            if hit.get("distance", 1.0) > _VECTOR_DISTANCE_MAX:
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
        return controls
    except Exception as exc:
        logger.debug(f"Vector search: {exc}")
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
    Search all six GRC registers and return a complete result dict.

    Retrieval: full-fetch (no OData filter) + Python filtering for all registers.
    Graph Search used optionally for keyword text matching. Falls back to
    Python substring if Graph Search fails.
    Returns ALL matching items — no arbitrary caps.
    """
    entities = await _extract_entities(question, recent_history=conversation_history)
    keywords        = entities.get("keywords") or []
    iso_clause      = entities.get("iso_clause")
    standard_filter = entities.get("standard")
    status_filter   = entities.get("status_filter") or []
    severity_filter = entities.get("severity_filter")
    document_code   = entities.get("document_code")
    is_personal     = bool(entities.get("is_personal_query"))

    logger.info(f"search_compliance | entities={entities} | user={user_oid[:8] if user_oid else '—'}")

    controls_raw, obligations, gaps, documents, risks = await asyncio.gather(
        _search_controls(keywords, iso_clause, question=question,
                         status_filter=status_filter,
                         user_oid=user_oid, is_personal_query=is_personal),
        _search_compliance_calendar(keywords, status_filter=status_filter,
                                    user_oid=user_oid, is_personal_query=is_personal),
        _search_gap_analysis(keywords, question=question,
                             status_filter=status_filter, severity_filter=severity_filter,
                             standard_filter=standard_filter, iso_clause=iso_clause,
                             user_oid=user_oid, is_personal_query=is_personal),
        _search_document_register(keywords, question=question, document_code=document_code,
                                   status_filter=status_filter,
                                   user_oid=user_oid, is_personal_query=is_personal),
        _search_strategic_risks(keywords, question=question,
                                status_filter=status_filter, severity_filter=severity_filter,
                                user_oid=user_oid, is_personal_query=is_personal),
    )

    if not controls_raw:
        controls_raw = await _vector_search_controls(question)

    # Enrich top N controls with evidence
    enriched = list(controls_raw[:_CONTROLS_ENRICH_LIMIT])
    if enriched:
        all_ev = await _get_all_evidence()
        ev_by_ctrl: dict[str, list] = {}
        for ev in all_ev:
            cid = ev.get("linked_control_id", "")
            if cid:
                ev_by_ctrl.setdefault(cid, []).append(ev)
        for ctrl in enriched:
            ctrl["evidence"] = ev_by_ctrl.get(ctrl["id"], [])[:_EVIDENCE_PER_CONTROL]

    # Resolve all OIDs in a single parallel batch
    all_oids = (
        [c["owner_oid"] for c in enriched if c.get("owner_oid")] +
        [ev.get("owner_oid", "") for c in enriched for ev in c.get("evidence", []) if ev.get("owner_oid")] +
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

    for ctrl in enriched:
        ctrl["owner"] = _person(ctrl.get("owner_oid", ""), fallback=ctrl.get("owner_role_title", ""))
    for ob in obligations:
        ob["owner"] = _person(ob.get("owner_oid", ""))
    for gap in gaps:
        gap["owner"] = _person(gap.get("owner_oid", ""))
    for doc in documents:
        doc["owner"] = _person(doc.get("owner_oid", ""))
    for risk in risks:
        risk["owner"] = _person(risk.get("owner_oid", ""))

    logger.info(
        f"search_compliance done | controls={len(enriched)} obls={len(obligations)} "
        f"gaps={len(gaps)} docs={len(documents)} risks={len(risks)}"
    )

    return {
        "question":    question,
        "entities":    entities,
        "controls":    enriched,
        "obligations": obligations,
        "gaps":        gaps,
        "documents":   documents,
        "risks":       risks,
        "found":       bool(enriched or obligations or gaps or documents or risks),
    }


# =============================================================================
#  Debug pipeline
# =============================================================================

async def debug_compliance_pipeline(question: str) -> dict:
    """
    Full pipeline introspection for the /debug endpoint.
    Shows entity extraction, raw register counts, Graph Search connectivity,
    and the exact LLM context block for the question.
    """
    result: dict = {"question": question, "stages": {}}

    try:
        entities = await _extract_entities(question)
        result["stages"]["1_entity_extraction"] = {"status": "ok", "entities": entities}
    except Exception as exc:
        result["stages"]["1_entity_extraction"] = {"status": "error", "error": str(exc)}
        return result

    async def _count(list_id, name):
        if not settings.is_list_configured(list_id):
            return {"status": "not_configured"}
        try:
            items = await get_list_items(list_id=list_id, list_name=name, top=500)
            statuses = list({i.get("fields", {}).get("Status", "") for i in items
                             if i.get("fields", {}).get("Status")})
            return {
                "status": "ok",
                "total": len(items),
                "field_names": list((items[0].get("fields", {}) if items else {}).keys())[:12],
                "status_values": statuses,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    counts = await asyncio.gather(
        _count(settings.gap_analysis_list_id,            "Gap Analysis"),
        _count(settings.control_register_list_id,        "Control Register"),
        _count(settings.strategic_risk_register_list_id, "Strategic Risk Register"),
        _count(settings.compliance_calendar_list_id,     "Compliance Calendar"),
        _count(settings.document_register_list_id,       "Document Register"),
        _count(settings.evidence_tracker_list_id,        "Evidence Tracker"),
    )
    result["stages"]["2_register_counts"] = dict(zip(
        ["gap_analysis", "control_register", "strategic_risks",
         "compliance_calendar", "document_register", "evidence_tracker"],
        counts,
    ))

    try:
        token  = await get_graph_access_token()
        client = get_client()
        r = await client.post(
            _GRAPH_SEARCH_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"requests": [{"entityTypes": ["listItem"],
                                "query": {"queryString": "test"},
                                "region": settings.graph_search_region, "size": 1}]},
            timeout=10.0,
        )
        result["stages"]["3_graph_search"] = {
            "http_status": r.status_code,
            "region": settings.graph_search_region,
            "ok": r.status_code == 200,
        }
    except Exception as exc:
        result["stages"]["3_graph_search"] = {"status": "error", "error": str(exc)}

    try:
        full = await search_compliance(question, conversation_history=[])
        from agents.nl_search.response_generator import _context_from_compliance
        ctx = _context_from_compliance(full)
        result["stages"]["4_full_search"] = {
            "entities":       full.get("entities", {}),
            "controls_found":    len(full.get("controls", [])),
            "obligations_found": len(full.get("obligations", [])),
            "gaps_found":        len(full.get("gaps", [])),
            "documents_found":   len(full.get("documents", [])),
            "risks_found":       len(full.get("risks", [])),
            "llm_context": ctx[:3000] if ctx else "(empty)",
        }
    except Exception as exc:
        result["stages"]["4_full_search"] = {"status": "error", "error": str(exc)}

    return result
