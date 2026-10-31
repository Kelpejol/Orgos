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
from typing import Optional

from agents.llm_client import llm_generate
from config import settings
from graph.client import get_list_items
from standards_map import catalogue

logger = logging.getLogger(__name__)

# =============================================================================
#  What must be covered — the shared clause catalogue
#
#  The clause list, and how a control is matched to a clause, come from
#  standards_map/catalogue.py — the same source the Standards Map uses, so the
#  two can no longer disagree about what Dragnet must cover.
# =============================================================================

# Canonical severity target days — aligned with spec: Critical 30d, Major 60d, Minor 90d
SEVERITY_DAYS = {"Critical": 30, "Major": 60, "Minor": 90}


# =============================================================================
#  Data loaders
# =============================================================================

# Gaps this analyzer writes and therefore may close itself when the condition is gone.
# (Coverage and obligation gaps from the registers, and gaps raised by hand, are not its own.)
ANALYZER_CATEGORIES = {"Missing artefact", "Ownership gap", "Evidence gap", "Implementation gap"}
# A gap a person has settled: never raised again for the same condition.
SETTLED = {"Accepted risk", "Accepted Risk", "Closed with rationale"}
_RETIRED_CONTROL = {"Withdrawn", "Superseded"}


async def _load_controls() -> list[dict]:
    """The LIVE controls: a withdrawn or superseded control covers no clause and owes no evidence."""
    items = await get_list_items(
        settings.control_register_list_id, "Control Register"
    )
    items = [i for i in items if (i.get("fields") or {}).get("Status") not in _RETIRED_CONTROL]
    return [
        {
            "id":         str(i["id"]),
            "statement":  i.get("fields", {}).get("ControlStatement", ""),
            "refs":       catalogue.control_mapping(i.get("fields", {})),
            "owner_role": i.get("fields", {}).get("OwnerRole", ""),
            "owner_oid":  i.get("fields", {}).get("OwnerEntraId", ""),
            "status":     i.get("fields", {}).get("Status", "Active"),
            "source_doc": i.get("fields", {}).get("SourceDocument", ""),
            "control_id": i.get("fields", {}).get("ControlId", ""),
            "blocked_reason": i.get("fields", {}).get("BlockedReason", ""),
            "definition": _definition(i.get("fields", {})),
        }
        for i in items
    ]


def _definition(fields: dict):
    try:
        return json.loads(fields.get("DefinitionJson") or "null")
    except (TypeError, ValueError):
        return None


async def _load_records() -> list[dict]:
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
            "fields":      i.get("fields", {}),
        }
        for i in items
    ]


async def _load_gap_items() -> Optional[list[dict]]:
    """Every row of the Gap Analysis list, or None if it can't be read."""
    if not settings.is_list_configured(settings.gap_analysis_list_id):
        return []
    try:
        return await get_list_items(settings.gap_analysis_list_id, "Gap Analysis")
    except Exception as exc:
        logger.warning(f"Could not load existing gaps: {exc}")
        return None


def validate_remediation_roles(remediation_json: str, book) -> str:
    """
    A remediation package proposes; it does not assign. Its roles are checked against Org Roles:
      • a role that exists is kept, by its Org Roles name;
      • a field name ("Document Owner", "Control owner") is a responsibility, not a role — it is
        moved to "responsibilities" ("the Document owner of the document concerned");
      • anything else (an AI's plausible guess) is moved to "roles_not_in_org_roles", to be chosen
        or created by a person — never shown as an assignment.
    """
    from doc_standards.roles import is_placeholder
    try:
        pkg = json.loads(remediation_json or "{}")
    except (TypeError, ValueError):
        return remediation_json
    if not isinstance(pkg, dict):
        return remediation_json
    real, responsibilities, unknown = [], [], []
    for r in pkg.get("roles") or []:
        r = str(r or "").strip()
        if not r:
            continue
        if is_placeholder(r):
            responsibilities.append(f"the {r.lower()} of the document concerned")
        elif book is not None and book.find(r) is not None:
            real.append(book.find(r).name)
        else:
            unknown.append(r)
    pkg["roles"] = list(dict.fromkeys(real))
    if responsibilities:
        pkg["responsibilities"] = list(dict.fromkeys(responsibilities))
    if unknown:
        pkg["roles_not_in_org_roles"] = list(dict.fromkeys(unknown))
    return json.dumps(pkg)


