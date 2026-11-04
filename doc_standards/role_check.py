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
# What counts as an ERROR (the card is Failed until it is fixed): a role that OWNS something
# downstream — a control's Control owner, the Document owner, the First pass or Final approval.
# Evidence obligations, acceptance and approval are all routed to them, so a name that is not
# in Org Roles reaches nobody. A role named only in the document's Roles table (a requester,
# "all staff", a line manager) is a WARNING: shown and fixable, but nothing is routed to it.
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
    return kind in ACCOUNTABLE_USES


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


async def with_role_problems(status: str, failures_json: str, file_bytes: bytes, filename: str) -> tuple[str, str]:
    """(CDIStatus, CDIFailures) with this file's role problems added. Never raises."""
    if status == "Error" or not (filename or "").lower().endswith(".docx"):
        return status, failures_json
    try:
        findings = await role_findings(file_bytes, filename)
        if not findings:
            return status, failures_json
        try:
            existing = json.loads(failures_json) if failures_json else []
        except ValueError:
            existing = []
        existing = [e for e in existing if (e.get("check_id") or e.get("check")) != ROLE_CHECK_ID]
        stored = as_stored(findings)
        merged = existing + stored
        if status == "Passed" and any(s["severity"] == "error" for s in stored):
            status = "Failed"
        return status, json.dumps(merged)
    except Exception as exc:
        logger.warning(f"Role problems not added for {filename}: {exc}")
        return status, failures_json
