# =============================================================================
# tests/lifecycle/test_approval_integrity.py — approval never damages the record
#
#   • the published copy has its own folder and never replaces the source;
#   • a document whose code is already in the Register updates that entry, never
#     a second one at 01; two live entries with one code are refused;
#   • an unreadable Register entry stops the approval, nothing is written;
#   • reversing the approval of a revision restores the entry, never withdraws it.
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import lifecycle.router as lr
from tests.lifecycle.test_approval_cdt import _lifecycle_doc
from tests.lifecycle.test_approval_versions import COMPLIANCE, GOOD, REGISTER, Env, approve, revision


def reg_rows(*rows):
    return [{"id": i, "fields": f} for i, f in rows]


async def test_the_published_copy_goes_in_its_own_folder_and_the_source_is_kept():
    with Env() as env:
        await approve(env, change_summary=GOOD)
    assert env.upload.await_args.kwargs.get("subfolder") == "Published"
    item_updates = [c.args[3] for c in env.update.call_args_list if c.args[1] == lr._LIST_NAME]
    assert not any("SharePointFileUrl" in u for u in item_updates)        # the item still points at its source
    reg_url = [c.args[3] for c in env.update.call_args_list
               if c.args[1] == "Document Register" and "SharePointUrl" in c.args[3]]
    assert reg_url == [{"SharePointUrl": "https://sp/pub.docx"}]          # the Register points at the published copy


async def test_a_document_whose_code_is_already_registered_updates_that_entry_not_a_new_one():
    doc = _lifecycle_doc()          # no RevisionOf: e.g. the library file read again by intake
    rows = reg_rows(("7", {"DocumentCode": doc["DocumentCode"], "Status": "Active"}))
    with Env(REGISTER) as env, patch("lifecycle.router.get_list_items", new=AsyncMock(return_value=rows)):
        rid, _ = await approve(env, doc=doc, version_decision="new", change_summary=GOOD)
    assert rid == "7" and not env.create.await_count
    assert env.register_update()["CurrentVersion"] == "03"


async def test_two_live_entries_with_one_code_are_refused_before_anything_is_written():
    doc = _lifecycle_doc()
    rows = reg_rows(("7", {"DocumentCode": doc["DocumentCode"], "Status": "Active"}),
                    ("8", {"DocumentCode": doc["DocumentCode"], "Status": "Under Review"}))
    with Env() as env, patch("lifecycle.router.get_list_items", new=AsyncMock(return_value=rows)):
        with pytest.raises(HTTPException) as e:
            await approve(env, doc=doc, change_summary=GOOD)
    assert e.value.status_code == 409 and env.nothing_written()


async def test_a_withdrawn_entry_with_the_same_code_does_not_make_it_a_revision():
    doc = _lifecycle_doc()
    rows = reg_rows(("7", {"DocumentCode": doc["DocumentCode"], "Status": "Withdrawn"}))
    with Env() as env, patch("lifecycle.router.get_list_items", new=AsyncMock(return_value=rows)):
        await approve(env, doc=doc, change_summary=GOOD)
    assert env.create.await_count == 1


async def test_an_unreadable_register_entry_stops_the_approval_and_writes_nothing():
    with Env(register_error=RuntimeError("timeout")) as env:
        with pytest.raises(HTTPException) as e:
            await approve(env, doc=revision(), version_decision="new", change_summary=GOOD)
    assert e.value.status_code == 502 and env.nothing_written()


async def test_approving_a_revision_keeps_a_snapshot_of_the_entry_for_a_reversal():
    with Env(REGISTER) as env:
        await approve(env, doc=revision(), version_decision="new", change_summary=GOOD)
    snap = [c.args[3] for c in env.update.call_args_list if "RegisterBeforeApproval" in c.args[3]]
    assert snap and json.loads(snap[0]["RegisterBeforeApproval"])["CurrentVersion"] == "R02"


# ── reversal ────────────────────────────────────────────────────────────────

