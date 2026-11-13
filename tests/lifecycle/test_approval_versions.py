# =============================================================================
# tests/lifecycle/test_approval_versions.py — what approval does to the version
# (CDI §14, lifecycle/versioning.py)
#
# The cases that matter: a first issue is 01 with a real change summary; a
# revision chooses new version, correction or annual review, and only a NEW
# version moves the version and the effective date; a refusal writes nothing and
# never leaves a document stranded in Approval.
# =============================================================================

import json
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import lifecycle.router as lr
from auth.validator import ROLE_COMPLIANCE, CurrentUser
from lifecycle.cover_suggest import REVIEW_PERIOD_DAYS
from lifecycle.schemas import CdtCoverFacts, RevisionHistoryEntry
from tests.lifecycle.test_approval_cdt import _lifecycle_doc

TODAY = date.today()
GOOD = "Added the leaver 24-hour rule because the audit found access kept after departure."
REGISTER = {"CurrentVersion": "R02", "EffectiveDate": "2026-03-01", "NextReviewDate": "2027-03-01"}
COMPLIANCE = CurrentUser(oid="c", name="Compliance", email="c@x", tenant_id="t", roles=[ROLE_COMPLIANCE])


class Env:
    def __init__(self, register=None, register_error=None):
        self.register, self.register_error = register, register_error

    async def get_item(self, list_id, name, item_id):
        if name == "Document Register":
            if self.register_error:
                raise self.register_error
            return {"id": item_id, "fields": self.register or {}}
        return {"id": item_id, "fields": {}}

    def __enter__(self):
        self.stack = ExitStack()
        p = lambda target, **kw: self.stack.enter_context(patch(target, **kw))
        self.update = p("lifecycle.router.update_list_item", new_callable=AsyncMock)
        self.create = p("lifecycle.router.create_list_item", new_callable=AsyncMock, return_value={"id": "99", "fields": {}})
        p("lifecycle.router.get_list_item", new=AsyncMock(side_effect=self.get_item))
        p("lifecycle.router.resolve_user", new=AsyncMock(return_value={"display_name": "Jane Approver", "email": "j@x"}))
        from lifecycle import document_file
        from tests.lifecycle.conftest import FakeLibrary
        self.library = FakeLibrary()
        self.library.add("https://sp/source.docx", b"SRC", "x.docx")
        for name in ("locate", "read", "save"):
            p(f"lifecycle.document_file.{name}", new=getattr(self.library, name))
        self.stack.enter_context(patch.object(type(lr.settings), "document_writes_live", property(lambda s: True)))
        self.merge = p("lifecycle.router.merge", return_value=type("R", (), {"document": b"M", "sha256": "x", "doc_code": "c"})())
        p("lifecycle.router._background_extract_and_flag", new_callable=AsyncMock)
        return self

    def __exit__(self, *a):
        self.stack.close()

    def register_update(self):
        calls = [c for c in self.update.call_args_list if c.args[1] == "Document Register" and "CurrentVersion" in c.args[3]]
        assert calls, "no Register update with a version"
        return calls[0].args[3]

    def nothing_written(self):
        return not self.update.await_count and not self.create.await_count and not self.library.saves


async def approve(env, doc=None, **kw):
    return await lr._finalize_document_approval("10", doc or _lifecycle_doc(), approver_oid="a", approver_email="", **kw)


def revision(**kw):
    return _lifecycle_doc(RevisionOf="7", **kw)


# ── a first issue ───────────────────────────────────────────────────────────

async def test_a_first_issue_is_version_01_with_dates_and_the_summary_in_the_history():
    with Env() as env:
        await approve(env, change_summary=GOOD)
    fields = env.create.call_args.args[2]
    assert fields["CurrentVersion"] == "01"
    assert fields["EffectiveDate"] == TODAY.isoformat()
    assert fields["NextReviewDate"] == (TODAY + timedelta(days=REVIEW_PERIOD_DAYS)).isoformat()
    history = RevisionHistoryEntry.list_from_json(fields["RevisionHistory"])
    assert history[-1].version == "01" and history[-1].purpose == GOOD


async def test_a_first_issue_without_a_real_change_summary_is_refused_and_writes_nothing():
    for summary in ("", "Issued for use", "short"):
        with Env() as env:
            with pytest.raises(HTTPException) as e:
                await approve(env, change_summary=summary)
        assert e.value.status_code == 422
        assert env.nothing_written()


# ── a revision: the three choices ───────────────────────────────────────────

