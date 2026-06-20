# =============================================================================
# agents/nl_search/intent_classifier.py — Query intent classification
#
# Returns one of four intents:
#   "compliance"     — rules, controls, ownership, evidence, ISO/NDPA clauses
#   "procedural"     — how-to, steps, forms, who to contact, process flows
#   "both"           — spans both categories
#   "conversational" — greetings, follow-ups, social phrases, no GRC topic
#
# Classification is done by the LLM at temperature=0 using llm_chat so that
# a classification-specific system prompt is used (not the generic gateway
# system prompt that wraps llm_generate).
#
# Default on LLM failure: "both" — safer than assuming one category.
# =============================================================================

import logging
from typing import Literal

from agents.llm_client import llm_chat

logger = logging.getLogger(__name__)

IntentType = Literal["compliance", "procedural", "both", "conversational"]

# How many prior messages to include for follow-up detection.
# 4 messages = 2 full turns — enough to catch references to the last answer.
_HISTORY_LOOKBACK = 4
_HISTORY_CHARS_PER_MSG = 400


# ---------------------------------------------------------------------------
# Classifier prompt
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a query router for OrgOS, Dragnet Solutions' GRC platform. "
    "Read the question and return exactly ONE word — nothing else."
)

_PROMPT = """\
Classify the question into exactly one of these four categories:

compliance   — the user is asking about: policies, rules, controls, who is
               responsible, evidence required, compliance status, ISO or NDPA
               clauses, gaps, risks, deadlines, standards, what is due, how long
               something must take, or the status of a specific obligation.

procedural   — the user is asking: how to do something, what steps to follow,
               what form to use, who to contact, which system to use, what the
               process is, what happens next, or how an approval workflow works.

both         — the question has clear signals from both compliance and procedural.

conversational — any of:
  • Greetings and social phrases: "hi", "hello", "good evening", "good morning",
    "how are you", and similar.
  • Acknowledgements: "ok", "thanks", "got it", "sure", "i see", "makes sense".
  • Follow-up: any question where the prior Assistant message already contains
    the answer or the context. KEY RULES:
    - If the assistant gave a specific answer (a duration, a deadline, a count,
      a step) and the user is asking about that same detail → conversational.
    - If the user is asking for the definition or full meaning of any term,
      acronym, role, or body that appeared in the prior assistant message
      → conversational. They are clarifying vocabulary from that answer, not
      starting a new GRC search.
    - Starting with "so", "but", "then", "and" is a strong follow-up signal.
  • Requests for elaboration: "can you explain", "can you explain better",
    "tell me more", "elaborate", "what do you mean", "explain that again",
    "go on", "more details", "can you clarify".
  • Any short vague message with no new GRC topic of its own.

{history_block}Question: {question}

Return exactly one word — compliance, procedural, both, or conversational:"""


def _history_block(history: list[dict]) -> str:
    if not history:
        return ""
    recent = history[-_HISTORY_LOOKBACK:]
    lines = []
    for m in recent:
        role    = "User" if m.get("role") == "user" else "Assistant"
        content = (m.get("content") or "").strip()[:_HISTORY_CHARS_PER_MSG]
        lines.append(f"{role}: {content}")
    return "Prior conversation:\n" + "\n".join(lines) + "\n\n"


async def classify_intent(
    question: str,
    conversation_history: list[dict] | None = None,
) -> IntentType:
    """
    Classify a user question. Always returns a valid IntentType — never raises.
    """
    if not question or not question.strip():
        return "both"

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": _PROMPT.format(
            history_block=_history_block(conversation_history or []),
            question=question.strip(),
        )},
    ]

    try:
        raw = await llm_chat(messages, max_tokens=40, temperature=0.0)
        if raw:
            # Scan every word — the model may add a preamble before the intent word
            for word in raw.strip().lower().split():
                clean = word.rstrip(".,!?;:()")
                if clean in ("compliance", "procedural", "both", "conversational"):
                    logger.debug(f"Intent: '{question[:70]}' → {clean}")
                    return clean  # type: ignore[return-value]
        logger.warning(f"Intent LLM returned unrecognised: '{raw[:60]}' — defaulting to both")
    except Exception as exc:
        logger.warning(f"Intent classifier error: {exc} — defaulting to both")

    return "both"
