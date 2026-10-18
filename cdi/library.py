# =============================================================================
# cdi/library.py — what a set of documents says together
#
# Which document DEFINES a control cannot be decided one document at a time.
# Bobby's rule, which the library bears out:
#
#   - The Standard is the defining source for its domain's controls.
#   - Where a family has no Standard, the defining Procedure carries them.
#   - Procedures beneath a Standard restate its controls under the same IDs
#     to carry them out; a restatement is not another control.
#
# So every statement of a control is collected, and the one from the most
# authoritative document defines it.
#
# Restatements come in two kinds, and the library splits cleanly between them
# (measured across all 123 documents: nothing between 60% and 80% alike):
#   - a SUMMARY in the procedure's own words (Access Control) — normal, and
#     not a conflict, so not reported;
#   - a NEAR-COPY of the Standard's wording (Vulnerability Management, IT).
#     A near-copy that is not identical has been edited on one side only —
#     "shall log" became "logs", "issued" was dropped — and is reported with
#     the words that changed.
#
# Findings:
#   DEFINED_TWICE            two equally authoritative documents both define it
#   RESTATEMENT_DIFFERS      a procedure's wording has drifted from its Standard
#   IMPLEMENTS_UNDEFINED     carried out, but no document read defines it
#   DEFINED_NOT_IMPLEMENTED  defined, but nothing carries it out
#   DUPLICATE_DOCUMENT_CODE  two files share one code — usually an old copy
#
# Pure: it takes ParsedDocuments and reads nothing else.
# =============================================================================

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from cdi.model import (
    ControlDefinition,
    DocumentRole,
    Finding,
    FindingKind,
    ImplementationStep,
    Location,
    ParsedDocument,
    Severity,
)

# Lower defines over higher. A Standard defines; a Procedure or Specification
# defines only where no Standard does; supporting documents and Policies only
# where nothing better states the control at all.
_AUTHORITY = {"STD": 0, "PRO": 1, "SPEC": 1, "SOP": 1, "": 1, "POL": 3}
_SUPPORTING_RANK = 2


def _authority(doc: ParsedDocument) -> int:
    return _AUTHORITY.get(doc.header.type_code, _SUPPORTING_RANK)


def _base_code(code: str) -> str:
    """A code without a legacy serial/year suffix: DRG-QI-PRO-CDI-01-26 → DRG-QI-PRO-CDI."""
    parts = code.split("-")
    while len(parts) > 4 and len(parts[-1]) == 2 and parts[-1].isdigit():
        parts.pop()
    return "-".join(parts)


