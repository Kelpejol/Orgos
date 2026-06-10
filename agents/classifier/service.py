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
import json
import re
from difflib import SequenceMatcher
from typing import Optional

import httpx

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
#  AI semantic assist — second pass only, never final authority
# =============================================================================

def _fallback_semantic(kind: str, candidate: dict) -> dict:
    """Deterministic fallback guidance when AI is unavailable or invalid."""
    if kind == "role_variant":
        best = candidate.get("best_match")
        return {
            "suggested_action": "Merge" if best else "Create new role or map manually",
            "canonical_suggestion": best or "",
            "reviewer_rationale": (
                f"Role term '{candidate.get('role_term', '')}' was detected as "
                f"{'similar to ' + best if best else 'unrecognised in the Role Register'}."
            ),
            "semantic_confidence": round(float(candidate.get("best_score") or 0), 2),
            "key_difference": "Exact organisational meaning requires human confirmation.",
        }
    if kind == "duplicate_control":
        return {
            "suggested_action": "Merge or standardise",
            "canonical_suggestion": candidate.get("control_a", "")[:180],
            "reviewer_rationale": (
                f"Controls from {candidate.get('source_a', '')} and {candidate.get('source_b', '')} "
                f"are textually similar ({round(float(candidate.get('similarity') or 0) * 100)}%)."
            ),
            "semantic_confidence": round(float(candidate.get("similarity") or 0), 2),
            "key_difference": "Compare scope, owner, frequency, evidence, and standard mapping before merging.",
        }
    return {
        "suggested_action": "Select governing document or escalate",
        "canonical_suggestion": "",
        "reviewer_rationale": candidate.get("reason", "Potential conflicting requirement."),
        "semantic_confidence": round(float(candidate.get("similarity") or 0), 2),
        "key_difference": candidate.get("reason", ""),
    }


def _guidance_text(guidance: dict) -> str:
    return (
        f"AI semantic assist: {guidance.get('suggested_action', 'Review manually')}. "
        f"Rationale: {guidance.get('reviewer_rationale', '')} "
        f"Key difference: {guidance.get('key_difference', '')} "
        f"Confidence: {round(float(guidance.get('semantic_confidence') or 0) * 100)}%."
    )[:500]


async def _semantic_assist(kind: str, candidate: dict) -> dict:
    """
    Ask AI to enrich a deterministic classifier candidate.
    The AI does not create candidates and does not decide outcomes.
    """
    fallback = _fallback_semantic(kind, candidate)
    prompt = f"""You are assisting a GRC reviewer. A deterministic classifier has already flagged this candidate.
Do NOT make a final governance decision. Provide concise review guidance only.

Candidate kind: {kind}
Candidate JSON:
{json.dumps(candidate, ensure_ascii=False)[:4000]}

Return JSON object only with exactly:
{{
  "suggested_action": "Merge | Partial merge | Keep separate | Rename and standardise | Select governing document | Escalate to ExCo | Create new role | Review manually",
  "canonical_suggestion": "short canonical role/control name or empty string",
  "reviewer_rationale": "one sentence explaining why reviewer should inspect this",
  "semantic_confidence": 0.0,
  "key_difference": "short note on scope/owner/frequency/evidence difference"
}}"""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_timeout, connect=10.0)
        ) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "num_predict": 500,
                    },
                },
            )
            resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return fallback
        return {
            "suggested_action": str(parsed.get("suggested_action") or fallback["suggested_action"])[:80],
            "canonical_suggestion": str(parsed.get("canonical_suggestion") or fallback["canonical_suggestion"])[:180],
            "reviewer_rationale": str(parsed.get("reviewer_rationale") or fallback["reviewer_rationale"])[:300],
            "semantic_confidence": max(0.0, min(1.0, float(parsed.get("semantic_confidence") or fallback["semantic_confidence"]))),
            "key_difference": str(parsed.get("key_difference") or fallback["key_difference"])[:220],
        }
    except Exception as exc:
        logger.warning(f"Classifier semantic assist fallback for {kind}: {exc}")
        return fallback


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


async def _fetch_all_queue_items() -> list[dict]:
    """Fetch queue items for duplicate/conflict suppression checks."""
    items = await get_list_items(_q_list_id(), _Q_LIST_NAME)
    return [
        {"id": str(i["id"]), **i.get("fields", {})}
        for i in items
    ]


