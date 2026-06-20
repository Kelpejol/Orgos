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


async def search_procedural(question: str) -> dict:
    """
    Semantic search over procedural steps.
    Returns a structured dict consumed by response_formatter.format_procedural_response().

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
    # Step 1: semantic search in ChromaDB
    hits = await search_procedures(question, n_results=5)
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
    for cand in candidates[:3]:  # cap at 3 processes per query
        doc_code     = cand["document_code"]
        process_name = cand["process_name"]

        if process_name:
            steps = await get_steps_for_process(doc_code, process_name)
        else:
            # No process_name in metadata — fall back to all steps for the document
            steps = await get_steps_for_document(doc_code)

        if not steps:
            # ChromaDB has the embedding but SharePoint list isn't configured yet
            # Still return the semantic match with the matched step text as a stub
            steps = [{
                "step_number": int(hit.get("metadata", {}).get("step_number", 1)),
                "step_text":   hit.get("document", ""),
                "roles_involved": hit.get("metadata", {}).get("roles_involved", ""),
                "forms_referenced": "",
                "systems_referenced": "",
            } for hit in hits
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