def _comparable(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


# A restatement at least this alike is a copy of the definition; below it, a
# summary. The library shows a clear gap either side of this line.
_NEAR_COPY = 0.80


def _changed_words(defined: str, restated: str, limit: int = 4) -> str:
    """The edits that turn the definition into the restatement, in words."""
    a, b = defined.split(), restated.split()
    edits = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if op == "replace":
            edits.append(f"“{old}” → “{new}”")
        elif op == "delete":
            edits.append(f"“{old}” dropped")
        elif op == "insert":
            edits.append(f"“{new}” added")
    more = f" and {len(edits) - limit} more" if len(edits) > limit else ""
    return "; ".join(edits[:limit]) + more


def document_label(doc: ParsedDocument) -> str:
    """How a document is named in a message: its code, else its file name."""
    return doc.header.code or doc.filename


@dataclass(frozen=True)
class Statement:
    """One document's statement of one control."""

    document: ParsedDocument
    control: ControlDefinition

    @property
    def fields_stated(self) -> int:
        return 8 - len(self.control.missing_fields)


@dataclass(frozen=True)
class LibraryFinding:
    document: str        # the document the finding is raised against
    finding: Finding


@dataclass
class LibraryIndex:
    documents: list[ParsedDocument]
    stated_by: dict[str, list[Statement]] = field(default_factory=dict)
    implemented_by: dict[str, list[ParsedDocument]] = field(default_factory=dict)
    supported_by: dict[str, list[ParsedDocument]] = field(default_factory=dict)
    _definers: dict[str, Statement | None] = field(default_factory=dict)
    _contested: dict[str, list[Statement]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for doc in self.documents:
            for control in doc.controls:
                self.stated_by.setdefault(control.control_id, []).append(Statement(doc, control))
            if doc.role is DocumentRole.IMPLEMENTING:
                # A procedure carries out what it cites AND what it states:
                # a restated control is one it implements, and a defining
                # procedure implements its own.
                for cid in dict.fromkeys(doc.implemented_ids + doc.defined_ids):
                    self.implemented_by.setdefault(cid, []).append(doc)
            elif doc.role is DocumentRole.SUPPORTING:
                for cid in dict.fromkeys(doc.implemented_ids + doc.defined_ids):
                    self.supported_by.setdefault(cid, []).append(doc)

        for cid, statements in self.stated_by.items():
            # Most authoritative document first; among equals, the fuller
            # statement — a defining block states all eight fields, a
            # restating table three or four.
            ranked = sorted(statements, key=lambda s: (_authority(s.document), -s.fields_stated))
            best = ranked[0]
            tied = [s for s in ranked
                    if (_authority(s.document), s.fields_stated)
                    == (_authority(best.document), best.fields_stated)]
            if len(tied) > 1:
                self._contested[cid] = tied
                self._definers[cid] = None
            else:
                self._definers[cid] = best

    # ── lookups ──────────────────────────────────────────────────────────────

    def definition(self, control_id: str) -> tuple[ParsedDocument, ControlDefinition] | None:
        """The defining document and its statement — None if undefined or contested."""
        s = self._definers.get(control_id)
        return (s.document, s.control) if s else None

    def restatements(self, control_id: str) -> list[Statement]:
        """Statements of a control other than its definition."""
        definer = self._definers.get(control_id)
        return [s for s in self.stated_by.get(control_id, []) if s is not definer]

    def implementations(self, control_id: str) -> list[tuple[ParsedDocument, ImplementationStep]]:
        """Every section, in every document, that carries out `control_id`."""
        return [
            (doc, step)
            for doc in self.implemented_by.get(control_id, [])
            for step in doc.implementations
            if control_id in step.control_ids
        ]

    @property
    def defined_ids(self) -> list[str]:
        """Control IDs with exactly one defining statement, sorted."""
        return sorted(cid for cid, s in self._definers.items() if s)

    @property
    def contested_ids(self) -> list[str]:
        """Control IDs two equally authoritative documents both define."""
        return sorted(self._contested)

    @property
    def defining_documents(self) -> list[ParsedDocument]:
        """Documents that define at least one control."""
        docs = {id(s.document): s.document for s in self._definers.values() if s}
        return list(docs.values())

    # ── findings across documents ───────────────────────────────────────────

    def findings(self) -> list[LibraryFinding]:
        out: list[LibraryFinding] = []
        out += self._duplicate_codes()
        out += self._contested_findings()
        out += self._drift()

        for cid in sorted(set(self.implemented_by) | set(self.supported_by)):
            if cid in self.stated_by:
                continue
            for doc in self.implemented_by.get(cid, []) + self.supported_by.get(cid, []):
                verb = "carries out" if doc.role is DocumentRole.IMPLEMENTING else "supports"
                out.append(LibraryFinding(document_label(doc), Finding(
                    FindingKind.IMPLEMENTS_UNDEFINED, Severity.WARNING,
                    f"{document_label(doc)} {verb} {cid}, but no document read defines "
                    "it. Its defining document may not be in the library, or the ID "
                    "is wrong.",
                    Location("", cid),
                )))

        for cid, definer in sorted(self._definers.items()):
            if definer and cid not in self.implemented_by:
                out.append(LibraryFinding(document_label(definer.document), Finding(
                    FindingKind.DEFINED_NOT_IMPLEMENTED, Severity.INFO,
                    f"{cid} is defined but no Procedure read carries it out.",
                    Location("", cid),
                )))
        return out

    def _duplicate_codes(self) -> list[LibraryFinding]:
        out = []
        by_code: dict[str, list[ParsedDocument]] = {}
        for doc in self.documents:
            if doc.header.code:
                by_code.setdefault(_base_code(doc.header.code), []).append(doc)
        for code, docs in sorted(by_code.items()):
            if len(docs) > 1:
                files = "; ".join(d.filename for d in docs)
                for doc in docs:
                    out.append(LibraryFinding(doc.filename, Finding(
                        FindingKind.DUPLICATE_DOCUMENT_CODE, Severity.WARNING,
                        f"{code} appears in {len(docs)} files ({files}). One is usually "
                        "a superseded or draft copy that should not be read as current.",
                        Location("", code),
                    )))
        return out

    def _contested_findings(self) -> list[LibraryFinding]:
        out = []
        for cid, tied in sorted(self._contested.items()):
            names = ", ".join(document_label(s.document) for s in tied)
            standards = all(s.document.header.type_code == "STD" for s in tied)
            for s in tied:
                out.append(LibraryFinding(document_label(s.document), Finding(
                    FindingKind.DEFINED_TWICE,
                    Severity.ERROR if standards else Severity.WARNING,
                    (f"{cid} is defined by more than one Standard ({names}). A control has "
                     "one defining statement; one of these is wrong.")
                    if standards else
                    (f"{cid} is stated equally by {names}, and no Standard defines it. "
                     "Confirm which document defines it."),
                    Location("", cid),
                )))
        return out

    def _drift(self) -> list[LibraryFinding]:
        """Near-copies of a definition that have been edited on one side."""
        out = []
        for cid, definer in sorted(self._definers.items()):
            if not definer or not definer.control.requirement:
                continue
            defined = _comparable(definer.control.requirement)
            for s in self.restatements(cid):
                restated = _comparable(s.control.requirement)
                if not restated or restated == defined:
                    continue
                if difflib.SequenceMatcher(None, defined, restated).ratio() < _NEAR_COPY:
                    continue   # a summary in the procedure's own words
                out.append(LibraryFinding(document_label(s.document), Finding(
                    FindingKind.RESTATEMENT_DIFFERS, Severity.WARNING,
                    f"{document_label(s.document)} copies {cid} from "
                    f"{document_label(definer.document)} but the wording has changed: "
                    f"{_changed_words(definer.control.requirement, s.control.requirement)}. "
                    "The defining document prevails; bring the copy into line.",
                    s.control.location,
                )))
        return out
