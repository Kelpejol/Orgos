# =============================================================================
# tests/control_register/test_library_sync.py — library → review → register
#
# Phase 3 exit: re-syncing an unchanged library produces zero reviewer items;
# changing one requirement produces exactly one. Accepting a changed control
# updates its row; it never adds a second.
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest

import review_queue.router as rq
from auth.validator import CurrentUser
from cdi.library import LibraryIndex
from cdi.parser import parse_document
from control_register.definitions import candidate_from, decide_status, diff
from control_register.sync import control_fields, plan_sync, queue_fields
from tests.cdi.builders import DocBuilder

USER = CurrentUser(oid="u", name="Reviewer", email="u@x", tenant_id="t", roles=["OrgOS.Admin"])


def library(requirement="The CTO shall log every change.", responsibility="CTO.",
            code="DRG-ISMS-STD-TST", ids=("TST-01", "TST-02"), version="1.0"):
    b = DocBuilder()
    b.control_block(title="Test Standard", code=code, owner="CTO", layer="Layer 3")
    for cid in ids:
        b.control(cid, "Change logging",
                  requirement=requirement if cid == "TST-01" else "The CTO shall review logs.",
                  trigger="A change.", responsibility=responsibility, evidence="REC-0001 Change log.")
    return LibraryIndex([parse_document(b.bytes(), f"std-{version}.docx")])


def confirmed_register(index, status="Active"):
    rows = []
    for n, cid in enumerate(index.defined_ids, start=1):
        doc, control = index.definition(cid)
        rows.append({"id": str(n), "fields": control_fields(candidate_from(doc, control), status, "")})
    return rows


def queued(action, item_id="50", status="Pending Review"):
    return {"id": item_id, "fields": {**queue_fields(action), "ReviewStatus": status}}


# ── the exit criterion ──────────────────────────────────────────────────────

def test_a_first_sync_raises_every_defined_control_once():
    plan = plan_sync(library(), [], [])
    assert [(a.kind, a.control_id, a.change) for a in plan.actions] == [
        ("create_item", "TST-01", "New"), ("create_item", "TST-02", "New")]


def test_re_syncing_an_unchanged_library_produces_nothing():
    index = library()
    plan = plan_sync(index, confirmed_register(index), [])
    assert plan.actions == [] and plan.unchanged == 2


def test_changing_one_requirement_produces_exactly_one_item_with_its_diff():
    register = confirmed_register(library())
    plan = plan_sync(library(requirement="The CTO shall log and approve every change."), register, [])
    [action] = plan.actions
    assert (action.kind, action.control_id, action.change) == ("create_item", "TST-01", "Changed")
    assert [d["label"] for d in action.diff] == ["Requirement"]
    assert action.diff[0]["before"] == "The CTO shall log every change."


def test_spacing_alone_is_not_a_change():
    register = confirmed_register(library())
    plan = plan_sync(library(requirement="The CTO  shall log\nevery change."), register, [])
    assert {a.kind for a in plan.actions} == {"refresh_control"}    # stored text follows; no reviewer


# ── the queue is never flooded ──────────────────────────────────────────────

def test_a_change_already_waiting_is_not_queued_twice():
    changed = library(requirement="Changed.")
    first = plan_sync(changed, confirmed_register(library()), [])
    again = plan_sync(changed, confirmed_register(library()), [queued(first.actions[0])])
    assert again.actions == [] and again.already_queued == 1


def test_a_further_change_updates_the_waiting_item_in_place():
    first = plan_sync(library(requirement="Changed once."), confirmed_register(library()), [])
    plan = plan_sync(library(requirement="Changed twice."), confirmed_register(library()),
                     [queued(first.actions[0], item_id="77")])
    [action] = plan.actions
    assert (action.kind, action.queue_item_id) == ("update_item", "77")


def test_a_rejected_change_is_not_raised_again_until_the_document_changes_again():
    first = plan_sync(library(requirement="Changed."), confirmed_register(library()), [])
    rejected = [queued(first.actions[0], status="Rejected")]
    assert plan_sync(library(requirement="Changed."), confirmed_register(library()), rejected).declined == 1
    later = plan_sync(library(requirement="Changed again."), confirmed_register(library()), rejected)
    assert [a.kind for a in later.actions] == ["create_item"]


def test_a_waiting_item_is_closed_when_the_document_reverts():
    first = plan_sync(library(requirement="Changed."), confirmed_register(library()), [])
    plan = plan_sync(library(), confirmed_register(library()), [queued(first.actions[0], item_id="9")])
    assert [(a.kind, a.queue_item_id) for a in plan.actions] == [("close_item", "9")]


