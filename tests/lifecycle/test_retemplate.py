# =============================================================================
# tests/lifecycle/test_retemplate.py — a revision of a published copy gets a live cover back
#
# Without this, a revision that starts from the published (merged) copy has no
# markers left, so its cover would keep the old version and dates for ever.
# =============================================================================

import io

import pytest
from docx import Document

from lifecycle.graft import graft_cover_onto_document
from lifecycle.merge import merge, scan_markers
from lifecycle.retemplate import RetemplateError, restore_live_cover
from lifecycle.schemas import CdtCoverFacts, MergeContext, RevisionHistoryEntry
from scripts.build_cdt_master_templates import build_master_template

MASTER = build_master_template("Procedure")


def body_doc() -> bytes:
    d = Document()
    d.add_paragraph("1.0 Purpose")
    d.add_paragraph("This Procedure sets how backups are restored.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Role", "Duty"
    t.cell(1, 0).text, t.cell(1, 1).text = "Head of IT", "Owns restores"
    d.add_paragraph("2.0 Scope")
    out = io.BytesIO(); d.save(out); return out.getvalue()


def ctx(version: str, effective: str) -> MergeContext:
    cover = CdtCoverFacts(owner="Head of IT", version=version, effective_date=effective,
                          next_review_due="October 2027", domain="Information Security")
    return MergeContext.from_lifecycle_dict({
        "DocumentCode": "DRG-ISMS-PRO-BKP", "Title": "Backup Procedure", "DocumentType": "Procedure",
        "CDTCoverFacts": cover.to_json(),
        "RevisionHistory": RevisionHistoryEntry.list_to_json([
            RevisionHistoryEntry(version="01", date="October 2026", purpose="First issue", approved_by="CCO")]),
    })


def texts(data: bytes) -> list[str]:
    d = Document(io.BytesIO(data))
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        out += [c.text for r in t.rows for c in r.cells]
    return out


def published_copy() -> bytes:
    source = graft_cover_onto_document(body_doc(), MASTER).document
    return merge(source, ctx("01", "October 2026")).document


def test_a_published_copy_gets_its_live_cover_back_and_the_next_approval_stamps_it():
    published = published_copy()
    assert not scan_markers(published)
    restored = restore_live_cover(published, MASTER).document
    assert scan_markers(restored)                                   # live again
    stamped = merge(restored, ctx("02", "November 2026")).document
    t = texts(stamped)
    assert "02" in t and "November 2026" in t                       # the new version is on the cover
    assert "This Procedure sets how backups are restored." in t     # body kept
    assert t.count("1.0 Purpose") == 1                              # body not duplicated


def test_the_body_is_carried_exactly_once_and_unchanged():
    published = published_copy()
    restored = restore_live_cover(published, MASTER).document
    body = [x for x in texts(restored) if x in ("1.0 Purpose", "2.0 Scope", "Head of IT", "Owns restores")]
    assert body == ["1.0 Purpose", "2.0 Scope", "Head of IT", "Owns restores"]


def test_a_live_source_is_left_alone():
    source = graft_cover_onto_document(body_doc(), MASTER).document
    assert restore_live_cover(source, MASTER).document == source


def test_a_document_without_the_template_cover_is_refused():
    with pytest.raises(RetemplateError):
        restore_live_cover(body_doc(), MASTER)