async def test_a_new_version_moves_the_version_both_dates_and_the_cover():
    with Env(REGISTER) as env:
        await approve(env, revision(), version_decision="new", change_summary=GOOD)
    update = env.register_update()
    assert update["CurrentVersion"] == "03" and update["EffectiveDate"] == TODAY.isoformat()
    assert update["NextReviewDate"] == (TODAY + timedelta(days=REVIEW_PERIOD_DAYS)).isoformat()
    cover = CdtCoverFacts.from_json(update["CDTCoverFacts"])
    assert cover.version == "03" and cover.effective_date == TODAY.strftime("%B %Y")


async def test_a_correction_keeps_the_version_and_both_dates_but_is_logged():
    with Env(REGISTER) as env:
        await approve(env, revision(), version_decision="correction", change_summary="Fixed a broken cross-reference in clause 5.3.")
    update = env.register_update()
    assert update["CurrentVersion"] == "02"                     # the old "R02" is written back plain
    assert "EffectiveDate" not in update and "NextReviewDate" not in update
    cover = CdtCoverFacts.from_json(update["CDTCoverFacts"])
    assert cover.version == "02" and cover.effective_date == "March 2026"      # stamped from the Register, not retyped
    history = RevisionHistoryEntry.list_from_json(update["RevisionHistory"])
    assert history[-1].purpose.startswith("Correction, no new version:") and history[-1].version == "02"


async def test_an_unchanged_annual_review_moves_only_the_review_date():
    with Env(REGISTER) as env:
        await approve(env, revision(), version_decision="review")
    update = env.register_update()
    assert update["CurrentVersion"] == "02" and "EffectiveDate" not in update
    assert update["NextReviewDate"] == (TODAY + timedelta(days=REVIEW_PERIOD_DAYS)).isoformat()
    cover = CdtCoverFacts.from_json(update["CDTCoverFacts"])
    assert cover.effective_date == "March 2026" and cover.next_review_due == (TODAY + timedelta(days=REVIEW_PERIOD_DAYS)).strftime("%B %Y")
    assert RevisionHistoryEntry.list_from_json(update["RevisionHistory"])[-1].purpose == "Annual review, no change"


async def test_a_revision_that_does_not_choose_is_refused_and_writes_nothing():
    with Env(REGISTER) as env:
        with pytest.raises(HTTPException) as e:
            await approve(env, revision(), change_summary=GOOD)
    assert e.value.status_code == 422 and "Choose" in e.value.detail and env.nothing_written()


async def test_a_scheduled_review_is_a_revision_of_the_entry_it_was_opened_for():
    doc = _lifecycle_doc(Trigger="Scheduled Review", LinkedDocumentRegisterItem="7")
    with Env(REGISTER) as env:
        await approve(env, doc, version_decision="review")
    assert env.register_update()["CurrentVersion"] == "02" and not env.create.await_count   # no second entry


async def test_a_correction_cannot_be_applied_when_the_register_entry_cannot_be_read():
    with Env(register_error=RuntimeError("SharePoint down")) as env:
        with pytest.raises(HTTPException) as e:
            await approve(env, revision(), version_decision="correction", change_summary="Fixed a broken cross-reference.")
    assert e.value.status_code == 502 and env.nothing_written()


# ── the skip-approver path must not strand a document ───────────────────────

async def test_skipping_the_approver_with_no_change_summary_is_refused_before_the_document_moves():
    doc = {**_lifecycle_doc(), "Stage": "Sensitisation", "ApprovalStatus": ""}
    body = lr.ProgressDoc(current_stage="Sensitisation", skip_approver=True)          # no change summary
    with Env() as env:
        with pytest.raises(HTTPException) as e:
            with patch("lifecycle.router._sp_to_doc", new=AsyncMock(return_value=doc)):
                await lr.progress_doc("10", body, user=COMPLIANCE)
    assert e.value.status_code == 422
    assert not any(c.args[3].get("Stage") == "Approval" for c in env.update.call_args_list)   # never moved into Approval


# ── what the screens are told ───────────────────────────────────────────────

async def test_version_options_for_a_first_issue_a_revision_and_a_scheduled_review():
    async def options(doc, register):
        with Env(register) as env, patch("lifecycle.router._sp_to_doc", new=AsyncMock(return_value=doc)):
            return await lr.version_options("10", user=COMPLIANCE)
    first = await options(_lifecycle_doc(), None)
    assert first["decisions"] == ["new"] and first["has_issued_version"] is False and first["next_version"] == "01"
    rev = await options(revision(), REGISTER)
    assert rev["decisions"] == ["new", "correction", "review"] and rev["current_version"] == "02" and rev["next_version"] == "03"
    assert rev["default_decision"] == "new"
    sched = await options(_lifecycle_doc(Trigger="Scheduled Review", LinkedDocumentRegisterItem="7"), REGISTER)
    assert sched["default_decision"] == "review"


