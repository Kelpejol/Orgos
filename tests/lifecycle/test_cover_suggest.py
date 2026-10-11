# =============================================================================
# tests/lifecycle/test_cover_suggest.py — proposing a document's cover facts
#
# The behaviour that matters most here is what the engine does when it is NOT
# sure: it must return UNRESOLVED rather than something plausible, because a
# guessed domain routes a document to the wrong approver (Procedure 11.2).
# =============================================================================

from datetime import date

import pytest

from lifecycle.cover_suggest import (
    Confidence,
    family_from_path,
    find_parent_document,
    parse_doc_code,
    suggest_approval_roles,
    suggest_cover_facts,
    suggest_dates,
    suggest_domain,
    suggest_owner,
    suggest_parent_document,
    suggest_type_layer,
)
from lifecycle.domains import Domain


def _register_doc(code: str, title: str, domain: str = "") -> dict:
    return {
        "document_code": code,
        "title": title,
        "cdt_cover": {"domain": domain} if domain else {},
    }


# The real CDI family, which is the worked example throughout the standard.
CDI_POLICY = _register_doc("DRG-QI-POL-CDI", "Control of Documented Information Policy", "Quality & Compliance")
CDI_STANDARD = _register_doc("DRG-QI-STD-CDI", "Control of Documented Information Standard", "Quality & Compliance")


# -----------------------------------------------------------------------------
#  Code parsing
# -----------------------------------------------------------------------------

def test_parse_current_format_code():
    assert parse_doc_code("DRG-QI-PRO-CDI") == ("QI", "PRO", "CDI")


def test_parse_strips_legacy_serial_and_year():
    """Legacy codes carry trailing serial/year groups the current format drops."""
    assert parse_doc_code("DRG-QI-PRO-CER-01-26") == ("QI", "PRO", "CER")
    assert parse_doc_code("DRG-CLE-SOP-01-25") == ("CLE", "SOP", "")


@pytest.mark.parametrize("bad", ["", None, "not a code", "DRG-QI", "QI-PRO-CDI"])
def test_parse_malformed_code_returns_blanks_without_raising(bad):
    """A malformed code should degrade the suggestion, never break the panel."""
    assert parse_doc_code(bad) == ("", "", "")


def test_family_is_first_path_segment():
    assert family_from_path("Data Protection & Privacy/01 Policy.docx") == "Data Protection & Privacy"


def test_family_steps_over_work_in_progress_staging():
    """The staging area nests families under a heading, one level deeper."""
    path = "00 WORK IN PROGRESS/Programme Assurance/Access Control/draft.docx"
    assert family_from_path(path) == "Access Control"


# -----------------------------------------------------------------------------
#  Domain — the priority order is the point
# -----------------------------------------------------------------------------

def test_parent_domain_beats_function_code():
    """The parent is the strongest signal and survives a file move. Here the
    function code would say Information Security, but the parent says Quality
    & Compliance — the parent must win."""
    parent = _register_doc("DRG-QI-STD-CDI", "CDI Standard", "Quality & Compliance")
    s = suggest_domain("DRG-ISMS-PRO-XYZ", "Access Control/x.docx", parent)
    assert s.value == Domain.QUALITY_COMPLIANCE.value
    assert s.confidence == Confidence.HIGH
    assert "parent" in s.source.lower()


def test_function_code_used_when_no_parent():
    s = suggest_domain("DRG-ISMS-PRO-ACC", "Access Control/x.docx", None)
    assert s.value == Domain.INFORMATION_SECURITY.value
    assert s.confidence == Confidence.MEDIUM
    assert "ISMS" in s.source


def test_function_code_beats_folder_so_a_move_does_not_change_it():
    """The same document in two different folders resolves identically, because
    the function code travels with it and the folder does not."""
    a = suggest_domain("DRG-HR-PRO-ONB", "HR People Governance/x.docx", None)
    b = suggest_domain("DRG-HR-PRO-ONB", "Finance & Administration/x.docx", None)
    assert a.value == b.value == Domain.HUMAN_RESOURCES.value


