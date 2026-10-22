# =============================================================================
# tests/doc_standards/test_gate.py — the standard as a gate in Lifecycle
#
# The rules that matter: advisory never stops anything; enforce stops on a BLOCK
# failure or an undecided FLAG; a BLOCK can never be waived; a decision covers
# exactly what was found; a gate that could not run does not wave a document
# through in enforce mode; and could-not-check results never read as a pass.
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import lifecycle.router as lr
from auth.validator import ROLE_COMPLIANCE, CurrentUser
from doc_standards import gate
from tests.lifecycle.test_parent_document_link import _lifecycle_doc

COMPLIANCE = CurrentUser(oid="c", name="Compliance Exec", email="c@x", tenant_id="t", roles=[ROLE_COMPLIANCE])
STAFF = CurrentUser(oid="s", name="Staff", email="s@x", tenant_id="t", roles=[])


def result(cid, status, findings=(), enforcement="BLOCK"):
    return {"id": cid, "name": f"{cid} name", "enforcement": enforcement, "status": status, "summary": "",
            "note": "", "findings": [{"message": m, "where": w, "fix": ""} for w, m in findings]}


def report(*results):
    return {"results": list(results), "checks_run": len(results), "checks_total": 24}


FLAGGED = result("V15", "flag", [("section Purpose", "No Purpose section.")], "FLAG")
FAILED = result("V22", "fail", [("ACS-01", "no mapping")])
PASSING = result("V23", "pass")


@pytest.fixture(autouse=True)
def mode(monkeypatch):
    def set_mode(value):
        monkeypatch.setattr(type(gate.settings), "standard_gate", value, raising=False)
        monkeypatch.setattr(gate.settings, "standard_gate", value, raising=False)
    set_mode("advisory")
    return set_mode


# ── the mode ────────────────────────────────────────────────────────────────

def test_the_default_is_advisory_and_a_bad_value_is_advisory_too(mode):
    assert gate.mode() == "advisory"
    mode("shout")
    assert gate.mode() == "advisory"
    mode("ENFORCE")
    assert gate.mode() == "enforce"


# ── decisions ───────────────────────────────────────────────────────────────

def test_a_decision_covers_exactly_what_was_found():
    decisions = gate.record_decision({}, report(FLAGGED), "V15", True, "Combined policy, no separate Purpose.", "C", "c")
    r = report(json.loads(json.dumps(FLAGGED)))
    gate.attach_decisions(r, decisions)
    assert r["results"][0]["decision"]["reason"].startswith("Combined policy")
    changed = report(result("V15", "flag", [("section Scope", "No Scope section.")], "FLAG"))
    gate.attach_decisions(changed, decisions)
    assert changed["results"][0]["decision"] is None and changed["results"][0]["decision_stale"] is True


def test_a_blocking_problem_cannot_be_waived():
    with pytest.raises(ValueError, match="cannot be waived"):
        gate.record_decision({}, report(FAILED), "V22", True, "We would rather not fix it.", "C", "c")


def test_a_decision_needs_a_real_reason_and_a_check_that_is_flagged():
    with pytest.raises(ValueError, match="reason"):
        gate.record_decision({}, report(FLAGGED), "V15", True, "ok", "C", "c")
    with pytest.raises(ValueError, match="no flag"):
        gate.record_decision({}, report(PASSING), "V23", True, "a perfectly good reason", "C", "c")


def test_a_decision_can_be_withdrawn():
    d = gate.record_decision({}, report(FLAGGED), "V15", True, "a perfectly good reason", "C", "c")
    assert gate.record_decision(d, report(FLAGGED), "V15", False, "", "C", "c") == {}


def test_damaged_stored_decisions_are_ignored_not_fatal():
    for raw in ("", None, "not json", '{"a": 1}', "[1, 2]"):
        assert gate.parse_decisions(raw) == {}


# ── the summary ─────────────────────────────────────────────────────────────

def test_ready_means_no_blocking_problem_and_every_flag_decided():
    assert gate.summarise(report(PASSING))["ready"]
    assert not gate.summarise(report(FAILED))["ready"]
    undecided = report(json.loads(json.dumps(FLAGGED)))
    gate.attach_decisions(undecided, {})
    assert gate.summarise(undecided)["undecided_flags"] == ["V15"] and not gate.summarise(undecided)["ready"]
    decided = report(json.loads(json.dumps(FLAGGED)))
    gate.attach_decisions(decided, gate.record_decision({}, decided, "V15", True, "a perfectly good reason", "C", "c"))
    assert gate.summarise(decided)["ready"] and gate.summarise(decided)["decided_flags"] == ["V15"]


def test_checks_that_could_not_run_are_listed_not_hidden_and_do_not_stop_a_document():
    s = gate.summarise(report(PASSING, result("V03", "could_not_check"), result("V07", "not_built")))
    assert s["ready"] and s["could_not_check"] == ["V03"] and s["not_built"] == ["V07"]


