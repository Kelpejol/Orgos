# =============================================================================
# control_register/definitions.py — a control's definition as OrgOS keeps it
#
# One dict per Control ID, built from the statement in its defining document
# (cdi.LibraryIndex decides which document that is). The same dict is:
#   • the candidate a library sync proposes   (AI Review Queue CandidateJson)
#   • the confirmed definition once accepted  (Control Register DefinitionJson)
# so "has this control changed?" is a comparison of two dicts of one shape.
#
# Only REVIEWED_FIELDS count as a change, compared as written with spacing
# ignored. Structured forms (record IDs, clause pairs, the accountable/executing
# split) are derived from those texts by the parser; a parser upgrade can
# change them without the document changing, and that must not put work in
# front of a reviewer. Nothing here is inferred: a field the document does not
# state is empty.
# =============================================================================

from __future__ import annotations

from typing import Any, Callable, Optional

from cdi.library import LibraryIndex, document_label
from cdi.model import ControlDefinition, ParsedDocument

# (key, label) in the order a reviewer reads them
REVIEWED_FIELDS: list[tuple[str, str]] = [
    ("title", "Title"),
    ("requirement", "Requirement"),
    ("trigger", "Trigger"),
    ("responsibility_as_written", "Control owner"),
    ("evidence_as_written", "Evidence"),
    ("risk", "Risk"),
    ("failure_route", "Failure route"),
    ("exception_route", "Exception route"),
    ("mapping_as_written", "Mapping"),
    ("authority", "Governing authority"),
    ("other_fields", "Other stated fields"),
    ("defined_in_code", "Defining document"),
]


def candidate_from(doc: ParsedDocument, control: ControlDefinition,
                   index: Optional[LibraryIndex] = None) -> dict[str, Any]:
    """
    The definition of `control` as `doc` states it. With the library `index`,
    also where it is carried out — derived from other documents, so it is
    refreshed by a sync, not reviewed.
    """
    r = control.responsibility
    h = doc.header
    return {
        "control_id": control.control_id,
        "title": control.title,
        "requirement": control.requirement,
        "trigger": control.trigger,
        "responsibility_as_written": r.as_written if r else "",
        "accountable": r.accountable if r else "",
        "executing": r.executing if r else "",
        "responsibility_ambiguous": bool(r and r.ambiguous),
        # True when the document states a single Control owner (one role, never ambiguous);
        # absent/False for the older "Accountable / Executing" form, which is read as before.
        "control_owner": bool(r and r.control_owner),
        "evidence_as_written": control.evidence_as_written,
        "evidence": [{"record_id": e.record_id, "name": e.name} for e in control.evidence],
        "risk": control.risk,
        "failure_route": control.failure_route,
        "exception_route": control.exception_route,
        "mapping_as_written": control.mapping_as_written,
        "mapping": [{"standard": m.standard, "clause": m.clause} for m in control.mapping],
        "authority": control.authority,
        "other_fields": dict(control.other_fields),
        "missing_fields": control.missing_fields,
        "defined_in_code": h.code,
        # What to call the document where it has no code yet ("Not assigned")
        "defined_in_label": h.code or h.title or doc.filename,
        "defined_in": {
            "code": h.code,
            "title": h.title,
            "version": h.version,
            "section": control.location.section,
            "filename": doc.filename,
            "layout": control.layout,
        },
        "parser_version": doc.parser_version,
        "implemented_in": _implemented_in(control.control_id, index),
        "supported_by": sorted({document_label(d) for d in index.supported_by.get(control.control_id, [])})
                        if index else [],
    }


def _implemented_in(control_id: str, index: Optional[LibraryIndex]) -> list[dict]:
    """[{document, section}] — a procedure citing the control only by list gives no section."""
    if index is None:
        return []
    out, with_steps = [], set()
    for doc, step in index.implementations(control_id):
        with_steps.add(id(doc))
        out.append({"document": document_label(doc),
                    "section": " ".join(filter(None, [step.section_number, step.section_title]))})
    for doc in index.implemented_by.get(control_id, []):
        if id(doc) not in with_steps:
            out.append({"document": document_label(doc), "section": ""})
    return out


def _same_text(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {k: _same_text(v) for k, v in sorted(value.items())}
    return value


def diff(confirmed: Optional[dict], candidate: dict) -> list[dict]:
    """
    Reviewed fields that differ: [{field, label, before, after}]. A control
    with no confirmed definition differs in every field it states.
    """
    confirmed = confirmed or {}
    out = []
    for key, label in REVIEWED_FIELDS:
        before, after = confirmed.get(key, ""), candidate.get(key, "")
        if _same_text(before or "") != _same_text(after or ""):
            out.append({"field": key, "label": label, "before": before, "after": after})
    return out


def is_unchanged(confirmed: Optional[dict], candidate: dict) -> bool:
    return confirmed is not None and not diff(confirmed, candidate)


def completeness(candidate: dict) -> tuple[str, str]:
    """('COMPLETE' | 'DEFICIENT', reason) from the CDI block's eight fields."""
    missing = candidate.get("missing_fields") or []
    if not missing:
        return "COMPLETE", ""
    return "DEFICIENT", "The defining document does not state: " + ", ".join(missing) + "."


# ── status at confirmation ──────────────────────────────────────────────────

def decide_status(candidate: dict, resolve: Callable[[str], dict]) -> tuple[str, str]:
    """
    ('Active' | 'Blocked', reason). Active only when the control owner (the
    accountable role, for a document still in the older form) is one OrgOS recognises. An Entra job title alone is not authority for a role
    assignment (Bobby), so a role that matches only a job title is Blocked.
    `resolve` is OwnershipIndex.resolve.
    """
    role = (candidate.get("accountable") or "").strip()
    if not role:
        return "Blocked", ("The defining document names no Control owner." if candidate.get("control_owner")
                           else "The defining document names no Control owner (it has no accountable role either).")
    if candidate.get("responsibility_ambiguous"):
        return "Blocked", (
            f"“{candidate.get('responsibility_as_written')}” could be one role or two; "
            "a person must settle which is accountable."
        )
    from doc_standards.roles import is_placeholder
    if is_placeholder(role):
        return "Blocked", (
            f"“{role}” is the name of a field, not a role. The document must name the actual role "
            "(one that exists in Org Roles) in this control.")
    hit = resolve(role)
    if hit.get("kind") == "group":
        return "Active", ""
    if hit.get("kind") == "job_title":
        return "Blocked", (
            f"“{role}” matches only an Entra job title, which is not authority for a role. "
            "Create it in Org Roles."
        )
    return "Blocked", f"“{role}” is not a role in Org Roles. Use a role that exists, or create it there."
