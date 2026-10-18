# =============================================================================
# tests/cdi/test_fields.py — interpreting the value of one labelled field
#
# The Standards Map and Gap Analysis are built on mappings, evidence links on
# Record IDs, ownership on the accountable/executing split. A misread here is
# silent everywhere downstream, so each shape seen in the real documents is
# pinned down.
# =============================================================================

import pytest

from cdi.codes import find_control_ids, find_record_ids, is_control_id
from cdi.fields import parse_evidence, parse_mapping, split_responsibility


def keys(text):
    refs, bad = parse_mapping(text)
    return [r.key for r in refs], bad


# ── standards mapping ────────────────────────────────────────────────────────

def test_mapping_splits_standards_and_inherits_within_a_group():
    assert keys("ISO 9001 7.5.2; ISO/IEC 27001 7.5.2, A.5.1.") == (
        ["ISO 9001 7.5.2", "ISO 27001 7.5.2", "ISO 27001 A.5.1"], [])


def test_mapping_annex_marker_applies_to_the_numbers_after_it():
    assert keys("ISO/IEC 27001:2022 Clause 7.5, Annex A 5.1, 5.12") == (
        ["ISO 27001 7.5", "ISO 27001 A.5.1", "ISO 27001 A.5.12"], [])


def test_mapping_reads_editions_clauses_keyword_and_sub_items():
    refs, bad = parse_mapping("ISO 22301:2019 Clauses 8.2, 8.3; ISO 9001 7.5.2 a)")
    assert [(r.key, r.edition, r.qualifier) for r in refs] == [
        ("ISO 22301 8.2", "2019", ""), ("ISO 22301 8.3", "2019", ""),
        ("ISO 9001 7.5.2", "", "a)"),
    ]
    assert bad == []


def test_mapping_reads_ndpa_sections_and_a_whole_law():
    assert keys("NDPA 2023 s24, s39") == (["NDPA S.24", "NDPA S.39"], [])
    assert keys("Nigeria Data Protection Act 2023 (NDPA)") == (["NDPA"], [])
    assert keys("ISO 27001") == (["ISO 27001"], [])


def test_mapping_reports_what_it_cannot_read_instead_of_dropping_it():
    refs, bad = parse_mapping("Supports ISO 27001 A.5.1")
    assert [r.key for r in refs] == ["ISO 27001 A.5.1"]
    assert bad == ["Supports"]


@pytest.mark.parametrize("value", ["None", "N/A", "", "Not applicable."])
def test_mapping_none_is_empty_not_an_error(value):
    assert parse_mapping(value) == ([], [])


# ── evidence ─────────────────────────────────────────────────────────────────

def test_evidence_keeps_the_name_beside_each_record_id():
    refs = parse_evidence("REC-0623 Controlled Document Register; validation result REC-0635.")
    assert [(r.record_id, r.name) for r in refs] == [
        ("REC-0623", "Controlled Document Register"), ("REC-0635", "validation result")]


def test_a_record_named_without_an_id_is_kept_as_a_gap():
    [ref] = parse_evidence("Internal audit report and findings (Internal Audit Procedure records).")
    assert ref.record_id is None
    assert ref.name.startswith("Internal audit report")


def test_semicolons_inside_parentheses_do_not_split_a_record():
    refs = parse_evidence("REC-0700 Register (rows; columns); REC-0701 Log")
    assert [r.record_id for r in refs] == ["REC-0700", "REC-0701"]


# ── accountable / executing ──────────────────────────────────────────────────

def test_responsibility_splits_accountable_from_executing():
    r = split_responsibility("Compliance Executive (QMS & NDPA) / platform check V03.")
    assert (r.accountable, r.executing, r.ambiguous) == (
        "Compliance Executive (QMS & NDPA)", "platform check V03", False)


def test_one_role_is_both_accountable_and_executing():
    r = split_responsibility("Document Owner.")
    assert r.single_role and r.accountable == "Document Owner" and not r.ambiguous


def test_a_slash_inside_a_role_name_is_flagged_without_a_vocabulary():
    r = split_responsibility("Managing Director / CEO")
    assert r.ambiguous   # could be one role or two — a person decides