def _at_approval(doc, **version):
    return {**doc, "Stage": "Approval", "ApprovalStatus": "", "ApproverEntraId": "", "OwnerEntraId": "owner",
            "id": "10", **version}


async def _preview(doc, register):
    with Env(register), patch("lifecycle.router._sp_to_doc", new=AsyncMock(return_value=doc)), \
         patch("lifecycle.router.is_valid_doc_code", return_value=True):
        return await lr.approval_impact("10", user=COMPLIANCE)


async def test_the_approval_preview_shows_the_version_compliance_set_on_the_card():
    new = await _preview(_at_approval(revision(), VersionDecision="new", ChangeSummary=GOOD), REGISTER)
    assert any("02 → 03" in u["detail"] for u in new["updates"])
    assert new["version"] == {"decision": "new", "version": "03", "change_summary": GOOD}
    correction = await _preview(_at_approval(revision(), VersionDecision="correction",
                                             ChangeSummary="Fixed a broken cross-reference."), REGISTER)
    assert any("stays at version 02" in u["detail"] for u in correction["updates"])


async def test_the_approval_preview_is_blocked_until_compliance_sets_the_version():
    unset = await _preview(_at_approval(revision()), REGISTER)
    assert unset["blocked"] and "Compliance sets it on the document's card" in unset["blocked_reason"]
    first_issue_without_summary = await _preview(_at_approval(_lifecycle_doc()), None)
    assert first_issue_without_summary["blocked"]


async def test_the_preview_warns_when_a_hand_typed_cover_version_will_be_replaced():
    out = await _preview(_at_approval(_lifecycle_doc(), VersionDecision="new", ChangeSummary=GOOD), None)
    assert any("typed by hand" in w and "version 01" in w for w in out["warnings"])         # the fixture's cover says 05


# ── the approver approves; the version comes from the card ──────────────────

APPROVER = CurrentUser(oid="a", name="Approver", email="a@x", tenant_id="t", roles=[])


async def _approve_as_approver(doc, register=None):
    with Env(register) as env, patch("lifecycle.router._current_item", new=AsyncMock(return_value={"id": "10"})), \
         patch("lifecycle.router._sp_to_doc", new=AsyncMock(return_value=doc)), \
         patch("lifecycle.router.standard_gate.enforce", new=AsyncMock()):
        try:
            await lr.approve_doc("10", lr.ApproveDoc(), user=APPROVER)
        except HTTPException as exc:
            return env, exc
    return env, None


async def test_approval_uses_the_version_set_on_the_card():
    doc = _at_approval(revision(), ApproverEntraId="a", VersionDecision="new", ChangeSummary=GOOD)
    env, error = await _approve_as_approver(doc, REGISTER)
    assert error is None and env.register_update()["CurrentVersion"] == "03"


async def test_approval_without_a_version_on_the_card_is_refused_and_writes_nothing():
    for doc, register in ((_at_approval(revision(), ApproverEntraId="a"), REGISTER),
                          (_at_approval(_lifecycle_doc(), ApproverEntraId="a"), None)):
        env, error = await _approve_as_approver(doc, register)
        assert error is not None and error.status_code == 422
        assert "Compliance sets it on the document's card" in error.detail and "Nothing was changed" in error.detail
        assert env.nothing_written()


async def test_the_approver_cannot_choose_the_version():
    assert "version_decision" not in lr.ApproveDoc.model_fields and "change_summary" not in lr.ApproveDoc.model_fields


# ── sending for approval settles the version ────────────────────────────────

async def _send_for_approval(doc, body):
    with Env() as env, patch("lifecycle.router._current_item", new=AsyncMock(return_value={"id": "10"})), \
         patch("lifecycle.router._sp_to_doc", new=AsyncMock(return_value=doc)):
        try:
            await lr.progress_doc("10", body, user=COMPLIANCE)
        except HTTPException as exc:
            return env, exc
    return env, None


def _moved(env):
    return [c.args[3] for c in env.update.call_args_list if c.args[3].get("Stage") == "Approval"]


async def test_sending_for_approval_saves_the_version_with_the_move():
    doc = {**_lifecycle_doc(), "Stage": "Sensitisation", "ApprovalStatus": ""}
    body = lr.ProgressDoc(current_stage="Sensitisation", approver_id="a", approver_name="A",
                          version_decision="new", change_summary=GOOD)
    env, error = await _send_for_approval(doc, body)
    assert error is None
    moved = _moved(env)
    assert moved and moved[0]["VersionDecision"] == "new" and moved[0]["ChangeSummary"] == GOOD


async def test_sending_for_approval_keeps_a_version_already_set_on_the_card():
    doc = {**_lifecycle_doc(), "Stage": "Sensitisation", "ApprovalStatus": "",
           "VersionDecision": "new", "ChangeSummary": GOOD}
    env, error = await _send_for_approval(doc, lr.ProgressDoc(current_stage="Sensitisation", approver_id="a"))
    assert error is None and _moved(env)[0]["ChangeSummary"] == GOOD


