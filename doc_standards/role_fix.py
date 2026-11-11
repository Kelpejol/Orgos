# =============================================================================
# doc_standards/role_fix.py — "use this role": change a role's name in a document
#
# When the role check finds a document naming something that is not in Org Roles
# and the author picks the role that was meant, the document itself is changed
# to name it (CDI 7.8: roles are named by controlled organisational title).
#
# This edits a controlled document, so it is deliberately narrow and proves itself:
#
#   WHERE   only a role FIELD is changed — a "Control owner:" line (or the older
#           Accountable / Executing / Responsible role line), a control table's
#           role column, a header table's Owner / First pass / Final approval row,
#           a Roles table's role column. The same words in running text ("the
#           Head of IT shall…") are left alone: they are prose, not a role field.
#           A label counts only where a field starts — "Record owner:" is not an
#           Owner field, and a records table's Owner column is not a role column.
#   SCOPE   a change can be limited to ONE use: a control (its owner line or its
#           row in a control table), one cover field, or the Roles table. So two
#           controls that wrote the same wrong role can each get the right one.
#   WHICH   every spelling of the role counts ("IT & Security Lead", "IT/Security
#           Lead", "it and security lead"), as the role check reads them.
#   FORM    an older "Accountable / Executing: X; Y" line is rewritten as
#           "Control owner: <role>" — Bobby's model has one owner per control.
#   PROOF   every paragraph that changed must read exactly as planned, every
#           other paragraph exactly as before, and nothing may be added or
#           removed. If not, nothing is returned.
#
# Pure: bytes in, bytes out.
# =============================================================================

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Iterator, Optional

from docx import Document
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from cdi.codes import find_control_ids, is_control_id
from cdi.fields import CONTROL_FIELD_ALIASES, control_field, norm as field_norm
from doc_standards.roles import norm as role_norm

# What a use of a role is, as the role check (V07) names it.
CONTROL_OWNER = "Control owner"
DOCUMENT_OWNER, FIRST_PASS, FINAL_APPROVAL = "Document owner", "First pass approval", "Final approval"
ROLES_SECTION = "Roles section"
KINDS = (CONTROL_OWNER, DOCUMENT_OWNER, FIRST_PASS, FINAL_APPROVAL, ROLES_SECTION)

_CONTROL_ROLE_KEYS = ("control_owner", "responsibility", "accountable", "executing")
_CONTROL_LABELS = sorted({a for k in _CONTROL_ROLE_KEYS for a in CONTROL_FIELD_ALIASES[k]}, key=len, reverse=True)
# An older line that names the accountable (and executing) role: rewritten as one Control owner.
_LEGACY_LABELS = {"accountable / executing", "accountable/executing", "accountable and executing",
                  "accountable / operating role", "accountable", "accountable role"}
_COVER_LABELS = {
    DOCUMENT_OWNER: ("document owner", "owner", "domain owner"),
    FIRST_PASS: ("first pass approval", "first pass"),
    FINAL_APPROVAL: ("final approval",),
}
_ALL_COVER_LABELS = tuple(sorted({a for v in _COVER_LABELS.values() for a in v}, key=len, reverse=True))
_ROLE_TABLE_HEADERS = ("role", "roles")
# A label starts a field: at the start of the text, after a list marker, or after a sentence.
_FIELD_START = r"(?:^|(?<=^[-•*]\s)|(?<=\.\s)|(?<=;\s))"


class RoleFixError(Exception):
    """The change could not be made safely; the message says why."""


@dataclass
class RoleFix:
    data: bytes
    count: int = 0
    places: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Scope:
    """Limit a change to one use. kind is one of KINDS; where is the control ID for a Control owner."""
    kind: str
    where: str = ""


