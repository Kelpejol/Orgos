# =============================================================================
# doc_standards/checks.py — does this document meet the CDI standard?
#
# The standard is CDI Procedure §10 "Validation Checks" (V01–V24): each check
# with its own enforcement level — BLOCK, FLAG or REPORT — read from the
# Procedure itself (doc_standards/cdi_reference.json, built by
# scripts/build_cdi_reference.py). Nothing here restates a rule from memory.
#
# What a check may answer — and why there are seven answers, not two:
#
#   pass             it looked, and the document meets it
#   fail             a BLOCK check found a problem            (stops approval)
#   flag             a FLAG check found a problem             (needs a decision)
#   report           a REPORT check found something to note
#   could_not_check  the check exists but lacked what it needs (say what)
#   not_applicable   the rule doesn't apply to this document   (say why)
#   not_built        OrgOS doesn't implement this check yet    (say what it needs)
#
# A check that could not look NEVER passes. A check that is not built is listed
# as not built, so a "clear" result can never be mistaken for "fully checked".
# A check that throws becomes could_not_check with the reason — it does not
# take the others down and it does not pass.
#
# Pure: parsed document in, results out. The caller supplies whatever
# cross-document context it has (Register rows, the Records Catalogue, the
# library); a check that needs context it was not given says so.
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Optional

from cdi.codes import is_valid_doc_code, parse_doc_code
from cdi.library import LibraryIndex, _base_code, document_label
from cdi.model import DocumentRole, FindingKind, ParsedDocument
from cdi.parser import _type_from_layer
from cdi.reader import read_document
from doc_standards import roles as role_matching
from doc_standards.roles import RoleBook

logger = logging.getLogger(__name__)

_REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdi_reference.json")

PASS, FAIL, FLAG, REPORT = "pass", "fail", "flag", "report"
COULD_NOT, NOT_APPLICABLE, NOT_BUILT = "could_not_check", "not_applicable", "not_built"


_AMENDMENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdi_amendments.json")


def _apply_amendments(ref: dict) -> dict:
    """
    Lay agreed-but-not-yet-published changes over the Procedure's own text, and
    say so: each amended row or check is tagged with the amendment that changed
    it. An amendment whose text is no longer in the Procedure (it has been
    reissued with the change) is reported as obsolete and not applied.
    """
    with open(_AMENDMENTS) as f:
        amendments = json.load(f)["amendments"]
    ref["amendments"] = []
    for a in amendments:
        rows = ref["annex_c_control_fields"]
        remove = set(a.get("annex_c", {}).get("remove", []))
        present = [r for r in rows if r["field"] in remove]
        if remove and not present:
            ref["amendments"].append({**a, "status": "obsolete"})
            continue
        at = next(i for i, r in enumerate(rows) if r["field"] in remove) if present else len(rows)
        kept = [r for r in rows if r["field"] not in remove]
        new = [{**r, "amended": a["id"]} for r in a.get("annex_c", {}).get("add", [])]
        ref["annex_c_control_fields"] = kept[:at] + new + kept[at:]
        for check in ref["checks"]:
            for old, replacement in a.get("check_wording", {}).get(check["id"], []):
                if old in check["name"]:
                    check["name"] = check["name"].replace(old, replacement)
                    check["amended"] = a["id"]
        ref["amendments"].append({**a, "status": "applied"})
    return ref


@lru_cache(maxsize=1)
def reference() -> dict:
    with open(_REFERENCE) as f:
        return _apply_amendments(json.load(f))


# ── result shapes ───────────────────────────────────────────────────────────

@dataclass
class Finding:
    message: str
    where: str = ""        # "ACS-L3-01", "section 5.0" — where in the document
    fix: str = ""
    data: dict = field(default_factory=dict)    # what a screen needs to act on it (e.g. a role and its suggestions)

    def as_dict(self) -> dict:
        return {"message": self.message, "where": self.where, "fix": self.fix, "data": self.data}


@dataclass
class Outcome:
    """What a check function returns; the runner turns it into a status."""
    problems: list[Finding] = field(default_factory=list)
    summary: str = ""
    note: str = ""
    skip: str = ""         # not applicable — why
    unknown: str = ""      # could not check — why


