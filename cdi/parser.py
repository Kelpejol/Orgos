# =============================================================================
# cdi/parser.py — read what a controlled document states, without inference
#
# CDI v06 documents are already structured, and this reads that structure:
#
#   Control block     a two-column table: title, code, layer, parent, owner,
#                     approval authority, standards, controls implemented, …
#   Control blocks    in a DEFINING document (a Standard, or the Procedure
#                     that defines a family with no Standard), each control is
#                     a heading "CDI-001 Title" followed by labelled lines:
#                     Requirement / Trigger / Accountable / Executing /
#                     Evidence / Risk / Failure route / Exception route /
#                     Mapping.
#   Implementation    in an IMPLEMENTING document, a section heading cites the
#                     controls it carries out — "4.0 Business impact
#                     assessment (BCDR-01)" or "5.0 Hierarchy and Parentage
#                     (implements CDI-001, CDI-019)" — with its numbered
#                     clauses and "Risk statement (BCDR-01): …".
#   Tables            Roles (role → duty), control map (control → clause),
#                     records (record → creator, step, location, retention),
#                     open parameters (deliberately unset values).
#
# The rule that keeps it honest: a control ID is only taken from a place the
# document's STRUCTURE marks as a control — a labelled block, a citing
# heading, a control-list field, a control map. Prose that mentions "BCDR-01"
# is never read as declaring it. Anything that does not fit is reported as a
# Finding; nothing is guessed to make it fit.
# =============================================================================

from __future__ import annotations

import re
from typing import Iterable, Optional

from cdi.codes import (
    CONTROL_ID_PATTERN,
    NON_CONTROL_PREFIXES,
    find_control_ids,
    find_doc_code_in_text,
    find_doc_codes,
    find_record_ids,
    parse_doc_code,
)
from cdi.fields import (
    norm,
    parse_evidence,
    parse_mapping,
    split_responsibility,
)
from cdi.model import (
    Clause,
    ControlDefinition,
    ControlMapEntry,
    DocumentHeader,
    DocumentRole,
    Finding,
    FindingKind,
    ImplementationStep,
    Location,
    OpenParameter,
    ParsedDocument,
    RecordRef,
    RoleDuty,
    Severity,
)
from cdi.reader import DocumentContent, Paragraph, Table, read_document

# Bump when parsing changes in a way that could change results, so stored
# extractions can be told apart and re-run.
PARSER_VERSION = "1.0"

# Document type codes (CDI Procedure Annex B) that support rather than control.
_SUPPORTING_TYPES = {"GDL", "PBK", "CHK", "FM", "REG", "MAN"}


def parse_document(
    file_bytes: bytes,
    filename: str,
    *,
    known_roles: Iterable[str] = (),
) -> ParsedDocument:
    """
    Parse a .docx or .pdf controlled document.

    `known_roles` is any role vocabulary already known (e.g. the Role
    Catalogue); the document's own Roles table is always added to it. It is
    used only to decide where "Accountable / Executing" splits.

    Raises cdi.reader.UnsupportedDocument for a file it cannot read.
    """
    content = read_document(file_bytes, filename)
    return parse_content(content, filename, known_roles=known_roles)


