# =============================================================================
# cdi/library.py — what a set of documents says together
#
# One document can't tell whether a control it carries out is defined
# anywhere, or whether another document also claims to define it. Read
# together, a library can:
#
#   DEFINED_TWICE            two documents both define BCDR-01 — one is wrong
#   IMPLEMENTS_UNDEFINED     a Procedure carries out BCDR-07, which nothing
#                            defines — the Standard is missing, or the ID is
#   DEFINED_NOT_IMPLEMENTED  a Standard defines CDI-007 and no Procedure
#                            carries it out — a gap, or intended
#   DUPLICATE_DOCUMENT_CODE  two files carry the same document code — usually
#                            a superseded or draft copy left beside the live one
#
# Pure: it takes ParsedDocuments and reads nothing else.
# =============================================================================

from __future__ import annotations

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


def _base_code(code: str) -> str:
    """A code without a legacy serial/year suffix: DRG-QI-PRO-CDI-01-26 → DRG-QI-PRO-CDI."""
    parts = code.split("-")
    while len(parts) > 4 and len(parts[-1]) == 2 and parts[-1].isdigit():
        parts.pop()
    return "-".join(parts)


def document_label(doc: ParsedDocument) -> str:
    """How a document is named in a message: its code, else its file name."""
    return doc.header.code or doc.filename


@dataclass(frozen=True)
class LibraryFinding:
    document: str        # the document the finding is raised against
    finding: Finding


@dataclass
class LibraryIndex:
    documents: list[ParsedDocument]
    defined_by: dict[str, list[ParsedDocument]] = field(default_factory=dict)
    implemented_by: dict[str, list[ParsedDocument]] = field(default_factory=dict)
    supported_by: dict[str, list[ParsedDocument]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for doc in self.documents:
            for cid in doc.defined_ids:
                self.defined_by.setdefault(cid, []).append(doc)
            target = (
                self.implemented_by if doc.role is DocumentRole.IMPLEMENTING
                else self.supported_by if doc.role is DocumentRole.SUPPORTING
                else None
            )
            if target is not None:
                for cid in doc.implemented_ids:
                    target.setdefault(cid, []).append(doc)

    # ── lookups ──────────────────────────────────────────────────────────────

    def definition(self, control_id: str) -> tuple[ParsedDocument, ControlDefinition] | None:
        """The defining document and definition — None if undefined or contested."""
        docs = self.defined_by.get(control_id, [])
        if len(docs) != 1:
            return None
        doc = docs[0]
        return doc, next(c for c in doc.controls if c.control_id == control_id)

    def implementations(self, control_id: str) -> list[tuple[ParsedDocument, ImplementationStep]]:
        """Every section, in every document, that carries out `control_id`."""
        return [
            (doc, step)
            for doc in self.implemented_by.get(control_id, [])
            for step in doc.implementations
            if control_id in step.control_ids
        ]

    # ── findings across documents ───────────────────────────────────────────

    def findings(self) -> list[LibraryFinding]:
        out: list[LibraryFinding] = []

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

        for cid, docs in sorted(self.defined_by.items()):
            if len(docs) > 1:
                names = ", ".join(document_label(d) for d in docs)
                for doc in docs:
                    out.append(LibraryFinding(document_label(doc), Finding(
                        FindingKind.DEFINED_TWICE, Severity.ERROR,
                        f"{cid} is defined by more than one document ({names}). A "
                        "control has one defining statement; one of these is wrong.",
                        Location("", cid),
                    )))

        for cid in sorted(set(self.implemented_by) | set(self.supported_by)):
            if cid in self.defined_by:
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

        for cid, docs in sorted(self.defined_by.items()):
            if cid not in self.implemented_by:
                for doc in docs:
                    out.append(LibraryFinding(document_label(doc), Finding(
                        FindingKind.DEFINED_NOT_IMPLEMENTED, Severity.INFO,
                        f"{cid} is defined but no Procedure read carries it out.",
                        Location("", cid),
                    )))
        return out
