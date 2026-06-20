# =============================================================================
# agents/nl_search/intent_classifier.py — Query intent detection
#
# Returns one of four intents:
#   "compliance"     — rules, controls, ownership, evidence, ISO/NDPA clauses
#   "procedural"     — how-to, steps, forms, who to contact, process flows
#   "both"           — spans both categories
#   "conversational" — greetings, follow-ups, social phrases, no GRC topic
#
# Two layers:
#   1. Greeting safety net (no LLM) — deterministic first-word check so greetings
#      never hit the search pipeline even when the LLM is unavailable.
#   2. LLM via llm_chat at temperature=0 — classifies everything else, including
#      subtle follow-ups ("can you explain better") using conversation history.
#
# Default on LLM failure: "procedural".
# =============================================================================

import logging
from typing import Literal

from agents.llm_client import llm_chat

logger = logging.getLogger(__name__)

IntentType = Literal["compliance", "procedural", "both", "conversational"]

# ---------------------------------------------------------------------------
# Layer 1 — greeting safety net
# Checked before any LLM call. Keeps greetings out of the search pipeline even
# when the LLM gateway is down. Simple first-word set membership — no regex.
# ---------------------------------------------------------------------------

_GREETING_FIRST_WORDS = {
    "hi", "hello", "hey", "howdy", "yo", "sup",
    "good",   # covers "good morning", "good evening", "good afternoon"
    "morning", "evening", "afternoon",  # in case user skips "good"
    "greetings", "salutations",
}


def _is_greeting(question: str) -> bool:
    """True if the question is clearly a greeting and nothing else."""
    q = question.strip().lower()
    if not q or len(q) > 60:          # long questions are never just greetings
        return False
    first_word = q.split()[0].rstrip("!,.:?")
    return first_word in _GREETING_FIRST_WORDS


# ---------------------------------------------------------------------------
# Layer 2 — LLM classification via llm_chat
# Uses a dedicated classification system prompt (not the generic gateway system
# prompt) so the LLM receives clear, unambiguous instructions.
# ---------------------------------------------------------------------------

_CLASSIFIER_SYSTEM = (
    "You are a query router for OrgOS, Dragnet's GRC platform. "
    "Read the question and return exactly ONE word — nothing else, no punctuation, no explanation."
)

_CLASSIFIER_PROMPT = """\
Classify the question into one of these four categories:

compliance   — asking about policies, rules, controls, who is responsible, evidence
               required, compliance status, ISO/NDPA clauses, gaps, risks, deadlines,
               standards, what is due, or the status of an obligation.

procedural   — asking how to do something, what steps to follow, what form to use,
               who to contact, which system to use, what the process is, or how an
               approval workflow works.

both         — clear signals from both compliance and procedural.

conversational — any of:
  • Greetings or social phrases: "hi", "hello", "good evening", "how are you", "thanks"
  • Acknowledgements: "ok", "okay", "got it", "sure", "i see", "makes sense"
  • Follow-up requests that refer to a prior answer: "can you explain", "can you explain
    better", "tell me more", "elaborate", "what do you mean", "explain that again",
    "go on", "more details", "can you clarify", "explain it better"
  • Any vague short message with no specific GRC topic of its own

{history_block}Question: {question}

Return exactly one word — compliance, procedural, both, or conversational:"""


def _build_history_block(history: list[dict]) -> str:
    """Include the last user+assistant turn so follow-ups classify correctly."""
    if not history:
        return ""
    recent = history[-2:]
    lines: list[str] = []
    for m in recent:
        role    = "User" if m.get("role") == "user" else "Assistant"
        content = (m.get("content") or "").strip()[:120]
        lines.append(f"{role}: {content}")
    return "Prior conversation:\n" + "\n".join(lines) + "\n\n"


async def _llm_classify(question: str, history: list[dict]) -> IntentType:
    history_block = _build_history_block(history)
    messages = [
        {"role": "system", "content": _CLASSIFIER_SYSTEM},
        {"role": "user",   "content": _CLASSIFIER_PROMPT.format(
            history_block=history_block,
            question=question.strip(),
        )},
    ]
    raw  = await llm_chat(messages, max_tokens=5, temperature=0.0)
    word = raw.strip().lower().rstrip(".,!?;:").split()[0] if raw.strip() else ""
    if word in ("compliance", "procedural", "both", "conversational"):
        return word  # type: ignore[return-value]
    logger.debug(f"Intent LLM returned unexpected '{raw}' — defaulting to procedural")
    return "procedural"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def classify_intent(
    question: str,
    conversation_history: list[dict] | None = None,
) -> IntentType:
    """
    Classify a user question as compliance, procedural, both, or conversational.
    Always returns a valid IntentType — never raises.
    """
    if not question or not question.strip():
        return "procedural"

    # Layer 1 — greeting check (instant, no LLM)
    if _is_greeting(question):
        logger.debug(f"Intent (greeting): '{question[:60]}' → conversational")
        return "conversational"

    # Layer 2 — LLM via llm_chat with classification-specific system prompt
    try:
        result = await _llm_classify(question, conversation_history or [])
        logger.debug(f"Intent (LLM): '{question[:60]}' → {result}")
        return result
    except Exception as exc:
        logger.warning(f"Intent classifier failed: {exc} — defaulting to procedural")
        return "procedural"
