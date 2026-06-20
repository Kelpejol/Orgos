# =============================================================================
# agents/nl_search/procedural_search.py — Procedural step semantic search
#
# Handles procedural-intent queries: how to do something, what steps to follow.
#
# Strategy:
#   1. Embed the user's question with get_embedding().
#   2. Query ChromaDB procedures_v1 for top semantic matches.
#   3. For each unique (document_code, process_name) hit, fetch ALL steps for
#      that process from SharePoint — not just the matching step.
#      Returning one step out of context is useless; the full workflow is needed.
#   4. Return structured result dict for response_formatter.py.
#
# Result: the response shows the complete numbered workflow, not a snippet.
# =============================================================================

import logging
from typing import Optional

from agents.nl_search.vector_store import search_procedures
from agents.nl_search.procedures_service import get_steps_for_process, get_steps_for_document
from config import settings

logger = logging.getLogger(__name__)

# Similarity distance threshold — ChromaDB cosine distance, lower = more similar.
# Results above this threshold are considered poor matches and excluded.
_DISTANCE_THRESHOLD = 0.42

# How many ChromaDB hits to fetch before threshold filtering and deduplication.
# Higher value means the threshold filter has more material to work with, which
# improves recall for multi-topic questions where two procedures may sit at
# different positions in the top-N results.
_VECTOR_FETCH = 15

# Cap on how many distinct processes to return per query — keeps responses readable.
_MAX_PROCESSES = 3


def _build_procedural_query(question: str, conversation_history: list[dict] | None) -> str:
    """
    Build the query string to embed for ChromaDB search.

    For short or vague questions (under 12 words), append the prior user message
    so the embedding captures the actual topic. Example:
      Prior: "how do I apply for leave?"
      Current: "what form do I need for that?"
      Query: "what form do I need for that? how do I apply for leave?"

    This is the same context-enrichment principle used in compliance entity extraction:
    a short follow-up alone doesn't carry enough signal for semantic search to work.
    The combined query always embeds correctly because the vector space is topic-driven.
    """
    if not conversation_history or len(question.split()) >= 12:
        return question

    prior_user = [
        m for m in conversation_history
        if m.get("role") == "user"
        and (m.get("content") or "").strip() != question.strip()
    ]
    if not prior_user:
        return question

    prior_text = (prior_user[-1].get("content") or "").strip()[:200]
    if not prior_text:
        return question

    return f"{question} {prior_text}"


async def search_procedural(
    question: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Semantic search over procedural steps.
    Returns a structured dict consumed by response_formatter.format_procedural_response().

    conversation_history: used to enrich the embedding query when the question is short
    or referential. The prior user message is appended so ChromaDB finds the right
    procedure even for follow-ups like "what form do I need" or "who does this step".

    Shape:
    {
      "question": str,
      "processes": [
        {
          "document_code":  str,
          "document_title": str,
          "process_name":   str,
          "section_ref":    str,
          "steps":          [ { step_number, step_text, roles_involved,
                                forms_referenced, systems_referenced } ],
          "document_link":  str,
          "match_score":    float,  # 1 - distance (higher = better)
        }
      ],
      "found": bool,
    }
    """
    # Build the embedding query — enriched with context for short/vague questions.
    embed_query = _build_procedural_query(question, conversation_history)

    # Step 1: semantic search in ChromaDB — fetch more hits so threshold filter
    # has enough candidates when the question covers multiple distinct procedures.
    hits = await search_procedures(embed_query, n_results=_VECTOR_FETCH)
    if not hits:
        logger.info(f"procedural_search: no ChromaDB hits for: {question[:60]}")
        return {"question": question, "processes": [], "found": False}

    # Step 2: collect unique (document_code, process_name) pairs from good hits
    seen: set[tuple[str, str]] = set()
    candidates = []
    for hit in hits:
        if hit.get("distance", 1.0) > _DISTANCE_THRESHOLD:
            continue
        meta = hit.get("metadata", {})
        doc_code     = meta.get("document_code", "")
        process_name = meta.get("process_name", "")
        key = (doc_code, process_name)
        if key not in seen and doc_code:
            seen.add(key)
            candidates.append({
                "document_code":  doc_code,
                "document_title": meta.get("document_title", doc_code),
                "process_name":   process_name,
                "section_ref":    meta.get("section_ref", ""),
                "match_score":    round(1.0 - hit.get("distance", 0.5), 3),
            })

    if not candidates:
        return {"question": question, "processes": [], "found": False}

    # Step 3: expand each hit to the full workflow (all steps for that process)
    processes = []
    for cand in candidates[:_MAX_PROCESSES]:
        doc_code     = cand["document_code"]
        process_name = cand["process_name"]

        if process_name:
            steps = await get_steps_for_process(doc_code, process_name)
        else:
            # No process_name in metadata — fall back to all steps for the document
            steps = await get_steps_for_document(doc_code)

        if not steps:
            # ChromaDB has the embedding but SharePoint list isn't configured yet.
            # Build a stub from the good hits only (distance-filtered, same doc_code).
            # Never use the raw unfiltered `hits` — that would mix steps from unrelated
            # documents if a poor-quality hit happens to share the same doc_code.
            good_hits = [h for h in hits if h.get("distance", 1.0) <= _DISTANCE_THRESHOLD]
            steps = [{
                "step_number":    int(hit.get("metadata", {}).get("step_number", 1)),
                "step_text":      hit.get("document", ""),
                "roles_involved": hit.get("metadata", {}).get("roles_involved", ""),
                "forms_referenced":   "",
                "systems_referenced": "",
            } for hit in good_hits
              if hit.get("metadata", {}).get("document_code") == doc_code]

        doc_link = steps[0].get("document_link", "") if steps else ""

        processes.append({
            "document_code":  doc_code,
            "document_title": cand.get("document_title") or steps[0].get("document_title", doc_code) if steps else doc_code,
            "process_name":   process_name,
            "section_ref":    cand["section_ref"] or (steps[0].get("section_ref", "") if steps else ""),
            "steps":          steps,
            "document_link":  doc_link,
            "match_score":    cand["match_score"],
        })

    return {
        "question":  question,
        "processes": processes,
        "found":     bool(processes),
    }
