# =============================================================================
# agents/gap_analyzer/service.py — Gap Analyzer Agent
# Per Bobby's amendment: finds gaps AND proposes full remediation packages.
#
# Two parts:
#   Part 1 — Finding (no model needed)
#     Reads confirmed registers, compares against clause list, identifies gaps.
#   Part 2 — Proposal (uses Ollama)
#     For each gap, generates a complete remediation package.
#
# Six gap types per DINT Section 5.4:
#   Missing artefact    — no document governs this area
#   Control gap         — document exists but controls are inadequate
#   Evidence gap        — controls exist but evidence is not being collected
#   Ownership gap       — controls exist but responsible role is unassigned
#   Standards misalignment — controls exist but mapped to wrong clauses
#   Obligation gap      — regulatory requirement not in Compliance Calendar
# =============================================================================

import json
import logging
from datetime import date, timedelta

from agents.llm_client import llm_generate
from config import settings
from graph.client import get_list_items

logger = logging.getLogger(__name__)

# =============================================================================
#  Standards clause list — what must be covered
# =============================================================================

REQUIRED_CLAUSES = [
    {"standard": "ISO 27001", "clause": "A.5.1",  "title": "Policies for information security",
     "requires": "policy"},
    {"standard": "ISO 27001", "clause": "A.5.12", "title": "Classification of information",
     "requires": "control"},
    {"standard": "ISO 27001", "clause": "A.5.15", "title": "Access control",
     "requires": "control"},
    {"standard": "ISO 27001", "clause": "A.5.16", "title": "Identity management",
     "requires": "control"},
    {"standard": "ISO 27001", "clause": "A.5.17", "title": "Authentication information",
     "requires": "control"},
    {"standard": "ISO 27001", "clause": "A.5.18", "title": "Access rights",
     "requires": "control+evidence"},
    {"standard": "ISO 27001", "clause": "A.5.25", "title": "Assessment of security events",
     "requires": "control"},
    {"standard": "ISO 27001", "clause": "A.5.26", "title": "Response to incidents",
     "requires": "control+evidence"},
    {"standard": "ISO 27001", "clause": "A.6.1",  "title": "Screening",
     "requires": "control"},
    {"standard": "ISO 27001", "clause": "A.8.1",  "title": "User endpoint devices",
     "requires": "control+evidence"},
    {"standard": "ISO 27001", "clause": "A.8.24", "title": "Use of cryptography",
     "requires": "control+evidence"},
    {"standard": "ISO 27001", "clause": "A.8.25", "title": "Secure development life cycle",
     "requires": "control"},
    {"standard": "ISO 27001", "clause": "A.8.32", "title": "Change management",
     "requires": "control"},
    {"standard": "ISO 9001",  "clause": "7.5",    "title": "Documented information",
     "requires": "policy"},
    {"standard": "ISO 9001",  "clause": "9.2",    "title": "Internal audit",
     "requires": "control+evidence"},
    {"standard": "ISO 9001",  "clause": "10.2",   "title": "Nonconformity and corrective action",
     "requires": "control"},
    {"standard": "NDPA",      "clause": "S.39",   "title": "Breach notification to Commission",
     "requires": "control+evidence"},
    {"standard": "NDPA",      "clause": "S.40",   "title": "Breach notification to data subject",
     "requires": "control"},
]

# Canonical severity target days — aligned with spec: Critical 30d, Major 60d, Minor 90d
SEVERITY_DAYS = {"Critical": 30, "Major": 60, "Minor": 90}


# =============================================================================
#  Data loaders
# =============================================================================

async def _load_controls() -> list[dict]:
    items = await get_list_items(
        settings.control_register_list_id, "Control Register"
    )
    return [
        {
            "id":         str(i["id"]),
            "statement":  i.get("fields", {}).get("ControlStatement", ""),
            "iso_clause": i.get("fields", {}).get("ISOClause", ""),
            "owner_role": i.get("fields", {}).get("OwnerRole", ""),
            "owner_oid":  i.get("fields", {}).get("OwnerEntraId", ""),
            "status":     i.get("fields", {}).get("Status", "Active"),
            "source_doc": i.get("fields", {}).get("SourceDocument", ""),
        }
        for i in items
    ]


async def _load_evidence() -> list[dict]:
    items = await get_list_items(
        settings.evidence_tracker_list_id, "Evidence Tracker"
    )
    return [
        {
            "id":          str(i["id"]),
            "linked_ctrl": i.get("fields", {}).get("LinkedControlId", ""),
            "status":      i.get("fields", {}).get("Status", "Pending"),
            "owner_oid":   i.get("fields", {}).get("OwnerEntraId", ""),
            "type":        i.get("fields", {}).get("EvidenceType", ""),
        }
        for i in items
    ]


