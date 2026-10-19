# =============================================================================
# tests/control_register/test_status_recheck.py — role changes re-check controls
# =============================================================================

from unittest.mock import AsyncMock, patch

import control_register.status as st
from tests.control_register.test_library_sync import confirmed_register, library


class _Owners:
    def __init__(self, kind):
        self.kind = kind

    def resolve(self, role):
        return {"kind": self.kind}


async def _recheck(register, kind):
    with patch.object(type(st.settings), "is_list_configured", lambda self, list_id: True), \
         patch("graph.client.get_list_items", new=AsyncMock(return_value=register)), \
         patch("ownership.resolver.get_ownership_index", new=AsyncMock(return_value=_Owners(kind))) as idx, \
         patch("control_register.sync.apply_sync", new=AsyncMock(return_value=[])) as write:
        result = await st.recheck_control_statuses()
    return result, write, idx


async def test_a_blocked_control_turns_active_once_its_role_is_a_group():
    result, write, idx = await _recheck(confirmed_register(library(), status="Blocked"), "group")
    assert result["changed"] == 2 and all("Active" in d for d in result["detail"])
    assert idx.await_args.kwargs == {"force": True}         # sees the change just made
    [plan] = write.await_args.args
    assert {a.kind for a in plan.actions} == {"refresh_status"}


async def test_a_role_that_is_still_only_a_job_title_stays_blocked():
    result, _, _ = await _recheck(confirmed_register(library(), status="Blocked"), "job_title")
    assert all(d.endswith("Blocked") for d in result["detail"])     # only the reason is filled in


async def test_a_status_a_person_set_is_left_alone():
    result, _, _ = await _recheck(confirmed_register(library(), status="Under Review"), "group")
    assert result["changed"] == 0