@dataclass
class CheckResult:
    id: str
    name: str
    enforcement: str
    status: str
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "enforcement": self.enforcement,
                "status": self.status, "summary": self.summary, "note": self.note,
                "findings": [f.as_dict() for f in self.findings]}


@dataclass
class Context:
    """Cross-document knowledge the caller has. Any of it may be absent."""
    register: Optional[list[dict]] = None          # Document Register rows ({"fields": {...}})
    catalogue: Optional[dict] = None               # Record ID → RecordEntry
    index: Optional[LibraryIndex] = None           # the library INCLUDING this document
    roles: Optional[RoleBook] = None               # Org Roles: the roles that exist


@dataclass
class Subject:
    parsed: ParsedDocument
    filename: str
    headings: list[str]
    ctx: Context
    type_code: str
    here: list                    # controls this document DEFINES
    here_reliable: bool           # whether `here` is known, or only guessed


# ── which controls does this document define? ───────────────────────────────

def defined_here(parsed: ParsedDocument, index: Optional[LibraryIndex]) -> tuple[list, bool]:
    """
    A control's rules (V08–V12, V22) apply to the document that DEFINES it, not
    to a procedure's short copy of its Standard. With the library we can tell;
    without it a Standard (role DEFINING) defines what it states, and for any
    other document we cannot tell — so the caller must say "could not check".
    """
    if index is not None and any(d is parsed for d in index.documents):
        out = []
        for c in parsed.controls:
            definer = index.definition(c.control_id)
            if definer is not None:
                if definer[0] is parsed:
                    out.append(c)
            elif c.control_id in index.contested_ids and any(
                    s.document is parsed for s in index.stated_by.get(c.control_id, [])):
                out.append(c)                            # defined twice: this is one of the two
        return out, True
    if parsed.role is DocumentRole.DEFINING:
        return list(parsed.controls), True
    return [], False


# ── helpers ─────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _ids(controls) -> str:
    return ", ".join(c.control_id for c in controls)


# ── the checks ──────────────────────────────────────────────────────────────

def v01(s: Subject) -> Outcome:
    h = s.parsed.header
    func = parse_doc_code(h.code)[0]
    master_or_manual = s.type_code == "MAN" or (
        s.type_code == "POL" and ("master" in _norm(h.domain) or "master" in _norm(h.title)))
    wanted = [
        ("Title", h.title), ("Display code", h.code),
        ("Document type and layer", h.layer_as_written or s.type_code),
        ("Primary domain", h.domain), ("Owner role", h.owner),
        ("First Pass and Final Approval roles",
         h.first_pass_approval and h.final_approval or h.approval_authority),
        ("Classification", h.classification),
    ]
    if not master_or_manual:
        wanted.insert(4, ("Parent", h.parent_as_written))
    if func in ("ISMS", "QI"):
        wanted.append(("Standards mapping (QMS or ISMS scoped)", h.standards_as_written))
    missing = [name for name, value in wanted if not (value or "").strip()]
    return Outcome(
        problems=[Finding(f"“{m}” is not stated in the document's header block.", "header block",
                          "State it in the control block at the top of the document.") for m in missing],
        summary=f"All {len(wanted)} register facts a document can state are present." if not missing
                else f"{len(missing)} of {len(wanted)} register facts are missing.",
        note="Facts the platform assigns (system ID, status, version, dates, authoritative location, "
             "transition status, AI Involvement, Offline Copy Required) are not in the file and are not checked here.")