async def _load_roles() -> list[dict]:
    items = await get_list_items(
        settings.role_register_list_id, "Role Register"
    )
    return [
        {
            "title":      i.get("fields", {}).get("Title", ""),
            "holder_oid": i.get("fields", {}).get("CurrentHolderEntraId", ""),
            "assigned":   i.get("fields", {}).get("AssignmentStatus", "") == "Assigned",
        }
        for i in items
    ]


async def _load_existing_gap_keys() -> set[str]:
    """
    Return the GapKey values of all currently open or in-progress gaps.
    Used to prevent duplicate findings on repeated runs.
    """
    if not settings.is_list_configured(settings.gap_analysis_list_id):
        return set()
    try:
        items = await get_list_items(settings.gap_analysis_list_id, "Gap Analysis")
        return {
            i.get("fields", {}).get("GapKey", "")
            for i in items
            if i.get("fields", {}).get("Status", "Open") in ("Open", "In progress")
            and i.get("fields", {}).get("GapKey", "")
        }
    except Exception as exc:
        logger.warning(f"Could not load existing gaps for deduplication: {exc}")
        return set()


# =============================================================================
#  Part 1 — Gap finding (no model)
# =============================================================================

def _make_gap_key(standard: str, clause: str, gap_category: str, ctrl_id: str = "") -> str:
    """Stable deduplication key for a gap finding."""
    parts = [standard, clause, gap_category]
    if ctrl_id:
        parts.append(ctrl_id)
    return "|".join(parts)


def _find_gaps(
    controls: list[dict],
    evidence: list[dict],
    roles:    list[dict],
) -> list[dict]:
    """
    Compare confirmed registers against the required clause list.
    Returns list of gap findings with type, severity, and GapKey.
    """
    gaps = []
    evidence_by_control = {e["linked_ctrl"]: e for e in evidence}

    for clause_def in REQUIRED_CLAUSES:
        clause   = clause_def["clause"]
        standard = clause_def["standard"]
        title    = clause_def["title"]
        requires = clause_def["requires"]

        clause_controls = [
            c for c in controls
            if c["iso_clause"] and c["iso_clause"].startswith(clause)
        ]

        # Missing artefact — no controls at all
        if not clause_controls and "control" in requires:
            gaps.append({
                "standard":    standard,
                "clause":      clause,
                "clause_title": title,
                "gap_category": "Missing artefact",
                "gap_key":     _make_gap_key(standard, clause, "Missing artefact"),
                "severity":    "Critical" if standard == "ISO 27001" else "Major",
                "finding": (
                    f"No controls found for {standard} {clause} ({title}). "
                    f"No document governs this area."
                ),
                "impact": (
                    f"This clause has no coverage. An auditor will write a "
                    f"{'major nonconformity' if standard == 'ISO 27001' else 'significant observation'}."
                ),
            })
            continue

        # Ownership gap — controls exist but owner is unassigned or control is blocked
        for ctrl in clause_controls:
            if ctrl["status"] == "Blocked" or not ctrl["owner_oid"]:
                gaps.append({
                    "standard":    standard,
                    "clause":      clause,
                    "clause_title": title,
                    "gap_category": "Ownership gap",
                    "gap_key":     _make_gap_key(standard, clause, "Ownership gap", ctrl["id"]),
                    "severity":    "Major",
                    "finding": (
                        f"Control '{ctrl['statement'][:100]}' for {standard} {clause} "
                        f"has no assigned owner. Role '{ctrl['owner_role']}' is unassigned."
                    ),
                    "impact": (
                        "Evidence cannot be collected. Control is unroutable. "
                        "Will generate an audit observation."
                    ),
                })

        # Evidence gap — controls exist but no evidence requirement is defined
        if "evidence" in requires:
            for ctrl in clause_controls:
                if ctrl["id"] not in evidence_by_control:
                    gaps.append({
                        "standard":    standard,
                        "clause":      clause,
                        "clause_title": title,
                        "gap_category": "Evidence gap",
                        "gap_key":     _make_gap_key(standard, clause, "Evidence gap", ctrl["id"]),
                        "severity":    "Major",
                        "finding": (
                            f"Control '{ctrl['statement'][:100]}' for {standard} {clause} "
                            f"has no evidence requirement defined."
                        ),
                        "impact": (
                            "The control cannot be proven to an auditor. "
                            "Without evidence, the control may as well not exist."
                        ),
                    })

    return gaps


