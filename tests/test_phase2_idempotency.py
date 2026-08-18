# =============================================================================
# tests/test_phase2_idempotency.py — Phase 2 idempotency / state guards
#
# Covers: Zone 1 decide is blocked once an item is already decided (no
# duplicate cascade); extraction skips already-queued statements on re-run;
# evidence submit/verify enforce state transitions.
# =============================================================================

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import agents.extractor.service as es
from agents.extractor.ollama_client import DocumentType
from auth.validator import CurrentUser, get_current_user
from main import app


def _override_user():
    return CurrentUser(oid="rev-oid", name="Reviewer", email="r@dragnet.com",
                       tenant_id="t", roles=["OrgOS.Admin", "Compliance.Lead"])


app.dependency_overrides[get_current_user] = _override_user
client = TestClient(app)


# -----------------------------------------------------------------------------
#  Zone 1 decide idempotency (I1)
# -----------------------------------------------------------------------------

def test_zone1_decide_blocks_already_decided_item_no_cascade():
    decided = {"id": "5", "fields": {"ReviewStatus": "Accepted", "ItemType": "Extraction",
                                     "SourceDocumentCode": "DRG-X-POL-Y-01-26"}}
    with patch("review_queue.router.get_list_item", new_callable=AsyncMock, return_value=decided), \
         patch("review_queue.router.create_list_item", new_callable=AsyncMock) as mk_create, \
         patch("review_queue.router.update_list_item", new_callable=AsyncMock) as mk_update:
        resp = client.patch("/api/v1/queue/items/5/decide",
                            json={"decision": "Accept", "rationale": "looks correct"})
    assert resp.status_code == 409
    mk_create.assert_not_called()   # cascade never ran → no duplicate records
    mk_update.assert_not_called()


def test_zone1_decide_allows_decidable_item():
    pending = {"id": "6", "fields": {"ReviewStatus": "Pending Review", "ItemType": "Extraction",
                                     "SourceDocumentCode": "DRG-X-POL-Y-01-26"}}
    with patch("review_queue.router.get_list_item", new_callable=AsyncMock, return_value=pending), \
         patch("review_queue.router.update_list_item", new_callable=AsyncMock) as mk_update:
        # "Route to Owner" is a non-cascade decision — should proceed and update.
        resp = client.patch("/api/v1/queue/items/6/decide",
                            json={"decision": "Route to Owner", "rationale": "needs owner input"})
    assert resp.status_code == 200
    mk_update.assert_awaited()      # the guard allowed the decision through


# -----------------------------------------------------------------------------
#  Extraction write dedupe (I2)
# -----------------------------------------------------------------------------

async def test_write_to_queue_skips_already_queued_statements():
    items = [
        {"control_statement": "The team shall log all calls", "completeness_flag": "COMPLETE"},
        {"control_statement": "Access shall be reviewed quarterly", "completeness_flag": "COMPLETE"},
    ]
    existing = [{"fields": {"Title": "The team shall log all calls"}}]  # first item already queued
    with patch("graph.client.get_list_items", new_callable=AsyncMock, return_value=existing), \
         patch("graph.client.create_list_item", new_callable=AsyncMock, return_value={"id": "1"}) as mk:
        written = await es._write_to_queue(items, "DRG-X-POL-Y-01-26", DocumentType.POLICY)
    assert written == 1             # only the non-duplicate was written
    assert mk.await_count == 1


# -----------------------------------------------------------------------------
#  Evidence state-transition guards (I7)
# -----------------------------------------------------------------------------

def test_submit_evidence_blocked_when_already_accepted():
    accepted = {"id": "9", "fields": {"Status": "Accepted"}}
    with patch("evidence_tracker.router.get_list_item", new_callable=AsyncMock, return_value=accepted), \
         patch("evidence_tracker.router.update_list_item", new_callable=AsyncMock) as mk_update:
        resp = client.patch("/api/v1/evidence/9/submit", json={"evidence_link": "https://x/y"})
    assert resp.status_code == 409
    mk_update.assert_not_called()


def test_verify_evidence_requires_submitted_state():
    pending = {"id": "9", "fields": {"Status": "Pending"}}
    with patch("evidence_tracker.router.get_list_item", new_callable=AsyncMock, return_value=pending), \
         patch("evidence_tracker.router.update_list_item", new_callable=AsyncMock) as mk_update:
        resp = client.patch("/api/v1/evidence/9/verify", json={"accepted": True})
    assert resp.status_code == 409
    mk_update.assert_not_called()
