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


# ── which document defines a control ────────────────────────────────────────

def procedure_restating(rows, code="DRG-ISMS-PRO-ASA"):
    """A procedure with a 'Control ID | Requirement' table restating controls."""
    b = DocBuilder()
    b.control_block(title="P", code=code, owner="CTO", layer="Layer 4")
    b.table([["Control ID", "Requirement", "Risk statement"], *rows])
    return parse(b)


def standard_table(rows, code="DRG-ISMS-STD-APPSEC"):
    b = DocBuilder()
    b.control_block(title="S", code=code, owner="CTO", layer="Layer 3")
    b.table([["ID", "Mandatory control requirement", "Required evidence", "Risk statement"], *rows])
    return parse(b)


APPSEC_01 = "Applications in scope MUST be onboarded to an approved assessment capability."


def test_a_standard_outranks_a_procedure_restating_its_control():
    std = standard_table([["APPSEC-01", APPSEC_01, "REC-0700", "Missed weakness."]])
    pro = procedure_restating([["APPSEC-01", APPSEC_01, "Missed weakness."]])
    lib = LibraryIndex([std, pro])
    doc, _ = lib.definition("APPSEC-01")
    assert doc.header.code == "DRG-ISMS-STD-APPSEC"
    assert [s.document.header.code for s in lib.restatements("APPSEC-01")] == ["DRG-ISMS-PRO-ASA"]
    assert lib.findings() == []          # a faithful restatement is the procedure carrying it out


def test_a_near_copy_that_was_edited_is_reported_with_the_words_that_changed():
    std = standard_table([["APPSEC-01", APPSEC_01, "REC-0700", "Missed weakness."]])
    edited = APPSEC_01.replace("MUST be onboarded", "should be onboarded")
    pro = procedure_restating([["APPSEC-01", edited, "Missed weakness."]])
    [f] = LibraryIndex([std, pro]).findings()
    assert f.finding.kind is FindingKind.RESTATEMENT_DIFFERS
    assert "“MUST” → “should”" in f.finding.message and f.document == "DRG-ISMS-PRO-ASA"


def test_a_summary_in_the_procedures_own_words_is_not_a_conflict():
    std = standard_table([["APPSEC-01", APPSEC_01, "REC-0700", "Missed weakness."]])
    pro = procedure_restating([["APPSEC-01", "Every app is onboarded within a day.", "Missed."]])
    assert LibraryIndex([std, pro]).findings() == []


def test_with_no_standard_the_fuller_procedure_statement_defines():
    full = DocBuilder()
    full.control_block(title="Defining", code="DRG-QI-PRO-CIP", owner="CCO", layer="Layer 4")
    full.control("CIP-001", "Context review", requirement="The context MUST be reviewed.",
                 trigger="Annual.", responsibility="Compliance Executive.", evidence="REC-0640.",
                 risk="Context drifts.", failure_route="Gap raised.", exception_route="None.",
                 mapping="ISO 9001 4.1.")
    restating = procedure_restating([["CIP-001", "The context MUST be reviewed.", "Context drifts."]],
                                    code="DRG-QI-PRO-CIX")
    lib = LibraryIndex([parse(full), restating])
    assert lib.definition("CIP-001")[0].header.code == "DRG-QI-PRO-CIP"
    # A defining procedure carries out its own controls: nothing is "defined, not carried out".
    assert FindingKind.DEFINED_NOT_IMPLEMENTED not in Counter(f.finding.kind for f in lib.findings())


def test_two_equal_procedure_statements_with_no_standard_ask_which_defines():
    a = procedure_restating([["CIP-001", "The context MUST be reviewed.", "Drift."]], code="DRG-QI-PRO-AAA")
    b = procedure_restating([["CIP-001", "The context MUST be reviewed.", "Drift."]], code="DRG-QI-PRO-BBB")
    twice = [f for f in LibraryIndex([a, b]).findings() if f.finding.kind is FindingKind.DEFINED_TWICE]
    assert len(twice) == 2
    assert all(f.finding.severity.value == "warning" for f in twice)   # a question, not an error