# =============================================================================
#  Part 2 — AI analysis + remediation proposal (uses Ollama — Bobby's amendment)
#
#  Single Ollama call per gap produces:
#    • finding_narrative  — contextual description specific to Dragnet
#    • audit_risk         — what an external auditor would write
#    • remediation package (document, controls, evidence, roles, target_date, verification)
# =============================================================================

async def _ai_analyse_and_remediate(gap: dict, role_titles: list[str]) -> dict:
    """
    One Ollama call per gap: generates an AI-written finding description,
    audit risk statement, and full remediation package together.

    Returns a dict with keys:
        finding_narrative, audit_risk, remediation_json (str)
    Falls back to template values if Ollama is unavailable.
    """
    roles_sample = ", ".join(role_titles[:8]) if role_titles else "ISMS Lead, Department Head"
    days   = SEVERITY_DAYS.get(gap["severity"], 90)
    target = (date.today() + timedelta(days=days)).isoformat()

    prompt = f"""You are a senior compliance consultant for Dragnet Solutions Limited, a Nigerian technology and digital services company operating under ISO 27001, ISO 9001, and the Nigeria Data Protection Act (NDPA).

A compliance gap has been identified in our registers:

Standard: {gap['standard']} {gap['clause']} — {gap['clause_title']}
Gap type: {gap['gap_category']}
Initial finding: {gap['finding']}
Current impact: {gap['impact']}
Available roles at Dragnet: {roles_sample}

Your task has two parts:

PART 1 — Describe the gap precisely in Dragnet's context:
- Write a specific finding narrative (2-3 sentences) that an internal auditor would record
- Write the audit risk statement (1 sentence) an external ISO auditor would use in their report

PART 2 — Propose a complete remediation package.

Respond with ONLY valid JSON in this exact structure (no extra text before or after):
{{
  "finding_narrative": "2-3 sentence specific description of this gap in Dragnet's context",
  "audit_risk": "Single sentence an external auditor would write as a nonconformity or observation",
  "document": "Specific document action required — include a suggested document title",
  "controls": ["Shall-statement control 1 specific to this clause", "Shall-statement control 2"],
  "evidence": ["EVT_CODE — evidence description. Source: system name. Frequency: period"],
  "roles": ["Specific role title from the available roles list"],
  "risk": "Business consequence if this gap remains open beyond the target date (one sentence)",
  "standards_mapping": "{gap['standard']} {gap['clause']}",
  "target_date": "{target}",
  "verification": "Specific, measurable way to confirm this gap is closed (one sentence)"
}}"""

    try:
        raw = await llm_generate(
            prompt,
            tier="heavy",
            max_tokens=800,
            temperature=0.2,
        )

        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
            finding_narrative = parsed.pop("finding_narrative", "").strip()
            audit_risk        = parsed.pop("audit_risk", "").strip()
            if finding_narrative:
                return {
                    "finding_narrative": finding_narrative,
                    "audit_risk":        audit_risk or gap["impact"],
                    "remediation_json":  json.dumps(parsed),
                }
    except Exception as exc:
        logger.warning(f"AI gap analysis failed for {gap['clause']}: {exc}")

    # Fallback — template values so the gap is still written even if Ollama is down
    return {
        "finding_narrative": gap["finding"],
        "audit_risk":        gap["impact"],
        "remediation_json":  json.dumps({
            "document":          f"Create or revise document covering {gap['clause_title']}",
            "controls":          [f"[Role] shall implement controls for {gap['clause_title']}"],
            "evidence":          ["REV — Review record. Source: SharePoint. Frequency: quarterly"],
            "roles":             [role_titles[0]] if role_titles else ["ISMS Lead"],
            "risk":              gap["impact"],
            "standards_mapping": f"{gap['standard']} {gap['clause']}",
            "target_date":       (date.today() + timedelta(days=days)).isoformat(),
            "verification":      "Gap closed when controls confirmed and first evidence accepted.",
        }),
    }


# =============================================================================
#  Main entry point
# =============================================================================

async def _log_gap_analysis_run(summary: dict, triggered_by: str = "system") -> None:
    """Persist Gap Analyzer run summary to Audit Log when configured."""
    if not settings.is_list_configured(settings.audit_log_list_id):
        return
    try:
        from graph.client import create_list_item
        await create_list_item(settings.audit_log_list_id, "Audit Log", {
            "Title": "Gap Analyzer run",
            "Action": "Gap Analyzer run",
            "ReviewerName": triggered_by,
            "Decision": summary.get("status", ""),
            "Rationale": json.dumps(summary, ensure_ascii=False)[:4000],
        })
    except Exception as exc:
        logger.warning(f"Could not write Gap Analyzer run to Audit Log: {exc}")