def test_a_new_version_with_the_same_wording_refreshes_without_review():
    register = confirmed_register(library(version="1.0"))
    plan = plan_sync(library(version="2.0"), register, [])
    assert {a.kind for a in plan.actions} == {"refresh_control"}    # filename changed, wording didn't


def test_a_confirmed_control_no_longer_defined_is_reported_not_withdrawn():
    plan = plan_sync(library(ids=("TST-01",)), confirmed_register(library()), [])
    assert plan.no_longer_defined == ["TST-02"]
    assert all(a.kind != "create_item" for a in plan.actions)


# ── status at confirmation ──────────────────────────────────────────────────

def _resolver(kind):
    return lambda role: {"kind": kind}


@pytest.mark.parametrize("kind,status", [("group", "Active"), ("job_title", "Blocked"),
                                         ("unresolved", "Blocked")])
def test_only_a_recognised_accountable_role_makes_a_control_active(kind, status):
    doc, control = library().definition("TST-01")
    got, reason = decide_status(candidate_from(doc, control), _resolver(kind))
    assert got == status and (reason == "") == (status == "Active")


def test_an_ambiguous_split_is_blocked_even_if_the_role_exists():
    doc, control = library(responsibility="Managing Director / CEO.").definition("TST-01")
    status, reason = decide_status(candidate_from(doc, control), _resolver("group"))
    assert status == "Blocked" and "one role or two" in reason


# ── the accept cascade ──────────────────────────────────────────────────────

class _Index:
    def resolve(self, role):
        return {"kind": "group"}


async def _accept(queue_item, register_rows):
    writes = {"create": [], "update": []}

    async def create(list_id, name, fields):
        writes["create"].append((name, fields))
        return {"id": "200"}

    async def update(list_id, name, item_id, fields):
        writes["update"].append((name, item_id, fields))
        return {}

    item = rq._sp_to_item(queue_item)
    with patch.object(rq, "get_list_items", new=AsyncMock(return_value=register_rows)), \
         patch.object(rq, "create_list_item", side_effect=create), \
         patch.object(rq, "update_list_item", side_effect=update), \
         patch("ownership.resolver.get_ownership_index", new=AsyncMock(return_value=_Index())):
        result = await rq._definition_accept_cascade(item, USER, "Matches the approved Standard.")
    return writes, result


async def test_accepting_a_changed_control_updates_its_row_never_a_second():
    register = confirmed_register(library())
    [action] = plan_sync(library(requirement="Changed."), register, []).actions
    writes, result = await _accept(queued(action), register)
    [(name, item_id, fields)] = writes["update"]
    assert (name, item_id) == ("Control Register", "1")
    assert fields["ControlStatement"] == "Changed." and fields["Status"] == "Active"
    assert [n for n, _ in writes["create"]] == ["Audit Log"]
    assert "Requirement" in result


async def test_accepting_a_new_control_creates_one_row_and_no_evidence_row():
    [action, _] = plan_sync(library(), [], []).actions
    writes, _ = await _accept(queued(action), [])
    assert [n for n, _ in writes["create"]] == ["Control Register", "Audit Log"]
    row = writes["create"][0][1]
    assert row["ControlId"] == "TST-01"
    assert json.loads(row["MappingJson"]) == []
    assert json.loads(row["DefinitionJson"])["evidence"] == [{"record_id": "REC-0001", "name": "Change log"}]


async def test_a_definition_cannot_be_edited_in_the_queue():
    [action, _] = plan_sync(library(), [], []).actions
    with patch.object(rq, "get_list_item", new=AsyncMock(return_value=queued(action))):
        with pytest.raises(rq.HTTPException) as exc:
            await rq.zone1_decide("50", rq.Zone1DecideBody(
                decision="Edit and Accept", rationale="Tidying the wording here."), user=USER)
    assert exc.value.status_code == 422 and "Document Lifecycle" in exc.value.detail


# ── Phase 4: where it is carried out, live status, records, ownership ──────

from cdi.parser import parse_document as _parse                       # noqa: E402
from tests.cdi.builders import implementing_procedure                   # noqa: E402


def test_a_definition_says_which_procedures_carry_it_out():
    index = library()
    index = LibraryIndex(index.documents + [_parse(implementing_procedure().bytes(), "pro.docx")])
    [action, _] = plan_sync(index, [], []).actions
    assert action.candidate["implemented_in"][0]["document"] == "DRG-ISMS-PRO-TST"
    assert action.candidate["implemented_in"][0]["section"].startswith("4.0")


def test_a_procedure_change_refreshes_the_control_without_a_reviewer():
    index = library()
    register = confirmed_register(index)
    with_procedure = LibraryIndex(index.documents + [_parse(implementing_procedure().bytes(), "pro.docx")])
    assert {a.kind for a in plan_sync(with_procedure, register, []).actions} == {"refresh_control"}


