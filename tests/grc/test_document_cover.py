# =============================================================================
# tests/grc/test_document_cover.py — CDT cover facts + PDF preview for
# Document Register items (the approved-document equivalent of the
# Document Lifecycle cover endpoints in lifecycle/router.py).
#
# House pattern: TestClient + app.dependency_overrides for auth, mock
# grc.router.service.* and the Graph helpers directly (see
# test_document_register.py).
# =============================================================================

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.validator import CurrentUser, get_current_user
from grc.schemas import CdtCoverFacts, DocumentRead, DocumentStatus, DocumentType
from lifecycle.merge import MergeError
from main import app


def override_auth():
    return CurrentUser(oid="test-oid", name="Test User", email="test@dragnet.com.ng",
                        tenant_id="test-tenant", roles=["orgos-admin"])


app.dependency_overrides[get_current_user] = override_auth
client = TestClient(app)


def _document_read(**overrides) -> DocumentRead:
    base = dict(
        id="8", document_code="DRG-QI-GDL-DAG-01-26", title="Document Authoring Guide",
        type=DocumentType.GUIDELINES, department="Quality & Compliance",
        current_version="R01", effective_date=date(2026, 1, 1), status=DocumentStatus.ACTIVE,
        sharepoint_url="https://sp/register/DAG.docx",
        cdt_cover=CdtCoverFacts(domain="Quality & Compliance", version="01"),
        revision_history=[{"version": "01", "date": "Jan 2026", "purpose": "Issued", "approved_by": "CCO"}],
    )
    base.update(overrides)
    return DocumentRead(**base)


class TestGetRegisterCover:
    def test_returns_cover_and_history(self):
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _document_read()
            resp = client.get("/api/v1/grc/documents/8/cover")

        assert resp.status_code == 200
        body = resp.json()
        assert body["cover"]["domain"] == "Quality & Compliance"
        assert body["revision_history"][0]["purpose"] == "Issued"

    def test_missing_cdt_cover_returns_blank_defaults(self):
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _document_read(cdt_cover=None, revision_history=[])
            resp = client.get("/api/v1/grc/documents/8/cover")

        assert resp.status_code == 200
        assert resp.json()["cover"]["domain"] == ""


class TestUpdateRegisterCover:
    def test_partial_update_merges_onto_existing_cover(self):
        current = _document_read()
        updated = _document_read(cdt_cover=CdtCoverFacts(domain="Quality & Compliance",
                                                          version="01", classification="Internal use only"))

        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.service.update_document", new_callable=AsyncMock) as mock_update:
            mock_get.return_value = current
            mock_update.return_value = updated

            resp = client.patch("/api/v1/grc/documents/8/cover", json={"classification": "Internal use only"})

        assert resp.status_code == 200
        assert resp.json()["cover"]["classification"] == "Internal use only"

        # The merge preserved the EXISTING domain rather than wiping it —
        # service.update_document was called with the merged cover, not a
        # cover built from scratch out of just the one field sent.
        call_body = mock_update.call_args.args[1]
        assert call_body.cdt_cover.domain == "Quality & Compliance"
        assert call_body.cdt_cover.classification == "Internal use only"

    def test_revision_history_only_sent_when_provided(self):
        current = _document_read()
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.service.update_document", new_callable=AsyncMock) as mock_update:
            mock_get.return_value = current
            mock_update.return_value = current

            client.patch("/api/v1/grc/documents/8/cover", json={"domain": "Information Security"})

        call_body = mock_update.call_args.args[1]
        assert call_body.revision_history is None


