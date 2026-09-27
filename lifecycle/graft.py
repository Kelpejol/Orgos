# =============================================================================
# lifecycle/graft.py — attach a CDT cover onto a document that has none
#
# Closes two gaps: (1) a document authored by hand can sit in Review with
# raw {{ markers }} still visible if the officer never fills in cover facts
# before it's checked/downloaded, and (2) a document written with no
# relationship to the master template at all (legacy content, or anything
# already in SharePoint) has no path onto CDT short of a full manual rebuild.
#
# graft_cover_onto_document() splices an existing document's WHOLE body
# (paragraphs + tables, in order) onto the front of a master template —
# after its cover + revision-history tables, replacing the template's own
# "[Body content begins here…]" placeholder. The result is a document with
# live {{ markers }} in its cover and the existing content, otherwise
# untouched, right after — from that point it behaves exactly like a
# document that was templated from day one (mergeable at every future
# revision via lifecycle/merge.py, same as an AI-drafted document).
#
# Scope, stated plainly rather than silently assumed:
#   • Paragraphs, runs, direct formatting (bold/italic/font overrides), and
#     tables carry over exactly.
#   • A paragraph style reference (Heading 1, List Paragraph, …) not also
#     defined in the master template degrades gracefully to default
#     formatting — python-docx/Word behaviour, not something this module
#     needs to handle specially.
#   • Inline images are carried over best-effort (the referenced image part
#     is copied into the master's package and the reference rewritten to a
#     new relationship id). Anything that fails is counted, never silently
#     dropped without saying so — see GraftResult.
#
# Pure transform over bytes — no I/O, no network, no AI. Callers fetch the
# master template (lifecycle/templates.py) and do all SharePoint I/O.
#
# Depends on: python-docx (already a dependency — no new library needed)
# =============================================================================

from __future__ import annotations

import copy
import io
from dataclasses import dataclass

from docx import Document
from docx.oxml.ns import qn

_BLIP_TAG = qn("a:blip")
_EMBED_ATTR = qn("r:embed")
_SECT_PR_TAG = qn("w:sectPr")


@dataclass(frozen=True)
class GraftResult:
    """Result of grafting a cover onto an existing document."""

    document: bytes
    images_carried: int
    images_skipped: int


def _find_sect_pr_index(body) -> int:
    """Index of the trailing <w:sectPr> (page setup) in a document's body."""
    for i, child in enumerate(body):
        if child.tag == _SECT_PR_TAG:
            return i
    return len(body)


def _copy_images(existing_doc: Document, master_doc: Document, elements: list) -> tuple[int, int]:
    """
    For every <a:blip r:embed="..."> inside `elements` (freshly copied from
    the existing document, so still pointing at ITS relationship ids), copy
    the referenced image part into master_doc's package and rewrite the
    reference to the new relationship id there. Returns (carried, skipped).
    """
    carried = skipped = 0
    for el in elements:
        for blip in el.iter(_BLIP_TAG):
            old_rid = blip.get(_EMBED_ATTR)
            if not old_rid:
                continue
            try:
                image_part = existing_doc.part.related_parts[old_rid]
                new_rid, _image = master_doc.part.get_or_add_image(io.BytesIO(image_part.blob))
                blip.set(_EMBED_ATTR, new_rid)
                carried += 1
            except Exception:
                # Leave the stale rId in place. Word shows a broken-image
                # placeholder for just this one picture — nothing else in
                # the document is affected, and the caller reports the count.
                skipped += 1
    return carried, skipped


def graft_cover_onto_document(existing_bytes: bytes, master_template_bytes: bytes) -> GraftResult:
    """
    Splice an existing document's whole body onto the front of a master
    template. See module docstring for exactly what carries over.
    """
    master_doc = Document(io.BytesIO(master_template_bytes))
    existing_doc = Document(io.BytesIO(existing_bytes))

    master_body = master_doc.element.body
    sect_idx = _find_sect_pr_index(master_body)

    # The element immediately before the trailing sectPr is the template's
    # "[Body content begins here…]" placeholder paragraph (see
    # scripts/build_cdt_master_templates.py) — drop it; the existing
    # document's own content replaces it in the same position.
    if sect_idx > 0:
        placeholder = master_body[sect_idx - 1]
        master_body.remove(placeholder)
        sect_idx -= 1

    existing_body = existing_doc.element.body
    existing_elements = [child for child in existing_body if child.tag != _SECT_PR_TAG]
    copied = [copy.deepcopy(el) for el in existing_elements]

    images_carried, images_skipped = _copy_images(existing_doc, master_doc, copied)

    for el in copied:
        master_body.insert(sect_idx, el)
        sect_idx += 1

    out = io.BytesIO()
    master_doc.save(out)
    return GraftResult(
        document=out.getvalue(),
        images_carried=images_carried,
        images_skipped=images_skipped,
    )
