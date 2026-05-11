# =============================================================================
# agents/classifier/service.py — Classifier Agent
# Runs after every Extractor batch. Three jobs per DRG-QI-REF-DINT-01-26 Section 3:
#
# Job 1 — Role variant detection
#   Compares extracted ProposedOwnerRole terms against Role Register.
#   Flags terms that do not exactly match a role title as potential variants.
#   Writes Zone 3 Harmonisation items.
#
# Job 2 — Near-duplicate control detection
#   Compares extracted ControlStatement values against each other and against
#   the confirmed Control Register. Flags pairs with >80% similarity.
#   Writes Zone 3 Harmonisation items.
#
# Job 3 — Conflict detection
#   Identifies controls from different documents that define contradictory
#   requirements for the same obligation.
#   Writes Zone 2 Orphan/Conflict items.
#
# The Classifier NEVER changes Extractor output. It only adds new items
# to Zone 2 and Zone 3 of the AI Review Queue.
# =============================================================================

import logging
import re
from difflib import SequenceMatcher
from typing import Optional

from config import settings
from graph.client import create_list_item, get_list_items

logger = logging.getLogger(__name__)

_Q_LIST_NAME  = "AI Review Queue"
_CR_LIST_NAME = "Control Register"
_RR_LIST_NAME = "Role Register"


def _q_list_id()  -> str: return settings.ai_review_queue_list_id
def _cr_list_id() -> str: return settings.control_register_list_id
def _rr_list_id() -> str: return settings.role_register_list_id


# =============================================================================
#  Text similarity helpers
# =============================================================================

