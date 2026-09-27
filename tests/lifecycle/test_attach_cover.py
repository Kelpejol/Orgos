# =============================================================================
# tests/lifecycle/test_attach_cover.py — POST .../attach-cover + the
# merge-if-templated behaviour of GET .../download and the CDI check inside
# POST .../upload.
#
# Graph is mocked at the lifecycle.router seam (house pattern — see
# test_approval_cdt.py). graft_cover_onto_document itself is tested in
# isolation in test_graft.py; here it's mocked so these tests are about the
# router's orchestration (auth gate, idempotent short-circuit, backup
# upload, error handling), not the graft engine.
# =============================================================================

import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from docx import Document

import lifecycle.router as lr
from auth.validator import CurrentUser
from lifecycle.graft import GraftResult
from lifecycle.schemas import CdtCoverFacts
from lifecycle.templates import TemplateNotFoundError

COMPLIANCE_USER = CurrentUser(oid="compliance-oid", name="Compliance Officer",
                               email="c@dragnet.com", tenant_id="t", roles=["compliance"])
OTHER_USER = CurrentUser(oid="someone-else", name="Someone Else",
                          email="s@dragnet.com", tenant_id="t", roles=[])


def _docx_bytes(text: str) -> bytes:
    """A real, minimal .docx (scan_markers() needs an actual zip, not a plain string)."""
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


_MARKER_DOCX = _docx_bytes("already has {{ doc_code }} markers")
_PLAIN_DOCX = _docx_bytes("plain legacy content, no markers at all")


def _lifecycle_doc(**overrides) -> dict:
    base = {
        "id": "10", "Title": "Old Acceptable Use Policy", "DocumentCode": "DRG-ISMS-STD-AU",
        "DocumentType": "Standard", "Department": "Information Security",
        "OwnerEntraId": "owner-oid", "OwnerName": "Owner Person",
        "SharePointFileUrl": "https://sp/source.docx",
        "RevisionOf": "", "Notes": "", "StandardsMapping": "", "SensitisationDeadline": "",
        "CDTCoverFacts": CdtCoverFacts().to_json(), "RevisionHistory": json.dumps([]),
    }
    base.update(overrides)
    return base


# -----------------------------------------------------------------------------
#  POST /documents/{id}/attach-cover
# -----------------------------------------------------------------------------

async def test_attach_cover_rejects_non_owner_non_compliance():
    doc = _lifecycle_doc()
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"id": "10", "fields": doc}
        with pytest.raises(Exception) as exc_info:
            await lr.attach_cdt_cover("10", user=OTHER_USER)
    assert getattr(exc_info.value, "status_code", None) == 403


async def test_attach_cover_already_templated_is_idempotent():
    doc = _lifecycle_doc()
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.graft_cover_onto_document") as mock_graft:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_dl.return_value = (_MARKER_DOCX, "x.docx")

        result = await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)

    assert result["already_templated"] is True
    mock_graft.assert_not_called()


async def test_attach_cover_no_file_yet_returns_404():
    doc = _lifecycle_doc(SharePointFileUrl="")
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"id": "10", "fields": doc}
        with pytest.raises(Exception) as exc_info:
            await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)
    assert getattr(exc_info.value, "status_code", None) == 404


async def test_attach_cover_grafts_backs_up_and_replaces_file():
    doc = _lifecycle_doc()
    grafted_bytes = b"GRAFTED-DOCX-WITH-MARKERS"

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router._upload_to_sharepoint", new_callable=AsyncMock) as mock_upload, \
         patch("lifecycle.router.load_master_template", new_callable=AsyncMock) as mock_template, \
         patch("lifecycle.router.graft_cover_onto_document") as mock_graft:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_dl.return_value = (_PLAIN_DOCX, "source.docx")
        mock_template.return_value = b"MASTER-TEMPLATE-BYTES"
        mock_graft.return_value = GraftResult(document=grafted_bytes, images_carried=2, images_skipped=0)
        mock_upload.side_effect = ["https://sp/backup.docx", "https://sp/source.docx"]

        result = await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)

    assert result == {
        "already_templated": False,
        "images_carried": 2,
        "images_skipped": 0,
        "backup_url": "https://sp/backup.docx",
    }
    mock_template.assert_called_once_with("Standard")
    mock_graft.assert_called_once_with(_PLAIN_DOCX, b"MASTER-TEMPLATE-BYTES")

    # Original bytes backed up FIRST, then the grafted result uploaded to
    # the same slot the normal upload endpoint would use.
    assert mock_upload.call_count == 2
    backup_call, replace_call = mock_upload.call_args_list
    assert backup_call.args[0] == "10"
    assert backup_call.args[2] == _PLAIN_DOCX
    assert replace_call.args[2] == grafted_bytes

    # The lifecycle item's file pointer now points at the grafted version.
    mock_update.assert_called_once_with(
        lr._get_list_id(), lr._LIST_NAME, "10", {"SharePointFileUrl": "https://sp/source.docx"},
    )


async def test_attach_cover_missing_master_template_returns_503():
    doc = _lifecycle_doc()
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.load_master_template", new_callable=AsyncMock) as mock_template:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_dl.return_value = (_PLAIN_DOCX, "source.docx")
        mock_template.side_effect = TemplateNotFoundError("no template for Standard")

        with pytest.raises(Exception) as exc_info:
            await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)

    assert getattr(exc_info.value, "status_code", None) == 503


# -----------------------------------------------------------------------------
#  GET /documents/{id}/download — merges when templated, redirects otherwise
# -----------------------------------------------------------------------------

async def test_download_serves_merged_bytes_when_templated():
    doc = _lifecycle_doc(CDTCoverFacts=CdtCoverFacts(version="01").to_json())
    merged_bytes = b"CLEAN-MERGED-BYTES"

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.merge") as mock_merge:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_dl.return_value = (_MARKER_DOCX, "source.docx")
        mock_merge.return_value = type("R", (), {"document": merged_bytes, "sha256": "x", "doc_code": "x"})()

        response = await lr.download_doc_file("10", user=COMPLIANCE_USER)

    assert response.body == merged_bytes
    assert response.status_code == 200


async def test_download_serves_raw_bytes_when_not_templated():
    doc = _lifecycle_doc()

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.merge") as mock_merge:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_dl.return_value = (_PLAIN_DOCX, "source.docx")

        response = await lr.download_doc_file("10", user=COMPLIANCE_USER)

    mock_merge.assert_not_called()
    assert response.status_code == 200
    assert response.body == _PLAIN_DOCX


async def test_download_serves_raw_bytes_when_merge_fails():
    doc = _lifecycle_doc()

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.merge") as mock_merge:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_dl.return_value = (_MARKER_DOCX, "source.docx")
        mock_merge.side_effect = Exception("bad template")

        response = await lr.download_doc_file("10", user=COMPLIANCE_USER)

    assert response.status_code == 200
    assert response.body == _MARKER_DOCX


async def test_download_returns_503_when_file_fetch_fails():
    doc = _lifecycle_doc()

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_dl.side_effect = Exception("Graph is unreachable")

        with pytest.raises(Exception) as exc_info:
            await lr.download_doc_file("10", user=COMPLIANCE_USER)

    assert getattr(exc_info.value, "status_code", None) == 503
