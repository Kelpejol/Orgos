# =============================================================================
# tests/cdi/test_real_document_shapes.py — shapes found by running the checkers over the 123
# library documents, each of which was once read wrongly
# =============================================================================

import pytest

from agents.cdi_checker.service import check_05_responsibilities_section
from cdi.fields import control_field


@pytest.mark.parametrize("text", [
    "1.0 Purpose\n2.0 Scope\n3.0 Definitions\n4.0 Roles\nThe Compliance Executive keeps the register.",
    "3.0 Roles\nThe reporter raises the incident.",
    "5.0 Roles and Responsibilities\nWho does what.",
    "4. Responsibilities\nEveryone.",
])
def test_the_section_that_says_who_does_what_may_be_called_roles(text):
    # 102 of 123 documents call it "Roles"; failing them was blocking nearly everything.
    assert check_05_responsibilities_section(text)["result"] == "PASS"


def test_a_document_with_no_such_section_still_fails():
    out = check_05_responsibilities_section("1.0 Purpose\n2.0 Scope\n3.0 Steps\nDo the thing, then stop.")
    assert out["result"] == "FAIL"


def test_a_prose_mention_of_roles_is_not_a_section():
    out = check_05_responsibilities_section("1.0 Purpose\nThis explains the roles people have in practice.\n2.0 Scope")
    assert out["result"] == "FAIL"


@pytest.mark.parametrize("label,field", [
    ("Trigger or frequency", "trigger"), ("Standard mapping", "mapping"),
    ("Standards mapping", "mapping"), ("Trigger / frequency", "trigger"),
])
def test_the_labels_documents_really_use_for_a_controls_fields_are_read(label, field):
    assert control_field(label) == field