def v02(s: Subject) -> Outcome:
    ref = reference()["annex_b"]
    h = s.parsed.header
    if not h.code:
        return Outcome(problems=[Finding(
            "The document states no document code.", "header block",
            "Add the display code: DRG-[Function]-[Type]-[Mnemonic], from Annex B.")],
            summary="No document code.")
    problems = []
    function, type_code, mnemonic = parse_doc_code(h.code)
    functions = {f["code"] for f in ref["function_codes"]}
    retired = {r["code"]: r for r in ref["retired_codes"]}
    types = {t["code"] for t in ref["document_types"]}
    if not is_valid_doc_code(h.code):
        problems.append(Finding(f"“{h.code}” is not built as DRG-[Function]-[Type]-[Mnemonic].", h.code))
    else:
        if function in retired:
            r = retired[function]
            problems.append(Finding(f"“{function}” is a retired function code ({r['former']}); use {r['current']}.", h.code,
                                    f"Recode using {r['current']}."))
        elif function not in functions:
            problems.append(Finding(f"“{function}” is not a function code in Annex B.", h.code,
                                    "Use one of: " + ", ".join(sorted(functions)) + "."))
        if type_code and type_code not in types:
            problems.append(Finding(f"“{type_code}” is not a document type in Annex B.", h.code,
                                    "Use one of: " + ", ".join(sorted(types)) + "."))
    unique_note = ""
    if s.ctx.index is not None:
        others = [d for d in s.ctx.index.documents
                  if d is not s.parsed and d.header.code and _base_code(d.header.code) == _base_code(h.code)]
        for d in others:
            problems.append(Finding(f"{h.code} is also the code of a different document: {document_label(d)} "
                                    f"(“{d.header.title}”).", h.code, "A display code is unique. Recode one of them."))
        unique_note = "Uniqueness was checked against the library."
    else:
        unique_note = "Uniqueness against other documents was not checked (the library was not available)."
    legacy = re.search(r"-\d{2}(-\d{2})?$", h.code) and function in {f["code"] for f in ref["function_codes"]}
    if legacy:
        unique_note += " The code carries a legacy year/serial suffix; CDI §6.3 holds those as fields, not in the code."
    return Outcome(problems=problems, summary="Valid, current and unique." if not problems else "",
                   note=unique_note.strip())


def v03(s: Subject) -> Outcome:
    h = s.parsed.header
    if s.type_code == "MAN" or (s.type_code == "POL" and ("master" in _norm(h.domain) or "master" in _norm(h.title))):
        return Outcome(skip="A Master Policy or Manual has no parent.")
    if not h.parent_as_written:
        return Outcome(problems=[Finding("The document names no parent.", "header block",
                                         "Name the approved parent document.")], summary="No parent named.")
    if s.ctx.register is None:
        return Outcome(unknown="The Document Register was not available, so the parent's approval could not be looked up.")
    rows = [(r.get("fields") or {}) for r in s.ctx.register]
    problems = []
    approved = {"Active", "Under Review"}
    wanted = list(h.parent_codes) or []
    for code in wanted:
        match = [f for f in rows if _base_code(f.get("DocumentCode") or "") == _base_code(code)]
        if not match:
            problems.append(Finding(f"The parent {code} is not in the Document Register, so it is not approved.",
                                    "Parent", "Approve the parent first (Policy → Standard → Procedure)."))
        elif not any((f.get("Status") or "") in approved for f in match):
            problems.append(Finding(f"The parent {code} is in the Register but is {match[0].get('Status')}, not approved.",
                                    "Parent"))
    if not wanted:
        title = _norm(re.sub(r"\(.*?\)", "", h.parent_as_written))
        match = [f for f in rows if _norm(f.get("Title") or "") == title]
        if not match:
            problems.append(Finding(f"The parent “{h.parent_as_written[:80]}” could not be found in the Document Register "
                                    "by code or title.", "Parent",
                                    "Cite the parent by its document code."))
        elif not any((f.get("Status") or "") in approved for f in match):
            problems.append(Finding(f"The parent “{h.parent_as_written[:80]}” is not approved.", "Parent"))
    return Outcome(problems=problems, summary="The parent is approved." if not problems else "")


def v04(s: Subject) -> Outcome:
    h = s.parsed.header
    problems = []
    layer_type = _type_from_layer(h.layer_as_written)
    if layer_type and s.type_code and layer_type != s.type_code:
        problems.append(Finding(f"The layer says “{h.layer_as_written}” ({layer_type}) but the code says {s.type_code}.",
                                "header block", "Make the code and the layer agree."))
    for f in s.parsed.findings:
        if f.kind is FindingKind.POLICY_DEFINES_CONTROLS:
            problems.append(Finding(f.message, f.location.item or "", "Controls belong in a Standard, not a Policy."))
    return Outcome(problems=problems, summary="Type, layer and content agree." if not problems else "",
                   note="Whether the content really matches its type (no tools or steps in a Policy) is only partly checked.")


def _needs_controls(s: Subject) -> Optional[Outcome]:
    if not s.here_reliable:
        return Outcome(unknown="OrgOS cannot tell which controls this document defines and which it only restates "
                               "without the library, so the check was not run.")
    if not s.here:
        return Outcome(skip="This document defines no controls.")
    return None


