# =============================================================================
# agents/nl_search/response_formatter.py — Format search results for the chat UI
#
# Converts raw search result dicts from compliance_search / procedural_search
# into the NLSearchResponse shape returned by the API.
#
# The "answer" field is markdown text rendered in the chat bubble.
# The "sources" field drives the SourcesAccordion component.
# compliance_data / procedural_data are structured payloads for rich UI rendering.
# =============================================================================

from typing import Optional


# =============================================================================
#  Evidence status → traffic light
# =============================================================================

def _evidence_traffic_light(evidence_items: list[dict]) -> str:
    if not evidence_items:
        return "Red"
    statuses = [e.get("status", "Pending") for e in evidence_items]
    if any(s == "Accepted" for s in statuses):
        if all(s in ("Accepted", "Submitted") for s in statuses):
            return "Green"
        return "Amber"
    if any(s == "Overdue" for s in statuses):
        return "Red"
    if any(s == "Submitted" for s in statuses):
        return "Amber"
    return "Amber"  # Pending but not overdue


# =============================================================================
#  Compliance response
# =============================================================================

def format_compliance_response(search_result: dict) -> dict:
    """
    Build the NLSearchResponse for a compliance-mode query.
    """
    controls    = search_result.get("controls", [])
    obligations = search_result.get("obligations", [])
    question    = search_result.get("question", "")
    entities    = search_result.get("entities", {})
    std_hint    = search_result.get("standards_hint")

    if not search_result.get("found"):
        return _not_found_response(question, "compliance")

    # Build markdown answer
    lines = []
    sources = []

    if controls:
        for ctrl in controls[:3]:
            ctrl_stmt  = ctrl.get("control_statement", "")
            iso        = ctrl.get("iso_clause", "")
            src_doc    = ctrl.get("source_document", "")
            owner      = ctrl.get("owner", {})
            owner_name = owner.get("display_name") or owner.get("email") or "Unassigned"
            evidence   = ctrl.get("evidence", [])
            traffic    = _evidence_traffic_light(evidence)
            traffic_emoji = {"Green": "🟢", "Amber": "🟡", "Red": "🔴"}.get(traffic, "⚪")

            lines.append(f"**{ctrl_stmt}**")
            if iso:
                lines.append(f"ISO clause: {iso}")
            lines.append(f"Owner: {owner_name}")
            lines.append(f"Evidence status: {traffic_emoji} {traffic}")
            if src_doc:
                lines.append(f"Source: {src_doc}")
            lines.append("")

            if src_doc:
                sources.append({
                    "title":         src_doc,
                    "document_code": src_doc,
                    "clause":        iso or "",
                    "link":          "",
                })

    if obligations:
        lines.append("**Compliance obligations:**")
        for ob in obligations[:3]:
            name    = ob.get("name", "")
            due     = ob.get("due_date", "")
            auth    = ob.get("authority", "")
            owner   = ob.get("owner", {})
            owner_n = owner.get("display_name") or "Unassigned"
            lines.append(f"- {name} — due {due}, authority: {auth}, owner: {owner_n}")

    if std_hint:
        lines.append(f"\nFor live traffic lights, see the **Standards Map** for {std_hint.get('clause', '')}.")

    answer = "\n".join(lines).strip()

    # Structured data for rich UI rendering
    compliance_data = {
        "controls":       controls,
        "obligations":    obligations,
        "standards_hint": std_hint,
        "entities":       entities,
    }

    return {
        "mode":             "compliance",
        "answer":           answer,
        "sources":          sources,
        "compliance_data":  compliance_data,
        "procedural_data":  None,
    }


# =============================================================================
#  Procedural response
# =============================================================================