async def run_gap_analysis(triggered_by: str = "system") -> dict:
    """
    Run the full Gap Analyzer pipeline.
    Part 1: find gaps from register data (fast, no model).
    Part 2: propose remediation for each gap (uses Ollama).
    Deduplicates against existing open/in-progress gaps before writing.
    Writes findings to the Gap Analysis SharePoint list.
    Returns summary of gaps found and written.
    """
    from graph.client import create_list_item

    logger.info("Gap Analyzer starting")

    controls    = await _load_controls()
    evidence    = await _load_evidence()
    roles       = await _load_roles()
    role_titles = [r["title"] for r in roles if r["title"]]

    logger.info(
        f"Loaded: {len(controls)} controls, {len(evidence)} evidence items, {len(roles)} roles"
    )

    # Load existing open gap keys for deduplication
    existing_keys = await _load_existing_gap_keys()
    logger.info(f"Existing open gap keys: {len(existing_keys)}")

    # Part 1 — find gaps
    gaps = _find_gaps(controls, evidence, roles)
    logger.info(f"Gap finding complete: {len(gaps)} gaps found before deduplication")

    if not gaps:
        summary = {
            "status":       "complete",
            "gaps_found":   0,
            "gaps_written": 0,
            "gaps_skipped": 0,
            "message":      "No gaps found. Register data covers all required clauses.",
        }
        await _log_gap_analysis_run(summary, triggered_by=triggered_by)
        return summary

    # Deduplicate — skip any gap whose key already exists as an open gap
    new_gaps = [g for g in gaps if g["gap_key"] not in existing_keys]
    skipped  = len(gaps) - len(new_gaps)
    if skipped:
        logger.info(f"Deduplication: skipping {skipped} gaps already tracked as open")

    if not new_gaps:
        summary = {
            "status":       "complete",
            "gaps_found":   len(gaps),
            "gaps_written": 0,
            "gaps_skipped": skipped,
            "message": (
                f"Gap analysis complete. {len(gaps)} gaps found, "
                f"all already tracked as open. No new gaps written."
            ),
        }
        await _log_gap_analysis_run(summary, triggered_by=triggered_by)
        return summary

    # Part 2 — AI analysis + remediation for each new gap, then write to SharePoint
    written = 0
    for gap in new_gaps:
        try:
            logger.info(
                f"AI analysing gap: {gap['standard']} {gap['clause']} "
                f"({gap['gap_category']})..."
            )
            ai = await _ai_analyse_and_remediate(gap, role_titles)

            days   = SEVERITY_DAYS.get(gap["severity"], 90)
            target = (date.today() + timedelta(days=days)).isoformat()

            fields = {
                "Title":               ai["finding_narrative"][:255],
                "Standard":            gap["standard"],
                "Clause":              gap["clause"],
                "ClauseTitle":         gap["clause_title"],
                "GapCategory":         gap["gap_category"],
                "GapKey":              gap["gap_key"],
                "Severity":            gap["severity"],
                "Finding":             ai["finding_narrative"],
                "Impact":              ai["audit_risk"],
                "ProposedRemediation": ai["remediation_json"],
                "Status":              "Open",
                "TargetDate":          target,
            }

            await create_list_item(settings.gap_analysis_list_id, "Gap Analysis", fields)
            written += 1
        except Exception as exc:
            logger.error(f"Failed to write gap for {gap['clause']}: {exc}")

    logger.info(
        f"Gap Analyzer complete: {written}/{len(new_gaps)} new gaps written, "
        f"{skipped} skipped (already open)"
    )

    severity_counts = {
        "Critical": sum(1 for g in new_gaps if g["severity"] == "Critical"),
        "Major":    sum(1 for g in new_gaps if g["severity"] == "Major"),
        "Minor":    sum(1 for g in new_gaps if g["severity"] == "Minor"),
    }

    summary = {
        "status":       "complete",
        "gaps_found":   len(gaps),
        "gaps_written": written,
        "gaps_skipped": skipped,
        "severity":     severity_counts,
        "message": (
            f"Gap analysis complete. {len(new_gaps)} new gaps written "
            f"({skipped} already tracked as open). "
            f"Critical: {severity_counts['Critical']}, "
            f"Major: {severity_counts['Major']}, "
            f"Minor: {severity_counts['Minor']}."
        ),
    }
    await _log_gap_analysis_run(summary, triggered_by=triggered_by)
    return summary
