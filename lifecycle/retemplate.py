# =============================================================================
# lifecycle/retemplate.py — put a live cover back on a published (merged) copy
#
# A document on the CDT template keeps {{ markers }} in its cover, and every
# approval stamps the cover from the Register (lifecycle/merge.py). The PUBLISHED
# copy has those markers rendered away. A revision that starts from the published
# copy therefore has nothing left to stamp: version 02 would still show "01" and
# the old dates on its cover.
#
# restore_live_cover() fixes that without touching the content:
#   1. find the template's front matter at the top of the merged copy — its
#      heading lines, the cover table and the revision-history table, exactly as
#      the master template lays them out;
#   2. graft the rest of the document (the body, unchanged) back onto the master
#      template, whose cover carries live markers again;
#   3. PROVE it: the body that follows the new cover reads exactly as the body
#      that followed the old one. If not, nothing is returned.
#
# The cover's VALUES are not lost: the Register holds them (CDTCoverFacts and
# RevisionHistory) and they merge back in at every view and at approval.
#
# Pure: bytes in, bytes out.
# =============================================================================

from __future__ import annotations

import io
from dataclasses import dataclass

from docx import Document
from docx.oxml.ns import qn

from lifecycle.cover_detect import _is_revision_history, _MIN_COVER_ROWS, _table_label_matches
from lifecycle.graft import graft_cover_onto_document
from lifecycle.merge import scan_markers

_P, _TBL, _SECT = qn("w:p"), qn("w:tbl"), qn("w:sectPr")
_T = qn("w:t")
# The master template puts six short paragraphs, the cover, two more and the history
# table before the body. A little slack for a document that gained an empty line.
_MAX_FRONT = 14


class RetemplateError(Exception):
    """The live cover could not be restored safely; the message says why."""


@dataclass(frozen=True)
class RetemplateResult:
    document: bytes
    removed: int            # front-matter elements replaced by the template's own


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(_T))


def _elements(doc) -> list:
    return [c for c in doc.element.body if c.tag != _SECT]


def _front_matter_end(doc) -> int:
    """How many leading body elements are the template's front matter: up to and including
    the revision-history table, plus the one empty paragraph the template puts after it.
    Raises RetemplateError if the top of the document is not that shape."""
    from docx.table import Table

    els = _elements(doc)
    cover_at = history_at = None
    for i, el in enumerate(els[:_MAX_FRONT]):
        if el.tag == _TBL:
            table = Table(el, doc)
            if cover_at is None and len(_table_label_matches(table)) >= _MIN_COVER_ROWS:
                cover_at = i
            elif cover_at is not None and _is_revision_history(table):
                history_at = i
                break
            else:
                raise RetemplateError("A table that is not the cover or the revision history sits in the cover area.")
        elif el.tag != _P:
            raise RetemplateError("Something other than text sits in the cover area.")
    if cover_at is None or history_at is None:
        raise RetemplateError("The document does not open with the template's cover and revision history.")
    end = history_at + 1
    if end < len(els) and els[end].tag == _P and not _text(els[end]).strip():
        end += 1
    return end


def restore_live_cover(merged_bytes: bytes, master_bytes: bytes) -> RetemplateResult:
    if scan_markers(merged_bytes):
        return RetemplateResult(merged_bytes, 0)          # already live: nothing to do
    original = Document(io.BytesIO(merged_bytes))
    end = _front_matter_end(original)
    graft = graft_cover_onto_document(merged_bytes, master_bytes, skip_leading=end)
    if graft.unresolved:
        raise RetemplateError("Restoring the cover would leave broken links: " + "; ".join(graft.unresolved))
    if not scan_markers(graft.document):
        raise RetemplateError("The master template has no live cover markers.")

    # ── proof: the body after the cover is exactly the body that was there ──
    result = Document(io.BytesIO(graft.document))
    before = [(el.tag, _text(el)) for el in _elements(original)[end:]]
    after = [(el.tag, _text(el)) for el in _elements(result)[graft.cover_elements:]]
    if before != after:
        raise RetemplateError("Restoring the cover would have changed the document's body, so it was not done.")
    return RetemplateResult(graft.document, end)