def test_a_blocked_control_becomes_active_once_its_role_is_recognised():
    index = library()
    register = confirmed_register(index, status="Blocked")
    [a1, a2] = plan_sync(index, register, [], resolve=lambda r: {"kind": "group"}).actions
    assert {a1.kind, a2.kind} == {"refresh_status"}
    assert a1.fields == {"Status": "Active", "BlockedReason": ""}


def test_a_status_a_person_set_is_never_overridden():
    index = library()
    register = confirmed_register(index, status="Under Review")
    assert plan_sync(index, register, [], resolve=lambda r: {"kind": "group"}).actions == []


async def test_a_controls_records_are_joined_to_the_catalogue():
    import control_register.router as cr
    from records_catalogue import service as catalogue
    from records_catalogue.model import RecordEntry
    entries = {"REC-0001": RecordEntry("REC-0001", "Change Log", admission_status="Governed Record",
                                       custodian="IT Executive", location="S01 SharePoint",
                                       retention_validation="Recommended - business review pending")}
    control = {"id": "1", "Definition": {"evidence": [
        {"record_id": "REC-0001", "name": "Change log"},
        {"record_id": "REC-0999", "name": "Lost"},
        {"record_id": None, "name": "Internal audit report"}]}}
    with patch.object(catalogue, "load", new=AsyncMock(return_value=entries)):
        rows = await cr._records_for(control)
    assert [r["catalogue"] for r in rows] == ["governed", "not in Catalogue", "no Record ID"]
    assert rows[0]["custodian"] == "IT Executive" and rows[0]["automated_disposition_allowed"] is False


async def test_a_document_defined_controls_owner_is_not_reassigned_in_orgos():
    import control_register.router as cr
    row = confirmed_register(library())[0]
    with patch.object(cr, "get_list_item", new=AsyncMock(return_value=row)), \
         patch.object(cr, "update_list_item", new=AsyncMock()) as update:
        with pytest.raises(cr.HTTPException) as exc:
            await cr.reassign_control_owner("1", cr.ReassignControlOwner(owner_role="CEO"), user=USER)
    assert exc.value.status_code == 422 and "Org Roles" in exc.value.detail
    update.assert_not_called()


# ── accepting a document's definitions together ───────────────────────────

async def test_a_documents_new_definitions_are_accepted_together_each_with_its_own_record():
    actions = plan_sync(library(), [], []).actions
    changed = plan_sync(library(requirement="Changed."), confirmed_register(library()), []).actions[0]
    queue = [queued(a, item_id=str(60 + n)) for n, a in enumerate(actions)]
    queue.append(queued(changed, item_id="70"))
    writes = {"create": [], "update": []}

    async def create(list_id, name, fields):
        writes["create"].append(name)
        return {"id": "300"}

    async def update(list_id, name, item_id, fields):
        writes["update"].append((name, item_id, fields.get("ReviewStatus")))
        return {}

    with patch.object(rq, "get_list_items", new=AsyncMock(side_effect=[queue, []])), \
         patch.object(rq, "create_list_item", side_effect=create), \
         patch.object(rq, "update_list_item", side_effect=update), \
         patch("ownership.resolver.get_ownership_index", new=AsyncMock(return_value=_Index())), \
         patch("evidence.service.sync_obligations", new=AsyncMock(return_value={"create": 2})):
        result = await rq.accept_document_definitions(rq.AcceptDocumentBody(
            document="DRG-ISMS-STD-TST", rationale="Matches the approved Standard v1."), user=USER)

    assert result["accepted"] == ["TST-01", "TST-02"]          # the Changed item is left for review
    assert writes["create"].count("Control Register") == 2 and writes["create"].count("Audit Log") == 2
    assert sorted(i for n, i, st in writes["update"] if n == "AI Review Queue") == ["60", "61"]
    assert result["evidence_obligations_created"] == 2


async def test_the_accept_preview_says_what_a_definition_accept_really_does():
    [action, _] = plan_sync(library(), [], []).actions
    item = rq._sp_to_item(queued(action))
    with patch.object(rq, "get_list_items", new=AsyncMock(return_value=[])), \
         patch("ownership.resolver.get_ownership_index", new=AsyncMock(return_value=_Index())):
        impact = await rq._zone1_impact(item, "Accept", rq._impact_shell("1", "Accept"))
        edit = await rq._zone1_impact(item, "Edit and Accept", rq._impact_shell("1", "Edit and Accept"))
    registers = [c["register"] for c in impact["creates"]]
    assert registers == ["Control Register", "Evidence Tracker", "Audit Log"]
    assert "REC-0001" in impact["creates"][1]["detail"] and "status Active" in impact["creates"][0]["detail"]
    assert edit["blocked"] is True
