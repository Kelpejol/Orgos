# Where a control's document states no record schedule, Compliance sets it in Extraction Review;
# it is kept on the control, audited, and its records take it at once. A schedule the document
# states changes only in the document. (13 Nov 2026)
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import control_register.router as cr
from auth.validator import CurrentUser

USER = CurrentUser(oid="u", name="Victoria", email="v@x", tenant_id="t", roles=["compliance"])


def _control(trigger):
    definition = {"control_id": "ICX-002", "requirement": "Each issue is classified.", "trigger": trigger,
                  "evidence": [{"record_id": "REC-0277", "name": "Context Analysis Record"}],
                  "defined_in": {"code": "DRG-QI-PRO-ICX", "title": "Strategic Context Procedure"}}
    return {"id": "3", "fields": {"ControlId": "ICX-002", "DefinitionJson": json.dumps(definition)}}


async def _set(trigger, days):
    item = _control(trigger)
    with patch.object(cr, "get_list_item", new=AsyncMock(return_value=item)), \
         patch.object(cr, "update_list_item", new=AsyncMock()) as update, \
         patch("audit.trail.record", new=AsyncMock()) as audit, \
         patch("evidence.service.sync_obligations", new=AsyncMock()) as sync, \
         patch("evidence.service.start_clocks", new=AsyncMock()) as clocks:
        try:
            await cr.set_record_schedule("3", cr.RecordScheduleBody(days=days), user=USER)
        except HTTPException as exc:
            return exc, update, audit, sync, clocks
    return None, update, audit, sync, clocks


async def test_compliance_sets_the_schedule_the_document_leaves_out():
    error, update, audit, sync, clocks = await _set("Each issue entered in the record", 91)
    assert error is None
    assert update.await_args.args[3] == {"RecordScheduleDays": 91, "RecordScheduleSetBy": "Victoria"}
    audit.assert_awaited_once()
    sync.assert_awaited_once() and clocks.assert_awaited_once()


async def test_a_schedule_the_document_states_is_changed_in_the_document():
    error, update, *_ = await _set("Quarterly ExCo session", 30)
    assert error.status_code == 409 and "Strategic Context Procedure" in error.detail
    update.assert_not_called()


@pytest.mark.parametrize("days", [0, -1, 4000])
async def test_a_schedule_is_a_sensible_number_of_days(days):
    error, update, *_ = await _set("Each issue", days)
    assert error.status_code == 422
    update.assert_not_called()
