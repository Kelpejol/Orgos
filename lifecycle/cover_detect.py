# =============================================================================
# lifecycle/cover_detect.py — does this document already carry a CDT cover?
#
# "Attach CDT cover" was offered on every document, including ones that already
# had a cover, so the officer had to know the answer before clicking. This
# decides it from the file itself.
#
# Two ways a document can have a cover, and both count:
#   1. LIVE  — it still carries {{ markers }}, so it is on the template and its
#              cover facts merge in on every view and at approval.
#   2. MERGED — the markers have been rendered away (a published or grafted
#              copy). No markers, but the cover TABLE is still there, so
#              grafting a second cover onto the front would duplicate it.
#
# Pure: bytes in, verdict out. No I/O, no network, so the rules are testable
# without SharePoint.
# =============================================================================

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

from docx import Document

from lifecycle.merge import scan_markers

logger = logging.getLogger(__name__)

# The 13 fixed cover rows built by scripts/build_cdt_master_templates.py, as
# they appear in the label column. Matching is normalised, so spacing, case and
# a trailing colon do not matter.
COVER_LABELS: tuple[str, ...] = (
    "document title", "document code", "document type / layer", "domain",
    "parent document", "classification", "distribution", "owner",
    "first pass approval", "final approval", "version", "effective date",
    "next review due",
)

# Wording that drifted in documents written before the template existed. Each
# maps onto the canonical label above so an older hand-built cover still counts.
_LABEL_ALIASES: dict[str, str] = {
    "title": "document title",
    "document reference": "document code",
    "document ref": "document code",
    "reference": "document code",
    "code": "document code",
    "document type": "document type / layer",
    "type / layer": "document type / layer",
    "type": "document type / layer",
    "parent": "parent document",
    "security classification": "classification",
    "document classification": "classification",
    "document owner": "owner",
    "process owner": "owner",
    "policy owner": "owner",
    "approved by": "final approval",
    "final approver": "final approval",
    "reviewed by": "first pass approval",
    "first pass approver": "first pass approval",
    "version no": "version",
    "version number": "version",
    "revision": "version",
    "issue date": "effective date",
    "date effective": "effective date",
    "next review": "next review due",
    "review due": "next review due",
    "next review date": "next review due",
}

# How many distinct cover rows one table must carry before it is a cover rather
# than an ordinary two-column table that happens to say "Owner". Four is the
# point where a coincidence stops being plausible.
_MIN_COVER_ROWS = 4

_REVISION_HEADERS = {"version", "date", "purpose of change", "approved by",
                     "author", "change", "purpose"}

_WS_RE = re.compile(r"\s+")


def _norm_label(text: str) -> str:
    """Canonical form of a label cell: lowercased, collapsed, colon stripped."""
    cleaned = _WS_RE.sub(" ", (text or "").strip()).strip(" :. ").lower()
    return _LABEL_ALIASES.get(cleaned, cleaned)


@dataclass
class CoverDetection:
    """What was found, and why — the reason is shown to the officer."""

    has_cover: bool = False
    # "markers" | "cover table" | "none" | "unreadable"
    source: str = "none"
    matched_labels: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    has_revision_history: bool = False
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "has_cover": self.has_cover,
            "source": self.source,
            "matched_labels": self.matched_labels,
            "marker_count": len(self.markers),
            "has_revision_history": self.has_revision_history,
            "detail": self.detail,
        }


def _table_label_matches(table) -> list[str]:
    """The canonical cover labels this table's first column carries, in order."""
    found: list[str] = []
    for row in table.rows:
        cells = row.cells
        if len(cells) < 2:
            continue
        label = _norm_label(cells[0].text)
        if label in COVER_LABELS and label not in found:
            found.append(label)
    return found


def _is_revision_history(table) -> bool:
    if not table.rows:
        return False
    headers = {_norm_label(c.text) for c in table.rows[0].cells}
    return len(headers & _REVISION_HEADERS) >= 3


def detect_cover(file_bytes: bytes, filename: str = "") -> CoverDetection:
    """
    Decide whether `file_bytes` already carries a CDT cover.

    A non-.docx (a PDF, typically) cannot be inspected for tables, and must not
    be grafted onto anyway, so it comes back `unreadable` rather than `none` —
    "I could not tell" is not the same answer as "there is no cover".
    """
    if filename and not filename.lower().endswith(".docx"):
        return CoverDetection(
            source="unreadable",
            detail=f"A {filename.rsplit('.', 1)[-1].upper()} cannot be inspected or "
                   "templated — upload the editable Word document.",
        )

    try:
        markers = scan_markers(file_bytes)
    except Exception as exc:
        logger.warning(f"Cover detection could not read the file: {exc}")
        return CoverDetection(source="unreadable",
                              detail="This file could not be read as a Word document.")

    if markers:
        return CoverDetection(
            has_cover=True, source="markers", markers=markers,
            detail=f"On the CDT template — {len(markers)} live marker(s); its cover "
                   "facts merge in whenever the document is viewed or approved.",
        )

    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as exc:
        logger.warning(f"Cover detection could not open the document: {exc}")
        return CoverDetection(source="unreadable",
                              detail="This file could not be read as a Word document.")

    best: list[str] = []
    has_history = False
    for table in doc.tables:
        matches = _table_label_matches(table)
        if len(matches) > len(best):
            best = matches
        if not has_history and _is_revision_history(table):
            has_history = True

    if len(best) >= _MIN_COVER_ROWS:
        return CoverDetection(
            has_cover=True, source="cover table", matched_labels=best,
            has_revision_history=has_history,
            detail=f"A cover table is already present ({len(best)} of "
                   f"{len(COVER_LABELS)} control facts found), with its markers "
                   "already filled in. Attaching another would duplicate it.",
        )

    return CoverDetection(
        source="none", matched_labels=best, has_revision_history=has_history,
        detail="No CDT cover found — attaching one adds the control-facts and "
               "revision-history tables to the front of this document.",
    )
