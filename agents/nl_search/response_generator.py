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
import re
from typing import Optional

from agents.llm_client import llm_chat

logger = logging.getLogger(__name__)

# Full human-readable labels for the 16 DRG evidence type codes (DRG-QI-REF-EVTX-01-26).
# Included in context so the LLM can explain the type without hallucinating.
_EVIDENCE_TYPE_LABELS: dict[str, str] = {
    "LOG": "System log export",
    "CFG": "Configuration evidence",
    "APR": "Signed approval record",
    "FRM": "Completed form/record",
    "TRN": "Training record",
    "ACK": "Policy acknowledgement",
    "TST": "Test/drill/verification",
    "CRT": "Certificate/external attestation",
    "MTG": "Meeting/governance record",
    "REV": "Review record",
    "CHK": "Checklist completion",
    "CNT": "Contract/agreement",
    "INV": "Inventory/register extract",
    "CHG": "Change record",
    "INC": "Incident record",
    "RPT": "Report/assessment",
}

# =============================================================================
#  System prompt — OrgOS AI persona
# =============================================================================

_SYSTEM = """\
You are OrgOS, the GRC and HR assistant for Dragnet Solutions Limited.
You help employees understand compliance policies and how-to procedures.

CRITICAL RULES:
1. For Dragnet-specific data (who owns a control, what the deadline is, evidence status,
   exact policy wording, ISO/NDPA clause numbers, source documents): answer ONLY from
   the provided OrgOS context. Never substitute your own knowledge for these fields.
   ISO clause numbers in the OrgOS context are Dragnet's official registered mapping —
   if the context says "ISO clause: A.5.25", report A.5.25, not any other clause you
   know about that topic. The same applies to source document codes and control types.
   Evidence details (type, description, source system, frequency, collection method,
   validation criteria): answer ONLY from the "Evidence type" lines in the OrgOS context.
   If the evidence status says "No evidence on file" and no "Evidence type" lines follow,
   say "The evidence requirements for this control haven't been configured in OrgOS yet"
   — never invent evidence types, source systems, or collection steps from general knowledge.
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

REGISTERS IN CONTEXT:
- [CONTROL] — active GRC control with evidence, ownership, ISO clause.
- [OBLIGATIONS] — statutory/regulatory/licensing deadlines from the Compliance Calendar.
- [GAP FINDINGS] — compliance gaps found by audit or AI gap analysis.
- [DOCUMENT REGISTER] — policy/procedure documents with version, review dates, owner.
- [STRATEGIC RISKS] — ExCo-level risk register entries with scoring and treatment.
- [PROCEDURE] — step-by-step how-to processes with roles, forms, and systems.
Answer from whichever register(s) contain relevant data for the question. A question may
touch multiple registers — e.g. "what is the risk and when is the next review?" needs
both [CONTROL] and [DOCUMENT REGISTER] data.

STYLE:
- Links: when the OrgOS context contains a markdown link like [label](url), reproduce it exactly as-is — never rewrite the label, never paraphrase the URL, never omit the link. If the user asks for a link, output the exact markdown link from context.
- Dates: show dates as YYYY-MM-DD. Never add time, timezone, or "at" suffix — the data contains dates only.
- Conversational and clear — explain the rule or process, not just state it.
- For procedures: numbered steps, mention key roles and forms naturally in the step text.
- For compliance: 2–4 sentences covering what the rule is, its ISO/NDPA reference, who owns it, and evidence status.
- If evidence is 🔴 Red or overdue, explicitly flag it — the user needs to know.
- Use **bold** for key terms, policy names, and ISO clauses.
- No markdown headers (###, ##). No bullet lists for compliance — prose only.
- Reference prior conversation or memory naturally when relevant.
- Be concise. Do not pad responses."""


# =============================================================================
#  Link label helpers
# =============================================================================

def _clean_link_label(fname: str) -> str:
    """
    Turn a raw SharePoint filename into a human-readable link label.

    Transforms:
      "EVID-10-AI_Engineer_Vacancy_Zenith_Bank.docx"
      → "AI Engineer Vacancy Zenith Bank.docx"

    Rules applied in order:
      1. Strip leading EVID-NN- / EVID_NN_ style prefixes (evidence ID artefact).
      2. Replace underscores with spaces.
      3. URL-decode %20 as spaces (already done before calling, but guard here too).
    Does NOT remove the file extension — the user needs to know if it's a .docx or .pdf.
    """
    if not fname:
        return fname
    cleaned = re.sub(r'^EVID[-_]\d+[-_]', '', fname, flags=re.IGNORECASE)
    cleaned = cleaned.replace('_', ' ').replace('%20', ' ')
    return cleaned.strip() or fname


