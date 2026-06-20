# =============================================================================
# agents/nl_search/response_generator.py — RAG response generation
#
# Converts retrieved GRC context + Mem0 memory + conversation history into a
# natural, grounded AI response using the LLM gateway.
#
# Token budget (approximate per query with gpt-4o-mini):
#   ~150  system prompt
#   ~100  Mem0 memory context (compact extracted facts — always fits)
#   ~300  conversation history (last 3 turns, trimmed)
#   ~450  OrgOS context (retrieved controls/steps, capped per item)
#   ~60   current question
#   ────────────────────────────────────────────────────────
#   ~1060 input  |  ~480 output  ≈  $0.0003 per query
#
# Returns None on LLM failure — callers fall back to the structured formatter.
# =============================================================================

import logging
from typing import Optional

from agents.llm_client import llm_chat

logger = logging.getLogger(__name__)

# =============================================================================
#  System prompt — OrgOS AI persona
# =============================================================================

_SYSTEM = """\
You are OrgOS, the GRC and HR assistant for Dragnet Solutions Limited.
You help employees understand compliance policies and how-to procedures.

CRITICAL RULES:
1. For Dragnet-specific data (who owns a control, what the deadline is, evidence status,
   exact policy wording): answer ONLY from the provided OrgOS context.
   For general GRC/IT terminology, acronyms, and industry concepts (e.g. what an acronym
   stands for, what a governance role or body does, what a standard covers, definitions of
   industry terms): answer from your domain knowledge — these are industry fundamentals,
   not Dragnet-specific data.
2. Follow-ups: if context is empty but the conversation history or memory context contains
   the relevant information (e.g. the user asks "can you explain that" after a prior answer),
   answer naturally from that history — you do not need fresh context to continue.
3. Memory context: if a "Memory from prior conversations" section is present, use it to
   recall what was discussed before — especially when the user references a term, process,
   or policy from a previous session.
4. No info: if context is empty AND history has nothing relevant AND it is not a general \
industry concept, say: "I don't have that information in OrgOS yet. Please contact the Compliance team."
5. Greetings: for "hi", "hello" and similar, reply warmly in one sentence and invite a \
GRC or HR question. Example: "Hi! Ask me about Dragnet's policies, controls, or procedures."
6. Nonsense: if the question is completely unclear, say: \
"I didn't quite catch that — try rephrasing with a specific policy, procedure, or compliance topic."
7. Scope: only answer GRC, HR, and directly related questions about Dragnet. For anything \
completely outside that scope say you can only help with Dragnet GRC matters.

STYLE:
- Conversational and clear — explain the rule or process, not just state it.
- For procedures: numbered steps, mention key roles and forms naturally in the step text.
- For compliance: 2–4 sentences covering what the rule is, its ISO/NDPA reference, who owns it, and evidence status.
- If evidence is 🔴 Red or overdue, explicitly flag it — the user needs to know.
- Use **bold** for key terms, policy names, and ISO clauses.
- No markdown headers (###, ##). No bullet lists for compliance — prose only.
- Reference prior conversation or memory naturally when relevant.
- Be concise. Do not pad responses."""


# =============================================================================
#  Evidence helper
# =============================================================================

def _evidence_status(evidence_items: list[dict]) -> str:
    if not evidence_items:
        return "🔴 No evidence on file"
    statuses = [e.get("status", "Pending") for e in evidence_items]
    if any(s == "Overdue" for s in statuses):
        return "🔴 Evidence overdue"
    if any(s == "Accepted" for s in statuses):
        return "🟢 Evidence accepted"
    if any(s == "Submitted" for s in statuses):
        return "🟡 Submitted — awaiting review"
    return "🟡 Evidence pending"


# =============================================================================
#  Context builders — compact text blocks sent to the LLM
# =============================================================================

