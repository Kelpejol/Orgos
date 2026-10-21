# =============================================================================
# tests/lifecycle/test_intake_classification.py — intake gives documents the
# right type
#
# 'form' matched 'Information', so every document in the Control of Documented
# Information folder was filed as a Form. The document's own code decides now;
# path words are a fallback, and only whole words count.
# =============================================================================

import pytest

from scripts.intake_sharepoint_to_lifecycle import (
    classify_for_lifecycle,
    document_type_from_code,
)

CDI_FOLDER = "Control of Documented Information & Records Governance"


@pytest.mark.parametrize("code,expected", [
    ("DRG-QI-STD-CDI", "Standard"),
    ("DRG-ISMS-STD-IDL", "Standard"),
    ("DRG-QI-POL-CDI", "Policy"),
    ("DRG-ISMS-PRO-JMLA", "Procedure"),
    ("DRG-QI-SPEC-DRP", "Procedure"),
    ("DRG-QI-REG-RRS", "Form"),
    ("DRG-ISMS-FRM-VFS", "Form"),
    ("DRG-QI-POL-MIMS-01-26", "Policy"),          # legacy year suffix
    ("", ""),
    ("not a code", ""),
])
def test_the_type_is_read_from_the_document_code(code, expected):
    assert document_type_from_code(code) == expected


def test_a_standard_in_the_information_folder_is_not_a_form():
    c = classify_for_lifecycle("Control of Documented Information Standard.docx", CDI_FOLDER, "DRG-QI-STD-CDI")
    assert c.document_type == "Standard" and c.confidence == "high"


def test_the_code_beats_the_folder_and_file_name():
    c = classify_for_lifecycle("Forms and Templates.docx", "Templates", "DRG-ISMS-PRO-JMLA")
    assert c.document_type == "Procedure"


@pytest.mark.parametrize("folder,name", [
    (CDI_FOLDER, "Something undated.docx"),               # 'form' inside Information
    ("Contracts", "Supplier contract.docx"),              # 'act' inside contract
    ("Compliance", "Flaw review.docx"),                   # 'law' inside flaw
])
def test_loose_text_is_not_a_signal_when_there_is_no_code(folder, name):
    assert classify_for_lifecycle(name, folder, "").document_type != "Form"


def test_whole_words_still_work_without_a_code():
    assert classify_for_lifecycle("Access Forms and Registers Set.docx", "Access Control", "").document_type == "Form"
    assert classify_for_lifecycle("Cloud Access Procedure Draft.docx", "Access Control", "").document_type == "Procedure"
    assert classify_for_lifecycle("Access Review Standard Draft.docx", "Access Control", "").document_type == "Standard"


# ── everything intake fills in is read from the document, not guessed ───────

from scripts.intake_sharepoint_to_lifecycle import (  # noqa: E402
    department_from_code,
    extract_document_code_from_text,
    read_header,
    standards_from_text,
    title_for,
)
from tests.cdi.builders import DocBuilder  # noqa: E402


def _doc(code="DRG-QI-STD-CDI", title="Control of Documented Information Standard", **extra) -> bytes:
    b = DocBuilder()
    b.control_block(title=title, code=code, owner="CTO", layer="Layer 3", **extra)
    b.para("This Standard supports the parent policy DRG-QI-POL-MIMS-01-26 and cites DRG-ISMS-PRO-CMIG.")
    return b.bytes()


def test_the_documents_own_code_is_read_from_its_header_never_a_cited_one():
    h = read_header(_doc(), "x.docx")
    assert h["code"] == "DRG-QI-STD-CDI" and h["title"] == "Control of Documented Information Standard"


def test_a_document_with_no_code_gets_none_rather_than_a_cited_one():
    h = read_header(_doc(code="Not assigned"), "x.docx")
    assert h["code"] == ""


def test_the_text_fallback_only_looks_at_the_opening():
    body = "Purpose text. " * 200 + "See DRG-ISMS-PRO-CMIG for the procedure."
    assert extract_document_code_from_text(body) == ""
    assert extract_document_code_from_text("DRG-QI-STD-CDI\n" + body) == "DRG-QI-STD-CDI"


@pytest.mark.parametrize("code,dept", [
    ("DRG-QI-STD-CDI", "QI"), ("DRG-ISMS-STD-IDL", "ISMS"), ("DRG-IT-PRO-APP", "IT"), ("", ""),
])
def test_the_department_is_the_codes_function(code, dept):
    assert department_from_code(code) == dept


def test_a_document_without_a_code_is_marked_as_a_guess():
    c = classify_for_lifecycle("Access Control Policy.docx", "Access Control", "")
    assert c.department == "ISMS" and "GUESSED" in c.department_source
    c = classify_for_lifecycle("Standard.docx", "Quality Management", "DRG-QI-STD-CDI")
    assert c.department == "QI" and "GUESSED" not in c.department_source


def test_department_words_match_whole_words():
    # 'hr' inside 'through', 'account' inside 'accountable' must not decide anything
    assert classify_for_lifecycle("Through the door.docx", "Misc", "").department == "QI"


@pytest.mark.parametrize("filename,title", [
    ("Access Procedure Draft.docx", "Access Procedure"),
    ("DRG-ISMS-STD-APPSEC Working Draft.docx", "DRG-ISMS-STD-APPSEC"),
    ("Context Policy Clean Operational Review Draft 2026-09-28.docx", "Context Policy Clean Operational Review"),
    ("Policy Draft for Approval.docx", "Policy"),
    ("Remote Access Procedure.docx", "Remote Access Procedure"),
])
def test_a_file_name_loses_its_status_when_it_is_used_as_the_title(filename, title):
    assert title_for(filename) == title


def test_the_documents_own_title_wins():
    assert title_for("Access Procedure Draft.docx", "Access Procedure") == "Access Procedure"


def test_standards_are_only_those_the_document_states():
    assert standards_from_text("ISO 9001:2015 Clause 7.5; ISO/IEC 27001:2022 Annex A 5.1; NDPA 2023 s24") \
        == "ISO 27001, ISO 9001, NDPA"
    assert standards_from_text("ISO/IEC 27001:2022 Annex A 5.15") == "ISO 27001"
    assert standards_from_text("") == ""                    # nothing assumed
    assert classify_for_lifecycle("x.docx", "f", "DRG-QI-STD-CDI", {"standards": ""}).standards == ""