def parse_content(
    content: DocumentContent,
    filename: str,
    *,
    known_roles: Iterable[str] = (),
) -> ParsedDocument:
    findings: list[Finding] = []
    sections = _section_index(content)

    header = _parse_header(content, filename, findings)
    roles = _parse_roles(content, sections)
    vocabulary = [*known_roles, *(r.role for r in roles)]

    controls = _parse_controls(content, sections, vocabulary, findings)
    implementations = _parse_implementations(content, sections)
    control_map = _parse_control_map(content, sections)
    records = _parse_records(content, sections, findings)
    open_parameters = _parse_open_parameters(content, sections, findings)

    _link_records_to_controls(records, implementations)
    role = _classify(header, controls, implementations, control_map)
    _cross_check(header, role, implementations, control_map, findings)

    if role is DocumentRole.UNSTRUCTURED:
        findings.append(Finding(
            FindingKind.NO_STRUCTURE, Severity.WARNING,
            "No control blocks and no citing sections were found. Controls in "
            "this document cannot be read from its structure, so any extracted "
            "from it are inferred and must be confirmed.",
        ))
    if controls and header.type_code == "POL":
        findings.append(Finding(
            FindingKind.POLICY_DEFINES_CONTROLS, Severity.WARNING,
            "A Policy carries control definitions. CDI 4.2: a document that is "
            "in substance an auditable specification is a Standard, and a "
            "Policy containing steps or rules is split or reclassified.",
        ))
    if content.tracked_changes:
        findings.insert(0, Finding(
            FindingKind.TRACKED_CHANGES, Severity.WARNING,
            f"The document has {content.tracked_changes} tracked change(s). It "
            "was read as if they were accepted; resolve them before relying on "
            "what was extracted.",
        ))

    return ParsedDocument(
        filename=filename,
        format=content.format,
        header=header,
        role=role,
        controls=controls,
        implementations=implementations,
        roles=roles,
        records=records,
        control_map=control_map,
        open_parameters=open_parameters,
        findings=findings,
        tracked_changes=content.tracked_changes,
        parser_version=PARSER_VERSION,
    )


# =============================================================================
#  Shared patterns
# =============================================================================

_CONTROL_HEADING = re.compile(
    r"^(?P<id>[A-Z][A-Z0-9]{1,7}-\d{2,3})\s*[-–:.]?\s+(?P<title>\S.*)$"
)
_LABEL_LINE = re.compile(r"^(?P<label>[A-Z][A-Za-z][A-Za-z /&-]{0,40}?)\s*:\s*(?P<value>.*)$")
_NUMBERED = re.compile(r"^(?P<num>\d+(?:\.\d+)+)\.?\s+(?P<text>\S.*)$")
_ANNEX = re.compile(r"^Annex\s+[A-Z]\b", re.IGNORECASE)
_RISK_STATEMENT = re.compile(
    r"^Risk statement\s*\((?P<ids>[^)]*)\)\s*:\s*(?P<text>.+)$", re.IGNORECASE
)


def _control_heading(text: str) -> Optional[re.Match]:
    m = _CONTROL_HEADING.match(text)
    if m and m.group("id").split("-")[0] not in NON_CONTROL_PREFIXES:
        return m
    return None


def _level(number: str) -> int:
    """'4.0' → 1, '4.1' → 2, '5.3.2' → 3. A trailing .0 marks a top section."""
    parts = number.split(".")
    if len(parts) > 1 and parts[-1] == "0":
        parts = parts[:-1]
    return len(parts)


def _is_section_heading(p: Paragraph) -> bool:
    text = p.text
    if _ANNEX.match(text):
        return True
    m = _NUMBERED.match(text)
    if m and _level(m.group("num")) == 1:
        return True
    return p.is_heading_style and not _control_heading(text)


def _section_index(content: DocumentContent) -> list[str]:
    """For every block, the nearest section heading above it."""
    current, out = "", []
    for block in content.blocks:
        if isinstance(block, Paragraph) and _is_section_heading(block):
            current = block.text[:80]
        out.append(current)
    return out


def _cells(row: tuple[str, ...]) -> list[str]:
    return [c for c in row if c]


def _header_row(table: Table) -> list[str]:
    return [norm(c) for c in _cells(table.rows[0])] if table.rows else []


def _row_cells(table: Table, row: tuple[str, ...], header_width: int) -> Optional[list[str]]:
    """
    A data row aligned to its header, or None when that cannot be done safely.

    Word tables keep real column positions, so a row is used as it stands.
    A PDF table keeps only the ORDER of non-empty cells; a row with a
    different count from its header has lost a position somewhere, and
    guessing which would put a value in the wrong column.
    """
    if table.positional:
        return list(row) + [""] * max(0, header_width - len(row))
    cells = _cells(row)
    return cells if len(cells) == header_width else None


# =============================================================================
#  The document's own control block and cover
# =============================================================================

