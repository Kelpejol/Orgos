# =============================================================================
# agents/gap_analyzer/control_gaps.py — gaps in the controls themselves
#
# The clause check (service._find_gaps) asks "does each applicable clause have
# controls?" It can only see controls mapped to a clause, and most controls in
# the library state no mapping. This asks the other question of every control
# confirmed from a defining document: is it owned, evidenced and carried out,
# and does its document state it completely?
#
# Gaps are grouped where the fix is shared, so the register holds work items,
# not noise: one per defining document for blocked, incomplete or unidentified
# definitions (its owner settles them together), one per control no procedure
# carries out, or that states no evidence at all.
#
# The fix is always to a document or the Role Catalogue, so each gap carries a
# stated remediation; none is written by a model. Pure: controls in, gaps out.
# =============================================================================

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

STANDARD = "CDI"
SEVERITY_DAYS = {"Critical": 30, "Major": 60, "Minor": 90}


def _gap(key_subject: str, category: str, severity: str, clause: str, title: str,
         finding: str, impact: str, document: str, roles: list[str], verification: str,
         controls: list[str]) -> dict:
    target = (date.today() + timedelta(days=SEVERITY_DAYS[severity])).isoformat()
    return {
        "standard": STANDARD,
        "clause": clause[:255],
        "clause_title": title,
        "gap_category": category,
        "gap_key": f"{STANDARD}|{key_subject}|{category}",
        "severity": severity,
        "finding": finding,
        "impact": impact,
        "stated": {
            "finding_narrative": finding,
            "audit_risk": impact,
            "remediation_json": json.dumps({
                "document": document,
                "controls": controls,
                "records": [],
                "roles": roles,
                "risk": impact,
                "standards_mapping": "",
                "target_date": target,
                "verification": verification,
            }),
        },
    }


def _ids(controls: list[dict], limit: int = 12) -> str:
    ids = [c["control_id"] for c in controls]
    return ", ".join(ids[:limit]) + (f" and {len(ids) - limit} more" if len(ids) > limit else "")


