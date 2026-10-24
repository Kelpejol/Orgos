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
    expand_control_ranges,
    find_control_ids,
    find_doc_code_in_text,
    find_doc_codes,
    find_record_ids,
    is_control_id,
    parse_doc_code,
)
from cdi.fields import (
    control_field,
    norm,
    parse_evidence,
    parse_control_list,
    parse_mapping,
    split_labelled,
    parse_control_owner,
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
    Responsibility,
    RoleDuty,
    Severity,
)
from cdi.reader import DocumentContent, Paragraph, Table, read_document

# Bump when parsing changes in a way that could change results, so stored
# extractions can be told apart and re-run.
PARSER_VERSION = "1.0"

# Document type codes (CDI Procedure Annex B) that support rather than control.
_SUPPORTING_TYPES = {"GDL", "PBK", "CHK", "FM", "FRM", "REG", "MAN"}
# Legacy SOP is a procedure by another name.
_PROCEDURE_TYPES = {"PRO", "SPEC", "SOP"}


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

    controls, row_links, partial = _parse_controls(content, sections, vocabulary, findings)
    implementations = _parse_implementations(content, sections)
    if header.type_code in _PROCEDURE_TYPES:
        implementations += _sections_headed_by_controls(partial)
    header.controls_declared_in_body = [
        i for i in _declared_in_body(content) if i not in header.controls_implemented
    ]
    control_map = _parse_control_map(content, sections) + row_links
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

# Built from the one control-ID pattern, so heading recognition can never
# drift from ID recognition (it did: three-part IDs like ACS-L3-01 were
# recognised in text but not as headings).
_CONTROL_HEADING = re.compile(
    r"^(?P<id>" + CONTROL_ID_PATTERN.pattern.replace(r"\b", "") + r")(?:\s*[-–:.]?\s+(?P<title>\S.*))?$"
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
    "code": ("document code", "display code", "code", "document reference"),
    "layer": ("layer", "document type / layer", "document type", "type / layer"),
    "domain": ("domain", "primary domain"),
    "parent": ("parent document", "parent"),
    "children": ("child documents", "child document"),
    "related": ("related documents", "related document"),
    "owner": ("document owner", "owner", "domain owner"),
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

def header_key(label: str) -> str:
    """The header field a label names ('Document code' → 'code'), or '' if it is not one."""
    return _HEADER_LABELS.get(norm(label), "")


# Where a value may come from, most authoritative first.
_SOURCE_RANK = {"control block": 0, "cover": 1, "body": 2, "filename": 3}
# Facts a document must not state two different ways.
_MUST_AGREE = ("code", "title", "version", "domain")


_LAYER_TYPES = (
    ("specification", "SPEC"), ("procedure", "PRO"), ("standard", "STD"),
    ("policy", "POL"), ("guideline", "GDL"), ("playbook", "PBK"),
    ("checklist", "CHK"), ("register", "REG"), ("manual", "MAN"),
    ("form", "FM"), ("template", "FM"),
)


def _type_from_layer(layer: str) -> str:
    """'Standard (Layer 3)' → 'STD', for a document whose code is missing."""
    text = norm(layer)
    return next((code for word, code in _LAYER_TYPES if word in text), "")


_STANDARD_LABEL = re.compile(r"(iso\b|ndp[ar]\b|nigeria data protection)")


def _is_standard_label(label: str) -> bool:
    """A header row whose label IS a standard ("ISO 27001:2022 Annex A | A.8.20, A.8.21")."""
    return bool(_STANDARD_LABEL.match(norm(label)))


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
            norm(" ".join(first)) in ("control block", "control metadata value", "field value", "field detail")
            or norm(first[0]) in _HEADER_LABELS
        )
        if not opens_as_block:
            continue
        pairs = []
        non_empty_rows = 0
        caption = norm(" ".join(first)) in ("control block", "control metadata value", "field value", "field detail")
        for r, row in enumerate(table.rows):
            cells = _cells(row)
            if cells and any(cells) and not (r == 0 and caption):    # a caption row is not a fact row
                non_empty_rows += 1
            if cells and (norm(cells[0]) in _HEADER_LABELS or _is_standard_label(cells[0])):
                pairs.append((cells[0], " ".join(cells[1:]).strip()))
        # A control block states at least four facts. A smaller table counts only
        # when EVERY row is a known header fact — which is what is left of a
        # converted document's block once the CDT cover has taken over the rest
        # (e.g. just "Supersedes", or "Controls implemented").
        every_row_a_fact = bool(pairs) and len(pairs) == non_empty_rows and not any(
            norm(c) in ("field", "rule", "mandatory") for c in first)
        if len(pairs) >= 4 or every_row_a_fact:
            first = norm(" ".join(_cells(table.rows[0])))
            out.append(("control block" if first == "control block" else "cover", pairs))
    return out