def v07(s: Subject) -> Outcome:
    """Every role the document names must be a role in Org Roles — never a job title, never a field name."""
    book = s.ctx.roles
    if book is None:
        return Outcome(unknown="Org Roles could not be read, so the roles this document names could not be checked.")
    h = s.parsed.header
    named: dict[str, dict] = {}

    def add(text: str, kind: str, where: str) -> None:
        text = (text or "").strip().rstrip(".").strip()
        if text:
            entry = named.setdefault(role_matching.norm(text), {"text": text, "uses": []})
            entry["uses"].append((kind, where))

    for c in s.parsed.controls:                       # a role named anywhere in the text, even in a copy
        if c.responsibility and c.responsibility.accountable:
            add(c.responsibility.accountable, "Control owner", c.control_id)
    add(h.owner, "Document owner", "cover")
    add(h.first_pass_approval, "First pass approval", "cover")
    add(h.final_approval, "Final approval", "cover")
    for duty in s.parsed.roles:
        add(duty.role, "Roles section", "roles section")

    problems = []
    for entry in named.values():
        text = entry["text"]
        placeholder, several = role_matching.is_placeholder(text), role_matching.names_several(text)
        if not (placeholder or several) and book.find(text):
            continue
        kinds = sorted({k for k, _ in entry["uses"]})
        places = list(dict.fromkeys(w for _, w in entry["uses"]))
        group = role_matching.describes_a_group(text)
        suggestions = [] if (several or group) else book.suggest(text)
        if group:
            message = (f"“{text}” describes a group of roles, not one role. Name each role that does the work, "
                       "as it is in Org Roles.")
        elif placeholder:
            message = (f"“{text}” is the name of a field, not a role. Name the role that holds it, "
                       "as it is in Org Roles.")
        elif several:
            message = f"“{text}” names more than one role. A control has exactly one {kinds[0].lower()}."
        else:
            message = f"“{text}” is not a role in Org Roles ({', '.join(kinds)})."
        if group:
            fix = "Rewrite this row to name the actual roles (one row each), or remove it."
        elif suggestions:
            fix = "Did you mean " + " or ".join(f"“{x.role.name}”" for x in suggestions) + "? Or create the role in Org Roles."
        else:
            fix = "Use a role that exists in Org Roles, or create this one."
        problems.append(Finding(message, ", ".join(places[:8]) + (f" +{len(places) - 8} more" if len(places) > 8 else ""), fix, {
            "kind": "role", "role": text, "kinds": kinds, "locations": places,
            "placeholder": placeholder, "several": several, "group": group,
            "suggestions": [x.as_dict() for x in suggestions],
        }))
    note = ""
    if not len(book):
        note = "Org Roles has no roles yet, so every role named is reported. " + note
    return Outcome(problems=problems, note=note,
                   summary=(f"All {len(named)} role(s) named exist in Org Roles." if not problems and named
                            else "The document names no roles." if not named
                            else f"{len(problems)} of {len(named)} role(s) named are not in Org Roles."))


def v08(s: Subject) -> Outcome:
    early = _needs_controls(s)
    if early:
        return early
    problems = []
    for c in s.here:
        gaps = [m for m in c.missing_fields if m != "Mapping"]      # mapping is V22
        if gaps:
            problems.append(Finding(f"does not state: {', '.join(gaps)}.", c.control_id,
                                    "Add each missing field to the control block."))
    # Not a failure — the older line still names a role — but the CDI now has one Control owner.
    legacy = [c.control_id for c in s.here if c.responsibility and not c.responsibility.control_owner]
    note = (f"{len(legacy)} control(s) still use the older “Accountable / Executing” line "
            f"({', '.join(legacy[:6])}{'…' if len(legacy) > 6 else ''}). Move them to “Control owner: <one role>”." if legacy else "")
    return Outcome(problems=problems, note=note,
                   summary=f"All {len(s.here)} control(s) state every required field." if not problems
                   else f"{len(problems)} of {len(s.here)} control(s) are incomplete.")


_AT_SOURCE = re.compile(r"at source|source system|admission request", re.IGNORECASE)


