# =============================================================================
# tests/evidence/test_obligations.py — evidence obligations, control × record
#
# One obligation per Record ID a control names; two frequencies kept apart;
# records referenced where they live; states (Missing, Late, Stale…) derived
# from the schedule and the record's own date; nothing a person set is
# overwritten by a sync.
# =============================================================================

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from agents.gap_analyzer.control_gaps import find_evidence_gaps
from auth.validator import CurrentUser
from evidence.obligations import (
    assess,
    obligations_for,
    parse_frequency,
    plan_obligations,
    suggest_frequency,
)
from evidence.service import state_changes
from records_catalogue.model import RecordEntry

TODAY = date(2026, 10, 19)
USER = CurrentUser(oid="u", name="Verifier", email="u@x", tenant_id="t", roles=["OrgOS.Admin"])


def definition(cid="CDI-001", evidence=(("REC-0623", "Register"),), trigger="On creation.",
               accountable="Compliance Executive", executing="Document Owner"):
    return {"control_id": cid, "title": "Register", "trigger": trigger,
            "accountable": accountable, "executing": executing, "defined_in_label": "DRG-QI-STD-CDI",
            "evidence": [{"record_id": r, "name": n} for r, n in evidence]}


CATALOGUE = {
    "REC-0623": RecordEntry("REC-0623", "Controlled Document Register", admission_status="Governed Record",
                            custodian="Document Controller", location="S01 SharePoint, Governance library"),
    "REC-0670": RecordEntry("REC-0670", "Old", admission_status="Withdrawn duplicate proposal"),
}


# ── generation ──────────────────────────────────────────────────────────────

def test_one_obligation_per_record_id_with_the_catalogues_name_and_home():
    [ob] = obligations_for(definition(evidence=(("REC-0623", "register"), ("REC-0623", "again"),
                                                (None, "audit report"))), CATALOGUE)
    assert ob.key == "CDI-001|REC-0623"
    assert (ob.record_name, ob.custodian, ob.system_id) == (
        "Controlled Document Register", "Document Controller", "S01")
    assert ob.owner_role == "Document Owner"          # who produces it: the executing role


def test_a_withdrawn_duplicate_record_makes_no_obligation():
    assert obligations_for(definition(evidence=(("REC-0670", "Old"),)), CATALOGUE) == []


def test_the_trigger_suggests_a_frequency_but_never_sets_one():
    [ob] = obligations_for(definition(trigger="Quarterly access review."), CATALOGUE)
    assert ob.suggested_frequency_days == 91
    assert "CheckFrequencyDays" not in ob.fields()
    assert suggest_frequency("Monthly check and annual audit") is None   # two cadences: no guess
    assert parse_frequency("90 days") == 90 and parse_frequency("quarterly") == 91
    assert parse_frequency("as needed") is None


def _controls(*defs):
    return [{"control_id": d["control_id"], "status": "Active", "definition": d} for d in defs]


def _rows(actions, **extra):
    return [{"id": str(n), "fields": {**a.fields, **extra}} for n, a in enumerate(actions, start=1)]


def test_reconciling_creates_then_changes_nothing():
    first = plan_obligations(_controls(definition()), [], CATALOGUE)
    assert [(a.kind, a.key) for a in first] == [("create", "CDI-001|REC-0623")]
    assert plan_obligations(_controls(definition()), _rows(first), CATALOGUE) == []


def test_a_schedule_and_submission_set_by_people_survive_a_sync():
    rows = _rows(plan_obligations(_controls(definition()), [], CATALOGUE),
                 CheckFrequencyDays=91.0, LastRecordDate="2026-09-01", Status="Accepted")
    changed = plan_obligations(_controls(definition(executing="Records Officer")), rows, CATALOGUE)
    [action] = changed
    assert action.fields == {"OwnerRole": "Records Officer"}       # only the generated field


def test_a_record_dropped_from_the_control_is_retired_and_restored_if_named_again():
    rows = _rows(plan_obligations(_controls(definition()), [], CATALOGUE))
    [retire] = plan_obligations(_controls(definition(evidence=())), rows, CATALOGUE)
    assert (retire.kind, retire.fields["Status"]) == ("retire", "Withdrawn")
    retired = [{"id": "1", "fields": {**rows[0]["fields"], "Status": "Withdrawn"}}]
    [back] = plan_obligations(_controls(definition()), retired, CATALOGUE)
    assert back.fields == {"Status": "Pending"}


def test_older_one_per_control_rows_are_left_alone():
    legacy = [{"id": "9", "fields": {"Title": "Evidence for: x", "LinkedControlId": "17"}}]
    assert [a.kind for a in plan_obligations([], legacy)] == []


# ── where an obligation stands ──────────────────────────────────────────────

def state(**f):
    return assess({"ObligationKey": "K", **f}, TODAY).state


def test_states_follow_the_schedule_and_the_records_own_date():
    assert state() == "Unscheduled"
    sched = {"CheckFrequencyDays": 30, "ScheduledFrom": "2026-10-01"}
    assert state(**sched) == "Awaiting first record"
    assert state(CheckFrequencyDays=30, ScheduledFrom="2026-09-01") == "Missing"
    accepted = {**sched, "Status": "Accepted"}
    assert state(**accepted, LastRecordDate="2026-10-10") == "Current"
    assert state(**accepted, LastRecordDate="2026-09-25") == "Due soon"     # due 25 Oct
    assert state(**accepted, LastRecordDate="2026-09-01") == "Late"
    assert state(**accepted, FreshnessDays=20, LastRecordDate="2026-09-28") == "Stale"
    assert state(**sched, Status="Submitted") == "Submitted"
    assert state(**sched, Status="Rejected") == "Rejected"
    assert state(Status="Withdrawn") == "Withdrawn"


