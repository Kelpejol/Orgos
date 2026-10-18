# =============================================================================
# tests/records_catalogue/test_catalogue.py — the Catalogue as OrgOS holds it
#
# What matters: validation statuses survive untouched, automated disposition is
# refused unless retention is validated (GR-11), withdrawn proposals are never
# matched, and an import changes only what changed and deletes nothing.
# =============================================================================

import io
import os
from unittest.mock import AsyncMock, patch

import openpyxl
import pytest

from auth.validator import CurrentUser
from records_catalogue import service
from records_catalogue.model import RecordEntry
from records_catalogue.workbook import COLUMNS, WorkbookError, read_catalogue

USER = CurrentUser(oid="u", name="U", email="u@x", tenant_id="t", roles=[])
REAL = "docs/Enterprise Records Catalogue - Production Candidate.xlsx"


def entry(rid="REC-0001", **kw):
    return RecordEntry(record_id=rid, name=kw.pop("name", "Controlled Document Register"),
                       admission_status=kw.pop("admission_status", "Governed Record"), **kw)


def workbook(rows, columns=tuple(COLUMNS), sheet="Enterprise Records Catalogue"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["Enterprise Records Catalogue — banner"])
    ws.append([])
    ws.append(list(columns))
    for r in rows:
        ws.append([r.get(c, "") for c in columns])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── workbook ─────────────────────────────────────────────────────────────────

def test_the_header_is_found_below_the_banner_and_aliases_split():
    [e] = read_catalogue(workbook([{
        "Proposed Record ID": "REC-0623", "Canonical Record Name": "Controlled Document Register",
        "Aliases / Source Names": "Document Register | Master List ", "Retention Validation":
        "Recommended - business review pending"}]))
    assert e.record_id == "REC-0623"
    assert e.aliases == ["Document Register", "Master List"]
    assert e.retention_validation == "Recommended - business review pending"


def test_a_changed_layout_stops_the_import():
    with pytest.raises(WorkbookError, match="Retention Validation"):
        read_catalogue(workbook([], columns=[c for c in COLUMNS if c != "Retention Validation"]))
    with pytest.raises(WorkbookError, match="sheet"):
        read_catalogue(workbook([], sheet="Sheet1"))


# ── disposition gate (GR-11) ────────────────────────────────────────────────

@pytest.mark.parametrize("validation", ["Recommended - business review pending",
                                        "Unreconciled - source statement only",
                                        "Set at business review", "Not validated", ""])
def test_unvalidated_retention_blocks_automated_disposition(validation):
    allowed, reason = entry(retention_validation=validation).disposition_gate()
    assert not allowed and "GR-11" in reason


def test_validated_retention_opens_the_gate_unless_the_record_prohibits_it():
    ok = entry(retention_validation="Validated from controlled source - 23 Sep 2026")
    assert ok.disposition_gate()[0]
    held = entry(retention_validation="Validated from controlled source",
                 record_validation_status="Automated disposition prohibited")
    assert not held.disposition_gate()[0]
    gone = entry(retention_validation="Validated", admission_status="Withdrawn duplicate proposal")
    assert not gone.disposition_gate()[0]


def test_the_system_id_is_read_from_the_location():
    assert entry(location="S01 SharePoint, Governance & Records library").system_id == "S01"
    assert entry(location="Finance shared drive").system_id == ""


# ── storage and matching ────────────────────────────────────────────────────

def test_an_entry_survives_the_round_trip_through_sharepoint():
    e = entry(aliases=["Master List"], retention_rule="RR-26", custodian="Document Controller")
    assert service.from_item({"id": "7", "fields": service.to_fields(e)}) == e


def test_names_match_on_canonical_name_or_alias_but_never_a_withdrawn_proposal():
    a = entry("REC-0001", aliases=["Master List"])
    w = entry("REC-0670", name="Master list", admission_status="Withdrawn duplicate proposal")
    assert service.match_name([a, w], "master-list") == [a]
    assert service.match_name([a, w], "CONTROLLED DOCUMENT REGISTER") == [a]
    assert service.match_name([a, w], "Document") == []        # exact, not contains


# ── import plan ─────────────────────────────────────────────────────────────

def test_an_import_creates_updates_and_never_deletes():
    same, changed, new = entry("REC-0001"), entry("REC-0002"), entry("REC-0003")
    existing = [
        {"id": "1", "fields": service.to_fields(same)},
        {"id": "2", "fields": service.to_fields(entry("REC-0002", custodian="old"))},
        {"id": "9", "fields": service.to_fields(entry("REC-0099"))},
    ]
    plan = service.plan_import(existing, [same, changed, new])
    assert plan.unchanged == 1
    assert [(i, e.record_id) for i, e in plan.update] == [("2", "REC-0002")]
    assert [e.record_id for e in plan.create] == ["REC-0003"]
    assert plan.not_in_workbook == ["REC-0099"]


def test_a_second_import_of_the_same_workbook_changes_nothing():
    entries = [entry("REC-0001"), entry("REC-0002")]
    existing = [{"id": str(i), "fields": service.to_fields(e)} for i, e in enumerate(entries)]
    plan = service.plan_import(existing, entries)
    assert (plan.create, plan.update, plan.unchanged) == ([], [], 2)


# ── API ─────────────────────────────────────────────────────────────────────

async def test_the_api_hides_withdrawn_records_and_explains_the_gate():
    import records_catalogue.router as r
    entries = {e.record_id: e for e in [
        entry("REC-0001", location="S01 SharePoint"),
        entry("REC-0670", admission_status="Withdrawn duplicate proposal")]}
    with patch.object(service, "load", new=AsyncMock(return_value=entries)):
        listed = await r.list_records(q=None, record_type=None, system_id="s01",
                                      include_withdrawn=False, user=USER)
        detail = await r.get_record("rec-0001", user=USER)
    assert [x["record_id"] for x in listed] == ["REC-0001"]
    assert detail["automated_disposition_allowed"] is False
    assert "GR-11" in detail["disposition_gate_reason"]


# ── the real Catalogue ──────────────────────────────────────────────────────

@pytest.mark.skipif(not os.path.exists(REAL), reason="Records Catalogue workbook not present")
def test_the_production_candidate_reads_completely():
    entries = read_catalogue(open(REAL, "rb").read())
    assert len(entries) == 729 and len({e.record_id for e in entries}) == 729
    assert sorted(e.record_id for e in entries if e.withdrawn) == ["REC-0670", "REC-0671"]
    assert sum(e.disposition_gate()[0] for e in entries) == 8
    assert all(len(service.to_fields(e)["Payload"]) < 60_000 for e in entries)