def v09(s: Subject) -> Outcome:
    early = _needs_controls(s)
    if early:
        return early
    problems, unresolved = [], []
    for c in s.here:
        if not c.evidence_as_written.strip():
            continue                                        # V08 reports a missing evidence field
        for ref in c.evidence:
            if ref.record_id:
                entry = s.ctx.catalogue.get(ref.record_id) if s.ctx.catalogue is not None else None
                if s.ctx.catalogue is None:
                    unresolved.append(ref.record_id)
                elif entry is None:
                    problems.append(Finding(f"{ref.record_id} is not in the Records Catalogue.", c.control_id,
                                            "Cite a Catalogue Record ID, or raise a Record admission request."))
                elif getattr(entry, "withdrawn", False):
                    problems.append(Finding(f"{ref.record_id} is a withdrawn Catalogue entry.", c.control_id,
                                            "Cite the governed record instead."))
            elif not _AT_SOURCE.search(ref.as_written or c.evidence_as_written):
                problems.append(Finding(f"evidence “{(ref.name or ref.as_written)[:60]}” has no Record ID, and is not "
                                        "declared as evidence at source or as an admission request.", c.control_id,
                                        "Cite its Record ID from the Catalogue."))
    if problems:
        return Outcome(problems=problems)
    if unresolved:
        return Outcome(unknown=f"The Records Catalogue was not available, so {len(set(unresolved))} cited Record ID(s) "
                               "could not be looked up.")
    return Outcome(summary="Every evidence reference resolves.")


_RISK_ID = re.compile(r"\b(?:RSK|RISK)-\d+\b|risk register|risk id", re.IGNORECASE)


def v10(s: Subject) -> Outcome:
    early = _needs_controls(s)
    if early:
        return early
    problems = []
    for c in s.here:
        if not c.risk.strip():
            problems.append(Finding("has no risk statement.", c.control_id,
                                    "State what could happen, why, and the consequence."))
        elif _RISK_ID.search(c.risk):
            problems.append(Finding("refers to an internal risk register or risk ID.", c.control_id,
                                    "Describe the risk in words; do not cite a risk ID."))
    return Outcome(problems=problems, summary="Every control carries a risk statement." if not problems else "")


def v11(s: Subject) -> Outcome:
    problems = []
    for f in s.parsed.findings:
        if f.kind is FindingKind.CONTROL_DUPLICATE_ID:
            problems.append(Finding(f.message, f.location.item or ""))
    if s.ctx.index is not None and any(d is s.parsed for d in s.ctx.index.documents):
        label = document_label(s.parsed)
        for lf in s.ctx.index.findings():
            if lf.document == label and lf.finding.kind in (FindingKind.RESTATEMENT_DIFFERS, FindingKind.DEFINED_TWICE):
                problems.append(Finding(lf.finding.message, lf.finding.location.item or "",
                                        "Bring the copy into line with the defining document, or cite the control by ID."))
        for cid in s.ctx.index.contested_ids:
            if any(st.document is s.parsed for st in s.ctx.index.stated_by.get(cid, [])) and not any(
                    p.where == cid for p in problems):
                problems.append(Finding(f"{cid} is defined by more than one document with equal authority.", cid))
        return Outcome(problems=problems, summary="No duplicate or reworded control." if not problems else "")
    if problems:
        return Outcome(problems=problems)
    if not s.parsed.controls:
        return Outcome(skip="This document states no controls.")
    return Outcome(unknown="The library was not available, so the document's controls could not be compared with "
                           "other documents (no duplicate inside this document was found).")


_VAGUE = re.compile(
    r"\b(regularly|periodically|frequently|promptly|timely|in a timely manner|appropriate(?:ly)?|adequate(?:ly)?|"
    r"reasonabl[ey]|sufficient(?:ly)?|suitable|as needed|as necessary|where possible|if possible|"
    r"where practicable|from time to time|ongoing)\b", re.IGNORECASE)


def v12(s: Subject) -> Outcome:
    early = _needs_controls(s)
    if early:
        return early
    problems = []
    for c in s.here:
        for label, text in (("requirement", c.requirement), ("trigger", c.trigger)):
            for m in _VAGUE.finditer(text or ""):
                problems.append(Finding(f"“{m.group(0)}” is vague in the {label}.", c.control_id,
                                        "State a measurable threshold, an event, or a cadence."))
    return Outcome(problems=problems, summary="No vague qualifier found." if not problems else "")