_HEADER_KEYS: dict[str, tuple[str, ...]] = {
    "title": ("document title", "title"),
    "code": ("document code", "code", "document reference"),
    "layer": ("layer", "document type / layer", "document type", "type / layer"),
    "domain": ("domain",),
    "parent": ("parent document", "parent"),
    "children": ("child documents", "child document"),
    "related": ("related documents", "related document"),
    "owner": ("document owner", "owner"),
    "approval_authority": ("approval authority",),
    "first_pass": ("first pass approval", "first pass"),
    "final_approval": ("final approval",),
    "classification": ("classification",),
    "distribution": ("distribution",),
    "issue_status": ("issue status",),
    "review_cycle": ("review cycle", "review cadence"),
    "supersedes": ("supersedes",),
    "legacy_code": ("legacy code",),
    "standards": ("standards", "standards mapping"),
    "controls_implemented": ("standard controls implemented", "controls implemented"),
    "version": ("version",),
    "effective_date": ("effective date",),
    "next_review": ("next review due", "next review"),
}
_HEADER_LABELS = {alias: key for key, aliases in _HEADER_KEYS.items() for alias in aliases}

# Where a value may come from, most authoritative first.
_SOURCE_RANK = {"control block": 0, "cover": 1, "body": 2, "filename": 3}
# Facts a document must not state two different ways.
_MUST_AGREE = ("code", "title", "version", "domain")


def _header_tables(content: DocumentContent) -> list[tuple[str, list[tuple[str, str]]]]:
    """
    Tables that are label/value control blocks, as (source, pairs).

    Only front matter counts. A Standard also carries tables ABOUT these
    fields — CDI's "Field | Rule" table defines what Domain means — whose rows
    look exactly like a control block's. Two tests keep them out: a control
    block opens with its title or a field row (not a "Field | Rule" header),
    and it comes before the first numbered section.
    """
    body_starts = next(
        (i for i, p in content.paragraphs()
         if (m := _NUMBERED.match(p.text)) and _level(m.group("num")) == 1),
        len(content.blocks),
    )
    out = []
    for idx, table in content.tables():
        if idx > body_starts or not table.rows:
            continue
        first = _cells(table.rows[0])
        opens_as_block = bool(first) and (
            norm(" ".join(first)) == "control block" or norm(first[0]) in _HEADER_LABELS
        )
        if not opens_as_block:
            continue
        pairs = []
        for row in table.rows:
            cells = _cells(row)
            if cells and norm(cells[0]) in _HEADER_LABELS:
                pairs.append((cells[0], " ".join(cells[1:]).strip()))
        if len(pairs) >= 4:
            first = norm(" ".join(_cells(table.rows[0])))
            out.append(("control block" if first == "control block" else "cover", pairs))
    return out


