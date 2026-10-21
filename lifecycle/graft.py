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
#   • A style the master template does not define (a table style, a list
#     paragraph style…) is COPIED across with its basedOn chain, so a table
#     keeps its borders and a list its spacing instead of degrading to
#     defaults.
#   • Automatic numbering and bullets carry over: each numbering definition a
#     paragraph (or a copied style) uses is copied into the template's
#     numbering part under a new id, and the references are rewritten. Without
#     this a numbered procedure silently loses its numbers.
#   • Anything else that points at a relationship of the ORIGINAL document
#     (a hyperlink, an embedded object) cannot be carried by this module. It
#     is reported in GraftResult.unresolved, never left silently dangling.
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
    styles_carried: int = 0
    numbering_carried: int = 0
    # Relationship references in the carried content that resolve to nothing in
    # the result (e.g. a hyperlink) — each a short description. Empty = sound.
    unresolved: tuple = ()
    # Elements of the original skipped from the front (see skip_leading).
    skipped_leading: int = 0
    # Elements the template put before the carried body, so a caller can
    # compare "the body" in the result with the original element by element.
    cover_elements: int = 0


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


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NUM_ID = qn("w:numId")
_STYLE_VAL_TAGS = (qn("w:pStyle"), qn("w:rStyle"), qn("w:tblStyle"))
_VAL = qn("w:val")


def _style_elements(doc) -> dict:
    """style id → its <w:style> element."""
    return {s.style_id: s.element for s in doc.styles}


def _copy_styles(existing_doc: Document, master_doc: Document, elements: list) -> tuple[int, list]:
    """
    Copy into the master every style the carried elements use that it lacks,
    with whatever those styles are based on. Returns (count, copied elements).
    """
    source = _style_elements(existing_doc)
    master_styles = master_doc.styles.element
    have = set(_style_elements(master_doc))
    used: list[str] = []
    for el in elements:
        for node in el.iter(*_STYLE_VAL_TAGS):
            sid = node.get(_VAL)
            if sid and sid not in used:
                used.append(sid)

    copied = []
    queue = [sid for sid in used if sid not in have]
    while queue:
        sid = queue.pop(0)
        if sid in have or sid not in source:
            continue
        clone = copy.deepcopy(source[sid])
        master_styles.append(clone)
        have.add(sid)
        copied.append(clone)
        for ref in ("w:basedOn", "w:next", "w:link"):
            node = clone.find(qn(ref))
            if node is not None and node.get(_VAL) not in have:
                queue.append(node.get(_VAL))
    return len(copied), copied


def _copy_numbering(existing_doc: Document, master_doc: Document, elements: list) -> int:
    """
    Carry the numbering definitions `elements` use (directly, or through
    styles just copied into them) into the master's numbering part under new
    ids, rewriting the references. Returns how many definitions were carried.
    """
    used = {n.get(_VAL) for el in elements for n in el.iter(_NUM_ID) if n.get(_VAL)}
    if not used:
        return 0
    try:
        source = existing_doc.part.numbering_part.element
    except Exception:
        return 0            # nothing to carry; the references stay as they are
    target = master_doc.part.numbering_part.element

    def ids(root, tag, attr):
        return [int(x.get(attr)) for x in root.iter(qn(tag)) if (x.get(attr) or "").isdigit()]

    next_abstract = max(ids(target, "w:abstractNum", "w:abstractNumId"), default=-1) + 1
    next_num = max(ids(target, "w:num", "w:numId"), default=0) + 1
    abstract_by_id = {a.get(qn("w:abstractNumId")): a for a in source.iter(qn("w:abstractNum"))}
    num_by_id = {n.get(qn("w:numId")): n for n in source.iter(qn("w:num"))}
    first_num = next(iter(target.iter(qn("w:num"))), None)

    remap: dict[str, str] = {}
    abstract_map: dict[str, str] = {}
    for old in sorted(used):
        num = num_by_id.get(old)
        if num is None:
            continue
        old_abs = num.find(qn("w:abstractNumId")).get(_VAL)
        if old_abs not in abstract_map:
            abstract = abstract_by_id.get(old_abs)
            if abstract is None:
                continue
            clone = copy.deepcopy(abstract)
            clone.set(qn("w:abstractNumId"), str(next_abstract))
            for tag in ("w:nsid", "w:tmpl"):          # a copy must not claim the original's identity
                for node in clone.findall(qn(tag)):
                    clone.remove(node)
            if first_num is not None:
                first_num.addprevious(clone)           # abstractNum elements come before num elements
            else:
                target.append(clone)
            abstract_map[old_abs] = str(next_abstract)
            next_abstract += 1
        new_num = copy.deepcopy(num)
        new_num.set(qn("w:numId"), str(next_num))
        new_num.find(qn("w:abstractNumId")).set(_VAL, abstract_map[old_abs])
        target.append(new_num)
        remap[old] = str(next_num)
        next_num += 1

    for el in elements:
        for node in el.iter(_NUM_ID):
            if node.get(_VAL) in remap:
                node.set(_VAL, remap[node.get(_VAL)])
    return len(remap)


def unresolved_relationships(body_elements: list, document) -> tuple:
    """
    Every relationship reference (r:id, r:embed, r:link …) in `body_elements`
    that does not exist among `document`'s own relationships — content that
    would show as broken, or make Word report the file as corrupt.
    """
    rels = set(document.part.rels.keys())
    bad = []
    for el in body_elements:
        for node in el.iter():
            for attr, value in node.attrib.items():
                if attr.startswith("{" + _R_NS + "}") and value not in rels:
                    bad.append(f"{node.tag.split('}')[-1]} → {value}")
    return tuple(dict.fromkeys(bad))


def graft_cover_onto_document(existing_bytes: bytes, master_template_bytes: bytes,
                              skip_leading: int = 0) -> GraftResult:
    """
    Splice an existing document's body onto the front of a master template.
    See module docstring for exactly what carries over.

    `skip_leading` leaves out that many elements from the top of the original's
    body — the document's own hand-typed header block, which the template's
    cover replaces. Zero (the default) carries everything, as before.
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
    existing_elements = [child for child in existing_body if child.tag != _SECT_PR_TAG][skip_leading:]
    copied = [copy.deepcopy(el) for el in existing_elements]

    images_carried, images_skipped = _copy_images(existing_doc, master_doc, copied)
    styles_carried, style_clones = _copy_styles(existing_doc, master_doc, copied)
    # Numbering is resolved after styles: a copied style may carry its own numPr.
    numbering_carried = _copy_numbering(existing_doc, master_doc, copied + style_clones)

    cover_elements = sect_idx
    for el in copied:
        master_body.insert(sect_idx, el)
        sect_idx += 1

    out = io.BytesIO()
    master_doc.save(out)
    return GraftResult(
        document=out.getvalue(),
        images_carried=images_carried,
        images_skipped=images_skipped,
        styles_carried=styles_carried,
        numbering_carried=numbering_carried,
        unresolved=unresolved_relationships(copied, master_doc),
        skipped_leading=skip_leading,
        cover_elements=cover_elements,
    )
