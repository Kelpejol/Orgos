# tests/test_document_file_lock.py — a library file someone has locked (outside tests/lifecycle,
# whose fixture replaces document_file.save with a fake library).

from unittest.mock import AsyncMock, patch

import pytest

from lifecycle import document_file
from lifecycle.document_file import DocFile


def _locked(times):
    from graph.exceptions import GraphAPIError
    calls = {"n": 0}

    async def put(drive, item, data):
        calls["n"] += 1
        if calls["n"] <= times:
            raise GraphAPIError(423, "resourceLocked")
        return {"id": item, "name": "Doc.docx", "parentReference": {"driveId": drive}, "cTag": "c2"}
    return put, calls


async def test_a_lock_that_clears_a_moment_later_is_waited_out():
    put, calls = _locked(1)
    f = DocFile(drive_id="d", item_id="i", name="Doc.docx", web_url="u")
    with patch.object(document_file.gc, "replace_drive_item_content", new=AsyncMock(side_effect=put)), \
         patch.object(document_file, "_LOCK_WAITS", (0, 0)):
        saved = await document_file.save(f, b"x")
    assert calls["n"] == 2 and saved.item_id == "i"


async def test_a_file_still_locked_is_refused_and_says_why():
    put, _ = _locked(99)
    f = DocFile(drive_id="d", item_id="i", name="Doc.docx", web_url="u")
    meta = {"publication": {"level": "checkout"}, "lastModifiedBy": {"user": {"displayName": "Ada"}},
            "lastModifiedDateTime": "2026-11-11T09:30:00Z"}
    with patch.object(document_file.gc, "replace_drive_item_content", new=AsyncMock(side_effect=put)), \
         patch.object(document_file.gc, "get_drive_item", new=AsyncMock(return_value=meta)), \
         patch.object(document_file, "_LOCK_WAITS", (0, 0)):
        with pytest.raises(document_file.FileLocked) as e:
            await document_file.save(f, b"x")
    assert "checked out" in str(e.value) and "Check in" in str(e.value) and "Ada" in str(e.value)

    meta["publication"] = {"level": "published"}
    with patch.object(document_file.gc, "replace_drive_item_content", new=AsyncMock(side_effect=put)), \
         patch.object(document_file.gc, "get_drive_item", new=AsyncMock(return_value=meta)), \
         patch.object(document_file, "_LOCK_WAITS", (0, 0)):
        with pytest.raises(document_file.FileLocked) as e:
            await document_file.save(f, b"x")
    assert "open for editing in Word" in str(e.value)