def _parse_header(content: DocumentContent, filename: str, findings: list[Finding]) -> DocumentHeader:
    candidates: dict[str, list[tuple[str, str]]] = {}   # key → [(source, value)]
    raw: dict[str, str] = {}

    def offer(label: str, value: str, source: str) -> None:
        key = _HEADER_LABELS.get(norm(label))
        if key is None:
            return
        raw.setdefault(f"{source}: {label.strip()}", value)
        candidates.setdefault(key, []).append((source, value.strip()))

    tables = _header_tables(content)
    for source, pairs in tables:
        for label, value in pairs:
            offer(label, value, source)

    if not tables:
        # A legacy document with no control block table may still state its
        # facts as "Label: value" lines near the top.
        for _, p in list(content.paragraphs())[:60]:
            m = _LABEL_LINE.match(p.text)
            if m:
                offer(m.group("label"), m.group("value"), "body")
        if not candidates:
            findings.append(Finding(
                FindingKind.NO_CONTROL_BLOCK, Severity.WARNING,
                "No control block was found, so the document's code, layer, "
                "parent and owner are not stated where the parser expects them.",
            ))

    header = DocumentHeader(fields=raw)

    def choose(key: str) -> str:
        offered = sorted(
            [(s, v) for s, v in candidates.get(key, []) if v],
            key=lambda sv: _SOURCE_RANK[sv[0]],
        )
        if not offered:
            return ""
        source, value = offered[0]
        header.sources[key] = source
        if key in _MUST_AGREE:
            compare = (
                (lambda v: find_doc_code_in_text(v) or norm(v)) if key == "code" else norm
            )
            others = {compare(v) for _, v in offered}
            if len(others) > 1:
                findings.append(Finding(
                    FindingKind.HEADER_CONFLICT, Severity.WARNING,
                    f"The document states its {key.replace('_', ' ')} more than one way: "
                    + "; ".join(f"{s}: “{v}”" for s, v in offered),
                    Location("Control block", key),
                ))
        return value

    header.title = choose("title")
    code_text = choose("code")
    header.code = find_doc_code_in_text(code_text)
    if not header.code:
        header.code = find_doc_code_in_text(filename)
        if header.code:
            header.sources["code"] = "filename"
    header.type_code = parse_doc_code(header.code)[1]

    header.layer_as_written = choose("layer")
    header.domain = choose("domain")
    header.version = choose("version")
    header.issue_status = choose("issue_status")
    header.effective_date = choose("effective_date")
    header.next_review = choose("next_review")
    header.owner = choose("owner")
    header.review_cycle = choose("review_cycle")
    header.supersedes = choose("supersedes")
    header.legacy_code = choose("legacy_code")

    header.parent_as_written = choose("parent")
    header.parent_codes = find_doc_codes(header.parent_as_written)
    header.child_documents_as_written = choose("children")
    header.child_codes = find_doc_codes(header.child_documents_as_written)
    header.child_record_ids = find_record_ids(header.child_documents_as_written)
    header.related_as_written = choose("related")
    header.related_codes = find_doc_codes(header.related_as_written)

    # "First Pass: X. Final Approval: Y (route)" — the control block's form.
    header.approval_authority = choose("approval_authority")
    fp = re.search(r"First Pass:\s*([^.]+)", header.approval_authority)
    fa = re.search(r"Final Approval:\s*([^.(]+)", header.approval_authority)
    header.first_pass_approval = fp.group(1).strip() if fp else choose("first_pass")
    header.final_approval = fa.group(1).strip() if fa else choose("final_approval")

    # "Internal Use Only. Distribution: All Staff" — two facts in one cell.
    classification = choose("classification")
    distribution = choose("distribution")
    m = re.search(r"\s*\.?\s*Distribution:\s*(.+)$", classification, re.IGNORECASE)
    if m:
        classification = classification[: m.start()].strip(" .")
        distribution = distribution or m.group(1).strip(" .")
    header.classification, header.distribution = classification, distribution

    header.standards_as_written = choose("standards")
    header.standards, bad = parse_mapping(header.standards_as_written)
    if bad:
        findings.append(Finding(
            FindingKind.MAPPING_UNREADABLE, Severity.WARNING,
            f"Part of the document's Standards field could not be read as clauses: {', '.join(bad)}",
            Location("Control block", "Standards"),
        ))

    header.controls_implemented_as_written = choose("controls_implemented")
    header.controls_implemented = find_control_ids(header.controls_implemented_as_written)
    return header


# =============================================================================
#  Control definitions
# =============================================================================

_CONTROL_KEYS: dict[str, tuple[str, ...]] = {
    "requirement": ("requirement",),
    "trigger": ("trigger",),
    "responsibility": ("accountable / executing", "accountable/executing", "accountable and executing"),
    "accountable": ("accountable", "accountable role"),
    "executing": ("executing", "executing role"),
    "evidence": ("evidence", "evidence records"),
    "risk": ("risk", "risk statement"),
    "failure_route": ("failure route",),
    "exception_route": ("exception route",),
    "mapping": ("mapping", "standards mapping"),
}
_CONTROL_LABELS = {alias: key for key, aliases in _CONTROL_KEYS.items() for alias in aliases}
# A block is a control when it states at least this many of the CDI fields;
# fewer, and a heading that merely starts with an ID is not mistaken for one.
_MIN_CONTROL_FIELDS = 3