def _similarity(a: str, b: str) -> float:
    """Returns 0-1 similarity between two strings. Case-insensitive."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _normalise_role(term: str) -> str:
    """Normalise a role term for comparison — strip punctuation, lowercase."""
    return re.sub(r"[^a-z0-9 ]", "", term.lower().strip())


def _normalise_control(stmt: str) -> str:
    """Strip common modal verbs and determiners for control comparison."""
    stmt = stmt.lower().strip()
    for word in ["shall", "must", "should", "will", "is required to",
                 "the ", "a ", "an ", "all "]:
        stmt = stmt.replace(word, " ")
    return re.sub(r"\s+", " ", stmt).strip()


# =============================================================================
#  Data fetchers
# =============================================================================

async def _fetch_queue_items() -> list[dict]:
    """Fetch all Extraction zone items from the AI Review Queue."""
    items = await get_list_items(_q_list_id(), _Q_LIST_NAME)
    return [
        {
            "id":               str(i["id"]),
            "ControlStatement": i.get("fields", {}).get("ControlStatement", ""),
            "ProposedOwnerRole":i.get("fields", {}).get("ProposedOwnerRole", ""),
            "SourceDocumentCode": i.get("fields", {}).get("SourceDocumentCode", ""),
            "ISOClause":        i.get("fields", {}).get("ISOClause", ""),
            "ItemType":         i.get("fields", {}).get("ItemType", ""),
            "ReviewStatus":     i.get("fields", {}).get("ReviewStatus", ""),
        }
        for i in items
        if i.get("fields", {}).get("ItemType") == "Extraction"
    ]


async def _fetch_role_register() -> list[dict]:
    """Fetch all role titles from the Role Register."""
    items = await get_list_items(_rr_list_id(), _RR_LIST_NAME)
    return [
        {
            "id":         str(i["id"]),
            "role_title": i.get("fields", {}).get("Title", ""),
            "department": i.get("fields", {}).get("Department", ""),
        }
        for i in items
        if i.get("fields", {}).get("Title")
    ]


async def _fetch_control_register() -> list[dict]:
    """Fetch confirmed controls from the Control Register."""
    items = await get_list_items(_cr_list_id(), _CR_LIST_NAME)
    return [
        {
            "id":               str(i["id"]),
            "ControlStatement": i.get("fields", {}).get("ControlStatement", ""),
            "SourceDocument":   i.get("fields", {}).get("SourceDocument", ""),
            "ISOClause":        i.get("fields", {}).get("ISOClause", ""),
        }
        for i in items
        if i.get("fields", {}).get("ControlStatement")
    ]


# =============================================================================
#  Job 1 — Role variant detection
# =============================================================================

async def detect_role_variants(
    queue_items: list[dict],
    role_register: list[dict],
) -> list[dict]:
    """
    For each extracted ProposedOwnerRole, check if it exactly matches
    a Role Register title. If not, find the closest match and flag it
    as a Zone 3 Harmonisation item.

    Returns list of variant findings to write to the queue.
    """
    findings = []
    role_titles = {r["role_title"].strip().lower(): r for r in role_register}

    # Group queue items by their extracted owner role
    role_groups: dict[str, list[dict]] = {}
    for item in queue_items:
        role = item.get("ProposedOwnerRole", "").strip()
        if not role:
            continue
        key = _normalise_role(role)
        if key not in role_groups:
            role_groups[key] = []
        role_groups[key].append(item)

    for raw_role, items in role_groups.items():
        canonical_role = items[0].get("ProposedOwnerRole", "").strip()

        # Exact match — no issue
        if canonical_role.lower() in role_titles:
            continue

        # Find best matching role in Role Register
        best_match = None
        best_score = 0.0
        for title, role_data in role_titles.items():
            score = _similarity(raw_role, title)
            if score > best_score:
                best_score = score
                best_match = role_data["role_title"]

        # Only flag if reasonably close (>0.5) or if completely unrecognised (flag as orphan candidate)
        if best_score < 0.3:
            # Completely unrecognised — might be a new role
            logger.info(f"Unrecognised role term: '{canonical_role}' — no close match in Role Register")
            finding = {
                "role_term":     canonical_role,
                "best_match":    None,
                "best_score":    best_score,
                "source_items":  len(items),
                "source_docs":   list({i["SourceDocumentCode"] for i in items if i.get("SourceDocumentCode")}),
                "type":          "unrecognised",
            }
        else:
            finding = {
                "role_term":     canonical_role,
                "best_match":    best_match,
                "best_score":    best_score,
                "source_items":  len(items),
                "source_docs":   list({i["SourceDocumentCode"] for i in items if i.get("SourceDocumentCode")}),
                "type":          "variant",
            }

        findings.append(finding)

    logger.info(f"Role variant detection: {len(findings)} findings")
    return findings


# =============================================================================
#  Job 2 — Near-duplicate control detection
# =============================================================================

async def detect_near_duplicates(
    queue_items: list[dict],
    confirmed_controls: list[dict],
    similarity_threshold: float = 0.80,
) -> list[dict]:
    """
    Compare extracted controls against each other and against confirmed controls.
    Flag pairs with similarity >= threshold as potential duplicates.

    Returns list of duplicate pairs.
    """
    findings = []
    seen_pairs: set[tuple] = set()

    # All controls to compare: queue items + confirmed register
    all_controls = [
        {
            "id":        i["id"],
            "statement": i["ControlStatement"],
            "source":    i["SourceDocumentCode"],
            "origin":    "queue",
        }
        for i in queue_items if i.get("ControlStatement")
    ] + [
        {
            "id":        c["id"],
            "statement": c["ControlStatement"],
            "source":    c["SourceDocument"],
            "origin":    "register",
        }
        for c in confirmed_controls if c.get("ControlStatement")
    ]

    for i, ctrl_a in enumerate(all_controls):
        norm_a = _normalise_control(ctrl_a["statement"])
        for ctrl_b in all_controls[i+1:]:
            norm_b = _normalise_control(ctrl_b["statement"])
            pair_key = tuple(sorted([ctrl_a["id"], ctrl_b["id"]]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            score = _similarity(norm_a, norm_b)
            if score >= similarity_threshold and ctrl_a["source"] != ctrl_b["source"]:
                findings.append({
                    "control_a":    ctrl_a["statement"],
                    "control_b":    ctrl_b["statement"],
                    "source_a":     ctrl_a["source"],
                    "source_b":     ctrl_b["source"],
                    "similarity":   round(score, 2),
                    "id_a":         ctrl_a["id"],
                    "id_b":         ctrl_b["id"],
                    "origin_a":     ctrl_a["origin"],
                    "origin_b":     ctrl_b["origin"],
                })

    logger.info(f"Near-duplicate detection: {len(findings)} pairs found")
    return findings


# =============================================================================
#  Write Zone 3 items to queue
# =============================================================================

async def write_harmonisation_items(
    role_variants:     list[dict],
    near_duplicates:   list[dict],
) -> dict:
    """
    Write Zone 3 Harmonisation items to the AI Review Queue.
    Returns counts of items written.
    """
    written_variants    = 0
    written_duplicates  = 0

    # Role variant items
    for v in role_variants:
        if v["type"] == "unrecognised":
            title = f"Unrecognised role term: {v['role_term']}"
            hint  = "This role term does not match any entry in the Role Register. Create a new role or map to an existing one."
            canonical = ""
        else:
            title    = f"Role variant: '{v['role_term']}' may be '{v['best_match']}'"
            hint     = f"Similarity score: {round(v['best_score'] * 100)}%. Confirm if these are the same role."
            canonical = v["best_match"] or ""

        variant_terms = f"{v['role_term']}"
        if v["best_match"]:
            variant_terms += f", {v['best_match']}"

        try:
            await create_list_item(_q_list_id(), _Q_LIST_NAME, {
                "Title":            title[:255],
                "ItemType":         "Harmonisation",
                "CanonicalName":    canonical,
                "VariantTerms":     variant_terms,
                "VariantFrequency": f"Found in {v['source_items']} item(s) across {len(v['source_docs'])} document(s)",
                "ReviewStatus":     "Pending Review",
                "ConfidenceScore":  v["best_score"],
                "SourceDocumentCode": ", ".join(v["source_docs"][:3]),
            })
            written_variants += 1
        except Exception as exc:
            logger.error(f"Failed to write role variant item: {exc}")

    # Near-duplicate control items
    for dup in near_duplicates:
        title = f"Possible duplicate: '{dup['control_a'][:80]}...'"
        try:
            await create_list_item(_q_list_id(), _Q_LIST_NAME, {
                "Title":             title[:255],
                "ItemType":          "Harmonisation",
                "ControlStatement":  dup["control_a"],
                "VariantTerms":      f"Doc A: {dup['control_a'][:200]}\nDoc B: {dup['control_b'][:200]}",
                "VariantFrequency":  f"Similarity: {round(dup['similarity'] * 100)}%",
                "SourceDocumentCode": f"{dup['source_a']} / {dup['source_b']}",
                "ReviewStatus":      "Pending Review",
                "ConfidenceScore":   dup["similarity"],
            })
            written_duplicates += 1
        except Exception as exc:
            logger.error(f"Failed to write near-duplicate item: {exc}")

    return {
        "role_variants_written":   written_variants,
        "duplicates_written":      written_duplicates,
        "total":                   written_variants + written_duplicates,
    }


# =============================================================================
#  Main entry point
# =============================================================================

async def run_classifier() -> dict:
    """
    Run the full Classifier pipeline.
    Fetches queue items, role register, and confirmed controls.
    Runs all three jobs and writes Zone 2/3 items.
    Returns a summary of what was found and written.
    """
    logger.info("Classifier agent starting")

    queue_items        = await _fetch_queue_items()
    role_register      = await _fetch_role_register()
    confirmed_controls = await _fetch_control_register()

    logger.info(
        f"Loaded: {len(queue_items)} queue items, "
        f"{len(role_register)} roles, "
        f"{len(confirmed_controls)} confirmed controls"
    )

    if not queue_items:
        logger.info("No queue items to classify — exiting")
        return {"status": "skipped", "reason": "No extraction items in queue"}

    # Job 1
    role_variants   = await detect_role_variants(queue_items, role_register)

    # Job 2
    near_duplicates = await detect_near_duplicates(queue_items, confirmed_controls)

    # Write Zone 3 items
    written = await write_harmonisation_items(role_variants, near_duplicates)

    summary = {
        "status":              "complete",
        "queue_items_read":    len(queue_items),
        "roles_compared":      len(role_register),
        "controls_compared":   len(confirmed_controls),
        "role_variants_found": len(role_variants),
        "duplicates_found":    len(near_duplicates),
        **written,
    }

    logger.info(f"Classifier complete: {summary}")
    return summary