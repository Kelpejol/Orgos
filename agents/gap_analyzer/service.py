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

import httpx

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
#  Part 2 — Remediation proposal (uses Ollama — Bobby's amendment)
# =============================================================================

async def _propose_remediation(gap: dict, role_titles: list[str]) -> str:
    """
    Generate a complete remediation package for a gap.
    Returns JSON string of the package.
    """
    roles_sample = ", ".join(role_titles[:6]) if role_titles else "ISMS Lead, Department Head"
    days   = SEVERITY_DAYS.get(gap["severity"], 90)
    target = (date.today() + timedelta(days=days)).isoformat()

    prompt = f"""You are a compliance expert for Dragnet Solutions Limited, a Nigerian technology services company.
A compliance gap has been identified:

Standard: {gap['standard']} {gap['clause']} — {gap['clause_title']}
Gap type: {gap['gap_category']}
Finding: {gap['finding']}
Impact: {gap['impact']}
Available roles: {roles_sample}

Propose a complete remediation package. Respond with ONLY valid JSON in this exact format:
{{
  "document": "Description of what document action is needed (new document title or specific revision)",
  "controls": ["Control statement 1 using shall/must", "Control statement 2"],
  "evidence": ["Evidence type code — description. Source: system. Frequency: period"],
  "roles": ["Role title from available roles list"],
  "risk": "What happens if this gap stays open (one sentence)",
  "standards_mapping": "{gap['standard']} {gap['clause']}",
  "target_date": "{target}",
  "verification": "How closure will be confirmed (one sentence)"
}}"""

    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model":  settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 600, "temperature": 0.2},
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()

        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = raw[start:end]
            json.loads(json_str)   # validate before returning
            return json_str
    except Exception as exc:
        logger.warning(f"Remediation proposal failed for {gap['clause']}: {exc}")

    # Fallback minimal package
    return json.dumps({
        "document":          f"Create or revise document covering {gap['clause_title']}",
        "controls":          [f"[Role] shall implement controls for {gap['clause_title']}"],
        "evidence":          ["REV — Review record. Source: SharePoint. Frequency: quarterly"],
        "roles":             [role_titles[0]] if role_titles else ["ISMS Lead"],
        "risk":              gap["impact"],
        "standards_mapping": f"{gap['standard']} {gap['clause']}",
        "target_date":       target,
        "verification":      "Gap closed when controls confirmed and first evidence accepted.",
    })


# =============================================================================
#  Main entry point
# =============================================================================

async def run_gap_analysis() -> dict:
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
        return {
            "status":       "complete",
            "gaps_found":   0,
            "gaps_written": 0,
            "gaps_skipped": 0,
            "message":      "No gaps found. Register data covers all required clauses.",
        }

    # Deduplicate — skip any gap whose key already exists as an open gap
    new_gaps = [g for g in gaps if g["gap_key"] not in existing_keys]
    skipped  = len(gaps) - len(new_gaps)
    if skipped:
        logger.info(f"Deduplication: skipping {skipped} gaps already tracked as open")

    if not new_gaps:
        return {
            "status":       "complete",
            "gaps_found":   len(gaps),
            "gaps_written": 0,
            "gaps_skipped": skipped,
            "message": (
                f"Gap analysis complete. {len(gaps)} gaps found, "
                f"all already tracked as open. No new gaps written."
            ),
        }

    # Part 2 — propose remediation for each new gap and write to SharePoint
    written = 0
    for gap in new_gaps:
        try:
            logger.info(f"Proposing remediation for {gap['standard']} {gap['clause']}...")
            remediation_json = await _propose_remediation(gap, role_titles)

            days   = SEVERITY_DAYS.get(gap["severity"], 90)
            target = (date.today() + timedelta(days=days)).isoformat()

            fields = {
                "Title":               gap["finding"][:255],
                "Standard":            gap["standard"],
                "Clause":              gap["clause"],
                "ClauseTitle":         gap["clause_title"],
                "GapCategory":         gap["gap_category"],
                "GapKey":              gap["gap_key"],
                "Severity":            gap["severity"],
                "Finding":             gap["finding"],
                "Impact":              gap["impact"],
                "ProposedRemediation": remediation_json,
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

    return {
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
