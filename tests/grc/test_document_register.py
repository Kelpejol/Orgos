# =============================================================================
# tests/grc/test_document_register.py — Document Register endpoint tests
# Tests all CRUD endpoints with mocked Graph API responses.
# =============================================================================

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from main import app
from auth.validator import CurrentUser, get_current_user
from grc.schemas import DocumentRead


# Override auth dependency for all tests in this module
def override_auth():
    return CurrentUser(
        oid="test-oid",
        name="Test User",
        email="test@dragnet.com.ng",
        tenant_id="test-tenant",
        roles=["OrgOS.Admin"],
    )

app.dependency_overrides[get_current_user] = override_auth
client = TestClient(app)


class TestDocumentRegisterList:
    """Tests for GET /api/v1/grc/documents"""

    def test_returns_documents_list(self, mock_document_item):
        """Happy path: service returns list of documents."""
        with patch("grc.router.service.get_documents", new_callable=AsyncMock) as mock_svc:
            from grc.schemas import DocumentRead, DocumentType, DocumentStatus
            from datetime import date
            mock_svc.return_value = [
                DocumentRead(
                    id="1",
                    document_code="DRG-ISMS-POL-ACP-01-25",
                    title="Access Control Policy",
                    type=DocumentType.POLICY,
                    department="ISMS",
                    current_version="R01",
                    effective_date=date(2025, 4, 1),
                    status=DocumentStatus.ACTIVE,
                )
            ]
            response = client.get("/api/v1/grc/documents")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["document_code"] == "DRG-ISMS-POL-ACP-01-25"

    def test_returns_503_when_list_not_configured(self):
        """Service raises SharePointListNotConfiguredError → 503 response."""
        from graph.exceptions import SharePointListNotConfiguredError
        with patch("grc.router.service.get_documents", new_callable=AsyncMock) as mock_svc:
            mock_svc.side_effect = SharePointListNotConfiguredError("Document Register")
            response = client.get("/api/v1/grc/documents")

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

    def test_filter_by_status(self):
        """Status query param is passed to service."""
        with patch("grc.router.service.get_documents", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = []
            response = client.get("/api/v1/grc/documents?status=Active")

        assert response.status_code == 200
        mock_svc.assert_called_once_with(status="Active", department=None)


class TestDocumentRegisterCreate:
    """Tests for POST /api/v1/grc/documents"""

    def test_creates_document_successfully(self):
        """Happy path: valid document data returns 201 with created document."""
        from datetime import date
        from grc.schemas import DocumentRead, DocumentType, DocumentStatus

        with patch("grc.router.service.create_document", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = DocumentRead(
                id="99",
                document_code="DRG-QI-POL-TEST-01-26",
                title="Test Policy",
                type=DocumentType.POLICY,
                department="QI",
                current_version="R01",
                effective_date=date(2026, 4, 1),
                status=DocumentStatus.ACTIVE,
            )
            response = client.post(
                "/api/v1/grc/documents",
                json={
                    "document_code": "DRG-QI-POL-TEST-01-26",
                    "title": "Test Policy",
                    "type": "Policy",
                    "department": "QI",
                    "current_version": "R01",
                    "effective_date": "2026-04-01",
                    "owner_id": "test-entra-oid",
                    "applicable_standards": ["ISO 9001"],
                },
            )

        assert response.status_code == 201
        assert response.json()["id"] == "99"

    def test_rejects_invalid_document_code_format(self):
        """Document code not starting with DRG- should return 422."""
        response = client.post(
            "/api/v1/grc/documents",
            json={
                "document_code": "INVALID-CODE",
                "title": "Test",
                "type": "Policy",
                "department": "QI",
                "current_version": "R01",
                "effective_date": "2026-04-01",
                "owner_id": "test-entra-oid",
            },
        )
        assert response.status_code == 422


class TestDocumentRegisterWithdraw:
    """Tests for POST /api/v1/grc/documents/{id}/withdraw"""

    def test_withdraw_returns_200(self):
        """Withdraw endpoint calls service and returns cascade result."""
        cascade_result = {
            "document_code": "DRG-TEST-POL-01-26",
            "withdrawal_reason": "Revoked",
            "queue_items_cancelled": [],
            "controls_flagged": [],
            "evidence_items_flagged": [],
            "lifecycles_cancelled": [],
            "gaps_reopened": [],
            "obligations_flagged": [],
            "coverage_gaps_created": [],
            "errors": [],
            "cascade_summary": "0 queue items cancelled | 0 controls flagged Under Review",
        }
        with patch(
            "grc.router.service.withdraw_document", new_callable=AsyncMock
        ) as mock_svc:
            mock_svc.return_value = cascade_result
            response = client.post(
                "/api/v1/grc/documents/1/withdraw",
                json={
                    "withdrawal_reason": "Revoked",
                    "rationale": "Regulation changed; document no longer applicable",
                },
            )

        assert response.status_code == 200
        assert response.json()["document_code"] == "DRG-TEST-POL-01-26"

    def test_delete_endpoint_returns_405(self):
        """Legacy DELETE endpoint returns 405 directing callers to /withdraw."""
        response = client.delete("/api/v1/grc/documents/1")
        assert response.status_code == 405