def _parse_header(content: DocumentContent, filename: str, findings: list[Finding]) -> DocumentHeader:
    candidates: dict[str, list[tuple[str, str]]] = {}   # key → [(source, value)]
    raw: dict[str, str] = {}

    standard_rows: list[str] = []      # a row whose LABEL is the standard: "ISO 27001:2022 Annex A | A.8.20, A.8.21"

    def offer(label: str, value: str, source: str) -> None:
        key = _HEADER_LABELS.get(norm(label))
        if key is None:
            if value.strip() and _is_standard_label(label):
                standard_rows.append(f"{label.strip()} {value.strip()}")
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
    # No type from the code: try the layer, then the title, then the file
    # name — "IT and Infrastructure Control Standard" is a Standard.
    for source, text in (("layer", header.layer_as_written), ("title", header.title),
                         ("filename", filename)):
        if header.type_code:
            break
        header.type_code = _type_from_layer(text)
        if header.type_code:
            header.sources["type_code"] = source
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
    if not header.standards_as_written and standard_rows:
        header.sources["standards"] = "standard rows"
        header.standards_as_written = "; ".join(standard_rows)
    header.standards, bad = parse_mapping(header.standards_as_written)
    if bad:
        findings.append(Finding(
            FindingKind.MAPPING_UNREADABLE, Severity.WARNING,
            f"Part of the document's Standards field could not be read as clauses: {', '.join(bad)}",
            Location("Control block", "Standards"),
        ))

    header.controls_implemented_as_written = choose("controls_implemented")
    header.controls_implemented = parse_control_list(header.controls_implemented_as_written)
    return header


# =============================================================================
#  Control definitions
#
#  The library states controls in three physical layouts, and all three read
#  through one field vocabulary (cdi.fields.CONTROL_FIELD_ALIASES):
#
#    BLOCK  a heading "CDI-001 Title", then the control's fields as
#           paragraphs. Fields may be labelled one per line ("Trigger: …"),
#           several to a line ("Governing authority: X. Responsible role:
#           Y."), or in a small two-column table under the heading (IT); an
#           unlabelled first paragraph is the requirement (Access Control).
#    ROW    a table with one control per row: "ID | Mandatory control
#           requirement | Required evidence | Risk statement" and its many
#           variants (APPSEC, Data Protection, IUHC, …).
#
#  Whether a statement DEFINES a control or restates one defined elsewhere is
#  not decided here: that takes the whole library (cdi.library), where a
#  Standard outranks a Procedure.
# =============================================================================

# A block is a control when it states at least this many fields; fewer, and a
# line that merely opens with an ID ("CDI-019 is implemented throughout…")
# is not mistaken for one.
_MIN_CONTROL_FIELDS = 3
_CORE_FIELDS = {
    "requirement", "trigger", "responsibility", "evidence", "risk",
    "failure_route", "exception_route", "mapping", "authority",
}
# Headers that open a row-per-control table's ID column.
_ID_HEADERS = {"id", "control id", "ref", "control ref", "control", "id and requirement"}