def _context_from_compliance(result: dict) -> str:
    controls    = result.get("controls", [])
    obligations = result.get("obligations", [])

    if not controls and not obligations:
        return ""

    lines: list[str] = []

    for ctrl in controls[:3]:
        stmt  = (ctrl.get("control_statement") or "")[:280]
        iso   = ctrl.get("iso_clause", "")
        src   = ctrl.get("source_document", "")
        ctype = ctrl.get("control_type", "")
        owner = (ctrl.get("owner") or {})
        name  = owner.get("display_name") or "Unassigned"
        ev    = ctrl.get("evidence", [])

        header = "[CONTROL"
        if src:
            header += f": {src}"
        if iso:
            header += f" ({iso})"
        header += "]"
        lines.append(header)
        lines.append(f"Rule: {stmt}")
        lines.append(f"Type: {ctype or 'N/A'} | Owner: {name} | {_evidence_status(ev)}")
        lines.append("")

    if obligations:
        lines.append("[OBLIGATIONS]")
        for ob in obligations[:3]:
            ob_name = ob.get("name", "")
            due     = ob.get("due_date", "")
            auth    = ob.get("authority", "")
            own     = (ob.get("owner") or {}).get("display_name") or "Unassigned"
            lines.append(f"- {ob_name} | Due: {due} | Authority: {auth} | Owner: {own}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _context_from_procedural(result: dict) -> str:
    processes = result.get("processes", [])
    if not processes:
        return ""

    lines: list[str] = []

    for proc in processes[:2]:
        proc_name = proc.get("process_name") or proc.get("document_code", "")
        doc_code  = proc.get("document_code", "")
        section   = proc.get("section_ref", "")
        steps     = sorted(proc.get("steps", []), key=lambda s: s.get("step_number") or 0)

        header = f"[PROCEDURE: {proc_name}"
        if doc_code and doc_code != proc_name:
            header += f" — {doc_code}"
        if section:
            header += f", §{section}"
        header += "]"
        lines.append(header)

        for step in steps[:8]:
            n     = step.get("step_number", "")
            text  = (step.get("step_text") or "")[:250]
            roles = step.get("roles_involved", "")
            forms = step.get("forms_referenced", "")
            step_line = f"Step {n}: {text}"
            extras: list[str] = []
            if roles:
                extras.append(f"Roles: {roles}")
            if forms:
                extras.append(f"Forms: {forms}")
            if extras:
                step_line += f" [{'; '.join(extras)}]"
            lines.append(step_line)

        lines.append("")

    return "\n".join(lines).rstrip()


def _context_for_combined(compliance_result: dict, procedural_result: dict) -> str:
    parts = [
        _context_from_compliance(compliance_result),
        _context_from_procedural(procedural_result),
    ]
    return "\n\n".join(p for p in parts if p)


# =============================================================================
#  History trimmer
# =============================================================================

def _trim_history(history: list[dict], max_turns: int = 3) -> list[dict]:
    """
    Keep the last N user/assistant turn pairs.
    Strips all fields except role and content (no sources, mode, timestamps).
    Caps assistant answers at 600 chars — enough to preserve full procedural answers.
    """
    clean: list[dict] = []
    for m in history:
        role    = m.get("role", "")
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if role == "assistant":
            content = content[:600]   # enough to keep key details in long procedural answers
        else:
            content = content[:150]
        clean.append({"role": role, "content": content})

    return clean[-(max_turns * 2):]


# =============================================================================
#  Main generator
# =============================================================================

async def generate_chat_response(
    question: str,
    intent: str,
    search_result: dict,
    conversation_history: list[dict],
    compliance_result: Optional[dict] = None,
    procedural_result: Optional[dict] = None,
    mem0_context: str = "",
) -> Optional[str]:
    """
    Generate a natural, LLM-written answer grounded in retrieved GRC context.

    Message layout sent to gateway:
      [{role: system, content: OrgOS persona}]
      [last 3 history pairs — user/assistant]
      [{role: user, content: "<mem0 facts> + <orgos context> + question"}]

    mem0_context: pre-fetched facts from Mem0 (memory_service.get_context).
    Returns None on failure so the caller can fall back to the structured formatter.
    """
    # ── Build OrgOS context block ────────────────────────────────────────────
    if intent == "conversational":
        orgos_context = ""
    elif intent == "compliance":
        orgos_context = _context_from_compliance(search_result)
    elif intent == "procedural":
        orgos_context = _context_from_procedural(search_result)
    else:  # "both"
        orgos_context = _context_for_combined(
            compliance_result or search_result,
            procedural_result or {},
        )

    # ── Build user message ───────────────────────────────────────────────────
    # Order: memory facts → OrgOS search context → question
    # Memory facts always appear even when OrgOS search returns nothing,
    # enabling the LLM to answer from prior session knowledge.
    parts: list[str] = []

    if mem0_context:
        parts.append(f"Memory from prior conversations:\n{mem0_context}")

    if orgos_context:
        parts.append(f"Context from OrgOS:\n{orgos_context}")
    elif intent != "conversational":
        parts.append("Context from OrgOS: (no matching records found)")

    parts.append(f"Question: {question}")
    user_content = "\n\n".join(parts)

    # ── Build full message list ──────────────────────────────────────────────
    history = _trim_history(conversation_history)
    messages: list[dict] = [{"role": "system", "content": _SYSTEM}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})

    try:
        answer = await llm_chat(messages, max_tokens=500, temperature=0.25)
        if not answer or not answer.strip():
            logger.warning("response_generator: LLM returned empty response")
            return None
        return answer.strip()
    except Exception as exc:
        logger.warning(f"response_generator: LLM call failed: {exc}")
        return None