class _OpenControl:
    def __init__(self, control_id: str, title: str, location: Location):
        self.control_id, self.title, self.location = control_id, title, location
        self.fields: dict[str, str] = {}
        self.other: dict[str, str] = {}
        self.last: Optional[tuple[str, str]] = None   # ("core"|"other", key)

    def add(self, label: str, value: str) -> None:
        key = _CONTROL_LABELS.get(norm(label))
        if key:
            self.fields[key] = value.strip()
            self.last = ("core", key)
        else:
            self.other[label.strip()] = value.strip()
            self.last = ("other", label.strip())

    def continue_last(self, text: str) -> None:
        if self.last is None:
            return
        kind, key = self.last
        target = self.fields if kind == "core" else self.other
        target[key] = f"{target[key]}\n{text}".strip()

    @property
    def core_count(self) -> int:
        keys = set(self.fields)
        if {"accountable", "executing"} & keys:
            keys = (keys - {"accountable", "executing"}) | {"responsibility"}
        return len(keys)


def _parse_controls(
    content: DocumentContent,
    sections: list[str],
    vocabulary: list[str],
    findings: list[Finding],
) -> list[ControlDefinition]:
    opened: list[_OpenControl] = []
    current: Optional[_OpenControl] = None

    for idx, block in enumerate(content.blocks):
        if not isinstance(block, Paragraph):
            continue
        text = block.text
        heading = _control_heading(text)
        if heading:
            current = _OpenControl(
                heading.group("id"), heading.group("title").strip(),
                Location(sections[idx], heading.group("id")),
            )
            opened.append(current)
            continue
        if current is None:
            continue
        if _is_section_heading(block) or _NUMBERED.match(text):
            current = None
            continue
        label = _LABEL_LINE.match(text)
        if label:
            current.add(label.group("label"), label.group("value"))
        else:
            current.continue_last(text)

    controls: list[ControlDefinition] = []
    seen: set[str] = set()
    for oc in opened:
        if oc.core_count < _MIN_CONTROL_FIELDS:
            continue   # an ID-led heading or line, not a control block
        if oc.control_id in seen:
            findings.append(Finding(
                FindingKind.CONTROL_DUPLICATE_ID, Severity.ERROR,
                f"{oc.control_id} is defined more than once in this document; "
                "only the first definition was read.",
                oc.location,
            ))
            continue
        seen.add(oc.control_id)
        controls.append(_build_control(oc, vocabulary, findings))
    return controls


def _build_control(oc: _OpenControl, vocabulary: list[str], findings: list[Finding]) -> ControlDefinition:
    f = oc.fields
    if "responsibility" in f:
        responsibility = split_responsibility(f["responsibility"], vocabulary)
    elif "accountable" in f or "executing" in f:
        acc = f.get("accountable", "").rstrip(".")
        exe = f.get("executing", "").rstrip(".") or acc
        responsibility = split_responsibility(
            acc if acc == exe else f"{acc} / {exe}", vocabulary
        )
    else:
        responsibility = None

    mapping, bad = parse_mapping(f.get("mapping", ""))
    control = ControlDefinition(
        control_id=oc.control_id,
        title=oc.title,
        requirement=f.get("requirement", ""),
        trigger=f.get("trigger", ""),
        responsibility=responsibility,
        evidence=parse_evidence(f.get("evidence", "")),
        evidence_as_written=f.get("evidence", ""),
        risk=f.get("risk", ""),
        failure_route=f.get("failure_route", ""),
        exception_route=f.get("exception_route", ""),
        mapping=mapping,
        mapping_as_written=f.get("mapping", ""),
        other_fields=dict(oc.other),
        location=oc.location,
    )
    for ref in control.evidence:
        ref.location = oc.location
        ref.control_ids = [oc.control_id]

    if control.missing_fields:
        findings.append(Finding(
            FindingKind.CONTROL_MISSING_FIELD,
            Severity.ERROR if not control.requirement else Severity.WARNING,
            f"{oc.control_id} does not state: {', '.join(control.missing_fields)}.",
            oc.location,
        ))
    if responsibility and responsibility.ambiguous:
        findings.append(Finding(
            FindingKind.RESPONSIBILITY_AMBIGUOUS, Severity.WARNING,
            f"{oc.control_id}: cannot tell where “{responsibility.as_written}” divides "
            f"accountable from executing. Read as accountable “{responsibility.accountable}”, "
            f"executing “{responsibility.executing}” — confirm.",
            Location(oc.location.section, f"{oc.control_id} › Accountable / Executing"),
        ))
    if bad:
        findings.append(Finding(
            FindingKind.MAPPING_UNREADABLE, Severity.WARNING,
            f"{oc.control_id}: part of the mapping could not be read as clauses: {', '.join(bad)}",
            Location(oc.location.section, f"{oc.control_id} › Mapping"),
        ))
    return control


