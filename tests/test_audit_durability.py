# =============================================================================
# tests/test_audit_durability.py — audit-log durability (R4)
#
# An audit-log write failure must NOT block the decision, but must NOT be
# silent either: control_register._write_audit_log returns False and records a
# visible gap marker on the decided item's CascadeResult.
# =============================================================================

from unittest.mock import AsyncMock, patch

import pytest

import control_register.router as cr
from auth.validator import CurrentUser

USER = CurrentUser(oid="oid-1", name="Reviewer", email="r@dragnet.com",
                   tenant_id="t", roles=["OrgOS.Admin"])

_ARGS = dict(item_id="42", item_type="Extraction", zone="1", ai_confidence=0.9,
             decision="Accept", rationale="looks good", cascade_result="Control Register: 5",
             state_from="Pending Review", state_to="Active")


async def test_audit_write_success_returns_true():
    with patch("control_register.router.create_list_item", new=AsyncMock(return_value={"id": "1"})):
        ok = await cr._write_audit_log(USER, **_ARGS)
    assert ok is True


async def test_audit_write_failure_returns_false_and_flags_item():
    with patch("control_register.router.create_list_item", new=AsyncMock(side_effect=Exception("boom"))), \
         patch("control_register.router.get_list_item",
               new=AsyncMock(return_value={"fields": {"CascadeResult": "Control Register: 5"}})), \
         patch("control_register.router.update_list_item", new=AsyncMock()) as upd:
        ok = await cr._write_audit_log(USER, **_ARGS)

    assert ok is False
    upd.assert_awaited_once()
    written_fields = upd.await_args.args[3]                 # (list_id, name, item_id, fields)
    assert "AUDIT LOG NOT WRITTEN" in written_fields["CascadeResult"]
    assert "Control Register: 5" in written_fields["CascadeResult"]  # existing content preserved