def role_pattern(role: str) -> str:
    """The role as a pattern that matches every spelling the role check treats as the same:
    any case, any spacing or punctuation between words, "&", "/" or "and" between them, and
    singular or plural words."""
    words = role_norm(role).split()
    if not words:
        raise RoleFixError("There is no role to look for.")
    # norm reads a plural as its singular, so the document may write either.
    def word(w: str) -> str:
        if w == "and":
            return r"(?:and|&|/)"
        if w.endswith("y") and len(w) > 2:
            return re.escape(w[:-1]) + r"(?:y|ies)"
        return re.escape(w) + r"(?:e?s)?"
    parts = [word(w) for w in words]
    body = r"[\W_]*".join(parts)
    return rf"(?i:(?<![\w])(?:{body})(?![\w]))"


def _flex(text: str) -> str:
    return r"\s+".join(re.escape(w) for w in text.split())


def _label_regex(labels) -> str:
    return "|".join(_flex(a) for a in sorted(labels, key=len, reverse=True))


# ── walking the document, knowing which control we are in ──────────────────

def _walk(doc) -> Iterator[tuple[object, Optional[str]]]:
    """Every paragraph and table of the body, in order, with the control it belongs to."""
    current: Optional[str] = None
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            ids = [i for i in find_control_ids(p.text[:40]) if is_control_id(i)]
            starts_with_id = bool(ids) and p.text.strip().startswith(ids[0])
            try:
                heading = (p.style is not None and (p.style.name or "").lower().startswith("heading"))
            except Exception:                    # a paragraph whose style can't be resolved
                heading = False
            if starts_with_id:
                current = ids[0]
            elif heading:
                current = None
            yield p, current
        elif tag == "tbl":
            yield Table(child, doc), current


def _cell_paragraphs(cell: _Cell) -> Iterator[Paragraph]:
    yield from cell.paragraphs
    for t in cell.tables:
        for row in t.rows:
            for c in _unique_cells(row):
                yield from _cell_paragraphs(c)


def _unique_cells(row) -> list[_Cell]:
    seen, out = set(), []
    for c in row.cells:
        if id(c._tc) not in seen:
            seen.add(id(c._tc))
            out.append(c)
    return out


def _all_paragraphs(doc) -> list[Paragraph]:
    out = []
    for block, _ in _walk(doc):
        if isinstance(block, Paragraph):
            out.append(block)
        else:
            for row in block.rows:
                for c in _unique_cells(row):
                    out.extend(_cell_paragraphs(c))
    return out


# ── editing text in runs, keeping formatting ────────────────────────────────

def _replace_span(paragraph: Paragraph, start: int, end: int, new: str) -> bool:
    """Replace characters [start, end) of the paragraph's text, keeping the formatting of the run
    the span begins in. False if the span does not lie in ordinary runs."""
    runs = paragraph.runs
    if "".join(r.text for r in runs) != paragraph.text:      # text held outside plain runs (tracked changes…)
        return False
    pos, first = 0, True
    for run in runs:
        r_start, r_end = pos, pos + len(run.text)
        pos = r_end
        if r_end <= start or r_start >= end:
            continue
        keep_before = run.text[: max(0, start - r_start)]
        keep_after = run.text[max(0, end - r_start):] if r_end > end else ""
        run.text = keep_before + (new if first else "") + keep_after
        first = False
    return not first


