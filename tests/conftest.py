# =============================================================================
# tests/conftest.py — pytest fixtures for OrgOS test suite
# Provides: mock Graph API responses, test app client, sample data.
# All Graph API calls are mocked — no real SharePoint calls in tests.
# Depends on: pytest, pytest-asyncio, pytest-httpx, fastapi TestClient
# =============================================================================

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from typing import AsyncGenerator

from main import app


# =============================================================================
#  App client fixtures
# =============================================================================

@pytest.fixture
def client() -> TestClient:
    """Synchronous test client for non-async tests."""
    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Async test client for async endpoint tests."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# =============================================================================
#  Mock SharePoint List response shapes
#  These match the EXACT structure returned by Microsoft Graph API:
#  GET /sites/{siteId}/lists/{listId}/items?$expand=fields
# =============================================================================

@pytest.fixture
def mock_document_item() -> dict:
    """A single Document Register item as returned by Graph API."""
    return {
        "id": "1",
        "createdDateTime": "2026-01-15T10:00:00Z",
        "lastModifiedDateTime": "2026-03-01T14:30:00Z",
        "fields": {
            "id": "1",
            "DocumentCode": "DRG-ISMS-POL-ACP-01-25",
            "Title": "Access Control Policy & Procedures",
            "DocumentType": "Policy",
            "Department": "ISMS",
            "Owner": "Daniel Iwuagwu",
            "OwnerId": "aaa-111-bbb",
            "OwnerEmail": "daniel@dragnet.com.ng",
            "OwnerEntraId": "aaa-111-bbb",
            "CurrentVersion": "R01",
            "EffectiveDate": "2025-04-01",
            "NextReviewDate": "2026-04-01",
            "ApplicableStandards": "ISO 27001",
            "LinkedControlsCount": 2,
            "Status": "Active",
        },
    }


@pytest.fixture
def mock_document_list_response(mock_document_item) -> dict:
    """Graph API response for listing documents."""
    return {
        "value": [mock_document_item],
        "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#...",
    }


@pytest.fixture
def mock_role_item() -> dict:
    """A single Role Register item as returned by Graph API."""
    return {
        "id": "2",
        "createdDateTime": "2026-01-10T09:00:00Z",
        "lastModifiedDateTime": "2026-02-15T11:00:00Z",
        "fields": {
            "id": "2",
            "Title": "ISMS Lead",
            "Department": "ISMS",
            "JDReference": "DRG-JD-ISMS-IL-01",
            "CurrentHolder": "Daniel Iwuagwu",
            "CurrentHolderId": "aaa-111-bbb",
            "CurrentHolderEmail": "daniel@dragnet.com.ng",
            "CurrentHolderEntraId": "aaa-111-bbb",
            "SourceSystem": "Entra ID",
            "VariantTerms": "ISMS Manager, Security Lead",
        },
    }


@pytest.fixture
def mock_obligation_item_overdue() -> dict:
    """A Compliance Calendar item with a past due date (Overdue)."""
    return {
        "id": "3",
        "createdDateTime": "2026-01-01T08:00:00Z",
        "lastModifiedDateTime": "2026-01-01T08:00:00Z",
        "fields": {
            "id": "3",
            "Title": "PAYE Remittance",
            "ObligationType": "Statutory",
            "Authority": "LIRS",
            "DueDate": "2026-01-10",   # Past date → Overdue
            "Recurrence": "Monthly",
            "Owner": "CGS",
            "OwnerId": "ccc-333-ddd",
            "OwnerEmail": "cgs@dragnet.com.ng",
            "OwnerEntraId": "ccc-333-ddd",
        },
    }


@pytest.fixture
def mock_obligation_item_upcoming() -> dict:
    """A Compliance Calendar item with a far future due date (Upcoming)."""
    return {
        "id": "4",
        "createdDateTime": "2026-01-01T08:00:00Z",
        "lastModifiedDateTime": "2026-01-01T08:00:00Z",
        "fields": {
            "id": "4",
            "Title": "ISO 9001 Surveillance Audit",
            "ObligationType": "Certification",
            "Authority": "Cert Body",
            "DueDate": "2027-09-15",   # Far future → Upcoming
            "Recurrence": "Annual",
            "Owner": "Wani",
            "OwnerId": "eee-555-fff",
            "OwnerEmail": "wani@dragnet.com.ng",
            "OwnerEntraId": "eee-555-fff",
        },
    }


@pytest.fixture
def mock_contract_item_active() -> dict:
    """A Contract Register item with a future expiry (Active)."""
    return {
        "id": "5",
        "createdDateTime": "2026-01-01T08:00:00Z",
        "lastModifiedDateTime": "2026-01-01T08:00:00Z",
        "fields": {
            "id": "5",
            "Title": "BGV-ACCESS-2027",
            "ContractTitle": "Background Verification",
            "Counterparty": "Access Bank",
            "ContractType": "Client",
            "StartDate": "2026-01-14",
            "EndDate": "2027-01-14",   # Far future → Active
            "Owner": "CRO",
            "OwnerId": "ggg-777-hhh",
            "OwnerEmail": "cro@dragnet.com.ng",
            "OwnerEntraId": "ggg-777-hhh",
            "ApplicableStandards": "ISO 9001",
            "LinkedControlsCount": 0,
        },
    }


@pytest.fixture
def mock_contract_item_expiring() -> dict:
    """A Contract Register item expiring within 60 days (Expiring Soon)."""
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=30)).isoformat()
    return {
        "id": "6",
        "createdDateTime": "2025-06-01T08:00:00Z",
        "lastModifiedDateTime": "2025-06-01T08:00:00Z",
        "fields": {
            "id": "6",
            "Title": "NDA-PEARSON-2026",
            "ContractTitle": "Mutual NDA — Assessment",
            "Counterparty": "Pearson VUE",
            "ContractType": "NDA",
            "EndDate": expiry,
            "Owner": "COO",
            "OwnerId": "iii-999-jjj",
            "OwnerEmail": "coo@dragnet.com.ng",
            "OwnerEntraId": "iii-999-jjj",
            "ApplicableStandards": "",
            "LinkedControlsCount": 0,
        },
    }


# =============================================================================
#  Token fixture — bypasses auth for testing
# =============================================================================

@pytest.fixture
def auth_headers() -> dict:
    """
    Headers that bypass Entra ID token validation in tests.
    In production, the real validator.py checks the JWKS signature.
    Tests mock the validator dependency directly.
    """
    return {"Authorization": "Bearer test-token-not-validated-in-tests"}


@pytest.fixture
def mock_current_user():
    """A mock CurrentUser for injecting into protected endpoints during tests."""
    from auth.validator import CurrentUser
    return CurrentUser(
        oid="test-oid-123",
        name="Test User",
        email="test@dragnet.com.ng",
        tenant_id="test-tenant-id",
        roles=["OrgOS.Admin"],
    )