async def test_sending_for_approval_without_a_version_is_refused_and_does_not_move():
    doc = {**_lifecycle_doc(), "Stage": "Sensitisation", "ApprovalStatus": ""}
    env, error = await _send_for_approval(doc, lr.ProgressDoc(current_stage="Sensitisation", approver_id="a"))
    assert error is not None and error.status_code == 422 and not _moved(env)


# ── setting it on the card ──────────────────────────────────────────────────

async def _set(doc, body, user=COMPLIANCE, register=None):
    with Env(register) as env, patch("lifecycle.router._current_item", new=AsyncMock(return_value={"id": "10"})), \
         patch("lifecycle.router._sp_to_doc", new=AsyncMock(return_value=doc)):
        try:
            return env, await lr.set_version_plan("10", body, user=user)
        except HTTPException as exc:
            return env, exc


async def test_compliance_sets_the_version_on_the_card():
    env, out = await _set(revision(Stage="Review"), lr.VersionPlanBody(version_decision="correction",
                                                                       change_summary="Fixed a broken cross-reference."),
                          register=REGISTER)
    assert out["version"] == "02" and out["issues_new_version"] is False
    env.update.assert_awaited_once()
    assert env.update.call_args.args[3] == {"VersionDecision": "correction",
                                            "ChangeSummary": "Fixed a broken cross-reference."}


async def test_a_first_issue_is_always_a_new_version():
    env, out = await _set(_lifecycle_doc(Stage="Review"), lr.VersionPlanBody(change_summary=GOOD))
    assert out["VersionDecision"] == "new" and out["version"] == "01"


async def test_setting_the_version_refuses_a_summary_that_says_nothing_and_writes_nothing():
    env, out = await _set(_lifecycle_doc(Stage="Review"), lr.VersionPlanBody(change_summary="Issued for use"))
    assert isinstance(out, HTTPException) and out.status_code == 422 and env.nothing_written()


async def test_only_the_owner_or_compliance_sets_the_version_and_not_after_approval():
    stranger = CurrentUser(oid="x", name="X", email="x@x", tenant_id="t", roles=[])
    env, out = await _set(_lifecycle_doc(Stage="Review"), lr.VersionPlanBody(change_summary=GOOD), user=stranger)
    assert isinstance(out, HTTPException) and out.status_code == 403 and env.nothing_written()
    env, out = await _set(_lifecycle_doc(Stage="Approval", ApprovalStatus="Approved"), lr.VersionPlanBody(change_summary=GOOD))
    assert isinstance(out, HTTPException) and out.status_code == 409 and env.nothing_written()


# ── the Teams card's "done" line (docs/TEAMS-APPROVAL-CARDS.md) ─────────────

def _decision_lines(env):
    return [c.args[3]["DecisionSummary"] for c in env.update.call_args_list if "DecisionSummary" in c.args[3]]


async def test_an_approval_leaves_a_line_for_the_teams_card():
    doc = _at_approval(revision(), ApproverEntraId="a", VersionDecision="new", ChangeSummary=GOOD)
    env, error = await _approve_as_approver(doc, REGISTER)
    assert error is None and _decision_lines(env)[-1].startswith("Approved by Jane Approver on ")
    writes = [c.args[3] for c in env.update.call_args_list if c.args[1] == "Document Lifecycle"]
    line = next(i for i, w in enumerate(writes) if "DecisionSummary" in w)
    approved = next(i for i, w in enumerate(writes) if w.get("ApprovalStatus") == "Approved")
    assert line < approved            # the Teams flow reacting to "Approved" always finds the line


async def test_the_line_is_never_a_reason_to_fail_an_approval():
    with patch("lifecycle.router.update_list_item", new=AsyncMock(side_effect=RuntimeError("no such column"))):
        await lr._note_decision("10", "Approved by X")          # logged, not raised


async def test_sending_for_approval_clears_the_old_line_and_gives_the_card_its_link():
    doc = {**_lifecycle_doc(), "Stage": "Sensitisation", "ApprovalStatus": "", "VersionDecision": "new", "ChangeSummary": GOOD}
    with patch.object(type(lr.settings), "app_url", property(lambda s: "https://orgos")):
        env, error = await _send_for_approval(doc, lr.ProgressDoc(current_stage="Sensitisation", approver_id="a"))
    assert error is None
    card = [c.args[3] for c in env.update.call_args_list if "ApproveUrl" in c.args[3]]
    assert card == [{"DecisionSummary": "", "ApproveUrl": "https://orgos/lifecycle/approve/10"}]