class TestPreviewRegisterDocumentPdf:
    def test_preview_merges_and_returns_pdf(self):
        merged_bytes = b"MERGED-DOCX-BYTES"

        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
             patch("grc.router.merge") as mock_merge, \
             patch("grc.router.resolve_compliance_drive", new_callable=AsyncMock) as mock_drive, \
             patch("grc.router.ensure_drive_folder", new_callable=AsyncMock), \
             patch("grc.router.upload_bytes_to_drive", new_callable=AsyncMock), \
             patch("grc.router.convert_drive_item_to_pdf", new_callable=AsyncMock) as mock_convert:

            mock_get.return_value = _document_read()
            mock_dl.return_value = (b"SOURCE-BYTES", "x.docx")
            mock_merge.return_value = type("R", (), {"document": merged_bytes, "sha256": "x", "doc_code": "x"})()
            mock_drive.return_value = ("site-id", "drive-id")
            mock_convert.return_value = b"%PDF-FAKE"

            resp = client.get("/api/v1/grc/documents/8/preview.pdf")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        mock_merge.assert_called_once()
        assert mock_merge.call_args.args[0] == b"SOURCE-BYTES"

    def test_preview_404_when_no_file_linked(self):
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _document_read(sharepoint_url=None)
            resp = client.get("/api/v1/grc/documents/8/preview.pdf")

        assert resp.status_code == 404

    def test_preview_422_when_merge_fails(self):
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
             patch("grc.router.merge") as mock_merge:

            mock_get.return_value = _document_read()
            mock_dl.return_value = (b"SOURCE-BYTES", "x.docx")
            mock_merge.side_effect = MergeError("bad template")

            resp = client.get("/api/v1/grc/documents/8/preview.pdf")

        assert resp.status_code == 422


class TestDocumentTypeCoversAllCdtTypes:
    """
    Regression guard: every document type the CDT master templates and the
    AI Drafter actually offer (scripts/build_cdt_master_templates.py's
    DOCUMENT_TYPES / frontend DocumentLifecycle's DOC_TYPES) must be a valid
    grc.schemas.DocumentType — otherwise approving one of them writes fine
    but crashes on every subsequent read of its Document Register entry
    (Pydantic rejects the unknown enum value). Caught once already: Combined,
    Manual, Guideline, Standard, SLA were missing from this enum entirely.
    """

    CDT_DOCUMENT_TYPES = ["Policy", "Procedure", "Combined", "Manual", "Guideline", "Standard", "SLA"]

    @pytest.mark.parametrize("doc_type", CDT_DOCUMENT_TYPES)
    def test_cdt_document_type_is_valid_register_type(self, doc_type):
        doc = _document_read(type=doc_type)
        assert doc.type.value == doc_type


class TestSuggestRegisterCover:
    """
    The register's half of the suggestion endpoint. It must behave exactly
    like the Lifecycle one so the shared Cover & control facts panel can be
    pointed at either — and, above all, it must not write.
    """

    def test_suggesting_never_writes(self):
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.service.get_documents", new_callable=AsyncMock) as mock_list, \
             patch("grc.router.service.update_document", new_callable=AsyncMock) as mock_update:

            mock_get.return_value = _document_read()
            mock_list.return_value = []

            resp = client.get("/api/v1/grc/documents/8/cover/suggest")

        assert resp.status_code == 200
        mock_update.assert_not_called()

    def test_response_shape_matches_the_lifecycle_endpoint(self):
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.service.get_documents", new_callable=AsyncMock) as mock_list:

            mock_get.return_value = _document_read()
            mock_list.return_value = []

            body = client.get("/api/v1/grc/documents/8/cover/suggest").json()

        assert set(body) == {"document_id", "suggestions", "unresolved"}
        for field, suggestion in body["suggestions"].items():
            assert set(suggestion) == {"value", "source", "confidence", "note"}, field

    def test_confirmed_domain_drives_the_approval_route(self):
        """The register entry already carries a confirmed domain, so the
        route follows it rather than being re-derived."""
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.service.get_documents", new_callable=AsyncMock) as mock_list:

            mock_get.return_value = _document_read()
            mock_list.return_value = []

            s = client.get("/api/v1/grc/documents/8/cover/suggest").json()["suggestions"]

        assert s["domain"]["value"] == "Quality & Compliance"
        assert s["first_pass_approval"]["value"] == "Chief Compliance Officer"
        assert s["final_approval"]["value"] == "Managing Director / CEO"

    def test_effective_date_comes_from_the_published_date(self):
        """A register entry is already approved, so its effective date is a
        fact, not a proposal — and the next review follows from it."""
        with patch("grc.router.service.get_document", new_callable=AsyncMock) as mock_get, \
             patch("grc.router.service.get_documents", new_callable=AsyncMock) as mock_list:

            mock_get.return_value = _document_read(cdt_cover=CdtCoverFacts(domain="Quality & Compliance"))
            mock_list.return_value = []

            s = client.get("/api/v1/grc/documents/8/cover/suggest").json()["suggestions"]

        assert s["effective_date"]["value"] == "January 2026"
        assert s["next_review_due"]["value"] == "January 2027"