# =============================================================================
#  Implementation — sections that carry out controls
# =============================================================================

_CITE = re.compile(r"^(?P<lead>.+?)\s*\((?P<cite>[^()]+)\)\s*$")
_CITE_FILLER = re.compile(r"\b(?:implements?|implementing|controls?|and)\b|[,;&]", re.IGNORECASE)


def _cited_ids(text: str) -> list[str]:
    """
    Control IDs a heading cites in its closing parenthesis, or [] when the
    parenthesis says anything besides IDs — "(see REC-0676)" or "(CTO)" is
    not a declaration that the section implements a control.
    """
    m = _CITE.match(text)
    if not m:
        return []
    cite = m.group("cite")
    ids = find_control_ids(cite)
    leftover = _CITE_FILLER.sub(" ", CONTROL_ID_PATTERN.sub(" ", cite)).strip()
    return ids if ids and not leftover else []


def _parse_implementations(content: DocumentContent, sections: list[str]) -> list[ImplementationStep]:
    blocks = content.blocks
    steps: list[ImplementationStep] = []

    for idx, block in enumerate(blocks):
        if not isinstance(block, Paragraph):
            continue
        ids = _cited_ids(block.text)
        if not ids:
            continue
        lead = _CITE.match(block.text).group("lead")
        numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$", lead)
        if numbered:
            number, title, level = numbered.group(1), numbered.group(2), _level(numbered.group(1))
        elif block.is_heading_style:
            number, title, level = "", lead, 0
        else:
            continue   # an unnumbered, unstyled line is prose, not a heading

        step = ImplementationStep(
            control_ids=ids,
            section_number=number,
            section_title=title.strip(),
            location=Location(block.text[:80], ", ".join(ids)),
        )
        for nxt in blocks[idx + 1:]:
            if isinstance(nxt, Table):
                continue
            text = nxt.text
            if _ANNEX.match(text):
                break
            m = _NUMBERED.match(text)
            if level and m and _level(m.group("num")) <= level:
                break
            if not level and nxt.is_heading_style:
                break
            risk = _RISK_STATEMENT.match(text)
            if risk:
                for cid in find_control_ids(risk.group("ids")) or ids:
                    step.risk_statements[cid] = risk.group("text").strip()
            elif m:
                step.clauses.append(Clause(m.group("num"), m.group("text").strip()))
            elif step.clauses:
                last = step.clauses[-1]
                step.clauses[-1] = Clause(last.number, f"{last.text} {text}")
            else:
                step.clauses.append(Clause("", text))
        step.record_ids = find_record_ids(" ".join(c.text for c in step.clauses))
        steps.append(step)
    return steps


# =============================================================================
#  Tables: Roles, control map, records, open parameters
# =============================================================================

def _parse_roles(content: DocumentContent, sections: list[str]) -> list[RoleDuty]:
    out: list[RoleDuty] = []
    for idx, table in content.tables():
        hdr = _header_row(table)
        if len(hdr) < 2 or hdr[0] not in ("role", "roles"):
            continue
        if not (hdr[1].startswith("dut") or "responsib" in hdr[1]):
            continue
        for row in table.rows[1:]:
            cells = _cells(row)
            if len(cells) >= 2:
                out.append(RoleDuty(cells[0], " ".join(cells[1:]), Location(sections[idx], "Roles")))
            elif len(cells) == 1:
                out.append(RoleDuty(cells[0], "", Location(sections[idx], "Roles")))
    return out