async def _reverse(doc):
    item = {"fields": {}}
    with patch.object(lr, "get_list_item", new=AsyncMock(return_value=item)), \
         patch.object(lr, "_sp_to_doc", new=AsyncMock(return_value=doc)), \
         patch.object(lr, "update_list_item", new=AsyncMock()) as upd, \
         patch.object(lr, "_audit_lifecycle_action", new=AsyncMock()):
        out = await lr.reverse_approval("10", lr.ReverseApproval(reason="Wrong approver signed it"), COMPLIANCE)
    return out, [(c.args[1], c.args[3]) for c in upd.call_args_list]


async def test_reversing_a_revision_restores_the_entry_and_never_withdraws_it():
    snap = {"CurrentVersion": "02", "EffectiveDate": "2026-03-01", "SharePointUrl": "https://sp/old.docx"}
    doc = revision(ApprovalStatus="Approved", LinkedDocumentRegisterItem="7",
                   RegisterBeforeApproval=json.dumps(snap), OwnerEntraId="c")
    out, writes = await _reverse(doc)
    reg = [f for name, f in writes if name == "Document Register"]
    assert reg == [{**snap, "Status": "Under Review"}]
    assert not out["RegisterEntryWithdrawn"]


async def test_reversing_a_first_issue_withdraws_its_entry():
    doc = _lifecycle_doc(ApprovalStatus="Approved", LinkedDocumentRegisterItem="7", OwnerEntraId="c")
    out, writes = await _reverse(doc)
    assert ("Document Register", {"Status": "Withdrawn"}) in writes and out["RegisterEntryWithdrawn"]


# ── who may change a document's file ────────────────────────────────────────

@pytest.mark.parametrize("fields,stages,code", [
    ({"Stage": "Review", "ApprovalStatus": "Approved", "OwnerEntraId": "c"}, ("Review",), 409),
    ({"Stage": "Sensitisation", "OwnerEntraId": "c"}, ("Review",), 409),
    ({"Stage": "Review", "OwnerEntraId": "someone-else"}, ("Review",), 403),
])
async def test_a_file_write_is_refused_outside_review_after_approval_or_by_a_stranger(fields, stages, code):
    from auth.validator import CurrentUser
    stranger = CurrentUser(oid="c", name="x", email="x", tenant_id="t", roles=[])
    with patch.object(lr, "get_list_item", new=AsyncMock(return_value={"fields": {**fields, "SharePointFileUrl": "u"}})):
        with pytest.raises(HTTPException) as e:
            await lr._writable_item("1", stranger, stages=stages)
    assert e.value.status_code == code


async def test_amendments_from_feedback_may_be_applied_in_sensitisation():
    from auth.validator import CurrentUser
    owner = CurrentUser(oid="o", name="x", email="x", tenant_id="t", roles=[])
    with patch.object(lr, "get_list_item", new=AsyncMock(return_value={"fields": {
            "Stage": "Sensitisation", "OwnerEntraId": "o", "SharePointFileUrl": "u"}})):
        assert await lr._writable_item("1", owner, stages=("Review", "Sensitisation"))


# ── a revision starts with the cover facts and the source ──────────────────

def test_a_revision_starts_from_the_latest_approved_source():
    items = [{"fields": {"LinkedDocumentRegisterItem": "7", "ApprovalStatus": "Approved",
                         "ApprovedDate": "2026-01-01", "SharePointFileUrl": "old"}},
             {"fields": {"LinkedDocumentRegisterItem": "7", "ApprovalStatus": "Approved",
                         "ApprovedDate": "2026-06-01", "SharePointFileUrl": "newest"}},
             {"fields": {"LinkedDocumentRegisterItem": "8", "ApprovalStatus": "Approved",
                         "ApprovedDate": "2026-09-01", "SharePointFileUrl": "other"}}]
    assert lr._approved_source(items, "7") == "newest"
    assert lr._approved_source(items, "9") == ""


def test_an_unclaimed_intake_card_is_visible_to_everyone_and_a_claimed_one_only_to_its_people():
    unclaimed = {"OwnerEntraId": "", "Owner": "System (SharePoint Intake)", "Stakeholders": []}
    mine = {"OwnerEntraId": "me", "Stakeholders": []}
    theirs = {"OwnerEntraId": "them", "Stakeholders": []}
    assert lr._involves(unclaimed, "anyone") and lr._involves(mine, "me") and not lr._involves(theirs, "me")