def _extract_link_label(raw_url: str, fallback: str = "View document") -> str:
    """
    Extract and clean the filename from a SharePoint ?file=... URL parameter.
    Falls back to the given fallback string if no file param found or filename is empty.
    Never returns an empty string — the LLM must always have a non-empty label to copy.
    """
    if "file=" in raw_url:
        try:
            fname = raw_url.split("file=")[1].split("&")[0].replace("%20", " ").strip()
            if fname:
                cleaned = _clean_link_label(fname)
                return cleaned if cleaned else fallback
        except Exception:
            pass
    return fallback or "View document"


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
    gaps        = result.get("gaps", [])
    documents   = result.get("documents", [])
    risks       = result.get("risks", [])

    if not controls and not obligations and not gaps and not documents and not risks:
        return ""

    lines: list[str] = []

    for ctrl in controls[:3]:
        stmt       = (ctrl.get("control_statement") or "")[:500]
        risk       = (ctrl.get("risk_statement") or "")[:500]
        iso        = ctrl.get("iso_clause", "")
        src        = ctrl.get("source_document", "")
        ctype      = ctrl.get("control_type", "")
        role_title = (ctrl.get("owner_role_title") or "").strip()
        owner      = (ctrl.get("owner") or {})
        person     = (owner.get("display_name") or "").strip()
        ev         = ctrl.get("evidence", [])

        # Build a clear ownership string — the LLM needs to be able to answer
        # "who owns this", "which role is responsible", and "who is the owner"
        # from the same line regardless of how the question is phrased.
        if role_title and person and person != role_title:
            owner_str = f"{role_title} (held by {person})"
        elif role_title:
            owner_str = role_title
        elif person:
            owner_str = person
        else:
            owner_str = "Unassigned"

        header = "[CONTROL"
        if src:
            header += f": {src}"
        header += "]"
        lines.append(header)
        lines.append(f"Rule: {stmt}")
        if iso:
            lines.append(f"ISO clause: {iso}")
        if risk:
            lines.append(f"Risk if fails: {risk}")
        lines.append(f"Type: {ctype or 'N/A'} | Owner role: {owner_str}")
        ev_status = _evidence_status(ev)
        lines.append(f"Evidence status: {ev_status}")
        if ev:
            for e in ev[:2]:
                etype         = e.get("type", "")
                elabel        = _EVIDENCE_TYPE_LABELS.get(etype, etype)
                edesc         = (e.get("description") or "")[:250]
                esrc          = e.get("source_system", "")
                efmt          = e.get("format", "")
                efreq         = e.get("frequency", "")
                ecoll         = e.get("collection_method", "")
                elink         = (e.get("link") or "").strip()
                estat         = e.get("status", "Pending")
                evalid        = (e.get("validation_criteria") or "")[:150]
                elast         = e.get("last_collected", "")
                ereviewer     = e.get("reviewer_name", "")
                erev_notes    = (e.get("reviewer_notes") or "")[:150]
                esub_notes    = (e.get("submission_notes") or "")[:150]
                # Show code + full label so LLM can explain both
                eline = f"  Evidence type: {etype} ({elabel})"
                if edesc:
                    eline += f" — {edesc}"
                extras: list[str] = []
                if esrc:
                    extras.append(f"Source system: {esrc}")
                if efmt:
                    extras.append(f"Format: {efmt}")
                if efreq:
                    extras.append(f"Frequency: {efreq}")
                if ecoll:
                    extras.append(f"Collection method: {ecoll}")
                extras.append(f"Status: {estat}")
                if elast:
                    extras.append(f"Last collected: {elast}")
                if ereviewer:
                    extras.append(f"Verified by: {ereviewer}")
                if erev_notes:
                    extras.append(f"Reviewer notes: {erev_notes}")
                if esub_notes:
                    extras.append(f"Submission notes: {esub_notes}")
                if elink:
                    link_label = _extract_link_label(elink, fallback="View submitted evidence")
                    extras.append(f"Evidence link: [{link_label}]({elink})")
                if evalid:
                    extras.append(f"Validation criteria: {evalid}")
                eline += " [" + " | ".join(extras) + "]"
                lines.append(eline)
        lines.append("")

    if obligations:
        lines.append("[OBLIGATIONS]")
        for ob in obligations[:3]:
            ob_name  = ob.get("name", "")
            due      = ob.get("due_date", "")
            auth     = ob.get("authority", "")
            recur    = ob.get("recurrence", "")
            notes    = (ob.get("notes") or "")[:150]
            own      = (ob.get("owner") or {}).get("display_name") or "Unassigned"
            parts    = [f"- {ob_name}", f"Due: {due}", f"Authority: {auth}"]
            if recur:
                parts.append(f"Recurrence: {recur}")
            parts.append(f"Owner: {own}")
            if notes:
                parts.append(f"Notes: {notes}")
            lines.append(" | ".join(parts))
        lines.append("")

    # Gap Analysis findings
    if gaps:
        lines.append("[GAP FINDINGS]")
        for gap in gaps[:3]:
            gid      = gap.get("gap_id", "")
            finding  = (gap.get("finding") or "")[:300]
            std      = gap.get("standard", "")
            clause   = gap.get("clause", "")
            severity = gap.get("severity", "")
            status   = gap.get("status", "")
            target   = gap.get("target_date", "")
            remedy   = (gap.get("proposed_remediation") or "")[:300]
            own      = (gap.get("owner") or {}).get("display_name") or "Unassigned"
            header   = f"[GAP: {gid}]" if gid else "[GAP]"
            lines.append(header)
            if finding:
                lines.append(f"Finding: {finding}")
            parts = []
            if std:
                parts.append(f"Standard: {std}")
            if clause:
                parts.append(f"Clause: {clause}")
            if severity:
                parts.append(f"Severity: {severity}")
            if status:
                parts.append(f"Status: {status}")
            if target:
                parts.append(f"Target date: {target}")
            parts.append(f"Owner: {own}")
            if parts:
                lines.append(" | ".join(parts))
            if remedy:
                lines.append(f"Proposed remediation: {remedy}")
            lines.append("")

    # Document Register
    if documents:
        lines.append("[DOCUMENT REGISTER]")
        for doc in documents[:3]:
            code     = doc.get("document_code", "")
            title    = doc.get("title", "")
            dtype    = doc.get("type", "")
            dept     = doc.get("department", "")
            status   = doc.get("status", "")
            version  = doc.get("current_version", "")
            eff      = doc.get("effective_date", "")
            review   = doc.get("next_review_date", "")
            stds     = doc.get("applicable_standards", "")
            sp_url   = (doc.get("sharepoint_url") or "").strip()
            own      = (doc.get("owner") or {}).get("display_name") or "Unassigned"
            header   = f"[DOC: {code}]" if code else "[DOC]"
            lines.append(header)
            if title:
                lines.append(f"Title: {title}")
            parts = []
            if dtype:
                parts.append(f"Type: {dtype}")
            if dept:
                parts.append(f"Department: {dept}")
            if status:
                parts.append(f"Status: {status}")
            if version:
                parts.append(f"Version: {version}")
            if eff:
                parts.append(f"Effective: {eff}")
            if review:
                parts.append(f"Next review: {review}")
            if stds:
                parts.append(f"Standards: {stds}")
            parts.append(f"Owner: {own}")
            if parts:
                lines.append(" | ".join(parts))
            if sp_url:
                doc_label = _extract_link_label(sp_url, fallback=title or code or "View document")
                lines.append(f"Document link: [{doc_label}]({sp_url})")
            lines.append("")

    # Strategic Risks
    if risks:
        lines.append("[STRATEGIC RISKS]")
        for risk in risks[:3]:
            desc      = (risk.get("description") or "")[:300]
            cat       = risk.get("category", "")
            score     = risk.get("risk_score", "")
            level     = risk.get("risk_level", "")
            likelihood= risk.get("likelihood", "")
            impact    = risk.get("impact", "")
            treatment = (risk.get("treatment") or "")[:250]
            status    = risk.get("status", "")
            gap_ref   = risk.get("related_gap_id", "")
            own       = (risk.get("owner") or {}).get("display_name") or "Unassigned"
            lines.append("[RISK]")
            if desc:
                lines.append(f"Description: {desc}")
            parts = []
            if cat:
                parts.append(f"Category: {cat}")
            parts.append(f"Score: {score} ({level}) — Likelihood: {likelihood} × Impact: {impact}")
            if status:
                parts.append(f"Status: {status}")
            if gap_ref:
                parts.append(f"Related gap: {gap_ref}")
            parts.append(f"Owner: {own}")
            if parts:
                lines.append(" | ".join(parts))
            if treatment:
                lines.append(f"Treatment: {treatment}")
            lines.append("")

    return "\n".join(lines).rstrip()