class _Editor:
    def __init__(self, role: str, new: str, convert_legacy: bool):
        self.role, self.new, self.convert = role, new, convert_legacy
        self.pattern = role_pattern(role)
        self.expected: dict[int, str] = {}         # id(paragraph element) → the text it must end with
        self.fix_count = 0
        self.places: list[str] = []

    def _plan(self, p: Paragraph, start: int, end: int, new: str, place: str) -> None:
        key = id(p._p)
        text = self.expected.get(key, p.text)
        if text != p.text:                          # one change per paragraph per call keeps the plan exact
            return
        if _replace_span(p, start, end, new):
            self.expected[key] = text[:start] + new + text[end:]
            self.fix_count += 1
            self.places.append(place)

    def labelled_line(self, p: Paragraph, labels, place_for) -> None:
        """A "Label: role" field inside the paragraph."""
        rx = re.compile(rf"{_FIELD_START}(?P<label>(?i:{_label_regex(labels)}))\s*:\s*"
                        rf"(?P<value>{self.pattern})(?=\s*(?:[.;,)(/]|$))")
        m = rx.search(p.text)
        if not m:
            return
        label = " ".join(m.group("label").lower().split())
        if self.convert and label in _LEGACY_LABELS:
            # "Accountable / Executing: X; Y." → "Control owner: <role>." (the whole value list goes)
            end = p.text.find(".", m.end("value"))
            end = len(p.text) if end < 0 else end
            self._plan(p, m.start("label"), end, f"Control owner: {self.new}", place_for(m.group("label").strip()))
        else:
            self._plan(p, m.start("value"), m.end("value"), self.new, place_for(m.group("label").strip()))

    def whole_cell(self, cell: _Cell, place: str) -> None:
        """A cell whose value IS the role (or the role leading an older "Role; other" value)."""
        for p in cell.paragraphs:
            m = re.match(rf"^\s*(?P<value>{self.pattern})(?=\s*(?:[.;,)(/]|$))", p.text)
            if m:
                self._plan(p, m.start("value"), m.end("value"), self.new, place)
                return


def _wants(scope: Optional[Scope], kind: str, where: str = "") -> bool:
    if scope is None:
        return True
    return scope.kind == kind and (kind != CONTROL_OWNER or not scope.where or scope.where == where)


def _cover_kind(label: str) -> Optional[str]:
    key = field_norm(label)
    for kind, labels in _COVER_LABELS.items():
        if key in labels:
            return kind
    return None


def replace_role(data: bytes, from_role: str, to_role: str, *, scope: Optional[Scope] = None,
                 convert_legacy: bool = True) -> RoleFix:
    from_role, to_role = " ".join((from_role or "").split()), " ".join((to_role or "").split())
    if not from_role or not to_role:
        raise RoleFixError("Both the role written in the document and the role to use are needed.")
    if from_role == to_role:
        raise RoleFixError("That is already the role the document names.")
    if scope is not None and scope.kind not in KINDS:
        raise RoleFixError(f"Unknown place for a role: {scope.kind}.")

    doc = Document(io.BytesIO(data))
    # Hold every paragraph element for the whole edit: lxml reuses an element's identity once
    # nothing refers to it, and the proof below compares paragraphs by identity.
    held = [p._p for p in _all_paragraphs(doc)]
    before = {id(el): Paragraph(el, doc).text for el in held}
    structure = (len(doc.paragraphs), len(doc.tables))
    ed = _Editor(from_role, to_role, convert_legacy)

    for block, control in _walk(doc):
        if isinstance(block, Paragraph):
            if control and _wants(scope, CONTROL_OWNER, control):
                ed.labelled_line(block, _CONTROL_LABELS, lambda lbl, c=control: f"{c} “{lbl}” line")
            elif not control and scope is None:
                ed.labelled_line(block, _CONTROL_LABELS, lambda lbl: f"“{lbl}” line")
            for kind, labels in _COVER_LABELS.items():
                if not control and _wants(scope, kind):
                    ed.labelled_line(block, labels, lambda lbl: f"the “{lbl}” line")
            continue
        _fix_table(block, ed, scope)

    if not ed.fix_count:
        return RoleFix(data=data)

    # ── proof: exactly the planned paragraphs changed, exactly as planned, nothing added or removed ──
    after = _all_paragraphs(doc)
    if (len(doc.paragraphs), len(doc.tables)) != structure or len(after) != len(before):
        raise RoleFixError("The change would have altered the document's structure, so it was not made.")
    for p in after:
        want = ed.expected.get(id(p._p), before.get(id(p._p)))
        if want is None or p.text != want:
            raise RoleFixError("The change would have altered more than the role's name, so it was not made.")
    out = io.BytesIO()
    doc.save(out)
    return RoleFix(data=out.getvalue(), count=ed.fix_count, places=ed.places)


