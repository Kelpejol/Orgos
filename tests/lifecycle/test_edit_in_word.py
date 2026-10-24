# =============================================================================
# tests/lifecycle/test_edit_in_word.py — editing a document in Word for the web
#
# Editing happens on the item's own working copy: the approved published file
# (a revision's starting point) and a library draft are never edited in place.
# =============================================================================

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import lifecycle.router as lr
from auth.validator import CurrentUser

OWNER = CurrentUser(oid="owner", name="Owner", email="o@x", tenant_id="t", roles=[])
OTHER = CurrentUser(oid="other", name="Other", email="x@x", tenant_id="t", roles=[])

APPROVED = "https://x.sharepoint.com/sites/orgos/_layouts/15/Doc.aspx?sourcedoc=%7BA%7D&file=IDL.docx&action=default"
COPY = "https://x.sharepoint.com/sites/orgos/_layouts/15/Doc.aspx?sourcedoc=%7BB%7D&file=IDL.docx&action=default"


def item(stage="Review", url=APPROVED):
    return {"fields": {"Stage": stage, "OwnerEntraId": "owner", "SharePointFileUrl": url,
                       "DocumentCode": "DRG-ISMS-STD-IDL"}}


def meta(folder_item_id, name="IDL.docx"):
    return {"name": name, "webUrl": COPY,
            "parentReference": {"path": f"/drives/d/root:/Lifecycle Documents/{folder_item_id}"}}


async def _open(lifecycle_item, metadata, user=OWNER):
    with patch.object(lr, "get_list_item", new=AsyncMock(return_value=lifecycle_item)), \
         patch.object(lr, "sharepoint_item_metadata", new=AsyncMock(return_value=metadata)), \
         patch.object(lr, "download_file_from_sharepoint", new=AsyncMock(return_value=(b"docx", "x"))), \
         patch.object(lr, "_upload_to_sharepoint", new=AsyncMock(return_value=COPY)) as upload, \
         patch.object(lr, "update_list_item", new=AsyncMock()) as update, \
         patch.object(lr, "_audit_lifecycle_action", new=AsyncMock()):
        result = await lr.open_for_editing("42", user)
    return result, upload, update


async def test_a_revision_edits_a_copy_never_the_approved_file():
    result, upload, update = await _open(item(), meta(folder_item_id="7"))   # the approved item's folder
    upload.assert_awaited_once_with("42", "IDL.docx", b"docx")
    assert update.await_args.args[3] == {"SharePointFileUrl": COPY}
    assert "action=edit" in result["edit_url"]


async def test_the_working_copy_is_reused():
    result, upload, update = await _open(item(url=COPY), meta(folder_item_id="42"))
    upload.assert_not_awaited() and update.assert_not_awaited()
    assert "action=edit" in result["edit_url"]


async def test_only_word_files_can_be_edited():
    with pytest.raises(HTTPException) as e:
        await _open(item(), meta(folder_item_id="7", name="IDL.pdf"))
    assert e.value.status_code == 422


async def test_only_in_review_and_only_by_the_owner_or_compliance():
    with pytest.raises(HTTPException) as e:
        await _open(item(stage="Approval"), meta("42"))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        await _open(item(), meta("42"), user=OTHER)
    assert e.value.status_code == 403


def test_a_plain_file_link_opens_in_the_browser():
    assert lr._office_edit_url("https://x/sites/o/Lifecycle%20Documents/42/IDL.docx").endswith("?web=1")


async def test_a_word_file_stored_without_an_extension_still_opens_as_a_properly_named_copy():
    import io
    from docx import Document
    buf = io.BytesIO(); Document().save(buf)
    meta_bad = {"name": "octet-stream", "webUrl": APPROVED,
                "parentReference": {"path": "/drives/d/root:/Lifecycle Documents/7/application"}}
    with patch.object(lr, "get_list_item", new=AsyncMock(return_value=item())), \
         patch.object(lr, "sharepoint_item_metadata", new=AsyncMock(return_value=meta_bad)), \
         patch.object(lr, "download_file_from_sharepoint", new=AsyncMock(return_value=(buf.getvalue(), "x"))), \
         patch.object(lr, "_upload_to_sharepoint", new=AsyncMock(return_value=COPY)) as upload, \
         patch.object(lr, "update_list_item", new=AsyncMock()), \
         patch.object(lr, "_audit_lifecycle_action", new=AsyncMock()):
        result = await lr.open_for_editing("42", OWNER)
    assert upload.await_args.args[1] == "DRG-ISMS-STD-IDL.docx" and "action=edit" in result["edit_url"]


async def test_a_file_that_is_not_word_is_still_refused_whatever_it_is_called():
    meta_bad = {"name": "octet-stream", "webUrl": APPROVED, "parentReference": {"path": "x/7"}}
    with pytest.raises(HTTPException) as e:
        with patch.object(lr, "get_list_item", new=AsyncMock(return_value=item())), \
             patch.object(lr, "sharepoint_item_metadata", new=AsyncMock(return_value=meta_bad)), \
             patch.object(lr, "download_file_from_sharepoint", new=AsyncMock(return_value=(b"%PDF-1.4", "x"))):
            await lr.open_for_editing("42", OWNER)
    assert e.value.status_code == 422


async def test_an_upload_name_with_a_slash_cannot_make_a_phantom_folder():
    sent = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"webUrl": "u"}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def put(self, url, **k): sent["url"] = url; return FakeResp()

    with patch.object(lr, "get_graph_access_token", new=AsyncMock(return_value="t")), \
         patch.object(lr.httpx, "AsyncClient", FakeClient):
        await lr._upload_to_sharepoint("9", "application/octet-stream", b"not a zip")
    assert "/9/octet-stream:/content" in sent["url"] and "application/" not in sent["url"]
