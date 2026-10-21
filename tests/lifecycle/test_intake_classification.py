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
