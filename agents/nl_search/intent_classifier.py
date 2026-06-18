# =============================================================================
# agents/nl_search/intent_classifier.py — Query intent detection
#
# Determines whether a user's question targets:
#   "compliance"  — asking about rules, ownership, status, gaps, schedules
#   "procedural"  — asking how to do something, what steps to follow
#   "both"        — question spans both (e.g. "what is the password policy
#                   and how do I change my password?")
#
# Two-layer approach:
#   1. Fast keyword heuristic — handles the clear-cut cases without an LLM call
#   2. LLM fallback — for ambiguous questions the heuristic can't classify
#
# Default when everything fails: "procedural" — most staff questions are how-to.
# =============================================================================

import logging
import re
from typing import Literal

from agents.llm_client import llm_generate

logger = logging.getLogger(__name__)

IntentType = Literal["compliance", "procedural", "both"]


# =============================================================================
#  Keyword heuristic (layer 1 — fast, no LLM)
# =============================================================================

_COMPLIANCE_PATTERNS = [
    r"\bwhat (are|is) the .*(requirement|control|policy|rule|standard|clause|obligation)\b",
    r"\bis .* compliant\b",
    r"\bwho is responsible\b",
    r"\bwho owns\b",
    r"\bwhat evidence\b",
    r"\bwhat is the status\b",
    r"\bshow (me )?gaps?\b",
    r"\bwhat are my overdue\b",
    r"\boverdue (items|evidence|controls)\b",
    r"\biso \d+\b",
    r"\biso clause\b",
    r"\bndpa\b",
    r"\bwhen is .*(due|next)\b",
    r"\bwhat controls?\b",
    r"\btraffic light\b",
    r"\bcompliance calendar\b",
    r"\brisk register\b",
    r"\bgap analysis\b",
    r"\bevidence (status|tracker|required)\b",
    r"\bcontrol register\b",
    r"\bstandards? map\b",
    r"\b(a\.\d+\.\d+)\b",   # ISO clause like A.5.17
]

_PROCEDURAL_PATTERNS = [
    r"\bhow (do|can|should) (i|we|you)\b",
    r"\bhow to\b",
    r"\bwhat steps?\b",
    r"\bwhat (is the )?process\b",
    r"\bwhat form\b",
    r"\bwhich form\b",
    r"\bwho (do i|should i) (contact|speak|report)\b",
    r"\bwhat (system|tool|platform)\b",
    r"\bwhat happens (when|if|after)\b",
    r"\bwhere do i\b",
    r"\bhow (long|many|much)\b",
    r"\bstep[- ]by[- ]step\b",
    r"\bapproval (chain|process|workflow)\b",
    r"\bwho approves?\b",
    r"\bwho signs?\b",
    r"\bwhat is the (procedure|workflow|process) for\b",
    r"\bhow (do|does) .* work\b",
    r"\bwalk me through\b",
    r"\bguide (me|us)\b",
    r"\bonboard\b",
    r"\boffboard\b",
    r"\brequest (a|an|the)\b",
    r"\bsubmit (a|an|the)\b",
    r"\bescalate\b",
    r"\breport (a|an|the)\b",
]

_COMPLIANCE_RE  = [re.compile(p, re.IGNORECASE) for p in _COMPLIANCE_PATTERNS]
_PROCEDURAL_RE  = [re.compile(p, re.IGNORECASE) for p in _PROCEDURAL_PATTERNS]


def _keyword_classify(question: str) -> IntentType | None:
    """
    Returns intent if the keyword heuristic is confident, None if ambiguous.
    """
    q = question.strip()
    compliance_hits  = sum(1 for p in _COMPLIANCE_RE  if p.search(q))
    procedural_hits  = sum(1 for p in _PROCEDURAL_RE  if p.search(q))

    if compliance_hits > 0 and procedural_hits > 0:
        return "both"
    if compliance_hits >= 1 and procedural_hits == 0:
        return "compliance"
    if procedural_hits >= 1 and compliance_hits == 0:
        return "procedural"
    return None  # ambiguous — delegate to LLM


# =============================================================================
#  LLM fallback (layer 2)
# =============================================================================

_INTENT_PROMPT = """\
You are the NL Search router for Dragnet OrgOS. Classify the user's question.

COMPLIANCE — the user asks about: rules/controls, who is responsible, evidence needed,
compliance status, what is due, gaps, risks, ISO/NDPA clauses, standards.

PROCEDURAL — the user asks: how to do something, what steps to follow, what form to use,
who to contact, what system, what the process is, what happens next.

BOTH — the question contains clear signals from both categories.

Return exactly one word: compliance, procedural, or both. No explanation."""


async def _llm_classify(question: str) -> IntentType:
    prompt = f"{_INTENT_PROMPT}\n\nQuestion: {question}\n\nAnswer:"
    raw = await llm_generate(prompt, tier="light", max_tokens=5, temperature=0.0)
    word = raw.strip().lower().split()[0] if raw.strip() else ""
    if word in ("compliance", "procedural", "both"):
        return word  # type: ignore[return-value]
    logger.debug(f"Intent LLM returned unexpected: '{raw}' — defaulting to procedural")
    return "procedural"


# =============================================================================
#  Public interface
# =============================================================================

async def classify_intent(question: str) -> IntentType:
    """
    Classify a user question as compliance, procedural, or both.
    Fast keyword heuristic first; LLM fallback for ambiguous cases.
    Always returns a valid IntentType — never raises.
    """
    if not question or not question.strip():
        return "procedural"

    # Layer 1: keyword heuristic
    heuristic = _keyword_classify(question)
    if heuristic is not None:
        logger.debug(f"Intent (heuristic): '{question[:60]}' → {heuristic}")
        return heuristic

    # Layer 2: LLM for genuinely ambiguous cases
    try:
        result = await _llm_classify(question)
        logger.debug(f"Intent (LLM): '{question[:60]}' → {result}")
        return result
    except Exception as exc:
        logger.warning(f"Intent LLM failed: {exc} — defaulting to procedural")
        return "procedural"