def _parse_control_map(content: DocumentContent, sections: list[str]) -> list[ControlMapEntry]:
    out: list[ControlMapEntry] = []
    for idx, table in content.tables():
        hdr = _header_row(table)
        if len(hdr) < 2 or hdr[0] not in ("standard control", "control", "control id"):
            continue
        if "clause" not in hdr[1] or "source" in hdr[1]:
            continue   # "Control | Source clauses" is a carry map of old wording
        for row in table.rows[1:]:
            cells = _cells(row)
            ids = find_control_ids(cells[0]) if cells else []
            if not ids or len(cells) < 2:
                continue
            title = re.sub(r"\s+", " ", CONTROL_ID_PATTERN.sub(" ", cells[0])).strip()
            out.append(ControlMapEntry(ids[0], title, cells[1].strip(), Location(sections[idx], "Control map")))
    return out


_RECORD_COLUMNS: dict[str, tuple[str, ...]] = {
    "record": ("record", "record name", "records"),
    "record_id": ("record id",),
    "created_by": ("created by", "creator", "produced by"),
    "at_step": ("at step", "step"),
    "kept_in": ("kept in", "location", "stored in", "held in"),
    "retention": ("retention", "retention period"),
    "production_mode": ("production mode",),
}


def _parse_records(content: DocumentContent, sections: list[str], findings: list[Finding]) -> list[RecordRef]:
    out: list[RecordRef] = []
    for idx, table in content.tables():
        hdr = _header_row(table)
        if not hdr or hdr[0] not in _RECORD_COLUMNS["record"]:
            continue
        columns = {
            key: next((i for i, h in enumerate(hdr) if h in aliases), None)
            for key, aliases in _RECORD_COLUMNS.items()
        }
        if sum(v is not None for k, v in columns.items() if k != "record") < 1:
            continue
        location = Location(sections[idx], "Records")
        width = len(table.rows[0]) if table.positional else len(hdr)
        if table.positional:
            # Index by real column: a Word header row may have empty cells.
            positions = [i for i, c in enumerate(table.rows[0]) if c]
            columns = {k: (positions[v] if v is not None else None) for k, v in columns.items()}

        for row in table.rows[1:]:
            cells = _row_cells(table, row, width)
            whole = " ".join(_cells(row))
            if cells is None:
                ids = find_record_ids(whole)
                findings.append(Finding(
                    FindingKind.TABLE_ROW_UNALIGNED, Severity.WARNING,
                    f"A records-table row could not be aligned to its columns "
                    f"({', '.join(ids) or whole[:60]}). Only its Record ID was read; "
                    "check the source document.",
                    location,
                ))
                out.extend(RecordRef(rid, as_written=whole, location=location) for rid in ids)
                continue

            def col(key: str) -> str:
                i = columns.get(key)
                return cells[i].strip() if i is not None and i < len(cells) else ""

            record_text = col("record")
            ids = find_record_ids(col("record_id")) or find_record_ids(record_text)
            name = re.sub(r"\s+", " ", re.sub(r"\bREC-\d{4}\b", " ", record_text)).strip(" .,:-")
            base = dict(
                name=name, as_written=whole,
                created_by=col("created_by"), at_step=col("at_step"),
                kept_in=col("kept_in"), retention=col("retention"),
                production_mode=col("production_mode"), location=location,
            )
            if not ids:
                out.append(RecordRef(None, **base))
            else:
                out.extend(RecordRef(rid, **base) for rid in ids)
    return out


def _parse_open_parameters(
    content: DocumentContent, sections: list[str], findings: list[Finding]
) -> list[OpenParameter]:
    out: list[OpenParameter] = []
    for idx, table in content.tables():
        hdr = _header_row(table)
        if not hdr or hdr[0] != "parameter" or not any("value" in h for h in hdr):
            continue
        location = Location(sections[idx], "Open parameters")
        for row in table.rows[1:]:
            if table.positional:
                positions = [i for i, c in enumerate(table.rows[0]) if c]
                cells = [row[i] if i < len(row) else "" for i in positions]
            else:
                cells = _cells(row)
            # The value comes last and is what is expected to be missing, so
            # a short PDF row is aligned by padding at the end.
            cells = (cells + ["", "", ""])[:3]
            parameter, used_in, value = (c.strip() for c in cells)
            if not parameter:
                continue
            param = OpenParameter(parameter, used_in, value or None, location)
            out.append(param)
            if param.value is None:
                findings.append(Finding(
                    FindingKind.OPEN_PARAMETER, Severity.INFO,
                    f"Open parameter not yet set: {parameter}"
                    + (f" (used in {used_in})" if used_in else "") + ".",
                    location,
                ))
    return out