_MODAL = re.compile(r"\b(should|may)\b", re.IGNORECASE)


def v14(s: Subject) -> Outcome:
    early = _needs_controls(s)
    if early:
        return early
    problems = []
    for c in s.here:
        words = sorted({m.group(1).lower() for m in _MODAL.finditer(c.requirement or "")})
        if words:
            problems.append(Finding(f"the requirement uses {', '.join(w.upper() for w in words)}. Confirm it is "
                                    "a recommendation or an option, not a mandate.", c.control_id,
                                    "Use MUST for a mandate (CDI §7.5)."))
    return Outcome(problems=problems, summary="Requirements use no SHOULD or MAY." if not problems else "",
                   note="Whether SHOULD/MAY is used correctly and abbreviations are defined needs a person; "
                        "this lists where they appear.")


_SECTION_WORDS = {"Purpose": ("purpose",), "Scope": ("scope",),
                  "Roles and Responsibilities": ("role", "responsib")}


def v15(s: Subject) -> Outcome:
    if not s.headings:
        return Outcome(unknown="The document's headings could not be read.")
    problems = []
    lowered = [h.lower() for h in s.headings]
    for section, words in _SECTION_WORDS.items():
        if not any(any(w in h for w in words) for h in lowered):
            problems.append(Finding(f"No “{section}” section.", f"section {section}",
                                    "CDI §7.3 requires it in every controlled document."))
    return Outcome(problems=problems, summary="Purpose, Scope and Roles and Responsibilities are present." if not problems else "",
                   note="The table of contents over five pages is not checked.")


def v22(s: Subject) -> Outcome:
    function = parse_doc_code(s.parsed.header.code)[0]
    if function not in ("ISMS", "QI"):
        return Outcome(skip=f"This document's function ({function or 'unknown'}) is outside QMS/ISMS scope.")
    early = _needs_controls(s)
    if early:
        return early
    problems = []
    for c in s.here:
        if not (c.mapping or c.mapping_as_written.strip()):
            problems.append(Finding("states no standards mapping.", c.control_id,
                                    "Add an ISO 9001 clause and/or ISO/IEC 27001 Annex A control (and NDPA section where relevant)."))
        elif not c.mapping:
            problems.append(Finding(f"its mapping “{c.mapping_as_written[:60]}” cannot be read as a clause.", c.control_id,
                                    "Name the clause, e.g. ISO 27001 A.5.16."))
    return Outcome(problems=problems, summary=f"All {len(s.here)} control(s) state a standards mapping." if not problems
                   else f"{len(problems)} of {len(s.here)} control(s) lack a readable mapping.")


_FILENAME_STATUS = re.compile(r"\b(draft|working|clean|final|issued|v\d+|ver(?:sion)?\s*\d+|rev(?:ision)?\s*\d+|"
                              r"\d{4}-\d{2}-\d{2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4})\b", re.IGNORECASE)


def v23(s: Subject) -> Outcome:
    stem = os.path.splitext(os.path.basename(s.filename))[0]
    title = s.parsed.header.title
    problems = []
    status = _FILENAME_STATUS.findall(stem)
    if status:
        problems.append(Finding(f"The file name carries status, version or date text (“{status[0]}”).", s.filename,
                                "Name the file exactly as its title; the Register holds status, version and dates."))
    elif title and _norm(stem) != _norm(title):
        problems.append(Finding(f"The file name “{stem}” is not the title “{title}”.", s.filename,
                                "Name the file exactly as its title."))
    elif not title:
        return Outcome(unknown="The document states no title to compare the file name with.")
    return Outcome(problems=problems, summary="The file name is the title." if not problems else "")


# ── the registry ────────────────────────────────────────────────────────────

CHECKS: dict[str, Callable[[Subject], Outcome]] = {
    "V01": v01, "V02": v02, "V03": v03, "V04": v04, "V07": v07, "V08": v08, "V09": v09, "V10": v10,
    "V11": v11, "V12": v12, "V14": v14, "V15": v15, "V22": v22, "V23": v23,
}