def _tracked_gap_keys(items: list[dict]) -> set[str]:
    """
    The GapKeys already tracked: open, in progress — or settled by a person (accepted as a risk),
    which must not come back as a new Open gap on the next run.
    """
    return {
        (i.get("fields") or {}).get("GapKey", "")
        for i in items
        if (i.get("fields") or {}).get("Status", "Open") in ({"Open", "In progress"} | SETTLED)
        and (i.get("fields") or {}).get("GapKey", "")
    }


async def _load_existing_gap_keys() -> set[str]:
    """The GapKeys already tracked (open, in progress, or accepted as a risk)."""
    return _tracked_gap_keys(await _load_gap_items() or [])


def _gap_id_allocator(items: list[dict]):
    """Next GapId per standard and year (GAP-{STANDARD}-{YY}-{NNN}), counting what exists."""
    year = date.today().strftime("%y")
    used: dict[str, int] = {}
    for i in items:
        gid = (i.get("fields") or {}).get("GapId", "") or ""
        prefix, _, n = gid.rpartition("-")
        if prefix and n.isdigit():
            used[prefix] = max(used.get(prefix, 0), int(n))

    def next_id(standard: str) -> str:
        prefix = f"GAP-{(standard or 'GEN').replace(' ', '').replace('-', '')}-{year}"
        used[prefix] = used.get(prefix, 0) + 1
        return f"{prefix}-{used[prefix]:03d}"
    return next_id


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
    records: list[dict],
    ownership=None,
) -> list[dict]:
    """
    Compare confirmed registers against the required clause list.
    Returns list of gap findings with type, severity, and GapKey.
    """
    gaps = []
    # One control may be evidenced by several records; any one means "a record
    # requirement is defined" for the evidence-gap check below.
    controls_with_records = {r["linked_ctrl"] for r in records if r["linked_ctrl"]}

    for row, requires in catalogue.applicable_clauses():
        clause, standard = row.clause, row.standard
        title = row.title or f"{standard} {clause}"

        clause_controls = [
            c for c in controls if any(catalogue.covers(row, ref) for ref in c["refs"])
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

        # Ownership gap — the control's OwnerRole doesn't resolve to anyone.
        # The Control owner is a role in Org Roles, never OwnerEntraId. The
        # shared resolver still has a legacy directory-title fallback.
        legacy = [c for c in clause_controls if not c.get("control_id")]
        for ctrl in legacy:
            owner_role = ctrl.get("owner_role") or ""
            unowned = (
                not ownership.has_owner(owner_role) if ownership is not None
                else not owner_role
            )
            if ctrl["status"] == "Blocked" or unowned:
                reason = (
                    "No Control owner is stated on this control."
                    if not owner_role else
                    f"Check whether Control owner '{owner_role}' exists in Org Roles "
                    "and has people assigned."
                )
                gaps.append({
                    "standard":    standard,
                    "clause":      clause,
                    "clause_title": title,
                    "gap_category": "Ownership gap",
                    "gap_key":     _make_gap_key(standard, clause, "Ownership gap", ctrl["id"]),
                    "severity":    "Major",
                    "finding": (
                        f"Control '{ctrl['statement'][:100]}' for {standard} {clause} "
                        f"needs ownership review. {reason}"
                    ),
                    "impact": (
                        "Records cannot be collected. Control is unroutable. "
                        "Will generate an audit observation."
                    ),
                })

        # Evidence gap — controls exist but no evidence requirement is defined
        if "record" in requires:
            for ctrl in legacy:
                if ctrl["id"] not in controls_with_records:
                    gaps.append({
                        "standard":    standard,
                        "clause":      clause,
                        "clause_title": title,
                        "gap_category": "Evidence gap",
                        "gap_key":     _make_gap_key(standard, clause, "Evidence gap", ctrl["id"]),
                        "severity":    "Major",
                        "finding": (
                            f"Control '{ctrl['statement'][:100]}' for {standard} {clause} "
                            f"has no record requirement defined."
                        ),
                        "impact": (
                            "The control cannot be proven to an auditor. "
                            "Without a record, the control may as well not exist."
                        ),
                    })

    return gaps


# =============================================================================
#  Part 2 — AI analysis + remediation proposal (uses Ollama — Bobby's amendment)
#
#  Single Ollama call per gap produces:
#    • finding_narrative  — contextual description specific to Dragnet
#    • audit_risk         — what an external auditor would write
#    • remediation package (document, controls, records, roles, target_date, verification)
# =============================================================================

async def _ai_analyse_and_remediate(gap: dict) -> dict:
    """
    One Ollama call per gap: generates an AI-written finding description,
    audit risk statement, and full remediation package together.

    Returns a dict with keys:
        finding_narrative, audit_risk, remediation_json (str)
    Falls back to template values if Ollama is unavailable.
    """
    days   = SEVERITY_DAYS.get(gap["severity"], 90)
    target = (date.today() + timedelta(days=days)).isoformat()

    prompt = f"""You are a senior compliance consultant for Dragnet Solutions Limited, a Nigerian technology and digital services company operating under ISO 27001, ISO 9001, and the Nigeria Data Protection Act (NDPA).

A compliance gap has been identified in our registers:

Standard: {gap['standard']} {gap['clause']} — {gap['clause_title']}
Gap type: {gap['gap_category']}
Initial finding: {gap['finding']}
Current impact: {gap['impact']}

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
  "records": ["EVT_CODE — evidence description. Source: system name. Frequency: period"],
  "roles": ["Specific role name that plausibly owns this remediation"],
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
            "records":           ["REV — Review record. Source: SharePoint. Frequency: quarterly"],
            "roles":             ["Compliance"],
            "risk":              gap["impact"],
            "standards_mapping": f"{gap['standard']} {gap['clause']}",
            "target_date":       (date.today() + timedelta(days=days)).isoformat(),
            "verification":      "Gap closed when controls confirmed and first record accepted.",
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


async def _close_resolved_control_gaps(current_keys: set[str], items: Optional[list[dict]] = None) -> int:
    """
    Close the open gaps this analyzer raised whose condition no longer holds — a control now
    mapped to the clause, a role now recognised, a record now accepted. Its checks are exact, so
    OrgOS can confirm the fix itself. Gaps it did not raise (coverage and obligation gaps from the
    registers, gaps raised by hand or from an audit) are left for a person.
    """
    from graph.client import update_list_item

    if not settings.is_list_configured(settings.gap_analysis_list_id):
        return 0
    if items is None:
        items = await _load_gap_items()
        if items is None:
            return 0
    closed = 0
    for item in items:
        f = item.get("fields", {})
        ours = (f.get("GapCategory") or (f.get("GapKey", "").split("|") + ["", "", ""])[2]) in ANALYZER_CATEGORIES
        if (ours and f.get("Status", "Open") in ("Open", "In progress")
                and f.get("GapKey") and f["GapKey"] not in current_keys):
            try:
                await update_list_item(settings.gap_analysis_list_id, "Gap Analysis", str(item["id"]), {
                    "Status": "Closed",
                    "ResolutionNotes": f"Closed by gap analysis on {date.today().isoformat()}: "
                                   "the condition no longer holds.",
                })
                closed += 1
            except Exception as exc:
                logger.error(f"Could not close resolved gap {item['id']}: {exc}")
    return closed


async def _refresh_open_gaps(gaps: list[dict], items: list[dict]) -> int:
    """An open gap OrgOS states itself (control-framework gaps) keeps up with what it found:
    more controls now Blocked, a different list of records. Clause gaps keep their reviewed text."""
    from graph.client import update_list_item

    open_by_key = {(i.get("fields") or {}).get("GapKey"): i for i in items
                   if (i.get("fields") or {}).get("Status", "Open") in ("Open", "In progress")}
    refreshed = 0
    for gap in gaps:
        item = open_by_key.get(gap["gap_key"])
        stated = gap.get("stated")
        if not item or not stated:
            continue
        f = item.get("fields") or {}
        update = {k: v for k, v in (("Finding", stated["finding_narrative"]),
                                    ("ProposedRemediation", stated["remediation_json"]),
                                    ("Severity", gap["severity"])) if f.get(k) != v}
        if update:
            try:
                await update_list_item(settings.gap_analysis_list_id, "Gap Analysis", str(item["id"]), update)
                refreshed += 1
            except Exception as exc:
                logger.error(f"Could not refresh gap {item['id']}: {exc}")
    return refreshed


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
    records     = await _load_records()

    logger.info(
        f"Loaded: {len(controls)} controls, {len(records)} record items"
    )

    # Existing gaps: tracked ones are not raised again; IDs continue from what exists.
    gap_items = await _load_gap_items()
    if gap_items is None:
        summary = {"status": "error", "gaps_found": 0, "gaps_written": 0, "gaps_skipped": 0,
                   "message": "The Gap Analysis list could not be read, so nothing was written "
                              "(writing blind would duplicate every open gap)."}
        await _log_gap_analysis_run(summary, triggered_by=triggered_by)
        return summary
    existing_keys = _tracked_gap_keys(gap_items)
    next_gap_id = _gap_id_allocator(gap_items)
    logger.info(f"Existing tracked gap keys: {len(existing_keys)}")

    # Part 1 — find gaps
    # Resolve the Control owner's holders once. The shared resolver's legacy
    # directory-title fallback remains supported here pending a policy decision.
    from ownership.resolver import get_ownership_index
    ownership = await get_ownership_index()

    from agents.gap_analyzer.control_gaps import find_control_gaps, find_evidence_gaps
    gaps = (_find_gaps(controls, records, ownership) + find_control_gaps(controls)
            + find_evidence_gaps([r["fields"] for r in records]))
    closed = await _close_resolved_control_gaps({g["gap_key"] for g in gaps}, gap_items)
    refreshed = await _refresh_open_gaps(gaps, gap_items)
    logger.info(f"Gap finding complete: {len(gaps)} gaps found before deduplication")

    if not gaps:
        summary = {
            "status":       "complete",
            "gaps_found":   0,
            "gaps_written": 0,
            "gaps_skipped": 0,
            "gaps_closed":  closed,
            "gaps_refreshed": refreshed,
        "gaps_refreshed": refreshed,
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
            "gaps_closed":  closed,
            "gaps_refreshed": refreshed,
        "gaps_refreshed": refreshed,
            "message": (
                f"Gap analysis complete. {len(gaps)} gaps found, "
                f"all already tracked as open. No new gaps written."
            ),
        }
        await _log_gap_analysis_run(summary, triggered_by=triggered_by)
        return summary

    # The roles a package names are checked against Org Roles before it is written.
    try:
        from doc_standards.roles import RoleBook
        from groups import service as groups_service
        role_book = RoleBook.from_groups(await groups_service.list_groups())
    except Exception as exc:
        logger.warning(f"Org Roles unavailable; remediation roles are kept as suggestions: {exc}")
        role_book = None

    # Part 2 — AI analysis + remediation for each new gap, then write to SharePoint
    written = 0
    for gap in new_gaps:
        try:
            logger.info(
                f"AI analysing gap: {gap['standard']} {gap['clause']} "
                f"({gap['gap_category']})..."
            )
            # Control-framework gaps carry their own stated remediation.
            ai = gap.get("stated") or await _ai_analyse_and_remediate(gap)

            days   = SEVERITY_DAYS.get(gap["severity"], 90)
            target = (date.today() + timedelta(days=days)).isoformat()

            fields = {
                "GapId":               next_gap_id(gap["standard"]),
                "Title":               ai["finding_narrative"][:255],
                "Standard":            gap["standard"],
                "Clause":              gap["clause"],
                "ClauseTitle":         gap["clause_title"],
                "GapCategory":         gap["gap_category"],
                "GapKey":              gap["gap_key"],
                "Severity":            gap["severity"],
                "Finding":             ai["finding_narrative"],
                "Impact":              ai["audit_risk"],
                "ProposedRemediation": validate_remediation_roles(ai["remediation_json"], role_book),
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
        "gaps_closed":  closed,
        "gaps_refreshed": refreshed,
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