def test_only_states_that_changed_are_written():
    rows = [{"id": "1", "fields": {"ObligationKey": "K", "CheckFrequencyDays": 30,
                                   "ScheduledFrom": "2026-09-01", "State": "Missing",
                                   "StateDetail": "No record has been accepted; the first was due 2026-10-01.",
                                   "NextDue": "2026-10-01T00:00:00Z"}},
            {"id": "2", "fields": {"ObligationKey": "L", "State": "Current"}}]
    assert state_changes(rows, TODAY) == [("2", {"State": "Unscheduled",
                                                 "StateDetail": "No check frequency is set.",
                                                 "NextDue": None})]


# ── gaps ─────────────────────────────────────────────────────────────────────

def test_late_or_missing_records_are_a_gap_per_control_and_unscheduled_ones_per_document():
    rows = [
        {"ObligationKey": "A|REC-1", "LinkedControlId": "A", "RecordId": "REC-1", "SourceDocument": "D",
         "CheckFrequencyDays": 30, "ScheduledFrom": "2026-08-01"},
        {"ObligationKey": "B|REC-2", "LinkedControlId": "B", "RecordId": "REC-2", "SourceDocument": "D"},
        {"ObligationKey": "C|REC-3", "LinkedControlId": "C", "RecordId": "REC-3", "SourceDocument": "D"},
    ]
    gaps = find_evidence_gaps(rows, TODAY)
    assert sorted(g["gap_key"] for g in gaps) == ["CDI|EVID:A|Evidence gap", "CDI|SCHED:D|Evidence gap"]
    assert next(g for g in gaps if "EVID:A" in g["gap_key"])["severity"] == "Major"


# ── the API ─────────────────────────────────────────────────────────────────

import record_tracker.router as rt                                          # noqa: E402

OBLIGATION = {"ObligationKey": "CDI-001|REC-0623", "LinkedControlId": "CDI-001", "RecordId": "REC-0623",
              "SourceSystem": "S01 SharePoint", "Status": "Accepted", "CheckFrequencyDays": 91,
              "LastRecordDate": "2026-07-01", "PendingRecordDate": "2026-10-10"}


def _patched(fields):
    store = {"fields": dict(fields)}

    async def get(*a, **k):
        return {"id": "5", "fields": dict(store["fields"])}

    async def update(list_id, name, item_id, new):
        store["fields"].update(new)
        return {}
    return store, patch.object(rt, "get_list_item", side_effect=get), \
        patch.object(rt, "update_list_item", side_effect=update)


async def test_the_next_periods_record_is_submitted_over_an_accepted_one_with_its_own_date():
    store, g, u = _patched(OBLIGATION)
    with g, u:
        with pytest.raises(rt.HTTPException) as exc:
            await rt.submit_record("5", rt.SubmitRecord(record_link="https://x/rec"), user=USER)
        assert exc.value.status_code == 422 and "record_date" in exc.value.detail
        result = await rt.submit_record("5", rt.SubmitRecord(
            record_link="https://sharepoint/rec", record_date="2026-10-12"), user=USER)
    assert result["Status"] == "Submitted" and store["fields"]["PendingRecordDate"] == "2026-10-12"


async def test_accepting_dates_the_schedule_from_the_record_not_the_check():
    store, g, u = _patched({**OBLIGATION, "Status": "Submitted"})
    with g, u:
        await rt.verify_record("5", rt.VerifyRecord(accepted=True), user=USER)
    assert store["fields"]["LastRecordDate"] == "2026-10-10"
    store, g, u = _patched({**OBLIGATION, "Status": "Submitted"})
    with g, u:
        await rt.verify_record("5", rt.VerifyRecord(accepted=False, rejection_note="Wrong period."), user=USER)
    assert store["fields"]["Status"] == "Rejected"


async def test_a_record_kept_elsewhere_is_linked_not_uploaded():
    from io import BytesIO
    from fastapi import UploadFile
    _, g, u = _patched(OBLIGATION)
    with g, u:
        with pytest.raises(rt.HTTPException) as exc:
            await rt.upload_record("5", UploadFile(BytesIO(b"x"), filename="r.pdf"),
                                   submission_notes=None, record_date="2026-10-10", user=USER)
    assert exc.value.status_code == 409 and "S01 SharePoint" in exc.value.detail


async def test_a_person_sets_the_schedule_once_and_the_first_record_falls_due_a_period_later():
    store, g, u = _patched({**OBLIGATION, "CheckFrequencyDays": 0, "Status": "Pending",
                            "LastRecordDate": None})
    with g, u:
        result = await rt.schedule_obligation("5", rt.ScheduleObligation(check_frequency_days=30), user=USER)
    assert store["fields"]["ScheduledFrom"] == date.today().isoformat()
    assert result["State"] == "Awaiting first record"


async def test_an_obligations_owner_comes_from_its_control():
    _, g, u = _patched(OBLIGATION)
    with g, u:
        with pytest.raises(rt.HTTPException) as exc:
            await rt.reassign_record_owner("5", rt.ReassignRecordOwner(owner_role="CEO"), user=USER)
    assert exc.value.status_code == 422