def test_the_message_names_the_checks_and_where_to_look():
    r = report(FAILED, json.loads(json.dumps(FLAGGED)))
    gate.attach_decisions(r, {})
    message = gate.block_message(r, gate.summarise(r))
    assert "V22" in message and "V15" in message and "Document standard" in message


# ── the gate ────────────────────────────────────────────────────────────────

def evaluation(*results):
    r = report(*results)
    gate.attach_decisions(r, {})
    return {"mode": gate.mode(), "available": True, "report": r, "gate": gate.summarise(r)}


async def test_advisory_and_off_never_evaluate_and_never_stop(mode):
    for value in ("advisory", "off"):
        mode(value)
        with patch.object(gate, "evaluate_item", new=AsyncMock()) as ev:
            assert await gate.enforce({"id": "1"}) is None
            ev.assert_not_awaited()


async def test_enforce_stops_a_document_with_a_blocking_problem(mode):
    mode("enforce")
    with patch.object(gate, "evaluate_item", new=AsyncMock(return_value=evaluation(FAILED))):
        with pytest.raises(HTTPException) as e:
            await gate.enforce({"id": "1"})
    assert e.value.status_code == 422 and "V22" in e.value.detail


async def test_enforce_lets_a_clean_document_through(mode):
    mode("enforce")
    with patch.object(gate, "evaluate_item", new=AsyncMock(return_value=evaluation(PASSING))):
        assert (await gate.enforce({"id": "1"}))["gate"]["ready"]


async def test_enforce_stops_an_unreadable_document_and_says_why(mode):
    mode("enforce")
    unreadable = {"mode": "enforce", "available": False, "unreadable": True, "reason": "A legacy .doc has no structure."}
    with patch.object(gate, "evaluate_item", new=AsyncMock(return_value=unreadable)):
        with pytest.raises(HTTPException) as e:
            await gate.enforce({"id": "1"})
    assert e.value.status_code == 422 and "legacy .doc" in e.value.detail


async def test_a_gate_that_could_not_run_does_not_wave_a_document_through_when_enforcing(mode):
    mode("enforce")
    with patch.object(gate, "evaluate_item", new=AsyncMock(side_effect=RuntimeError("SharePoint down"))):
        with pytest.raises(HTTPException) as e:
            await gate.enforce({"id": "1"})
    assert e.value.status_code == 503


# ── in Lifecycle ────────────────────────────────────────────────────────────

def _progress(doc_fields=None):
    doc = _lifecycle_doc()
    body = lr.ProgressDoc(current_stage="Review", stakeholders=[{"oid": "s1", "name": "S"}])
    return doc, body


async def test_progress_is_stopped_by_the_standard_only_when_enforcing(mode):
    doc, body = _progress()
    mode("enforce")
    with patch("lifecycle.router.get_list_item", new=AsyncMock(return_value={"id": "10", "fields": doc})), \
         patch("lifecycle.router.update_list_item", new=AsyncMock()) as update, \
         patch.object(gate, "evaluate_item", new=AsyncMock(return_value=evaluation(FAILED))):
        with pytest.raises(HTTPException) as e:
            await lr.progress_doc("10", body, user=COMPLIANCE)
    assert e.value.status_code == 422 and "V22" in e.value.detail
    update.assert_not_awaited()                                   # nothing moved


async def test_progress_goes_ahead_in_advisory_mode_even_when_the_document_would_be_stopped(mode):
    doc, body = _progress()
    mode("advisory")
    with patch("lifecycle.router.get_list_item", new=AsyncMock(return_value={"id": "10", "fields": doc})), \
         patch("lifecycle.router.update_list_item", new=AsyncMock()) as update, \
         patch("grc.service.get_documents", new=AsyncMock(return_value=[])):
        await lr.progress_doc("10", body, user=COMPLIANCE)
    assert update.await_args_list[0].args[3]["Stage"] == "Sensitisation"


async def test_the_decision_endpoint_is_for_compliance_and_saves_the_decision(mode):
    doc = {**_lifecycle_doc(), "Stage": "Review"}
    ev = evaluation(json.loads(json.dumps(FLAGGED)))
    body = lr.StandardDecision(check_id="V15", accept=True, reason="Combined policy, no separate Purpose.")
    with patch("lifecycle.router.get_list_item", new=AsyncMock(return_value={"id": "10", "fields": doc})), \
         patch("lifecycle.router.update_list_item", new=AsyncMock()) as update, \
         patch("lifecycle.router._audit_lifecycle_action", new=AsyncMock()) as audit, \
         patch.object(gate, "evaluate_item", new=AsyncMock(return_value=ev)):
        out = await lr.standard_decision("10", body, user=COMPLIANCE)
    saved = json.loads(update.await_args.args[3]["StandardsDecisions"])
    assert saved[0]["check"] == "V15" and saved[0]["by"] == "Compliance Exec"
    assert out["gate"]["ready"] and out["gate"]["decided_flags"] == ["V15"]
    audit.assert_awaited_once()


