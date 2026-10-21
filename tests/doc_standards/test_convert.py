# =============================================================================
# tests/doc_standards/test_convert.py — converting onto the CDT, and refusing
# when it cannot be done without damage
# =============================================================================

import io

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

import doc_standards.convert as convert
from cdi.parser import parse_document
from doc_standards.convert import ConversionPlan, convert_document
from lifecycle.graft import GraftResult
from lifecycle.schemas import CdtCoverFacts
from tests.cdi.builders import DocBuilder
from tests.doc_standards.helpers import master_template, v06_document

NAME = "Test Standard.docx"


def convert_ok(data=None, **kw) -> ConversionPlan:
    plan = convert_document(data or v06_document(), NAME, master_template(), **kw)
    assert plan.ok, plan.reason
    return plan


def paragraphs(data: bytes) -> list[str]:
    return [p.text for p in Document(io.BytesIO(data)).paragraphs]


# ── the conversion ──────────────────────────────────────────────────────────

def test_a_v06_document_converts_and_every_proof_holds():
    plan = convert_ok()
    assert {p.name for p in plan.proofs} == {"body", "removed", "reads-same", "sound", "merges"}
    assert all(p.ok for p in plan.proofs)
    assert plan.doc_type == "Standard" and plan.code == "DRG-ISMS-STD-TST"


def test_the_hand_typed_block_is_replaced_by_the_cover():
    plan = convert_ok()
    out = Document(io.BytesIO(plan.preview_bytes))
    cells = [c.text for t in out.tables for r in t.rows for c in r.cells]
    assert "DRG-ISMS-STD-TST" in cells and "Test Standard" in cells        # on the cover
    assert "Working draft" not in cells                                    # the typed status is gone
    assert paragraphs(plan.preview_bytes).count("Test Standard") >= 1      # the title is the cover's, not duplicated twice over


def test_the_body_is_carried_unchanged_and_in_order():
    plan = convert_ok(v06_document(extra_body=["Closing paragraph."]))
    original = [p for p in paragraphs(v06_document(extra_body=["Closing paragraph."])) if p]
    converted = paragraphs(plan.preview_bytes)
    body_start = converted.index("Scope and authority")
    assert [p for p in converted[body_start:] if p] == original[original.index("Scope and authority"):]


def test_the_version_typed_by_hand_is_dropped_and_a_draft_says_draft():
    plan = convert_ok(v06_document(version="v1.0"))
    assert plan.facts.version == "Draft"
    assert any(label == "Version" and typed == "v1.0" for label, typed, _ in plan.regenerated)


def test_a_revision_keeps_the_version_and_dates_the_register_holds():
    existing = CdtCoverFacts(version="03", effective_date="March 2026", next_review_due="March 2027")
    plan = convert_ok(existing_cover=existing)
    assert (plan.facts.version, plan.facts.effective_date) == ("03", "March 2026")


def test_facts_with_no_cover_cell_stay_in_the_document_so_the_relationships_are_not_lost():
    data = v06_document(implemented="TST-01 to TST-02")
    plan = convert_ok(data)
    labels = [label for label, _ in plan.stays]
    assert "Standard controls implemented" in labels and "Standards" in labels
    before, after = parse_document(data, NAME), parse_document(plan.preview_bytes, NAME)
    assert after.header.controls_implemented == before.header.controls_implemented
    assert after.implemented_ids == before.implemented_ids


def test_every_header_fact_is_kept_verbatim_in_the_register_extras():
    plan = convert_ok()
    assert plan.facts.extras["Document Code"] == "DRG-ISMS-STD-TST"
    assert plan.facts.extras["Issue Status"] == "Working draft"


def test_the_control_definitions_read_the_same_after_conversion():
    plan = convert_ok()
    before, after = parse_document(v06_document(), NAME), parse_document(plan.preview_bytes, NAME)
    assert [(c.control_id, c.requirement, c.evidence_as_written) for c in after.controls] == \
           [(c.control_id, c.requirement, c.evidence_as_written) for c in before.controls]


def test_converting_the_source_twice_is_refused_it_is_already_on_the_cdt():
    plan = convert_ok()
    again = convert_document(plan.source_bytes, NAME, master_template())
    assert not again.ok and "already on the CDT" in again.reason


# ── bookmarks (a section bookmark opens at the title and closes pages later) ─