# =============================================================================
#  Linking and cross-checking within one document
# =============================================================================

def _top(number: str) -> str:
    return number.split(".")[0] if number else ""


def _link_records_to_controls(records: list[RecordRef], steps: list[ImplementationStep]) -> None:
    """
    Tie each records-table row to the controls it evidences: through its
    "at step" (step 4.1 sits in section 4.0, which implements BCDR-01), and
    through any section that names the record.
    """
    by_section = {_top(s.section_number): s for s in steps if s.section_number}
    for ref in records:
        ids: list[str] = []
        for step_no in re.findall(r"\d+(?:\.\d+)*", ref.at_step or ""):
            step = by_section.get(_top(step_no))
            if step:
                ids.extend(step.control_ids)
        if ref.record_id:
            for step in steps:
                if ref.record_id in step.record_ids:
                    ids.extend(step.control_ids)
        ref.control_ids = list(dict.fromkeys(ref.control_ids + ids))


def _cross_check(
    header: DocumentHeader,
    role: DocumentRole,
    steps: list[ImplementationStep],
    control_map: list[ControlMapEntry],
    findings: list[Finding],
) -> None:
    """
    An implementing document states which controls it carries out up to three
    times — the control block list, the section headings, the control map.
    Where they disagree, say so: one of them is wrong.
    """
    listed = header.controls_implemented
    cited = list(dict.fromkeys(i for s in steps for i in s.control_ids))
    mapped = [e.control_id for e in control_map]

    # A forms set, guideline or playbook SUPPORTS the controls it lists as a
    # whole; it has no sections that carry them out, and is not expected to.
    for cid in (listed if role is DocumentRole.IMPLEMENTING else []):
        if cid not in cited and cid not in mapped:
            findings.append(Finding(
                FindingKind.IMPLEMENTED_NOT_CITED, Severity.WARNING,
                f"The control block lists {cid} as implemented, but no section "
                "carries it out.",
                Location("Control block", "Standard controls implemented"),
            ))
    if listed:
        for cid in cited:
            if cid not in listed:
                findings.append(Finding(
                    FindingKind.CITED_NOT_LISTED, Severity.WARNING,
                    f"A section carries out {cid}, but the control block does not "
                    "list it as implemented.",
                    Location("Control block", "Standard controls implemented"),
                ))

    by_section = {_top(s.section_number): s for s in steps if s.section_number}
    for entry in control_map:
        step = by_section.get(_top(entry.clause))
        if step is None or entry.control_id not in step.control_ids:
            where = f"section {entry.clause}" if step is None else (
                f"section {step.section_number} cites {', '.join(step.control_ids)}"
            )
            findings.append(Finding(
                FindingKind.CONTROL_MAP_MISMATCH, Severity.ERROR,
                f"The control map puts {entry.control_id} at clause {entry.clause}, "
                f"but {where}.",
                entry.location,
            ))
    if control_map:
        for cid in cited:
            if cid not in mapped:
                findings.append(Finding(
                    FindingKind.CONTROL_MAP_MISMATCH, Severity.WARNING,
                    f"A section carries out {cid}, but the control map does not list it.",
                    Location("Annex", "Control map"),
                ))


def _classify(
    header: DocumentHeader,
    controls: list[ControlDefinition],
    steps: list[ImplementationStep],
    control_map: list[ControlMapEntry],
) -> DocumentRole:
    if controls:
        return DocumentRole.DEFINING
    if header.type_code in _SUPPORTING_TYPES:
        # Even when it lists the controls it supports: a form supports a
        # control, it does not carry it out.
        return DocumentRole.SUPPORTING
    if steps or header.controls_implemented or control_map:
        return DocumentRole.IMPLEMENTING
    if header.type_code == "POL":
        return DocumentRole.AUTHORITY
    return DocumentRole.UNSTRUCTURED