async def _fetch_role_register() -> list[dict]:
    """Fetch all role titles from the Role Register."""
    items = await get_list_items(_rr_list_id(), _RR_LIST_NAME)
    return [
        {
            "id":         str(i["id"]),
            "role_title": i.get("fields", {}).get("Title", ""),
            "department": i.get("fields", {}).get("Department", ""),
            "variant_terms": i.get("fields", {}).get("VariantTerms", ""),
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
    known_terms: set[str] = set()
    for role in role_register:
        known_terms.add(_normalise_role(role["role_title"]))
        for term in (role.get("variant_terms") or "").replace("\n", ",").split(","):
            if term.strip():
                known_terms.add(_normalise_role(term))

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
        if canonical_role.lower() in role_titles or raw_role in known_terms:
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


def _frequency_hint(statement: str) -> Optional[str]:
    text = statement.lower()
    for freq, patterns in {
        "daily": ["daily", "each day", "every day"],
        "weekly": ["weekly", "each week", "every week"],
        "monthly": ["monthly", "each month", "every month"],
        "quarterly": ["quarterly", "each quarter", "every quarter"],
        "bi-annually": ["bi-annually", "biannually", "twice a year", "semi-annually"],
        "annual": ["annually", "annual", "yearly", "once a year"],
        "per event": ["per event", "each incident", "upon occurrence", "when required"],
    }.items():
        if any(p in text for p in patterns):
            return freq
    return None


async def detect_conflicts(
    queue_items: list[dict],
    similarity_threshold: float = 0.72,
) -> list[dict]:
    """
    Detect likely contradictory requirements from different documents.
    Conservative first pass: similar controls with different frequency or owner.
    """
    findings = []
    seen_pairs: set[tuple[str, str]] = set()
    controls = [i for i in queue_items if i.get("ControlStatement")]

    for i, a in enumerate(controls):
        for b in controls[i + 1:]:
            if a.get("SourceDocumentCode") == b.get("SourceDocumentCode"):
                continue
            pair_key = tuple(sorted([a["id"], b["id"]]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            score = _similarity(
                _normalise_control(a["ControlStatement"]),
                _normalise_control(b["ControlStatement"]),
            )
            if score < similarity_threshold:
                continue

            freq_a = _frequency_hint(a["ControlStatement"])
            freq_b = _frequency_hint(b["ControlStatement"])
            owner_a = (a.get("ProposedOwnerRole") or "").strip()
            owner_b = (b.get("ProposedOwnerRole") or "").strip()

            reasons = []
            if freq_a and freq_b and freq_a != freq_b:
                reasons.append(f"frequency differs ({freq_a} vs {freq_b})")
            if owner_a and owner_b and _normalise_role(owner_a) != _normalise_role(owner_b):
                reasons.append(f"owner differs ({owner_a} vs {owner_b})")

            if reasons:
                findings.append({
                    "control_a": a["ControlStatement"],
                    "control_b": b["ControlStatement"],
                    "source_a": a.get("SourceDocumentCode", ""),
                    "source_b": b.get("SourceDocumentCode", ""),
                    "owner_a": owner_a,
                    "owner_b": owner_b,
                    "frequency_a": freq_a,
                    "frequency_b": freq_b,
                    "similarity": round(score, 2),
                    "reason": "; ".join(reasons),
                })

    logger.info(f"Conflict detection: {len(findings)} conflicts found")
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
    existing_items = await _fetch_all_queue_items()

    def already_harmonised(*needles: str) -> bool:
        clean_needles = [_normalise_role(n) for n in needles if n]
        for existing in existing_items:
            if existing.get("ItemType") != "Harmonisation":
                continue
            haystack = _normalise_role(
                " ".join([
                    existing.get("Title", ""),
                    existing.get("CanonicalName", ""),
                    existing.get("VariantTerms", ""),
                    existing.get("SourceDocumentCode", ""),
                ])
            )
            if clean_needles and all(n in haystack for n in clean_needles):
                return True
        return False

    # Role variant items
    for v in role_variants:
        if already_harmonised(v["role_term"], v.get("best_match") or ""):
            continue
        guidance = await _semantic_assist("role_variant", v)
        if v["type"] == "unrecognised":
            title = f"Unrecognised role term: {v['role_term']}"
            hint  = "This role term does not match any entry in the Role Register. Create a new role or map to an existing one."
            canonical = guidance.get("canonical_suggestion") or ""
        else:
            title    = f"Role variant: '{v['role_term']}' may be '{v['best_match']}'"
            hint     = f"Similarity score: {round(v['best_score'] * 100)}%. Confirm if these are the same role."
            canonical = guidance.get("canonical_suggestion") or v["best_match"] or ""

        variant_terms = f"{v['role_term']}"
        if v["best_match"]:
            variant_terms += f", {v['best_match']}"

        try:
            await create_list_item(_q_list_id(), _Q_LIST_NAME, {
                "Title":            title[:255],
                "ItemType":         "Harmonisation",
                "CanonicalName":    canonical,
                "VariantTerms":     variant_terms,
                "VariantFrequency": (
                    f"Found in {v['source_items']} item(s) across {len(v['source_docs'])} document(s). "
                    f"{_guidance_text(guidance)}"
                )[:500],
                "ReviewStatus":     "Pending Review",
                "ConfidenceScore":  max(float(v["best_score"] or 0), float(guidance.get("semantic_confidence") or 0)),
                "SourceDocumentCode": ", ".join(v["source_docs"][:3]),
            })
            written_variants += 1
        except Exception as exc:
            logger.error(f"Failed to write role variant item: {exc}")

    # Near-duplicate control items
    for dup in near_duplicates:
        if already_harmonised(dup["source_a"], dup["source_b"], dup["control_a"][:40]):
            continue
        guidance = await _semantic_assist("duplicate_control", dup)
        title = f"Possible duplicate: '{dup['control_a'][:200]}...'"
        try:
            await create_list_item(_q_list_id(), _Q_LIST_NAME, {
                "Title":             title[:255],
                "ItemType":          "Harmonisation",
                "ControlStatement":  dup["control_a"],
                "CanonicalName":     guidance.get("canonical_suggestion", ""),
                "VariantTerms":      f"Doc A: {dup['control_a'][:200]}\nDoc B: {dup['control_b'][:200]}",
                "VariantFrequency":  (
                    f"Similarity: {round(dup['similarity'] * 100)}%. "
                    f"{_guidance_text(guidance)}"
                )[:500],
                "SourceDocumentCode": f"{dup['source_a']} / {dup['source_b']}",
                "ReviewStatus":      "Pending Review",
                "ConfidenceScore":   max(float(dup["similarity"] or 0), float(guidance.get("semantic_confidence") or 0)),
            })
            written_duplicates += 1
        except Exception as exc:
            logger.error(f"Failed to write near-duplicate item: {exc}")

    return {
        "role_variants_written":   written_variants,
        "duplicates_written":      written_duplicates,
        "total":                   written_variants + written_duplicates,
    }


async def write_conflict_items(conflicts: list[dict]) -> dict:
    written = 0
    existing_items = await _fetch_all_queue_items()

    def already_flagged(conflict: dict) -> bool:
        key_parts = [
            _normalise_control(conflict.get("control_a", ""))[:80],
            conflict.get("source_a", ""),
            conflict.get("source_b", ""),
        ]
        for existing in existing_items:
            if existing.get("ItemType") != "Orphan":
                continue
            haystack = " ".join([
                existing.get("Title", ""),
                existing.get("ControlStatement", ""),
                existing.get("OrphanReason", ""),
                existing.get("SourceDocumentCode", ""),
            ]).lower()
            if all(part.lower() in haystack for part in key_parts if part):
                return True
        return False

    for conflict in conflicts:
        if already_flagged(conflict):
            continue
        guidance = await _semantic_assist("conflict", conflict)
        title = f"Conflict: {conflict['control_a'][:90]}"
        try:
            await create_list_item(_q_list_id(), _Q_LIST_NAME, {
                "Title":                    title[:255],
                "ItemType":                 "Orphan",
                "DocumentType":             "Policy",
                "ControlStatement":         conflict["control_a"][:500],
                "RiskStatement":            f"Contradictory requirement: {conflict['reason']}"[:500],
                "ProposedOwnerRole":        conflict.get("owner_a", ""),
                "SourceDocumentCode":       f"{conflict['source_a']} / {conflict['source_b']}",
                "OrphanDirection":          "Conflict",
                "OrphanClassification":     "CONTROL_CONFLICT",
                "OrphanReason":             (
                    f"{conflict['reason']}. "
                    f"{_guidance_text(guidance)} "
                    f"Doc A: {conflict['control_a'][:220]} | "
                    f"Doc B: {conflict['control_b'][:220]}"
                )[:500],
                "VariantTerms":             f"Doc A: {conflict['control_a']}\nDoc B: {conflict['control_b']}"[:500],
                "VariantFrequency":         f"Similarity: {round(conflict['similarity'] * 100)}%",
                "ReviewStatus":             "Pending Review",
                "ConfidenceScore":          max(float(conflict["similarity"] or 0), float(guidance.get("semantic_confidence") or 0)),
            })
            written += 1
        except Exception as exc:
            logger.error(f"Failed to write conflict item: {exc}")

    return {"conflicts_written": written}


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

    # Job 3
    conflicts = await detect_conflicts(queue_items)

    # Write Zone 3 items
    written = await write_harmonisation_items(role_variants, near_duplicates)
    conflict_written = await write_conflict_items(conflicts)

    summary = {
        "status":              "complete",
        "queue_items_read":    len(queue_items),
        "roles_compared":      len(role_register),
        "controls_compared":   len(confirmed_controls),
        "role_variants_found": len(role_variants),
        "duplicates_found":    len(near_duplicates),
        "conflicts_found":     len(conflicts),
        **written,
        **conflict_written,
        "total_written":       written.get("total", 0) + conflict_written.get("conflicts_written", 0),
    }

    logger.info(f"Classifier complete: {summary}")
    return summary