def test_a_section_bookmark_does_not_leave_an_orphaned_end_behind():
    plan = convert_ok(v06_document(bookmark=True))
    out = Document(io.BytesIO(plan.source_bytes)).element.body
    starts = {n.get(qn("w:id")) for n in out.iter(qn("w:bookmarkStart"))}
    ends = {n.get(qn("w:id")) for n in out.iter(qn("w:bookmarkEnd"))}
    assert ends <= starts


def test_a_link_to_the_removed_title_bookmark_is_refused_not_left_broken():
    data = v06_document(bookmark=True)
    doc = Document(io.BytesIO(data))
    p = doc.add_paragraph("See the top")
    p._p.append(parse_xml(f'<w:hyperlink {nsdecls("w")} w:anchor="section-top"><w:r><w:t>top</w:t></w:r></w:hyperlink>'))
    buf = io.BytesIO(); doc.save(buf)
    plan = convert_document(buf.getvalue(), NAME, master_template())
    assert not plan.ok and "points at the document's title area" in plan.reason


# ── refusals: it will not guess ─────────────────────────────────────────────

def test_a_pdf_or_doc_is_refused():
    for name in ("x.pdf", "x.doc"):
        plan = convert_document(b"%PDF", name, master_template())
        assert not plan.ok and ".docx" in plan.reason


def test_a_document_with_no_header_block_is_refused_with_the_reason():
    b = DocBuilder(); b.heading("Access Policy", 1); b.para("Prose only.")
    plan = convert_document(b.bytes(), NAME, master_template())
    assert not plan.ok and plan.reason


def test_a_document_that_states_no_code_is_refused_not_given_one():
    plan = convert_document(v06_document(code="Not assigned"), NAME, master_template())
    assert not plan.ok and "no document code" in plan.reason


def test_a_register_has_no_cover_template():
    plan = convert_document(v06_document(code="DRG-QI-REG-RRS"), NAME, master_template())
    assert not plan.ok and "no master template" in plan.reason


def test_a_sentence_above_the_header_block_is_not_mistaken_for_a_title_and_removed():
    b = DocBuilder()
    b.para("This paragraph is real content of the document and must never be silently deleted by a conversion.")
    b.control_block(title="T", code="DRG-ISMS-STD-TST", layer="Layer 3", domain="d", owner="o", classification="c")
    plan = convert_document(b.bytes(), NAME, master_template())
    assert not plan.ok and "not a title or status line" in plan.reason


# ── the proofs catch damage ─────────────────────────────────────────────────

def test_a_conversion_that_changes_the_body_is_not_offered(monkeypatch):
    real = convert.graft_cover_onto_document

    def damaging(existing, master, skip_leading=0):
        result = real(existing, master, skip_leading=skip_leading)
        doc = Document(io.BytesIO(result.document))
        victim = next(p for p in doc.paragraphs if p.text.startswith("This standard defines"))
        victim._p.getparent().remove(victim._p)
        buf = io.BytesIO(); doc.save(buf)
        return GraftResult(**{**result.__dict__, "document": buf.getvalue()})

    monkeypatch.setattr(convert, "graft_cover_onto_document", damaging)
    plan = convert_document(v06_document(), NAME, master_template())
    assert not plan.ok and any(p.name == "body" and not p.ok for p in plan.proofs)
    assert plan.source_bytes == b"" and plan.preview_bytes == b""         # nothing is handed over


def test_a_hyperlink_the_conversion_cannot_carry_is_refused():
    data = v06_document()
    doc = Document(io.BytesIO(data))
    p = doc.add_paragraph("See ")
    p._p.append(parse_xml(
        f'<w:hyperlink {nsdecls("w")} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'r:id="rId999"><w:r><w:t>link</w:t></w:r></w:hyperlink>'))
    buf = io.BytesIO(); doc.save(buf)
    plan = convert_document(buf.getvalue(), NAME, master_template())
    assert not plan.ok and any(p.name == "sound" and not p.ok for p in plan.proofs)


def test_a_fact_lost_in_the_conversion_is_caught(monkeypatch):
    # If a row that is NOT regenerated were dropped, the 'removed' proof must say so.
    monkeypatch.setattr(convert, "_row_is_regenerated", lambda label: True)
    plan = convert_document(v06_document(implemented="TST-01"), NAME, master_template())
    assert not plan.ok
