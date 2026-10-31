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
# Advisory gate (default): a role problem is a WARNING — shown, never blocking.
# Enforced gate: an ERROR — the document cannot leave Review until it is fixed.
# If Org Roles can't be read, nothing is added (a check that could not look never
# passes or fails a document; the Document standard panel says it could not check).
# =============================================================================

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

ROLE_CHECK_ID = "V07"
ROLE_CHECK_NAME = "Every role named exists in Org Roles"
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


def as_stored(findings: list[dict], *, enforced: bool) -> list[dict]:
    """The findings in the shape the Lifecycle item stores its CDI results in."""
    out = []
    for f in findings:
        d = f.get("data") or {}
        out.append({
            "check": ROLE_CHECK_ID, "check_id": ROLE_CHECK_ID, "check_name": ROLE_CHECK_NAME,
            "detail": f["message"], "finding": f["message"], "fix": f.get("fix", ""),
            "proposed_fix": f.get("fix", ""), "current_text": d.get("role", ""), "find": d.get("role", ""),
            "anchor": f.get("where", ""), "fixable": "manual" if d.get("group") else "choice",
            "rule": ROLE_RULE, "severity": "error" if enforced else "warning",
            "role": d.get("role", ""), "uses": d.get("uses", []),
        })
    return out


async def with_role_problems(status: str, failures_json: str, file_bytes: bytes, filename: str) -> tuple[str, str]:
    """(CDIStatus, CDIFailures) with this file's role problems added. Never raises."""
    if status == "Error" or not (filename or "").lower().endswith(".docx"):
        return status, failures_json
    try:
        from doc_standards import gate
        findings = await role_findings(file_bytes, filename)
        if not findings:
            return status, failures_json
        try:
            existing = json.loads(failures_json) if failures_json else []
        except ValueError:
            existing = []
        existing = [e for e in existing if (e.get("check_id") or e.get("check")) != ROLE_CHECK_ID]
        enforced = gate.mode() == "enforce"
        merged = existing + as_stored(findings, enforced=enforced)
        if enforced and status == "Passed":
            status = "Failed"
        return status, json.dumps(merged)
    except Exception as exc:
        logger.warning(f"Role problems not added for {filename}: {exc}")
        return status, failures_json