async def test_the_decision_endpoint_refuses_to_waive_a_blocking_problem(mode):
    doc = {**_lifecycle_doc(), "Stage": "Review"}
    body = lr.StandardDecision(check_id="V22", accept=True, reason="A perfectly good reason.")
    with patch("lifecycle.router.get_list_item", new=AsyncMock(return_value={"id": "10", "fields": doc})), \
         patch("lifecycle.router.update_list_item", new=AsyncMock()) as update, \
         patch.object(gate, "evaluate_item", new=AsyncMock(return_value=evaluation(FAILED))):
        with pytest.raises(HTTPException) as e:
            await lr.standard_decision("10", body, user=COMPLIANCE)
    assert e.value.status_code == 422 and "cannot be waived" in e.value.detail
    update.assert_not_awaited()


async def test_a_missing_decisions_column_is_explained_not_swallowed(mode):
    doc = {**_lifecycle_doc(), "Stage": "Review"}
    body = lr.StandardDecision(check_id="V15", accept=True, reason="Combined policy, no separate Purpose.")
    with patch("lifecycle.router.get_list_item", new=AsyncMock(return_value={"id": "10", "fields": doc})), \
         patch("lifecycle.router.update_list_item", new=AsyncMock(side_effect=Exception("field not recognized"))), \
         patch.object(gate, "evaluate_item", new=AsyncMock(return_value=evaluation(json.loads(json.dumps(FLAGGED))))):
        with pytest.raises(HTTPException) as e:
            await lr.standard_decision("10", body, user=COMPLIANCE)
    assert e.value.status_code == 503 and "StandardsDecisions" in e.value.detail


def test_the_decision_endpoint_requires_the_compliance_role():
    from fastapi.testclient import TestClient
    import main
    from auth.validator import get_current_user
    saved = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[get_current_user] = lambda: STAFF
    try:
        r = TestClient(main.app).post("/api/v1/lifecycle/documents/10/standard-decision",
                                      json={"check_id": "V15", "reason": "a perfectly good reason"})
        assert r.status_code == 403
    finally:
        main.app.dependency_overrides.clear(); main.app.dependency_overrides.update(saved)


# ── the real path, from a file to a result ──────────────────────────────────

from doc_standards.checks import Context  # noqa: E402
from doc_standards.convert import convert_document  # noqa: E402
from tests.doc_standards.helpers import master_template, v06_document  # noqa: E402


def _evaluate(file_bytes, fields=None, name="Test Standard.docx"):
    doc = {"id": "7", "SharePointFileUrl": "https://x/Test%20Standard.docx", **(fields or {})}
    return gate.evaluate_item(doc), file_bytes, name


async def _run_evaluate(file_bytes, fields=None, name="Test Standard.docx"):
    gate._cache.clear()
    doc = {"id": "7", "SharePointFileUrl": f"https://x/{name}", **(fields or {})}
    with patch("graph.client.download_file_from_sharepoint", new=AsyncMock(return_value=(file_bytes, "x"))), \
         patch("lifecycle.router._filename_from_sharepoint_url", return_value=name), \
         patch("doc_standards.service.build_context", new=AsyncMock(return_value=(Context(), ["library not read"]))):
        return await gate.evaluate_item(doc)


async def test_a_real_document_is_checked_end_to_end():
    out = await _run_evaluate(v06_document())
    assert out["available"] and out["report"]["document"]["code"] == "DRG-ISMS-STD-TST"
    assert out["gate"]["checks_total"] == 24 and out["context_notes"] == ["library not read"]


async def test_a_cdt_source_is_judged_as_a_reader_will_see_it_not_as_raw_placeholders():
    plan = convert_document(v06_document(), "Test Standard.docx", master_template())
    assert plan.ok
    out = await _run_evaluate(plan.source_bytes, {
        "Title": "Test Standard", "DocumentCode": "DRG-ISMS-STD-TST", "DocumentType": "Standard",
        "CDTCoverFacts": plan.facts.to_json()})
    assert out["available"]
    assert out["report"]["document"]["code"] == "DRG-ISMS-STD-TST"        # the placeholder was filled before checking


async def test_decisions_stored_on_the_item_are_applied_to_the_result():
    plain = await _run_evaluate(v06_document())
    flagged = next(r for r in plain["report"]["results"] if r["status"] == "flag")
    saved = gate.dump_decisions(gate.record_decision(
        {}, plain["report"], flagged["id"], True, "Combined document, accepted by Compliance.", "C", "c"))
    again = await _run_evaluate(v06_document(), {"StandardsDecisions": saved})
    decided = next(r for r in again["report"]["results"] if r["id"] == flagged["id"])
    assert decided["decision"] and flagged["id"] in again["gate"]["decided_flags"]


async def test_no_file_and_an_unreadable_file_are_reported_not_raised():
    gate._cache.clear()
    assert (await gate.evaluate_item({"id": "1"}))["available"] is False
    bad = await _run_evaluate(b"this is not a word document")
    assert bad["available"] is False and bad["unreadable"] is True


async def test_a_result_made_without_its_context_is_never_cached():
    gate._cache.clear()
    await _run_evaluate(v06_document())                       # context had no library/register/catalogue
    assert gate._cache == {}