def _context_from_procedural(result: dict) -> str:
    processes = result.get("processes", [])
    if not processes:
        return ""

    lines: list[str] = []

    for proc in processes[:2]:
        proc_name  = proc.get("process_name") or proc.get("document_code", "")
        doc_code   = proc.get("document_code", "")
        doc_title  = proc.get("document_title", "")
        section    = proc.get("section_ref", "")
        doc_link   = proc.get("document_link", "")
        steps      = sorted(proc.get("steps", []), key=lambda s: s.get("step_number") or 0)

        header = f"[PROCEDURE: {proc_name}"
        if doc_code and doc_code != proc_name:
            header += f" — {doc_code}"
        if doc_title and doc_title not in (proc_name, doc_code):
            header += f" | {doc_title}"
        if section:
            header += f", §{section}"
        header += "]"
        lines.append(header)
        if doc_link:
            dl_label = _extract_link_label(doc_link, fallback="View document")
            lines.append(f"Document link: [{dl_label}]({doc_link})")

        for step in steps[:8]:
            n       = step.get("step_number", "")
            text    = (step.get("step_text") or "")[:300]
            roles   = step.get("roles_involved", "")
            forms   = step.get("forms_referenced", "")
            systems = step.get("systems_referenced", "")
            step_line = f"Step {n}: {text}"
            extras: list[str] = []
            if roles:
                extras.append(f"Roles: {roles}")
            if forms:
                extras.append(f"Forms: {forms}")
            if systems:
                extras.append(f"Systems: {systems}")
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
