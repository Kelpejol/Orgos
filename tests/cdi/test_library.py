# =============================================================================
# tests/cdi/test_library.py — what documents say together
# =============================================================================

from collections import Counter

from cdi.library import LibraryIndex
from cdi.model import FindingKind
from cdi.parser import parse_document
from tests.cdi.builders import DocBuilder, defining_standard, implementing_procedure


def parse(builder, name="t.docx"):
    return parse_document(builder.bytes(), name)


def standard_defining(*ids, code="DRG-ISMS-STD-TST"):
    b = DocBuilder()
    b.control_block(title="S", code=code, owner="CTO", layer="Layer 3")
    for cid in ids:
        b.control(cid, "Control", requirement="MUST.", trigger="Issue.",
                  responsibility="CTO.", evidence="REC-0001 Log.")
    return parse(b)


def test_a_procedure_resolves_against_the_standard_that_defines_its_controls():
    lib = LibraryIndex([standard_defining("TST-01", "TST-02"), parse(implementing_procedure())])
    assert lib.findings() == []
    doc, control = lib.definition("TST-01")
    assert doc.header.code == "DRG-ISMS-STD-TST" and control.control_id == "TST-01"
    [(impl_doc, step)] = lib.implementations("TST-01")
    assert (impl_doc.header.code, step.section_number) == ("DRG-ISMS-PRO-TST", "4.0")


def test_a_control_carried_out_but_defined_nowhere_is_reported():
    lib = LibraryIndex([parse(implementing_procedure())])
    found = Counter(f.finding.kind for f in lib.findings())
    assert found[FindingKind.IMPLEMENTS_UNDEFINED] == 2


def test_a_control_defined_twice_is_an_error_on_both_documents():
    lib = LibraryIndex([
        standard_defining("TST-01", code="DRG-ISMS-STD-AAA"),
        standard_defining("TST-01", code="DRG-ISMS-STD-BBB"),
    ])
    twice = [f for f in lib.findings() if f.finding.kind is FindingKind.DEFINED_TWICE]
    assert sorted(f.document for f in twice) == ["DRG-ISMS-STD-AAA", "DRG-ISMS-STD-BBB"]
    assert lib.definition("TST-01") is None     # contested: no single definition


def test_a_defined_control_nothing_carries_out_is_informational():
    lib = LibraryIndex([parse(defining_standard())])
    kinds = Counter(f.finding.kind for f in lib.findings())
    assert kinds == {FindingKind.DEFINED_NOT_IMPLEMENTED: 2}


def test_two_files_with_one_document_code_are_flagged_as_a_possible_old_copy():
    live = standard_defining("TST-01", code="DRG-QI-PRO-CDI")
    draft = standard_defining("TST-09", code="DRG-QI-PRO-CDI-01-26")   # legacy suffix, same document
    dupes = [f for f in LibraryIndex([live, draft]).findings()
             if f.finding.kind is FindingKind.DUPLICATE_DOCUMENT_CODE]
    assert len(dupes) == 2 and "DRG-QI-PRO-CDI" in dupes[0].finding.message