NOT_BUILT_REASONS = {
    "V05": "Needs the approval routes by domain (two-step First Pass and Final Approval), which Bobby has not yet decided how OrgOS should hold.",
    "V06": "Needs the approval routes by domain (two-step First Pass and Final Approval), which Bobby has not yet decided how OrgOS should hold.",
    "V13": "Needs a careful rule set: drafting notes and markers can be found, but an individual's name cannot "
           "be told from other capitalised text reliably.",
    "V16": "Not built yet: reading each Layer 4 step's responsible role.",
    "V17": "Not built yet: reading each automated step's declared evidence output.",
    "V18": "Not built yet: finding retention, custodian or disposition wording written into the text.",
    "V19": "Not built yet: showing the author similar existing documents.",
    "V20": "Checked when the document is approved in Document Lifecycle; not built yet.",
    "V21": "Checked in Document Lifecycle (consultation and sensitisation); not built yet.",
    "V24": "Not built yet: the AI Involvement field and current versions of cited laws and standards.",
}

_RESULT_FOR_PROBLEM = {"BLOCK": FAIL, "FLAG": FLAG, "REPORT": REPORT}


def _headings(file_bytes: bytes, filename: str) -> list[str]:
    try:
        content = read_document(file_bytes, filename)
        return [p.text.strip() for _, p in content.paragraphs()
                if p.text.strip() and (p.is_heading_style or re.match(r"^\d+(\.\d+)*\.?\s+\S", p.text))
                and len(p.text) < 120]
    except Exception:
        return []


def run_checks(parsed: ParsedDocument, filename: str, file_bytes: bytes,
               ctx: Optional[Context] = None) -> dict:
    ctx = ctx or Context()
    type_code = parsed.header.type_code or parse_doc_code(parsed.header.code)[1]
    here, reliable = defined_here(parsed, ctx.index)
    subject = Subject(parsed=parsed, filename=filename, headings=_headings(file_bytes, filename),
                      ctx=ctx, type_code=type_code, here=here, here_reliable=reliable)

    results: list[CheckResult] = []
    for entry in reference()["checks"]:
        cid, name, enforcement = entry["id"], entry["name"], entry["enforcement"]
        if cid not in CHECKS:
            results.append(CheckResult(cid, name, enforcement, NOT_BUILT, NOT_BUILT_REASONS.get(cid, "Not built yet.")))
            continue
        try:
            out = CHECKS[cid](subject)
        except Exception as exc:                   # a check that breaks does not pass, and does not take the rest down
            logger.exception("Check %s failed to run", cid)
            results.append(CheckResult(cid, name, enforcement, COULD_NOT,
                                       f"The check failed to run ({type(exc).__name__}: {exc})."))
            continue
        if out.skip:
            results.append(CheckResult(cid, name, enforcement, NOT_APPLICABLE, out.skip, note=out.note))
        elif out.unknown:
            results.append(CheckResult(cid, name, enforcement, COULD_NOT, out.unknown, note=out.note))
        elif out.problems:
            results.append(CheckResult(cid, name, enforcement, _RESULT_FOR_PROBLEM[enforcement],
                                       out.summary or f"{len(out.problems)} problem(s).", out.problems, out.note))
        else:
            results.append(CheckResult(cid, name, enforcement, PASS, out.summary, note=out.note))

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    failed = [r.id for r in results if r.status == FAIL]
    flagged = [r.id for r in results if r.status == FLAG]
    ran = sum(counts.get(k, 0) for k in (PASS, FAIL, FLAG, REPORT))
    verdict = "blocked" if failed else "decision" if flagged else "clear"
    cannot = counts.get(COULD_NOT, 0) + counts.get(NOT_BUILT, 0)
    headline = {
        "blocked": f"{len(failed)} blocking problem(s): {', '.join(failed)}.",
        "decision": f"No blocking problems, but {len(flagged)} flag(s) need a decision: {', '.join(flagged)}.",
        "clear": "No problems found by the checks that ran.",
    }[verdict]
    if verdict != "blocked" and cannot:
        headline += (f" This is not a full clearance: {cannot} of {len(results)} checks could not run or are not built yet.")
    return {
        "document": {"file": filename, "code": parsed.header.code, "title": parsed.header.title,
                     "type": type_code, "role": parsed.role.value, "controls_defined_here": len(here),
                     "controls_stated": len(parsed.controls)},
        "verdict": verdict, "headline": headline, "counts": counts, "checks_run": ran,
        "checks_total": len(results), "cross_document": ctx.index is not None,
        "results": [r.as_dict() for r in results],
    }
