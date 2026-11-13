# Extraction Review asks for a reason only when an item is rejected (13 Nov 2026, meeting with
# Compliance): accepting what a document states needs no explanation. "Mark false positive" is
# withdrawn; items already marked keep their status.
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from main import app


def _user():
    return CurrentUser(oid="rev-oid", name="Reviewer", email="r@x", tenant_id="t", roles=["orgos-admin", "compliance"])


PENDING = {"id": "6", "fields": {"ReviewStatus": "Pending Review", "ItemType": "Extraction",
                                 "SourceDocumentCode": "DRG-X-POL-Y"}}


@pytest.fixture(autouse=True)
def _as_compliance():
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[require_compliance_lead] = _user
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def _client():
    return TestClient(app)


def test_a_decision_other_than_reject_needs_no_reason():
    with patch("review_queue.router.get_list_item", new_callable=AsyncMock, return_value=PENDING), \
         patch("review_queue.router.update_list_item", new_callable=AsyncMock) as update:
        resp = _client().patch("/api/v1/queue/items/6/decide", json={"decision": "Route to Owner"})
    assert resp.status_code == 200
    assert update.await_args.args[3]["DecisionRationale"] == ""


def test_reject_through_decide_still_needs_a_reason():
    with patch("review_queue.router.get_list_item", new_callable=AsyncMock, return_value=PENDING), \
         patch("review_queue.router.update_list_item", new_callable=AsyncMock) as update:
        resp = _client().patch("/api/v1/queue/items/6/decide", json={"decision": "Reject", "rationale": "no"})
    assert resp.status_code == 422
    update.assert_not_called()


def test_reject_needs_a_reason_and_records_it():
    with patch("control_register.router._get_queue_item", new_callable=AsyncMock, return_value=PENDING["fields"]), \
         patch("control_register.router.update_list_item", new_callable=AsyncMock) as update, \
         patch("control_register.router._write_audit_log", new_callable=AsyncMock):
        short = _client().post("/api/v1/queue/items/6/reject", json={"rationale": "no"})
        assert short.status_code == 422 and "Say why" in short.json()["detail"]
        update.assert_not_called()
        ok = _client().post("/api/v1/queue/items/6/reject",
                            json={"rationale": "The document does not state this as a control."})
    assert ok.status_code == 200
    assert update.await_args.args[3]["DecisionRationale"] == "The document does not state this as a control."


def test_mark_false_positive_is_withdrawn():
    with patch("review_queue.router.get_list_item", new_callable=AsyncMock, return_value=PENDING), \
         patch("review_queue.router.update_list_item", new_callable=AsyncMock) as update, \
         patch("control_register.router._get_queue_item", new_callable=AsyncMock, return_value=PENDING["fields"]), \
         patch("control_register.router.update_list_item", new_callable=AsyncMock) as cr_update:
        decide = _client().patch("/api/v1/queue/items/6/decide",
                                 json={"decision": "Mark False Positive", "rationale": "Not a real control here."})
        reject = _client().post("/api/v1/queue/items/6/reject",
                                json={"rationale": "Not a real control here.", "reject_type": "Mark False Positive"})
    assert decide.status_code == 422 and reject.status_code == 422
    update.assert_not_called()
    cr_update.assert_not_called()


def test_accepting_a_document_s_controls_together_needs_no_reason():
    from review_queue.router import AcceptDocumentBody
    assert AcceptDocumentBody(document="DRG-QI-STD-CDI").rationale == ""