class _RawControl:
    """A control as found, before its values are interpreted."""

    def __init__(self, control_id: str, title: str, location: Location, layout: str,
                 *, styled: bool = False):
        self.control_id, self.title, self.location, self.layout = control_id, title, location, layout
        self.styled = styled                  # opened by a heading-styled paragraph
        self.fields: dict[str, str] = {}
        self.other: dict[str, str] = {}
        self.paragraphs: list[str] = []       # every paragraph in the block, in order
        self.last: Optional[tuple[str, str]] = None   # ("core"|"other", key)

    def add(self, label: str, value: str, *, field_name: Optional[str] = None) -> None:
        key = field_name or control_field(label)
        value = value.strip()
        if key and key != "title":
            # The same field stated twice (a label line and a table row) is
            # kept whole rather than one silently replacing the other.
            self.fields[key] = f"{self.fields[key]}\n{value}" if self.fields.get(key) else value
            self.last = ("core", key)
        elif key == "title" and not self.title:
            self.title = value
        else:
            self.other[label.strip()] = value
            self.last = ("other", label.strip())

    def open_label(self, label: str) -> None:
        """A sub-heading: the paragraphs that follow belong to this field."""
        key = control_field(label)
        if key and key != "title":
            self.last = ("core", key)
            self.fields.setdefault(key, "")
        else:
            self.last = ("other", label.strip())
            self.other.setdefault(label.strip(), "")

    def continue_last(self, text: str) -> None:
        if self.last is None:
            return
        kind, key = self.last
        target = self.fields if kind == "core" else self.other
        target[key] = f"{target[key]}\n{text}".strip()

    @property
    def field_count(self) -> int:
        owners = {"accountable", "executing", "control_owner"}
        keys = {k for k, v in self.fields.items() if v and k in _CORE_FIELDS | owners}
        if owners & keys:
            keys = (keys - owners) | {"responsibility"}
        return len(keys)


def _heading_level(p: Paragraph) -> Optional[int]:
    """'Heading 2' → 2; None for a paragraph that is not heading-styled."""
    m = re.match(r"heading\s*(\d)", p.style.lower())
    return int(m.group(1)) if m else (0 if p.style.lower() == "title" else None)


def _block_controls(content: DocumentContent, sections: list[str]) -> list[_RawControl]:
    """Every ID-led block, full or not — the caller decides what each one is."""
    found: list[_RawControl] = []
    current: Optional[_RawControl] = None
    control_level: Optional[int] = None
    awaiting_first = False

    for idx, block in enumerate(content.blocks):
        if isinstance(block, Table):
            if current is None:
                continue
            # A per-control field table: "Responsible role | IT Executive".
            for row in block.rows:
                cells = _cells(row)
                if len(cells) >= 2 and control_field(cells[0]):
                    current.add(cells[0], " ".join(cells[1:]))
                    awaiting_first = False
            continue

        text = block.text
        heading = _control_heading(text)
        if heading:
            control_id, title = heading.group("id"), (heading.group("title") or "").strip()
            step_ref = ""
            if is_control_id(title):
                # "AP-01 ACS-L3-01": the procedure's own step number, then the
                # control it carries out. The control is the second.
                step_ref, control_id, title = control_id, title, ""
            current = _RawControl(
                control_id, title, Location(sections[idx], control_id), "block",
                styled=block.is_heading_style,
            )
            if step_ref:
                current.other["Step reference"] = step_ref
            found.append(current)
            control_level = _heading_level(block)
            awaiting_first = True
            continue
        if current is None:
            continue
        level = _heading_level(block)
        if (control_level is not None and level is not None and level > control_level
                and not _NUMBERED.match(text)):
            # A sub-heading inside the control — Change Management's "Control
            # requirement", "Procedure" — labels the paragraphs beneath it.
            current.open_label(text)
            awaiting_first = False
            continue
        if _is_section_heading(block) or _NUMBERED.match(text):
            current = None
            continue

        current.paragraphs.append(text)
        pairs = split_labelled(text)
        if pairs:
            for label, value in pairs:
                current.add(label, value)
        elif awaiting_first and not current.fields:
            # Access Control and IT open each control with its requirement,
            # unlabelled, straight under the heading.
            current.add("Requirement", text, field_name="requirement")
        else:
            current.continue_last(text)
        awaiting_first = False

    return found


