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
# Context injected (in order of priority):
#   1. mem0_context — extracted facts from prior sessions (cross-session memory)
#      Compact, never truncated. Solves the "CISO cutoff" problem: a term that
#      appeared late in a long prior answer is present as a clean extracted fact.
#   2. conversation_history — last 4 raw messages from this session at 400 chars each.
#      Provides the immediate turn-level context Mem0 hasn't yet processed.
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
               something must take, the status of a specific obligation, OR any
               document register query such as: next review date, effective date,
               document status, document version, document owner, applicable
               standards — including when a specific document code (e.g.
               DRG-HR-SOP-COMTEN-01-26) is mentioned in the question.

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
      acronym, role, or body that appeared in the prior assistant message OR in
      the extracted memory facts → conversational. They are clarifying vocabulary
      from a past answer, not starting a new GRC search.
    - Starting with "so", "but", "then", "and" is a strong follow-up signal.
  • Requests for elaboration: "can you explain", "can you explain better",
    "tell me more", "elaborate", "what do you mean", "explain that again",
    "go on", "more details", "can you clarify".
  • Any short vague message with no new GRC topic of its own.

{context_block}Question: {question}

Return exactly one word — compliance, procedural, both, or conversational:"""


def _context_block(
    history: list[dict],
    mem0_context: str = "",
) -> str:
    """
    Build the context block injected before the question.
    Mem0 extracted facts come first (compact, no truncation risk).
    Raw conversation history comes second (truncated to 400 chars per message).
    """
    sections: list[str] = []

    # ── Mem0 cross-session facts ─────────────────────────────────────────────
    # These are clean extracted facts (not raw text) so they are never cut off
    # mid-sentence. A term like "CISO" that appeared at position 450 in a prior
    # answer will be present here as a fact regardless of char limits.
    if mem0_context:
        sections.append(f"Extracted facts from prior conversations:\n{mem0_context}")

    # ── Raw conversation history (this session) ──────────────────────────────
    if history:
        recent = history[-_HISTORY_LOOKBACK:]
        lines: list[str] = []
        for m in recent:
            role    = "User" if m.get("role") == "user" else "Assistant"
            content = (m.get("content") or "").strip()[:_HISTORY_CHARS_PER_MSG]
            lines.append(f"{role}: {content}")
        sections.append("Prior conversation:\n" + "\n".join(lines))

    if not sections:
        return ""
    return "\n\n".join(sections) + "\n\n"


async def classify_intent(
    question: str,
    conversation_history: list[dict] | None = None,
    mem0_context: str = "",
) -> IntentType:
    """
    Classify a user question. Always returns a valid IntentType — never raises.

    mem0_context: pre-fetched Mem0 memory facts (from memory_service.get_context).
    Pass "" if memory is unavailable — the classifier degrades gracefully to
    raw conversation history only.
    """
    if not question or not question.strip():
        return "both"

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": _PROMPT.format(
            context_block=_context_block(conversation_history or [], mem0_context),
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
