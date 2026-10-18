# =============================================================================
# tests/lifecycle/test_extraction_targets.py
#
# A document that reaches the Document Register and never extracts is a silent
# failure: the controls simply never appear in the review queue, and nothing
# says so. That happened because the extractor's type list named four types by
# hand while the Register's enum grew to ten — a Standard, the most
# control-dense type Dragnet writes, was skipped.
#
# So the mapping is checked against the enum itself, not against a copy.
# =============================================================================

import pytest

import lifecycle.router as lr
from grc.schemas import DocumentType


def test_every_register_document_type_has_a_decision():
    """Adding a type to the enum must force a choice here, not a silent skip."""
    for member in DocumentType:
        assert member.value.lower() in lr._EXTRACTOR_TYPE_BY_DOCUMENT_TYPE, (
            f"{member.value} has no extraction decision — it would be guessed"
        )


@pytest.mark.parametrize("doc_type", [
    "Policy", "Standard", "Procedure", "SOP", "Manual",
    "Guideline", "Guidelines", "Combined",
])
def test_controlled_documents_extract_as_policies(doc_type):
    assert lr._extractor_type_for_lifecycle(doc_type) == "Policy"


def test_an_sla_extracts_with_the_contract_schema():
    assert lr._extractor_type_for_lifecycle("SLA") == "Contract"


def test_a_form_is_not_a_control_source():
    assert lr._extractor_type_for_lifecycle("Form") is None


def test_a_missing_type_does_not_extract():
    assert lr._extractor_type_for_lifecycle("") is None
    assert lr._extractor_type_for_lifecycle(None) is None


def test_case_and_padding_do_not_decide_whether_a_document_extracts():
    assert lr._extractor_type_for_lifecycle("  standard  ") == "Policy"
    assert lr._extractor_type_for_lifecycle("PROCEDURE") == "Policy"


def test_an_unknown_type_still_extracts():
    """Missing controls is the costly failure; a few spurious queue items
    are reviewed and rejected by a person."""
    assert lr._extractor_type_for_lifecycle("Playbook") == "Policy"
    assert lr._extractor_type_for_lifecycle("Specification") == "Policy"