def _row_controls(
    content: DocumentContent, sections: list[str], findings: list[Finding]
) -> tuple[list[_RawControl], list[ControlMapEntry]]:
    """Controls from tables with one control per row, plus any clause links."""
    found: list[_RawControl] = []
    links: list[ControlMapEntry] = []

    for idx, table in content.tables():
        hdr = _header_row(table)
        if len(hdr) < 2 or hdr[0] not in _ID_HEADERS:
            continue
        columns: dict[str, int] = {}
        for i, h in enumerate(hdr[1:], start=1):
            name = control_field(h, allow_keywords=True)
            if name and name not in columns:
                columns[name] = i
        combined = hdr[0] == "id and requirement"
        if "requirement" not in columns and not combined:
            continue   # a forms or parameter table: rows open with IDs, but state no control

        location = Location(sections[idx], "Control table")
        width = len(table.rows[0]) if table.positional else len(hdr)
        positions = (
            [i for i, c in enumerate(table.rows[0]) if c] if table.positional else list(range(len(hdr)))
        )
        for row in table.rows[1:]:
            id_cell = row[positions[0]] if positions[0] < len(row) else ""
            m = CONTROL_ID_PATTERN.match(id_cell.strip())
            if not m or m.group(1) in NON_CONTROL_PREFIXES:
                continue
            cells = _row_cells(table, row, width)
            if cells is None:
                findings.append(Finding(
                    FindingKind.TABLE_ROW_UNALIGNED, Severity.WARNING,
                    f"The row for {m.group(0)} could not be aligned to its columns, so "
                    "it was not read; check the source document.",
                    location,
                ))
                continue
            # Only the separator after the ID goes: "CIP-001 — The context
            # MUST be reviewed." keeps its full stop.
            rest = id_cell.strip()[m.end():].lstrip(" .:-–").strip()
            raw = _RawControl(m.group(0), "" if combined else rest, Location(sections[idx], m.group(0)), "row")
            if combined and rest:
                raw.add("Requirement", rest, field_name="requirement")
            for name, i in columns.items():
                value = cells[positions[i]].strip() if positions[i] < len(cells) else ""
                if value:
                    raw.add(hdr[i], value, field_name=name)
            if "clause" in raw.fields:
                links.append(ControlMapEntry(m.group(0), raw.title, raw.fields.pop("clause"), location))
            found.append(raw)
    return found, links


def _parse_controls(
    content: DocumentContent,
    sections: list[str],
    vocabulary: list[str],
    findings: list[Finding],
) -> tuple[list[ControlDefinition], list[ControlMapEntry], list[_RawControl]]:
    """
    Returns (control statements, clause links from control tables, partial
    blocks). A partial block is a heading-styled control heading that does
    not state enough fields to be a control — in a procedure, that is a
    section carrying the control out (see _sections_headed_by_controls).
    """
    blocks = _block_controls(content, sections)
    full = [b for b in blocks if b.field_count >= _MIN_CONTROL_FIELDS]
    partial = [b for b in blocks if b.field_count < _MIN_CONTROL_FIELDS and b.styled]
    rows, links = _row_controls(content, sections, findings)
    controls: list[ControlDefinition] = []
    seen: set[str] = set()
    for raw in full + rows:
        if raw.control_id in seen:
            findings.append(Finding(
                FindingKind.CONTROL_DUPLICATE_ID, Severity.ERROR,
                f"{raw.control_id} is stated more than once in this document; "
                "only the first was read.",
                raw.location,
            ))
            continue
        seen.add(raw.control_id)
        controls.append(_build_control(raw, vocabulary, findings))
    return controls, links, partial


def _sections_headed_by_controls(partial: list[_RawControl]) -> list[ImplementationStep]:
    """
    A procedure section headed by the control it carries out — "BCDR-01
    Business impact assessment", "IT-01 Technology service requests", "AP-01
    ACS-L3-01" — followed by its steps and labelled lines.
    """
    steps = []
    for raw in partial:
        step = ImplementationStep(
            control_ids=[raw.control_id],
            section_number="",
            section_title=raw.title,
            location=raw.location,
        )
        for text in raw.paragraphs:
            pairs = split_labelled(text)
            if pairs:
                for label, value in pairs:
                    step.fields[label] = value
                continue
            m = re.match(r"^(\d+(?:\.\d+)*)[.)]?\s+(\S.*)$", text)
            step.clauses.append(Clause(m.group(1), m.group(2)) if m else Clause("", text))
        step.record_ids = find_record_ids(
            " ".join([c.text for c in step.clauses] + list(step.fields.values()))
        )
        steps.append(step)
    return steps


