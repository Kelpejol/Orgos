# =============================================================================
# tests/doc_standards/test_router.py — the Document Standards API
#
# Run through the real app and its real permission checks. What matters here:
# everyone may read the standard and check a document (nothing is written);
# only Compliance may convert; a conversion is only applied to a document still
# in Review; and the original file is never the one that gets changed.
# =============================================================================

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import doc_standards.router as drouter
import main
from auth.validator import ROLE_COMPLIANCE, CurrentUser, get_current_user
from doc_standards.checks import Context
from tests.doc_standards.helpers import master_template, v06_document

STAFF = CurrentUser(oid="staff", name="Staff", email="s@x", tenant_id="t", roles=[])
COMPLIANCE = CurrentUser(oid="comp", name="Compliance", email="c@x", tenant_id="t", roles=[ROLE_COMPLIANCE])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client():
    # Restore, never clear: the rest of the suite relies on overrides it set up itself.
    saved = dict(main.app.dependency_overrides)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(saved)


def as_user(user):
    main.app.dependency_overrides[get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def no_network():
    with patch("doc_standards.service.build_context", new=AsyncMock(return_value=(Context(), ["library not read"]))), \
         patch("lifecycle.templates.load_master_template", new=AsyncMock(return_value=master_template())):
        yield


def upload(name="Test Standard.docx", data=None, **extra):
    return {"file": (name, data if data is not None else v06_document(), DOCX)}, extra


# ── the standard and the check: for everyone ────────────────────────────────

def test_everyone_can_read_the_standard(client):
    as_user(STAFF)
    body = client.get("/api/v1/doc-standards/standard").json()
    assert body["total"] == 24 and 0 < body["built"] < 24
    assert {t["code"] for t in body["types"]} >= {"POL", "STD", "PRO"}
    unbuilt = [c for c in body["checks"] if not c["built"]]
    assert unbuilt and all(c["needs"] for c in unbuilt)          # nothing "not built" without saying what it needs


def test_anyone_can_check_a_document_and_nothing_is_written(client):
    as_user(STAFF)
    files, _ = upload()
    r = client.post("/api/v1/doc-standards/check", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["document"]["code"] == "DRG-ISMS-STD-TST" and len(body["results"]) == 24
    assert body["context_notes"] == ["library not read"]


@pytest.mark.parametrize("name,data,status", [
    ("notes.txt", b"hello", 422), ("empty.docx", b"", 422), ("broken.docx", b"not a zip", 422)])
def test_a_bad_upload_is_refused_plainly(client, name, data, status):
    as_user(STAFF)
    r = client.post("/api/v1/doc-standards/check", files={"file": (name, data, DOCX)})
    assert r.status_code == status and r.json()["detail"]


def test_an_oversized_file_is_refused(client, monkeypatch):
    as_user(STAFF)
    monkeypatch.setattr(drouter, "MAX_BYTES", 10)
    assert client.post("/api/v1/doc-standards/check", files=upload()[0]).status_code == 413


# ── conversion: Compliance only ─────────────────────────────────────────────

def test_a_standard_user_cannot_convert_anything(client):
    as_user(STAFF)
    files, _ = upload()
    for path in ("preview", "download"):
        assert client.post(f"/api/v1/doc-standards/convert/{path}", files=files).status_code == 403
    assert client.post("/api/v1/doc-standards/convert/apply", json={"item_id": "1"}).status_code == 403


def test_compliance_previews_a_conversion_with_every_proof(client):
    as_user(COMPLIANCE)
    r = client.post("/api/v1/doc-standards/convert/preview", files=upload()[0])
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and {p["name"] for p in body["proofs"]} == {"body", "removed", "reads-same", "sound", "merges"}
    assert body["source"] == {"kind": "upload"} and body["taken_out"] and "cover" in body


def test_a_refused_document_is_explained_not_errored(client):
    as_user(COMPLIANCE)
    r = client.post("/api/v1/doc-standards/convert/preview",
                    files=upload(data=v06_document(code="DRG-QI-REG-RRS"))[0])
    assert r.status_code == 200 and r.json()["ok"] is False and "no master template" in r.json()["reason"]


def test_preview_needs_exactly_one_source(client):
    as_user(COMPLIANCE)
    assert client.post("/api/v1/doc-standards/convert/preview").status_code == 422


def test_download_gives_the_reading_copy_or_the_source_and_refuses_a_failed_conversion(client):
    as_user(COMPLIANCE)
    reading = client.post("/api/v1/doc-standards/convert/download", files=upload()[0], data={"kind": "reading"})
    source = client.post("/api/v1/doc-standards/convert/download", files=upload()[0], data={"kind": "source"})
    assert reading.status_code == source.status_code == 200
    assert b"{{" not in reading.content and reading.content != source.content
    assert "Test Standard (reading copy).docx" in reading.headers["content-disposition"]
    assert client.post("/api/v1/doc-standards/convert/download", files=upload()[0], data={"kind": "x"}).status_code == 422
    bad = client.post("/api/v1/doc-standards/convert/download",
                      files=upload(data=v06_document(code="Not assigned"))[0], data={"kind": "reading"})
    assert bad.status_code == 422


# ── apply: only a document in Review; never the original file ───────────────

ITEM = {"Stage": "Review", "ApprovalStatus": "", "SharePointFileUrl": "https://x/orig/Test%20Standard.docx",
        "DocumentCode": "DRG-ISMS-STD-TST", "CDTCoverFacts": ""}


def apply_patches(fields):
    return (
        patch("graph.client.get_list_item", new=AsyncMock(return_value={"fields": fields})),
        patch("graph.client.download_file_from_sharepoint", new=AsyncMock(return_value=(v06_document(), DOCX))),
        patch("lifecycle.router._upload_to_sharepoint", new=AsyncMock(return_value="https://x/copy/Test Standard.docx")),
        patch("graph.client.update_list_item", new=AsyncMock()),
        patch("lifecycle.router._cdi_check_file", new=AsyncMock(return_value=("Passed", ""))),
        patch("lifecycle.router._audit_lifecycle_action", new=AsyncMock()),
        patch("lifecycle.router._sp_to_doc", new=AsyncMock(return_value={"id": "7"})),
    )


def run_apply(client, fields):
    from contextlib import ExitStack
    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in apply_patches(fields)]
        r = client.post("/api/v1/doc-standards/convert/apply", json={"item_id": "7"})
    return r, mocks


def test_apply_converts_a_review_item_into_its_own_working_copy(client):
    as_user(COMPLIANCE)
    r, (_, _, upload_mock, update_mock, cdi_mock, audit_mock, _) = run_apply(client, ITEM)
    assert r.status_code == 200 and r.json()["ok"]
    upload_mock.assert_awaited_once()
    assert upload_mock.await_args.args[:2] == ("7", "Test Standard.docx")       # named as its title (V23)
    first_update = update_mock.await_args_list[0].args[3]
    assert first_update["SharePointFileUrl"] == "https://x/copy/Test Standard.docx"   # a new file, not the original
    assert '"version":"Draft"' in first_update["CDTCoverFacts"].replace(" ", "")
    assert first_update["Title"] == "Test Standard" and first_update["Revised"] is True
    audit_mock.assert_awaited_once()
    assert "original file is unchanged" in audit_mock.await_args.args[3]


def test_apply_refuses_a_document_that_is_no_longer_in_review(client):
    as_user(COMPLIANCE)
    r, (_, _, upload_mock, *_) = run_apply(client, {**ITEM, "Stage": "Approval"})
    assert r.status_code == 409
    upload_mock.assert_not_awaited()


def test_apply_refuses_when_the_item_and_the_document_disagree_about_the_code(client):
    as_user(COMPLIANCE)
    r, (_, _, upload_mock, *_) = run_apply(client, {**ITEM, "DocumentCode": "DRG-ISMS-STD-OTHER"})
    assert r.status_code == 422 and "DRG-ISMS-STD-OTHER" in r.json()["detail"]["message"]
    upload_mock.assert_not_awaited()


def test_apply_does_nothing_when_a_proof_fails(client):
    as_user(COMPLIANCE)
    with patch("doc_standards.service.convert_document", side_effect=lambda *a, **k: __import__(
            "doc_standards.convert", fromlist=["ConversionPlan"]).ConversionPlan(ok=False, reason="a proof failed")):
        r, (_, _, upload_mock, update_mock, *_) = run_apply(client, ITEM)
    assert r.status_code == 422
    upload_mock.assert_not_awaited() and update_mock.assert_not_awaited()


# ── "Keep my wording": agree a spelling as an alias of an existing role ───────────────

async def test_role_alias_is_saved_for_an_existing_role():
    from unittest.mock import AsyncMock, patch
    from doc_standards import router as r
    groups = [{"id": "g1", "name": "Information Security Officer", "aliases": [], "description": ""}]
    saved = {**groups[0], "aliases": ["ISO Lead"]}
    with patch("groups.service.list_groups", new=AsyncMock(return_value=groups)), \
         patch("groups.service.update_group", new=AsyncMock(return_value=saved)) as upd, \
         patch("control_register.status.recheck_soon"):
        out = await r.add_role_alias(r.RoleAlias(group_id="g1", alias="ISO  Lead"), None)
    assert out["ok"] and upd.await_args.args[4] == ["ISO Lead"]


async def test_role_alias_refuses_a_field_name_and_a_spelling_that_belongs_to_another_role():
    import pytest
    from unittest.mock import AsyncMock, patch
    from fastapi import HTTPException
    from doc_standards import router as r
    groups = [{"id": "g1", "name": "A Role", "aliases": [], "description": ""},
              {"id": "g2", "name": "Other Role", "aliases": [], "description": ""}]
    with patch("groups.service.list_groups", new=AsyncMock(return_value=groups)):
        with pytest.raises(HTTPException) as e1:
            await r.add_role_alias(r.RoleAlias(group_id="g1", alias="Control Owner"), None)
        with pytest.raises(HTTPException) as e2:
            await r.add_role_alias(r.RoleAlias(group_id="g1", alias="Other Role"), None)
    assert e1.value.status_code == 422 and e2.value.status_code == 409


async def test_role_alias_that_was_not_stored_is_not_reported_as_saved():
    import pytest
    from unittest.mock import AsyncMock, patch
    from fastapi import HTTPException
    from doc_standards import router as r
    groups = [{"id": "g1", "name": "A Role", "aliases": [], "description": ""}]
    with patch("groups.service.list_groups", new=AsyncMock(return_value=groups)), \
         patch("groups.service.update_group", new=AsyncMock(return_value=groups[0])):
        with pytest.raises(HTTPException) as e:
            await r.add_role_alias(r.RoleAlias(group_id="g1", alias="ISO Lead"), None)
    assert e.value.status_code == 503
