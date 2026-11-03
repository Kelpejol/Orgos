# =============================================================================
# tests/lifecycle/test_edit_in_word.py — editing a document in Word for the web
#
# A document has one file, in the library. "Edit in Word" opens THAT file: nothing
# is copied, and the item keeps pointing at the same file.
# =============================================================================

import io
from unittest.mock import AsyncMock, patch

import pytest
from docx import Document
from fastapi import HTTPException

import lifecycle.router as lr
from auth.validator import CurrentUser

OWNER = CurrentUser(oid="owner", name="Owner", email="o@x", tenant_id="t", roles=[])
OTHER = CurrentUser(oid="other", name="Other", email="x@x", tenant_id="t", roles=[])

FILE = "https://x.sharepoint.com/sites/everybody/_layouts/15/Doc.aspx?sourcedoc=%7BA%7D&file=IDL.docx&action=default"


def _word() -> bytes:
    buf = io.BytesIO()
    Document().save(buf)
    return buf.getvalue()


def item(stage="Review", url=FILE):
    return {"fields": {"Stage": stage, "OwnerEntraId": "owner", "SharePointFileUrl": url,
                       "DocumentCode": "DRG-ISMS-STD-IDL", "Title": "Identity Lifecycle Standard"}}


async def _open(lifecycle_item, user=OWNER):
    with patch.object(lr, "get_list_item", new=AsyncMock(return_value=lifecycle_item)), \
         patch.object(lr, "update_list_item", new=AsyncMock()) as update:
        result = await lr.open_for_editing("42", user)
    return result, update


async def test_the_library_file_itself_is_opened_never_a_copy(library):
    library.add(FILE, _word(), "IDL.docx")
    result, _update = await _open(item())
    assert result["file_url"] == FILE and "action=edit" in result["edit_url"]
    assert library.created == [] and library.saves == []


async def test_only_word_files_can_be_edited(library):
    library.add(FILE, b"%PDF-1.4", "IDL.pdf")
    with pytest.raises(HTTPException) as e:
        await _open(item())
    assert e.value.status_code == 422


async def test_only_in_review_and_only_by_the_owner_or_compliance(library):
    library.add(FILE, _word(), "IDL.docx")
    with pytest.raises(HTTPException) as e:
        await _open(item(stage="Approval"))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        await _open(item(), user=OTHER)
    assert e.value.status_code == 403


def test_a_plain_file_link_opens_in_the_browser():
    assert lr._office_edit_url("https://x/sites/o/Library/IDL.docx").endswith("?web=1")


async def test_a_word_file_stored_without_an_extension_is_renamed_in_place(library):
    library.add(FILE, _word(), "octet-stream")
    result, _update = await _open(item())
    assert library.files[FILE]["name"] == "Identity Lifecycle Standard.docx"
    assert library.created == [] and "action=edit" in result["edit_url"]


async def test_a_file_that_is_not_word_is_still_refused_whatever_it_is_called(library):
    library.add(FILE, b"%PDF-1.4", "octet-stream")
    with pytest.raises(HTTPException) as e:
        await _open(item())
    assert e.value.status_code == 422