def _fix_table(table: Table, ed: _Editor, scope: Optional[Scope]) -> None:
    rows = table.rows
    if not rows:
        return
    head = [c.text.strip() for c in rows[0].cells]
    # A control table: rows begin with a Control ID. Only there is an "Owner" column a role column.
    control_rows = [r for r in rows[1:] if r.cells and find_control_ids(r.cells[0].text)]
    role_columns = [i for i, h in enumerate(head)
                    if h and control_field(h, allow_keywords=True) in _CONTROL_ROLE_KEYS] if control_rows else []
    roles_table = len(head) >= 2 and field_norm(head[0]) in _ROLE_TABLE_HEADERS
    if role_columns:
        for row in control_rows:
            cid = find_control_ids(row.cells[0].text)[0]
            if _wants(scope, CONTROL_OWNER, cid):
                for i in role_columns:
                    if i < len(row.cells):
                        ed.whole_cell(row.cells[i], f"{cid} in a control table")
        return
    if roles_table:
        if _wants(scope, ROLES_SECTION):
            for row in rows[1:]:
                if row.cells:
                    ed.whole_cell(row.cells[0], "a Roles table")
        return
    for row in rows:                                     # a header (cover) table: Label | value rows
        cells = _unique_cells(row)
        if len(cells) < 2:
            continue
        kind = _cover_kind(cells[0].text)
        if kind and _wants(scope, kind):
            ed.whole_cell(cells[1], f"the “{cells[0].text.strip()}” row")
        elif field_norm(cells[0].text) in ("approval authority", "approval route"):
            # "First Pass: X. Final Approval: Y (route)" in one cell
            for k in (FIRST_PASS, FINAL_APPROVAL):
                if _wants(scope, k):
                    for p in cells[1].paragraphs:
                        ed.labelled_line(p, _COVER_LABELS[k], lambda lbl: f"the “{lbl}” part of the approval row")


# ── giving a control that names NO owner one ────────────────────────────────

def set_control_owner(data: bytes, control_id: str, role: str) -> RoleFix:
    """
    Add "Control owner: <role>" to a control that states no owner at all. `role` must already be
    the exact name of a role in Org Roles (the caller checks).

    Where it goes depends on how the document lays its controls out:
      a control TABLE (one row per control)     a "Control owner" column, created if the table has none
      a control block table (Field | Entry)     a "Control owner" row
    Any other layout is refused: the author adds the line in Word.

    The edit proves itself: re-reading the new file must give that control exactly this owner, every
    control's other fields exactly as before, and every existing paragraph exactly as before with
    only the new column or row's own text added.
    """
    from collections import Counter

    from cdi.parser import parse_document

    role = " ".join((role or "").split())
    if not role or not is_control_id(control_id or ""):
        raise RoleFixError("A control and a role are needed.")
    doc = Document(io.BytesIO(data))
    held = [p._p for p in _all_paragraphs(doc)]                 # keep elements alive for the whole edit
    before_texts = Counter(Paragraph(el, doc).text for el in held)

    done = False
    for block, current in _walk(doc):
        if not isinstance(block, Table) or not block.rows:
            continue
        if _set_in_row_table(block, control_id, role) or _set_in_block_table(block, current, control_id, role):
            done = True
            break
    if not done:
        raise RoleFixError(f"{control_id} could not be given an owner here: its layout is not a control table or a "
                           "Field | Entry block. Add “Control owner: <role>” to it in Word.")

    after_texts = Counter(p.text for p in _all_paragraphs(doc))
    before_texts.pop("", None)             # an empty owner cell is filled: blank paragraphs do not count
    after_texts.pop("", None)
    if before_texts - after_texts:
        raise RoleFixError("The change would have altered existing text, so it was not made.")
    added = after_texts - before_texts
    if any(t.strip() and t.strip() not in (role, CONTROL_OWNER) for t in added):
        raise RoleFixError("The change would have added more than the owner, so it was not made.")

    out = io.BytesIO()
    doc.save(out)
    new = out.getvalue()
    # Proof by reading it back, as OrgOS will.
    old_doc, new_doc = parse_document(data, "before.docx"), parse_document(new, "after.docx")
    old_by, new_by = {c.control_id: c for c in old_doc.controls}, {c.control_id: c for c in new_doc.controls}
    if set(old_by) != set(new_by):
        raise RoleFixError("The change would have altered which controls the document states, so it was not made.")
    got = new_by[control_id].responsibility
    if not got or role_norm(got.accountable or "") != role_norm(role):
        raise RoleFixError(f"After the change {control_id} still would not read as owned by “{role}”, so it was not made.")
    same = ("requirement", "trigger", "risk", "evidence_as_written", "failure_route", "exception_route", "mapping_as_written")
    for cid, c in old_by.items():
        for attr in same:
            if getattr(c, attr, None) != getattr(new_by[cid], attr, None):
                raise RoleFixError(f"The change would have altered {cid}'s {attr}, so it was not made.")
        if cid != control_id and (c.responsibility and c.responsibility.accountable) != \
                (new_by[cid].responsibility and new_by[cid].responsibility.accountable):
            raise RoleFixError(f"The change would have altered {cid}'s owner, so it was not made.")
    return RoleFix(data=new, count=1, places=[f"{control_id} Control owner"])


