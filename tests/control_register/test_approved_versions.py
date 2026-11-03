# =============================================================================
# tests/control_register/test_approved_versions.py — the approved library reads a
# document AS APPROVED
#
# A document has one file. While a revision is in progress (or someone edits the
# file in SharePoint) the file holds unapproved work; the approved library must
# read the version approval recorded, never the draft.
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

from control_register import approved_library as al

STATE = {"drive": "d", "item": "i", "ctag": "c-approved", "approved_version": "4.0"}


async def test_an_unchanged_file_is_read_as_it_is():
    with patch("graph.client.get_drive_item", new=AsyncMock(return_value={"cTag": "c-approved"})), \
         patch("graph.client.download_drive_item", new=AsyncMock(return_value=b"APPROVED")) as current, \
         patch("graph.client.download_drive_item_version", new=AsyncMock()) as version:
        assert await al._approved_bytes("u", STATE) == b"APPROVED"
    current.assert_awaited_once() and version.assert_not_awaited()


async def test_a_file_changed_since_approval_is_read_at_the_approved_version():
    with patch("graph.client.get_drive_item", new=AsyncMock(return_value={"cTag": "c-draft"})), \
         patch("graph.client.download_drive_item", new=AsyncMock(return_value=b"DRAFT")), \
         patch("graph.client.download_drive_item_version", new=AsyncMock(return_value=b"APPROVED")) as version:
        assert await al._approved_bytes("u", STATE) == b"APPROVED"
    version.assert_awaited_once_with("d", "i", "4.0")


async def test_without_a_record_the_file_is_read_as_it_is():
    with patch("graph.client.download_file_from_sharepoint", new=AsyncMock(return_value=(b"FILE", "x"))):
        assert await al._approved_bytes("u", {}) == b"FILE"


async def test_the_latest_approval_of_each_register_entry_is_used():
    old = {"drive": "d", "item": "i", "approved_version": "2.0"}
    items = [
        {"fields": {"ApprovalStatus": "Approved", "LinkedDocumentRegisterItem": "7", "ApprovedDate": "2026-01-01",
                    "FileState": json.dumps(old)}},
        {"fields": {"ApprovalStatus": "Approved", "LinkedDocumentRegisterItem": "7", "ApprovedDate": "2026-10-01",
                    "FileState": json.dumps(STATE)}},
        {"fields": {"Stage": "Review", "LinkedDocumentRegisterItem": "7", "FileState": json.dumps({"item": "i"})}},
    ]
    with patch.object(al.settings, "document_lifecycle_list_id", "lifecycle-list"), \
         patch("graph.client.get_list_items", new=AsyncMock(return_value=items)):
        files = await al._approved_files()
    assert files == {"7": STATE}
