# =============================================================================
# agents/nl_search/intent_classifier.py — Query intent detection
#
# Classifies a user's question as one of four intents:
#   "compliance"     — rules, controls, ownership, evidence, ISO/NDPA clauses
#   "procedural"     — how-to, steps, forms, who to contact, process flows
#   "both"           — spans both categories
#   "conversational" — greetings, follow-ups, social phrases with no GRC topic
#
# The LLM classifies every query at temperature=0.
# Last conversation turn is included so follow-ups ("can you explain better",
# "what do you mean") are classified correctly in context.
#
# Default on LLM failure: "procedural" — most staff questions are how-to.
# =============================================================================

import logging
from typing import Literal

from agents.llm_client import llm_generate

logger = logging.getLogger(__name__)

IntentType = Literal["compliance", "procedural", "both", "conversational"]


# =============================================================================
#  LLM prompt
# =============================================================================

_INTENT_PROMPT = """\
You are a query router for OrgOS, Dragnet Solutions' GRC platform.
Classify the user's question into exactly one of these four categories:

COMPLIANCE — the user is asking about: policies, rules, controls, who is responsible,
evidence required, compliance status, ISO or NDPA clauses, gaps, risks, deadlines,
standards, what is due, or the status of a specific control or obligation.

PROCEDURAL — the user is asking: how to do something, what steps to follow, what form
to use, who to contact, which system to use, what the process is, what happens next,
or how an approval workflow works.

BOTH — the question has clear signals from both compliance and procedural.

CONVERSATIONAL — any of the following:
• Greetings or social phrases: "hi", "hello", "good evening", "how are you", "hey"
• Acknowledgements: "ok", "thanks", "got it", "sure", "i see", "makes sense"
• Follow-up requests referencing a prior answer: "can you explain", "can you explain
  better", "tell me more", "elaborate", "what do you mean", "explain that again",
  "go on", "more details", "what does that mean", "can you clarify"
• Any vague short message with no specific GRC topic of its own

{history_block}\
Question: {question}

Return exactly one word — compliance, procedural, both, or conversational:"""


# =============================================================================
#  Helpers
# =============================================================================

def _build_history_block(conversation_history: list[dict]) -> str:
    """
    Include the last user+assistant pair so the LLM understands what a
    follow-up like "can you explain better" is referring to.
    """
    if not conversation_history:
        return ""
    # Take the last two messages (one full turn)
    recent = conversation_history[-2:]
    lines: list[str] = []
    for m in recent:
        role    = "User" if m.get("role") == "user" else "Assistant"
        content = (m.get("content") or "").strip()[:120]
        lines.append(f"{role}: {content}")
    return "Prior conversation:\n" + "\n".join(lines) + "\n\n"


# =============================================================================
#  Public interface
# =============================================================================

async def classify_intent(
    question: str,
    conversation_history: list[dict] | None = None,
) -> IntentType:
    """
    Classify a user question as compliance, procedural, both, or conversational.
    LLM is called for every query at temperature=0 — no regex, no phrase lists.
    Always returns a valid IntentType — never raises.
    """
    if not question or not question.strip():
        return "procedural"

    history_block = _build_history_block(conversation_history or [])
    prompt = _INTENT_PROMPT.format(
        history_block=history_block,
        question=question.strip(),
    )

    try:
        raw  = await llm_generate(prompt, tier="light", max_tokens=5, temperature=0.0)
        word = raw.strip().lower().split()[0] if raw.strip() else ""
        if word in ("compliance", "procedural", "both", "conversational"):
            logger.debug(f"Intent: '{question[:60]}' → {word}")
            return word  # type: ignore[return-value]
        logger.debug(f"Intent LLM returned unexpected '{raw}' — defaulting to procedural")
        return "procedural"
    except Exception as exc:
        logger.warning(f"Intent classifier failed: {exc} — defaulting to procedural")
        return "procedural"