def test_the_vocabulary_settles_a_slash_inside_a_role_name():
    known = ["Managing Director / CEO", "Compliance Executive (QMS & NDPA)"]
    assert split_responsibility("Managing Director / CEO", known).single_role
    r = split_responsibility("Managing Director / CEO / Compliance Executive (QMS & NDPA)", known)
    assert (r.accountable, r.executing, r.ambiguous) == (
        "Managing Director / CEO", "Compliance Executive (QMS & NDPA)", False)


def test_the_as_written_text_is_always_kept():
    text = "Information Security Officer / internal auditor."
    assert split_responsibility(text).as_written == text


# ── identifiers ──────────────────────────────────────────────────────────────

def test_control_ids_exclude_retention_and_governance_rules():
    assert find_control_ids("BCDR-01; RR-26; GR-01; CDI-001; IRG-024") == [
        "BCDR-01", "CDI-001", "IRG-024"]
    assert not is_control_id("RR-26") and is_control_id("BCDR-01")


def test_record_ids_are_exactly_four_digits():
    assert find_record_ids("REC-0675, REC-675, REC-06751 and REC-0675") == ["REC-0675"]


# ── vocabulary and lists ────────────────────────────────────────────────────

from cdi.codes import expand_control_ranges          # noqa: E402
from cdi.fields import control_field, parse_control_list, split_labelled   # noqa: E402


def test_every_spelling_reaches_one_canonical_field():
    for label, field_name in [("Risk treated", "risk"), ("Risk statement", "risk"),
                              ("Responsible role", "responsibility"), ("Owner", "responsibility"),
                              ("Executor", "executing"), ("Evidence Record ID", "record_ids"),
                              ("Trigger and monitoring", "trigger"),
                              ("Governing authority", "authority")]:
        assert control_field(label) == field_name, label


def test_compound_table_headers_resolve_only_when_asked():
    assert control_field("Evidence of operation / monitoring", allow_keywords=True) == "evidence"
    assert control_field("Evidence of operation / monitoring") is None   # not as a paragraph label
    assert control_field("Default or note", allow_keywords=True) is None


def test_a_paragraph_splits_only_at_known_labels():
    assert split_labelled("Owner: the CTO. Trigger: a change. Note: see annex.") == [
        ("Owner", "the CTO."), ("Trigger", "a change. Note: see annex.")]
    assert split_labelled("Evidence freshness: 90 days.") == [("Evidence freshness", "90 days.")]
    assert split_labelled("The officer shall maintain an inventory: all accounts.") is None


def test_ranges_expand_with_their_padding_and_letters():
    assert parse_control_list("CM-01 to CM-03") == ["CM-01", "CM-02", "CM-03"]
    assert parse_control_list("EVT-C08 to EVT-C10") == ["EVT-C08", "EVT-C09", "EVT-C10"]
    assert expand_control_ranges("IRG-001 to IRG-002") == "IRG-001, IRG-002"


def test_control_id_shapes_in_use():
    assert find_control_ids("ACS-L3-01; EVT-C01; NETEDGE-17; DP-064") == [
        "ACS-L3-01", "EVT-C01", "NETEDGE-17", "DP-064"]


def test_a_legacy_document_code_is_not_read_as_a_control():
    """Inside DRG-QI-PRO-CDI-01-26, 'PRO-CDI-01' has exactly a control ID's shape."""
    assert find_control_ids("Supersedes DRG-QI-PRO-CDI-01-26 and DRG-ISMS-POL-IUHC-01-26") == []


# ── laws, ranges and standards named together ───────────────────────────────

def test_ndpa_sections_in_every_form_the_library_uses():
    assert keys("NDPA 16, 18")[0] == ["NDPA S.16", "NDPA S.18"]            # bare numbers
    assert keys("NDPA Sections 39 to 41")[0] == ["NDPA S.39", "NDPA S.40", "NDPA S.41"]
    assert keys("NDPA 2023 s24")[0] == ["NDPA S.24"]


def test_the_gaid_is_cited_by_article_and_schedule():
    assert keys("NDPA 2023 Sections 24 to 25, GAID 2025 Articles 17, Schedules 4") == (
        ["NDPA S.24", "NDPA S.25", "GAID Art.17", "GAID Sch.4"], [])
    assert keys("GAID 2025 Articles 7 to 9")[0] == ["GAID Art.7", "GAID Art.8", "GAID Art.9"]


def test_two_iso_standards_named_together_are_both_kept():
    assert keys("ISO/IEC 27017 and 27018") == (["ISO 27017", "ISO 27018"], [])
