# =============================================================================
# tests/lifecycle/test_attach_cover.py — POST .../attach-cover, and how a
# document is shown for reading (cover facts merged in when it has markers).
#
# The document's file lives in the fake library (tests/lifecycle/conftest.py).
# graft_cover_onto_document itself is tested in isolation in test_graft.py;
# here it's mocked so these tests are about the router's orchestration (auth
# gate, idempotent short-circuit, saving over the one file, error handling).
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
SOURCE = "https://sp/source.docx"


def _lifecycle_doc(**overrides) -> dict:
    base = {
        "id": "10", "Title": "Old Acceptable Use Policy", "DocumentCode": "DRG-ISMS-STD-AU",
        "DocumentType": "Standard", "Department": "Information Security",
        "OwnerEntraId": "owner-oid", "OwnerName": "Owner Person",
        "SharePointFileUrl": SOURCE,
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


async def test_attach_cover_already_templated_is_idempotent(library):
    library.add(SOURCE, _MARKER_DOCX, "source.docx")
    doc = _lifecycle_doc()
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.graft_cover_onto_document") as mock_graft:
        mock_get.return_value = {"id": "10", "fields": doc}
        result = await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)

    assert result["already_templated"] is True
    mock_graft.assert_not_called()
    assert library.saves == []


async def test_attach_cover_no_file_yet_returns_404():
    doc = _lifecycle_doc(SharePointFileUrl="")
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"id": "10", "fields": doc}
        with pytest.raises(Exception) as exc_info:
            await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)
    assert getattr(exc_info.value, "status_code", None) == 404


async def test_attach_cover_is_saved_over_the_document_s_own_file(library):
    """The LIVE path: the grafted document replaces the content of the SAME file (its history
    keeps the old content). No backup copy, no second file; the checks run on the result."""
    library.add(SOURCE, _PLAIN_DOCX, "source.docx")
    doc = _lifecycle_doc()
    grafted_bytes = b"GRAFTED-DOCX-WITH-MARKERS"

    with patch.object(type(lr.settings), "document_writes_live", property(lambda self: True)), \
         patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.load_master_template", new_callable=AsyncMock) as mock_template, \
         patch("lifecycle.router._cdi_check_file", new=AsyncMock(return_value=("Failed", "[]"))), \
         patch("lifecycle.router.graft_cover_onto_document") as mock_graft:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_template.return_value = b"MASTER-TEMPLATE-BYTES"
        mock_graft.return_value = GraftResult(document=grafted_bytes, images_carried=2, images_skipped=0)

        result = await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)

    assert result["already_templated"] is False and result["images_carried"] == 2
    assert result["file_url"] == SOURCE and result["cdi_status"] == "Failed"
    mock_template.assert_called_once_with("Standard")
    mock_graft.assert_called_once_with(_PLAIN_DOCX, b"MASTER-TEMPLATE-BYTES")
    assert library.saves == [(SOURCE, grafted_bytes)] and library.created == []
    stored = [c.args[3] for c in mock_update.call_args_list if "CDIStatus" in c.args[3]]
    assert stored == [{"Revised": True, "CDIStatus": "Failed", "CDIFailures": "[]"}]


async def test_attach_cover_missing_master_template_returns_503(library):
    library.add(SOURCE, _PLAIN_DOCX, "source.docx")
    doc = _lifecycle_doc()
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.load_master_template", new_callable=AsyncMock) as mock_template:
        mock_get.return_value = {"id": "10", "fields": doc}
        mock_template.side_effect = TemplateNotFoundError("no template for Standard")
        with pytest.raises(Exception) as exc_info:
            await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)

    assert getattr(exc_info.value, "status_code", None) == 503


async def test_attach_cover_in_dev_mode_does_not_touch_sharepoint(library):
    """Dev mode still grafts and reports, so the officer sees what would happen —
    it simply never saves, so the live library cannot be marked up."""
    library.add(SOURCE, _PLAIN_DOCX, "source.docx")
    doc = _lifecycle_doc()

    with patch.object(type(lr.settings), "document_writes_live", property(lambda self: False)), \
         patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.load_master_template", new_callable=AsyncMock) as mock_template, \
         patch("lifecycle.router.graft_cover_onto_document") as mock_graft:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_template.return_value = b"MASTER-TEMPLATE-BYTES"
        mock_graft.return_value = GraftResult(document=b"GRAFTED", images_carried=2, images_skipped=0)

        result = await lr.attach_cdt_cover("10", user=COMPLIANCE_USER)

    assert result["wrote_to_sharepoint"] is False
    assert result["images_carried"] == 2
    mock_graft.assert_called_once()          # the work was still done
    assert library.saves == []               # ...and never written
    mock_update.assert_not_called()


# -----------------------------------------------------------------------------
#  Reading a document: cover facts merged in when it has markers. No download.
# -----------------------------------------------------------------------------

async def test_a_templated_document_is_shown_merged(library):
    library.add(SOURCE, _MARKER_DOCX, "source.docx")
    doc = _lifecycle_doc(CDTCoverFacts=CdtCoverFacts(version="01").to_json())
    with patch("lifecycle.router.merge") as mock_merge:
        mock_merge.return_value = type("R", (), {"document": b"CLEAN-MERGED-BYTES"})()
        f, content, merged = await lr._document_for_display("10", doc)
    assert content == b"CLEAN-MERGED-BYTES" and merged and f.web_url == SOURCE


async def test_a_plain_document_is_shown_as_it_is(library):
    library.add(SOURCE, _PLAIN_DOCX, "source.docx")
    with patch("lifecycle.router.merge") as mock_merge:
        _f, content, merged = await lr._document_for_display("10", _lifecycle_doc())
    mock_merge.assert_not_called()
    assert content == _PLAIN_DOCX and not merged


async def test_a_failed_merge_shows_the_file_as_it_is(library):
    library.add(SOURCE, _MARKER_DOCX, "source.docx")
    with patch("lifecycle.router.merge", side_effect=Exception("bad template")):
        _f, content, merged = await lr._document_for_display("10", _lifecycle_doc())
    assert content == _MARKER_DOCX and not merged


async def test_there_is_no_download_route():
    paths = {getattr(r, "path", "") for r in lr.router.routes}
    assert not any(p.endswith("/download") for p in paths)