def format_procedural_response(search_result: dict) -> dict:
    """
    Build the NLSearchResponse for a procedural-mode query.
    """
    processes = search_result.get("processes", [])
    question  = search_result.get("question", "")

    if not search_result.get("found") or not processes:
        return _not_found_response(question, "procedural")

    lines   = []
    sources = []
    proc    = processes[0]  # best match

    title      = proc.get("document_title", proc.get("document_code", ""))
    process_nm = proc.get("process_name", "")
    section    = proc.get("section_ref", "")
    doc_code   = proc.get("document_code", "")
    doc_link   = proc.get("document_link", "")
    steps      = proc.get("steps", [])

    heading = process_nm or title
    if section:
        heading += f" (§{section})"
    lines.append(f"**{heading}**")
    lines.append(f"*From: {title}*")
    lines.append("")

    for step in sorted(steps, key=lambda s: s.get("step_number") or 0):
        n    = step.get("step_number", "")
        text = step.get("step_text", "")
        lines.append(f"{n}. {text}")
        roles = step.get("roles_involved", "")
        forms = step.get("forms_referenced", "")
        systems = step.get("systems_referenced", "")
        if roles:
            lines.append(f"   *Roles: {roles}*")
        if forms:
            lines.append(f"   *Forms: {forms}*")
        if systems:
            lines.append(f"   *Systems: {systems}*")

    # Collect forms and contacts from all steps for the summary box
    all_forms   = list({s.get("forms_referenced", "") for s in steps if s.get("forms_referenced")})
    all_roles   = list({
        r.strip()
        for s in steps
        for r in (s.get("roles_involved") or "").split(",")
        if r.strip()
    })

    if all_forms:
        lines.append(f"\n**Forms needed:** {', '.join(all_forms)}")
    if all_roles:
        lines.append(f"**Contacts/roles:** {', '.join(all_roles)}")

    if len(processes) > 1:
        lines.append(f"\n*Also see: {', '.join(p.get('process_name', '') for p in processes[1:])}*")

    answer = "\n".join(lines).strip()

    sources.append({
        "title":         title,
        "document_code": doc_code,
        "clause":        section,
        "link":          doc_link,
    })

    procedural_data = {
        "process_name":  process_nm,
        "steps":         steps,
        "forms_needed":  all_forms,
        "contacts":      all_roles,
        "document_code": doc_code,
        "document_link": doc_link,
    }

    return {
        "mode":            "procedural",
        "answer":          answer,
        "sources":         sources,
        "compliance_data": None,
        "procedural_data": procedural_data,
    }


# =============================================================================
#  Combined response
# =============================================================================

def format_combined_response(
    compliance_result: dict,
    procedural_result: dict,
) -> dict:
    """
    Merge compliance + procedural results into a single combined response.
    """
    comp = format_compliance_response(compliance_result)
    proc = format_procedural_response(procedural_result)

    # Merge answers with clear section headers
    answer_parts = []
    if comp["answer"] and comp["answer"] != _NO_RESULTS_MSG:
        answer_parts.append("### Compliance\n" + comp["answer"])
    if proc["answer"] and proc["answer"] != _NO_RESULTS_MSG:
        answer_parts.append("### How-to\n" + proc["answer"])

    answer = "\n\n".join(answer_parts) if answer_parts else _NO_RESULTS_MSG

    # Merge and deduplicate sources
    seen_codes: set[str] = set()
    combined_sources = []
    for src in (comp.get("sources") or []) + (proc.get("sources") or []):
        code = src.get("document_code", src.get("title", ""))
        if code not in seen_codes:
            seen_codes.add(code)
            combined_sources.append(src)

    return {
        "mode":            "combined",
        "answer":          answer,
        "sources":         combined_sources,
        "compliance_data": comp.get("compliance_data"),
        "procedural_data": proc.get("procedural_data"),
    }


# =============================================================================
#  Not-found fallback
# =============================================================================

_NO_RESULTS_MSG = (
    "I couldn't find a direct match in the OrgOS registers or procedural index. "
    "Try rephrasing your question, or check with the Compliance team."
)


def _not_found_response(question: str, mode: str) -> dict:
    return {
        "mode":            mode,
        "answer":          _NO_RESULTS_MSG,
        "sources":         [],
        "compliance_data": None,
        "procedural_data": None,
    }