def _build_control(raw: _RawControl, vocabulary: list[str], findings: list[Finding]) -> ControlDefinition:
    f = raw.fields
    if f.get("control_owner"):
        # One role, as written. Wins over any older accountable / executing line.
        responsibility = parse_control_owner(f["control_owner"])
    elif f.get("responsibility"):
        responsibility = split_responsibility(f["responsibility"], vocabulary)
    elif f.get("accountable") or f.get("executing"):
        # Stated on separate lines, the split is already made; re-splitting
        # "A / B" would only invent an ambiguity.
        acc = f.get("accountable", "").rstrip(".").strip()
        exe = f.get("executing", "").rstrip(".").strip() or acc
        responsibility = Responsibility(
            acc or exe, exe, f"Accountable: {acc or '—'}; Executing: {exe}"
        )
    else:
        responsibility = None

    # Evidence may be named in one field and identified in another ("Required
    # evidence: …. Record IDs: REC-0691; REC-0692"). The IDs are authoritative;
    # the names stay in evidence_as_written for whoever matches them.
    evidence = parse_evidence(f.get("evidence", ""))
    listed_ids = find_record_ids(f.get("record_ids", ""))
    if listed_ids:
        evidence = [r for r in evidence if r.record_id]
        known = {r.record_id for r in evidence}
        evidence += [RecordRef(rid, as_written=f["record_ids"]) for rid in listed_ids if rid not in known]
    evidence_as_written = "\n".join(
        v for v in (f.get("evidence", ""), f"Record IDs: {f['record_ids']}" if f.get("record_ids") else "") if v
    )

    mapping, bad = parse_mapping(f.get("mapping", ""))
    control = ControlDefinition(
        control_id=raw.control_id,
        title=raw.title,
        requirement=f.get("requirement", ""),
        trigger=f.get("trigger", ""),
        responsibility=responsibility,
        evidence=evidence,
        evidence_as_written=evidence_as_written,
        risk=f.get("risk", ""),
        failure_route=f.get("failure_route", ""),
        exception_route=f.get("exception_route", ""),
        mapping=mapping,
        mapping_as_written=f.get("mapping", ""),
        authority=f.get("authority", ""),
        layout=raw.layout,
        other_fields=dict(raw.other),
        location=raw.location,
    )
    for ref in control.evidence:
        ref.location = raw.location
        ref.control_ids = [raw.control_id]

    if control.missing_fields:
        findings.append(Finding(
            FindingKind.CONTROL_MISSING_FIELD,
            Severity.ERROR if not control.requirement else Severity.WARNING,
            f"{raw.control_id} does not state: {', '.join(control.missing_fields)}.",
            raw.location,
        ))
    if responsibility and responsibility.ambiguous:
        findings.append(Finding(
            FindingKind.RESPONSIBILITY_AMBIGUOUS, Severity.WARNING,
            f"{raw.control_id}: cannot tell where “{responsibility.as_written}” divides "
            f"accountable from executing. Read as accountable “{responsibility.accountable}”, "
            f"executing “{responsibility.executing}” — confirm.",
            Location(raw.location.section, f"{raw.control_id} › Responsible role"),
        ))
    if bad:
        findings.append(Finding(
            FindingKind.MAPPING_UNREADABLE, Severity.WARNING,
            f"{raw.control_id}: part of the mapping could not be read as clauses: {', '.join(bad)}",
            Location(raw.location.section, f"{raw.control_id} › Mapping"),
        ))
    return control


# =============================================================================
#  Implementation — sections that carry out controls
# =============================================================================

_CITE = re.compile(r"^(?P<lead>.+?)\s*\((?P<cite>[^()]+)\)\s*$")
_CITE_FILLER = re.compile(r"\b(?:implements?|implementing|controls?|and)\b|[,;&]", re.IGNORECASE)