def find_control_gaps(controls: list[dict]) -> list[dict]:
    """
    `controls`: Control Register rows as the analyzer loads them, with
    control_id, status, blocked_reason and definition (the DefinitionJson).
    Legacy rows (no Control ID) are left to the clause check.
    """
    defined = [c for c in controls
               if c.get("control_id") and c.get("definition")
               and c.get("status") not in ("Withdrawn", "Superseded")]
    gaps: list[dict] = []

    # ── ownership: one gap per defining document ───────────────────────────
    # Role spellings vary too much ("DPO", "DPO + Legal", prose) for one gap
    # per role to group anything; the document is where the fix is decided —
    # its owner either confirms the roles for the Role Catalogue or corrects
    # the text.
    blocked: dict[str, list[dict]] = defaultdict(list)
    for c in defined:
        if c["status"] == "Blocked":
            blocked[c["definition"].get("defined_in_label", "")].append(c)

    for doc, group in sorted(blocked.items()):
        unrecognised: dict[str, int] = defaultdict(int)
        unstated = []
        for c in group:
            d = c["definition"]
            role = (d.get("accountable") or "").strip()
            if role and not d.get("responsibility_ambiguous"):
                unrecognised[role] += 1
            else:
                unstated.append(c)
        parts = []
        if unrecognised:
            parts.append("roles OrgOS does not recognise — " + "; ".join(
                f"“{r}” ({n})" for r, n in sorted(unrecognised.items(), key=lambda x: (-x[1], x[0]))))
        if unstated:
            parts.append(f"{len(unstated)} name no single accountable role ({_ids(unstated, 8)})")
        gaps.append(_gap(
            f"OWN:{doc}", "Ownership gap", "Major", doc, f"Blocked controls in {doc}",
            f"{len(group)} control(s) in {doc} are Blocked: " + "; ".join(parts) + ". "
            f"Controls: {_ids(group)}.",
            "Nobody is answerable for these controls, so their evidence cannot be routed and an "
            "auditor will find them unowned.",
            "Add each real role to the Role Catalogue (or as an alias of the role it means). "
            f"Where a control names no role, several, or a misspelt one, revise {doc} to state one "
            "accountable role and the executing role.",
            ["Document Owner", "Compliance Executive (QMS & NDPA)"],
            "Every listed control shows Active after the next library sync.",
            [c["control_id"] for c in group],
        ))

    # ── per control: defined but carried out nowhere; no evidence at all ──
    for c in defined:
        d = c["definition"]
        doc = d.get("defined_in_label", "")
        title = f"{c['control_id']} {d.get('title', '')}".strip()
        if not d.get("implemented_in"):
            gaps.append(_gap(
                f"{c['control_id']}", "Implementation gap", "Minor", c["control_id"], title,
                f"{c['control_id']} is defined in {doc}, but no procedure carries it out.",
                "A requirement nobody's procedure performs is unlikely to operate; an auditor "
                "asking how it is done will find no answer.",
                f"Cite {c['control_id']} in the procedure that performs it, or raise a procedure "
                f"change if none does. If the control is no longer needed, withdraw it from {doc}.",
                ["Document Owner"],
                f"A procedure cites {c['control_id']} and the next library sync shows where it is carried out.",
                [c["control_id"]],
            ))
        if not d.get("evidence") and not d.get("evidence_as_written"):
            gaps.append(_gap(
                f"{c['control_id']}", "Evidence gap", "Major", c["control_id"], title,
                f"{c['control_id']} states no evidence: nothing records that it operated.",
                "The control cannot be shown to work; to an auditor it may as well not exist.",
                f"Revise {doc}: name the record (with its REC ID) that proves {c['control_id']} operated.",
                ["Document Owner"],
                f"{c['control_id']} names a governed record after the next library sync.",
                [c["control_id"]],
            ))

    # ── per defining document: incomplete definitions; records without IDs ─
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for c in defined:
        by_doc[c["definition"].get("defined_in_label", "")].append(c)

    for doc, group in sorted(by_doc.items()):
        incomplete = [c for c in group if c["definition"].get("missing_fields")]
        if incomplete:
            counts: dict[str, int] = defaultdict(int)
            for c in incomplete:
                for f in c["definition"]["missing_fields"]:
                    counts[f] += 1
            missing = "; ".join(f"{f} ({n})" for f, n in sorted(counts.items(), key=lambda x: -x[1]))
            gaps.append(_gap(
                f"DOC:{doc}", "Control gap", "Minor", doc, f"Incomplete control definitions in {doc}",
                f"{len(incomplete)} of {len(group)} control(s) in {doc} leave CDI control fields "
                f"unstated — {missing}. Controls: {_ids(incomplete)}.",
                "Unstated triggers, routes and mappings leave operators to guess when a control "
                "runs and what happens when it fails, and keep it off the Standards Map.",
                f"Revise {doc}: state the missing fields for each listed control.",
                ["Document Owner"],
                "The next library sync shows no unstated fields for these controls.",
                [c["control_id"] for c in incomplete],
            ))

        unidentified = [c for c in group
                        if any(not e.get("record_id") for e in c["definition"].get("evidence") or [])]
        if unidentified:
            gaps.append(_gap(
                f"DOC:{doc}", "Evidence gap", "Minor", doc, f"Records named without a Record ID in {doc}",
                f"{len(unidentified)} control(s) in {doc} name evidence without a Record ID, so OrgOS "
                f"cannot find it in the Records Catalogue: {_ids(unidentified)}.",
                "Evidence that can't be located can't be checked, kept or disposed of correctly.",
                f"Revise {doc}: cite each record by its REC ID; ask Records Governance to admit any "
                "record that has none.",
                ["Document Owner", "Records Governance"],
                "Every evidence record for these controls resolves in the Records Catalogue.",
                [c["control_id"] for c in unidentified],
            ))
    return gaps