def test_family_folder_used_only_as_last_resort():
    """No parent and an unrecognised function code — only then does the folder
    decide, and it comes back as LOW confidence."""
    s = suggest_domain("DRG-ZZZ-PRO-ABC", "Cryptography & Key Management/x.docx", None)
    assert s.value == Domain.INFORMATION_SECURITY.value
    assert s.confidence == Confidence.LOW


def test_unconfirmed_family_warns_with_the_alternative():
    """Families Compliance has not signed off on must say so, and name the
    other credible domain, rather than being nodded through."""
    s = suggest_domain("DRG-ZZZ-PRO-ABC", "Quality & Service Delivery/x.docx", None)
    assert s.confidence == Confidence.LOW
    assert "not yet confirmed" in s.note.lower()
    assert Domain.SERVICE_DELIVERY_OPERATIONS.value in s.note


def test_domain_unresolved_rather_than_guessed():
    """Nothing to go on — must not invent a domain."""
    s = suggest_domain("DRG-ZZZ-PRO-ABC", "Some Unknown Folder/x.docx", None)
    assert s.value == ""
    assert s.confidence == Confidence.UNRESOLVED


# -----------------------------------------------------------------------------
#  Approval roles follow the domain — never resolved independently
# -----------------------------------------------------------------------------

def test_approval_roles_come_from_the_domain_route():
    first, final = suggest_approval_roles("Information Security")
    assert first.value == "Information Security Officer"
    assert final.value == "Chief Compliance Officer"
    assert first.confidence == Confidence.HIGH


def test_approval_roles_unresolved_when_domain_is():
    first, final = suggest_approval_roles("")
    assert first.confidence == Confidence.UNRESOLVED
    assert final.confidence == Confidence.UNRESOLVED
    assert "domain" in first.note.lower()


# -----------------------------------------------------------------------------
#  Parent document
# -----------------------------------------------------------------------------

def test_parent_matched_by_function_type_and_mnemonic():
    """DRG-QI-PRO-CDI's parent is DRG-QI-STD-CDI — the real CDI chain."""
    parent = find_parent_document("DRG-QI-PRO-CDI", None, [CDI_POLICY, CDI_STANDARD])
    assert parent is CDI_STANDARD


def test_standard_parent_is_the_policy():
    parent = find_parent_document("DRG-QI-STD-CDI", None, [CDI_POLICY, CDI_STANDARD])
    assert parent is CDI_POLICY


def test_parent_falls_back_to_policy_when_no_standard_exists():
    """Procedure 5.5: a Procedure names its parent Standard, 'or its parent
    Policy where no Standard is required'."""
    parent = find_parent_document("DRG-QI-PRO-CDI", None, [CDI_POLICY])
    assert parent is CDI_POLICY


def test_ambiguous_parent_is_not_picked():
    """Two candidate Standards in the same function and neither mnemonic
    matches — picking one would be a guess."""
    a = _register_doc("DRG-QI-STD-AAA", "Standard A")
    b = _register_doc("DRG-QI-STD-BBB", "Standard B")
    assert find_parent_document("DRG-QI-PRO-CCC", None, [a, b]) is None


def test_parent_suggestion_includes_title_and_code():
    s = suggest_parent_document("DRG-QI-PRO-CDI", None, [CDI_POLICY, CDI_STANDARD])
    assert "Control of Documented Information Standard" in s.value
    assert "DRG-QI-STD-CDI" in s.value
    assert s.confidence == Confidence.HIGH


def test_policy_with_no_parent_explains_the_master_policy_rule():
    s = suggest_parent_document("DRG-QI-POL-NEW", None, [])
    assert s.confidence == Confidence.UNRESOLVED
    assert "master" in s.note.lower()


# -----------------------------------------------------------------------------
#  Type / layer
# -----------------------------------------------------------------------------

def test_type_layer_from_code():
    assert suggest_type_layer("DRG-QI-PRO-CDI", None).value == "Procedure (Layer 4)"


def test_type_layer_falls_back_to_the_document_type_name():
    s = suggest_type_layer("not-a-code", "Standard")
    assert s.value == "Standard (Layer 3)"


def test_policy_layer_asks_for_confirmation():
    """POL is 'Layer 1 or 2' — Master vs Domain Policy is a real distinction."""
    s = suggest_type_layer("DRG-QI-POL-CDI", None)
    assert s.confidence == Confidence.MEDIUM
    assert "Layer 1" in s.note and "Layer 2" in s.note


