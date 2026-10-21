# =============================================================================
# tests/lifecycle/test_stale_cdi_gate.py — a stored CDI result never outlives
# the checker that wrote it
# =============================================================================

from unittest.mock import AsyncMock, patch

import lifecycle.router as lr


async def _refresh(doc, result):
    with patch.object(lr, "download_file_from_sharepoint", new=AsyncMock(return_value=(b"x", "x"))), \
         patch.object(lr, "_cdi_check_file", new=AsyncMock(return_value=result)), \
         patch.object(lr, "update_list_item", new=AsyncMock()) as update:
        await lr._refresh_stale_cdi("42", doc)
    return update


async def test_a_day_one_failure_the_current_checker_no_longer_raises_clears():
    doc = {"SharePointFileUrl": "https://x/IDL.docx", "CDIStatus": "Failed", "CDIFailures": "[old]"}
    update = await _refresh(doc, ("Passed", ""))
    assert doc["CDIStatus"] == "Passed" and doc["CDIFailures"] == ""
    assert update.await_args.args[3] == {"CDIStatus": "Passed", "CDIFailures": ""}


async def test_a_real_failure_stays_failed():
    doc = {"SharePointFileUrl": "https://x/IDL.docx", "CDIStatus": "Failed", "CDIFailures": "[old]"}
    await _refresh(doc, ("Failed", "[current]"))
    assert doc["CDIStatus"] == "Failed" and doc["CDIFailures"] == "[current]"


async def test_a_checker_error_is_not_a_verdict():
    doc = {"SharePointFileUrl": "https://x/IDL.docx", "CDIStatus": "Failed", "CDIFailures": "[old]"}
    update = await _refresh(doc, ("Error", "[err]"))
    assert doc["CDIStatus"] == "Failed"
    update.assert_not_awaited()


async def test_an_unfetchable_file_keeps_the_stored_result():
    doc = {"SharePointFileUrl": "https://x/IDL.docx", "CDIStatus": "Failed"}
    with patch.object(lr, "download_file_from_sharepoint", new=AsyncMock(side_effect=RuntimeError("down"))):
        await lr._refresh_stale_cdi("42", doc)
    assert doc["CDIStatus"] == "Failed"
