# =============================================================================
# tests/lifecycle/test_role_fix_endpoint.py — "Use this role" on a Lifecycle item
#
# The change is made on the item's own working copy, only to a role that exists
# in Org Roles, and is refused rather than guessed when nothing could be changed.
# =============================================================================

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import lifecycle.router as lr
from auth.validator import CurrentUser
from tests.cdi.builders import DocBuilder

OWNER = CurrentUser(oid="owner", name="Owner", email="o@x", tenant_id="t", roles=[])
COPY = "https://x.sharepoint.com/sites/orgos/_layouts/15/Doc.aspx?sourcedoc=%7BB%7D&file=IDL.docx&action=default"
OLD, NEW = "Info Sec Officer", "Information Security Officer"
GROUPS = [{"id": "g1", "name": NEW, "aliases": [], "description": ""}]


def doc_bytes():
    b = DocBuilder()
    b.control_block(title="T", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="Chief Compliance Officer", first_pass="Chief Compliance Officer",
                    final_approval="Chief Compliance Officer", classification="c")
    b.control("TST-01", "One", requirement="The Info Sec Officer shall review it.", trigger="Creation.")
    b.para(f"Control owner: {OLD}.")
    return b.bytes()


async def _fix(to_role=NEW, from_role=OLD, data=None, cover=""):
    item = {"fields": {"Stage": "Review", "OwnerEntraId": "owner", "SharePointFileUrl": COPY,
                       "DocumentCode": "DRG-ISMS-STD-TST", "CDTCoverFacts": cover}}
    meta = {"name": "IDL.docx", "webUrl": COPY, "parentReference": {"path": "/drives/d/root:/Lifecycle Documents/42"}}
    with patch.object(lr, "get_list_item", new=AsyncMock(return_value=item)), \
         patch.object(lr, "sharepoint_item_metadata", new=AsyncMock(return_value=meta)), \
         patch.object(lr, "download_file_from_sharepoint", new=AsyncMock(return_value=(data or doc_bytes(), "x"))), \
         patch.object(lr, "_upload_to_sharepoint", new=AsyncMock(return_value=COPY)) as upload, \
         patch.object(lr, "update_list_item", new=AsyncMock()) as update, \
         patch.object(lr, "_audit_lifecycle_action", new=AsyncMock()) as audit, \
         patch("groups.service.list_groups", new=AsyncMock(return_value=GROUPS)):
        result = await lr.role_fix("42", lr.RoleFixBody(from_role=from_role, to_role=to_role), OWNER)
    return result, upload, update, audit


async def test_the_role_is_changed_on_the_working_copy_and_audited():
    result, upload, update, audit = await _fix()
    assert result["changed"] >= 1 and result["to_role"] == NEW
    name, saved = upload.await_args.args[1], upload.await_args.args[2]
    assert name == "IDL.docx" and saved != doc_bytes()
    audit.assert_awaited_once()


async def test_the_canonical_name_is_used_not_the_callers_spelling():
    result, upload, *_ = await _fix(to_role="information security officer")
    assert result["to_role"] == NEW


async def test_a_role_that_is_not_in_org_roles_is_refused():
    with pytest.raises(HTTPException) as e:
        await _fix(to_role="Chief Wizard")
    assert e.value.status_code == 422


async def test_nothing_found_is_said_not_silently_ignored():
    with pytest.raises(HTTPException) as e:
        await _fix(from_role="Someone Not In It")
    assert e.value.status_code == 409
