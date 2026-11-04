# =============================================================================
# doc_standards/role_check.py — the role check, run every time a document's file changes
#
# A role a document names that is not in Org Roles must be flagged when the
# document ENTERS Lifecycle and every time its file changes — not only when
# someone thinks to press "Check against the standard". This runs the role check
# (V07) on its own (it needs Org Roles, not the library) and adds its problems to
# the result stored on the Lifecycle item beside the CDI checks, so the card shows
# them and "Fix CDI issues" offers the fix.
#
# EVERY role problem is an ERROR: the card is Failed, and the document cannot leave Review, until
# each role it names is a role in Org Roles. A role that owns something (a Control owner, the
# Document owner, an approver) is routed work and evidence; a role in the Roles table (a requester,
# "all staff") is part of what the document says. Either way the compliance officer adds the role
# (or an alias) to Org Roles, or the author names one that exists.
# If Org Roles can't be read, nothing is added (a check that could not look never
# passes or fails a document; the Document standard panel says it could not check).
# =============================================================================

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

ROLE_CHECK_ID = "V07"
ROLE_CHECK_NAME = "Every role named exists in Org Roles"
# The uses that route work to the role. Anything else (the Roles table) only describes who is involved.
ACCOUNTABLE_USES = ("Control owner", "Document owner", "First pass approval", "Final approval")


def is_error_use(kind: str) -> bool:
    """Every use is an error. Kept as a function so the rule lives in one place."""
    return True


ROLE_RULE = ("Every role a document names must be a role in Org Roles: a control's Control owner, the "
             "Document owner, the approvers and any Roles table. (CDI V07.)")


async def role_findings(file_bytes: bytes, filename: str) -> list[dict] | None:
    """V07's findings for this file, or None if the check could not run."""
    from cdi.parser import parse_document
    from doc_standards import checks
    from doc_standards.roles import RoleBook
    from groups import service as groups_service

    try:
        parsed = parse_document(file_bytes, filename)
        book = RoleBook.from_groups(await groups_service.list_groups())
    except Exception as exc:
        logger.info(f"Role check skipped for {filename}: {exc}")
        return None
    subject = checks.Subject(parsed=parsed, filename=filename, headings=[],
                             ctx=checks.Context(roles=book), type_code=parsed.header.type_code or "",
                             here=[], here_reliable=False)
    outcome = checks.v07(subject)
    if outcome.unknown or outcome.skip:
        return [] if outcome.skip else None
    return [f.as_dict() for f in outcome.problems]


def as_stored(findings: list[dict], *, enforced: bool = True) -> list[dict]:
    """The findings in the shape the Lifecycle item stores its CDI results in. `enforced` is
    kept for callers; severity no longer depends on the gate: it depends on what the role does."""
    out = []
    for f in findings:
        d = f.get("data") or {}
        owns = any(is_error_use(k) for k in (d.get("kinds") or [u.get("kind", "") for u in d.get("uses", [])]))
        out.append({
            "check": ROLE_CHECK_ID, "check_id": ROLE_CHECK_ID, "check_name": ROLE_CHECK_NAME,
            "detail": f["message"], "finding": f["message"], "fix": f.get("fix", ""),
            "proposed_fix": f.get("fix", ""), "current_text": d.get("role", ""), "find": d.get("role", ""),
            "anchor": f.get("where", ""),
            "fixable": "manual" if (d.get("group") or d.get("kind") == "missing-owner") else "choice",
            "rule": ROLE_RULE, "severity": "error" if owns else "warning",
            "role": d.get("role", ""), "uses": d.get("uses", []),
        })
    return out


# What a Standard's controls must state for OrgOS to read them: every field of the control record
# (V08), a risk statement (V10) and a standards mapping (V22). A Standard always DEFINES its controls,
# so these can be judged from the document alone and BLOCK the card. For any other document type the
# library is needed to tell a defining control from a restated one, so Fix CDI lists them as warnings.
CONTROL_CHECKS = {
    "V08": "Each control states every field of the control record",
    "V10": "Every control has a risk statement",
    "V22": "Every control states its standards mapping",
}


def control_findings(file_bytes: bytes, filename: str) -> list[dict]:
    """The stored (aggregated, one per check) errors for a Standard's incomplete controls; [] for any
    other document, or if the document can't be read."""
    from cdi.parser import parse_document
    from doc_standards import checks

    try:
        parsed = parse_document(file_bytes, filename)
    except Exception as exc:
        logger.info(f"Control checks skipped for {filename}: {exc}")
        return []
    if (parsed.header.type_code or "") != "STD" or not parsed.controls:
        return []
    subject = checks.Subject(parsed=parsed, filename=filename, headings=[], ctx=checks.Context(),
                             type_code="STD", here=list(parsed.controls), here_reliable=True)
    out = []
    for check_id, name in CONTROL_CHECKS.items():
        outcome = getattr(checks, check_id.lower())(subject)
        if outcome.skip or outcome.unknown or not outcome.problems:
            continue
        where = [f.where for f in outcome.problems]
        shown = ", ".join(where[:6]) + (f" +{len(where) - 6} more" if len(where) > 6 else "")
        out.append({
            "check": check_id, "check_id": check_id, "check_name": name,
            "detail": f"{outcome.summary or name} ({shown})", "finding": f"{outcome.summary or name} ({shown})",
            "fix": outcome.problems[0].fix, "proposed_fix": outcome.problems[0].fix, "current_text": "", "find": "",
            "anchor": shown, "fixable": "manual", "rule": f"CDI {check_id}: {name}.", "severity": "error",
            "uses": [{"kind": "Control", "where": w} for w in where],
        })
    return out


async def with_role_problems(status: str, failures_json: str, file_bytes: bytes, filename: str) -> tuple[str, str]:
    """(CDIStatus, CDIFailures) with this file's role problems, and a Standard's incomplete controls,
    added. Never raises."""
    if status == "Error" or not (filename or "").lower().endswith(".docx"):
        return status, failures_json
    try:
        findings = await role_findings(file_bytes, filename)
        controls = control_findings(file_bytes, filename)
        if not findings and not controls:
            return status, failures_json
        try:
            existing = json.loads(failures_json) if failures_json else []
        except ValueError:
            existing = []
        existing = [e for e in existing if (e.get("check_id") or e.get("check")) != ROLE_CHECK_ID]
        stored = as_stored(findings or []) + controls
        existing = [e for e in existing if (e.get("check_id") or e.get("check")) not in CONTROL_CHECKS]
        merged = existing + stored
        if status == "Passed" and any(s["severity"] == "error" for s in stored):
            status = "Failed"
        return status, json.dumps(merged)
    except Exception as exc:
        logger.warning(f"Role problems not added for {filename}: {exc}")
        return status, failures_json