def _owner_column(head: list[str]) -> Optional[int]:
    return next((i for i, h in enumerate(head) if h and control_field(h, allow_keywords=True) == "control_owner"), None)


def _set_in_row_table(table: Table, control_id: str, role: str) -> bool:
    rows = table.rows
    head = [c.text.strip() for c in rows[0].cells]
    if not head or field_norm(head[0]) not in {"id", "control id", "ref", "control ref", "control", "id and requirement"}:
        return False
    row = next((r for r in rows[1:] if r.cells and find_control_ids(r.cells[0].text)[:1] == [control_id]), None)
    if row is None:
        return False
    col = _owner_column(head)
    if col is None:
        if any(control_field(h, allow_keywords=True) in _CONTROL_ROLE_KEYS for h in head if h):
            return False                      # an Accountable / Executing column exists: that is replace_role's job
        width = table.rows[0].cells[-1].width
        table.add_column(width if width else 914400)
        col = len(table.columns) - 1
        rows[0].cells[col].text = CONTROL_OWNER
        # the header's formatting follows its neighbour
        _copy_run_format(rows[0].cells[col - 1], rows[0].cells[col])
    cell = row.cells[col]
    if cell.text.strip():
        return False
    cell.text = role
    if col > 0:
        _copy_run_format(row.cells[col - 1], cell)
    return True


def _set_in_block_table(table: Table, current: Optional[str], control_id: str, role: str) -> bool:
    import copy
    rows = table.rows
    if current != control_id or not rows or len(rows[0].cells) != 2:
        return False
    if field_norm(rows[0].cells[0].text) != "field":
        return False
    if any(control_field(r.cells[0].text) in ("control_owner", "accountable", "responsibility") for r in rows):
        return False
    new_tr = copy.deepcopy(rows[-1]._tr)
    rows[-1]._tr.addnext(new_tr)
    new_row = table.rows[len(rows)]
    new_row.cells[0].text = CONTROL_OWNER
    new_row.cells[1].text = role
    return True


def _copy_run_format(src: _Cell, dst: _Cell) -> None:
    """Give the first run of `dst` the font of the first run of `src` (size, bold, name)."""
    try:
        s = next(r for p in src.paragraphs for r in p.runs)
        d = next(r for p in dst.paragraphs for r in p.runs)
        d.font.size, d.font.name, d.font.bold = s.font.size, s.font.name, s.font.bold
    except StopIteration:
        pass