# -----------------------------------------------------------------------------
#  Owner — a role, not a person
# -----------------------------------------------------------------------------

def test_owner_role_is_used_when_present():
    s = suggest_owner("Compliance Executive (QMS & NDPA)", "Jane Doe")
    assert s.value == "Compliance Executive (QMS & NDPA)"
    assert s.confidence == Confidence.HIGH


def test_person_name_is_not_accepted_as_the_owner():
    """Procedure 7.8 — individuals are not named in controlled text."""
    s = suggest_owner(None, "Jane Doe")
    assert s.value == ""
    assert s.confidence == Confidence.UNRESOLVED
    assert "role" in s.note.lower()
    assert "Jane Doe" in s.source


# -----------------------------------------------------------------------------
#  Dates
# -----------------------------------------------------------------------------

def test_next_review_is_twelve_months_after_effective_date():
    effective, due = suggest_dates("March 2026")
    assert effective.value == "March 2026"
    assert due.value == "March 2027"


def test_dates_derived_from_approval_date():
    effective, due = suggest_dates(None, approved_on=date(2026, 3, 15))
    assert effective.value == "March 2026"
    assert due.value == "March 2027"


def test_unapproved_document_does_not_invent_an_effective_date():
    effective, due = suggest_dates(None, approved_on=None)
    assert effective.value == ""
    assert "on approval" in effective.source.lower()


def test_iso_effective_date_is_understood():
    _, due = suggest_dates("2026-03-15")
    assert due.value == "March 2027"


# -----------------------------------------------------------------------------
#  End to end
# -----------------------------------------------------------------------------

def _lifecycle_doc(**overrides) -> dict:
    base = {
        "id": "10",
        "Title": "Control of Documented Information Procedure",
        "DocumentCode": "DRG-QI-PRO-CDI",
        "DocumentType": "Procedure",
        "OwnerName": "Jane Doe",
        "cover": {},
    }
    base.update(overrides)
    return base


def test_full_suggestion_resolves_the_whole_approval_chain():
    s = suggest_cover_facts(
        _lifecycle_doc(),
        [CDI_POLICY, CDI_STANDARD],
        folder_path="Control of Documented Information & Records Governance/x.docx",
    )
    assert s.domain.value == Domain.QUALITY_COMPLIANCE.value
    assert s.first_pass_approval.value == "Chief Compliance Officer"
    assert s.final_approval.value == "Managing Director / CEO"
    assert s.type_layer.value == "Procedure (Layer 4)"
    assert "DRG-QI-STD-CDI" in s.parent_document.value
    assert s.classification.value == "Internal Use Only"
    assert s.distribution.value == "All Staff"


def test_existing_confirmed_domain_is_never_overwritten():
    """The whole reason a file move is harmless: once a person has confirmed
    the domain it is a stored decision, and re-deriving must not silently
    replace it — even when the folder now says something else."""
    doc = _lifecycle_doc(cover={"domain": "Data Protection & Privacy"})
    s = suggest_cover_facts(doc, [CDI_STANDARD], folder_path="Access Control/x.docx")
    assert s.domain.value == Domain.DATA_PROTECTION_PRIVACY.value
    assert "already set" in s.domain.source.lower()
    # and the approval route follows the confirmed domain, not the folder's
    assert s.final_approval.value == "Managing Director / CEO"


def test_unresolved_fields_are_listed_for_the_reviewer():
    s = suggest_cover_facts(
        _lifecycle_doc(DocumentCode="DRG-ZZZ-PRO-ABC", OwnerName="Jane Doe"),
        [],
        folder_path="Unknown Folder/x.docx",
    )
    assert "domain" in s.unresolved_fields
    assert "owner" in s.unresolved_fields
    assert "first_pass_approval" in s.unresolved_fields


def test_suggestions_serialise_with_provenance():
    s = suggest_cover_facts(_lifecycle_doc(), [CDI_STANDARD])
    payload = s.as_dict()
    assert set(payload["domain"]) == {"value", "source", "confidence", "note"}
    assert payload["domain"]["confidence"] in {
        Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW, Confidence.UNRESOLVED,
    }
