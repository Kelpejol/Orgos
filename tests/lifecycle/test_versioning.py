# =============================================================================
# tests/lifecycle/test_versioning.py — one version number, and what approval does to it
# (CDI Procedure §12 and §14)
# =============================================================================

from datetime import date

import pytest

from lifecycle import versioning as v
from lifecycle.versioning import CORRECTION, NEW, REVIEW, VersionError

TODAY = date(2026, 10, 22)
GOOD = "Added the leaver 24-hour rule because the audit found access kept after departure."


# ── reading and writing a version ───────────────────────────────────────────

@pytest.mark.parametrize("stored,number", [
    ("R02", 2), ("r2", 2), ("02", 2), ("2", 2), ("v3", 3), ("Version 04", 4), ("R10", 10),
    ("Draft", None), ("", None), (None, None), ("TBC", None), ("00", None)])
def test_an_old_R_version_is_still_read_and_a_draft_has_none(stored, number):
    assert v.parse_version(stored) == number


def test_versions_are_written_plain_with_no_R():
    assert v.next_version("R02") == "03" and v.next_version("02") == "03"
    assert v.next_version("Draft") == "01" and v.next_version("") == "01" and v.next_version(None) == "01"
    assert v.next_version("99") == "100"


def test_a_stored_R_version_displays_without_it():
    assert v.display_version("R02") == "02" and v.display_version("Draft") == "Draft" and v.display_version("") == ""


# ── the first issue ─────────────────────────────────────────────────────────

def test_the_first_issue_is_version_01_with_a_change_summary_and_its_dates():
    o = v.plan(None, "First issue of the access standard, replacing the 2025 access policy.",
               existing_version="", today=TODAY, review_days=365)
    assert (o.version, o.issues_new_version, o.effective_date) == ("01", True, TODAY)
    assert o.next_review_date == date(2027, 10, 22)


def test_a_first_issue_cannot_be_called_a_correction_or_a_review():
    for decision in (CORRECTION, REVIEW):
        with pytest.raises(VersionError, match="first issue"):
            v.plan(decision, GOOD, existing_version="", today=TODAY, review_days=365)


# ── a revision: the three choices ───────────────────────────────────────────

def test_a_new_version_raises_the_number_and_moves_both_dates():
    o = v.plan(NEW, GOOD, existing_version="R02", today=TODAY, review_days=365)
    assert (o.version, o.issues_new_version, o.effective_date) == ("03", True, TODAY)
    assert o.next_review_date == date(2027, 10, 22) and o.history_purpose == GOOD


def test_a_correction_keeps_the_version_and_the_dates_and_is_logged():
    o = v.plan(CORRECTION, "Fixed a broken cross-reference in clause 5.3.", existing_version="02", today=TODAY, review_days=365)
    assert (o.version, o.issues_new_version, o.effective_date, o.next_review_date) == ("02", False, None, None)
    assert o.history_purpose.startswith("Correction, no new version:") and not o.history_new_row_is_issue


def test_an_unchanged_annual_review_keeps_the_version_and_moves_only_the_review_date():
    o = v.plan(REVIEW, "", existing_version="02", today=TODAY, review_days=365)
    assert (o.version, o.effective_date, o.next_review_date) == ("02", None, date(2027, 10, 22))
    assert o.history_purpose == "Annual review, no change"
    assert "Reviewed with the Compliance Executive" in v.plan(
        REVIEW, "Reviewed with the Compliance Executive.", existing_version="02", today=TODAY, review_days=365).history_purpose


def test_a_revision_must_choose():
    for blank in (None, "", "maybe"):
        with pytest.raises(VersionError, match="Choose"):
            v.plan(blank, GOOD, existing_version="02", today=TODAY, review_days=365)


# ── a change summary has to say something ───────────────────────────────────

@pytest.mark.parametrize("empty", [
    "Issued for use", "issued for use.", "Approved", "Updated", "Minor changes", "N/A", "Initial issue", "no change", "  "])
def test_a_summary_that_says_nothing_is_refused_for_a_new_version(empty):
    with pytest.raises(VersionError):
        v.plan(NEW, empty, existing_version="02", today=TODAY, review_days=365)


def test_a_too_short_summary_is_refused_and_a_real_one_is_accepted():
    with pytest.raises(VersionError, match="at least 20"):
        v.plan(NEW, "Changed the rule", existing_version="02", today=TODAY, review_days=365)
    v.plan(NEW, GOOD, existing_version="02", today=TODAY, review_days=365)


def test_a_correction_must_say_what_was_corrected_but_a_review_needs_no_words():
    with pytest.raises(VersionError):
        v.plan(CORRECTION, "typo", existing_version="02", today=TODAY, review_days=365)
    v.plan(REVIEW, "", existing_version="02", today=TODAY, review_days=365)


def test_the_migration_rewrites_only_old_R_versions():
    from scripts.migrate_versions import migrated
    assert [migrated(x) for x in ("R01", "r10", "02", "Draft", "", "R", "V2")] == ["01", "10", "02", "Draft", "", "R", "V2"]