_IMPLEMENTS_LINE = re.compile(r"^(?:this section\s+)?implements?\s+(?P<ids>.+?)\.?$", re.IGNORECASE)
# "This Procedure implements IUHC-001 to IUHC-012." — the first sentence only.
_DECLARATION = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+)?(?:this|the)\s+(?:procedure|specification|instrument|document)"
    r"\s+implements\s+(?P<ids>[^.]+)\.",
    re.IGNORECASE,
)
# "Inherited controls: APPSEC-01 to APPSEC-13"
_CONTROL_LIST_LABELS = {"inherited controls", "controls implemented", "implemented controls", "controls"}


def _implements_line(text: str) -> list[str]:
    """
    Control IDs from a line under a section heading that says only what the
    section implements — "Implements IRG-001, IRG-002 and IRG-023." — or [].
    A sentence that goes on to say anything else is prose.
    """
    m = _IMPLEMENTS_LINE.match(text.strip())
    return _pure_id_list(m.group("ids")) if m else []


def _pure_id_list(text: str) -> list[str]:
    """IDs from text that lists IDs and nothing else, or []."""
    listed = expand_control_ranges(text)
    ids = find_control_ids(listed)
    leftover = _CITE_FILLER.sub(" ", CONTROL_ID_PATTERN.sub(" ", listed)).strip(" .")
    return ids if ids and not leftover else []


def _declared_in_body(content: DocumentContent) -> list[str]:
    """
    Controls a document declares it implements outside its control block, in
    one of three strict forms. Each must be ONLY a declaration and a list of
    IDs; a sentence that says anything more is prose and is not read.
    """
    ids: list[str] = []
    for _, p in content.paragraphs():
        found: list[str] = []
        m = _DECLARATION.match(p.text)
        if m:
            found = _pure_id_list(m.group("ids"))
        if not found:
            for part in p.text.split("|"):        # "Working Draft | Layer 4 | Implements DP-001 to DP-046"
                found = _implements_line(part)
                if found:
                    break
        if not found and ":" in p.text:
            label, _, value = p.text.partition(":")
            if norm(label) in _CONTROL_LIST_LABELS:
                found = _pure_id_list(value)
        ids.extend(i for i in found if i not in ids)
    return ids


def _cited_ids(text: str) -> list[str]:
    """
    Control IDs a heading cites in its closing parenthesis, or [] when the
    parenthesis says anything besides IDs — "(see REC-0676)" or "(CTO)" is
    not a declaration that the section implements a control.
    """
    m = _CITE.match(text)
    if not m:
        return []
    cite = expand_control_ranges(m.group("cite"))
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
        lead = _CITE.match(block.text).group("lead") if ids else block.text
        if not ids and _is_section_heading(block):
            # Records Governance style: the heading names the section and the
            # line beneath it says what it implements.
            nxt = blocks[idx + 1] if idx + 1 < len(blocks) else None
            if isinstance(nxt, Paragraph):
                ids = _implements_line(nxt.text)
        if not ids:
            continue
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
            if _implements_line(text):
                continue   # the citation line itself, not a clause
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
        duties = hdr[1].startswith("dut") or "responsib" in hdr[1]
        # A sign-off block ("Role | Name | Signature | Date") names the roles that sign; a
        # "Role | Access level" table describes system roles and is not read as roles.
        sign_off = hdr[1] in ("name", "signatory", "signed by", "holder") or hdr[1].startswith("signat")
        if not (duties or sign_off):
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
    """
    What the document is, by its layer. Note what this does NOT decide: a
    Procedure that states controls may be restating its Standard's, or — where
    a family has no Standard — be the document that defines them. That needs
    the whole library; see cdi.library.
    """
    kind = header.type_code
    if kind in _SUPPORTING_TYPES:
        # A form or register supports the controls it lists; it does not
        # carry them out, even when it restates them.
        return DocumentRole.SUPPORTING
    carries_out = bool(
        steps or header.controls_implemented or header.controls_declared_in_body or control_map
    )
    if kind in _PROCEDURE_TYPES and (controls or carries_out):
        return DocumentRole.IMPLEMENTING
    if controls:
        return DocumentRole.DEFINING
    if kind == "POL":
        # A Policy that lists controls AUTHORISES them; it does not carry
        # them out.
        return DocumentRole.AUTHORITY
    if carries_out:
        return DocumentRole.IMPLEMENTING
    return DocumentRole.UNSTRUCTURED
