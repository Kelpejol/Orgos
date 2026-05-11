# =============================================================================
# tests/grc/test_contract_register.py — Contract Register tests
# Focus: contract status calculation (Active / Expiring Soon / Expired).
# =============================================================================

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from main import app
from auth.validator import CurrentUser, get_current_user
from grc.service import _calculate_contract_status
from grc.schemas import ContractStatus


def override_auth():
    return CurrentUser(
        oid="test-oid", name="Test", email="test@dragnet.com.ng",
        tenant_id="test-tenant", roles=["OrgOS.Admin"],
    )

app.dependency_overrides[get_current_user] = override_auth
client = TestClient(app)


class TestContractStatusCalculation:

    def test_no_end_date_is_active(self):
        assert _calculate_contract_status(None) == ContractStatus.ACTIVE

    def test_past_end_date_is_expired(self):
        yesterday = date.today() - timedelta(days=1)
        assert _calculate_contract_status(yesterday) == ContractStatus.EXPIRED

    def test_within_60_days_is_expiring_soon(self):
        soon = date.today() + timedelta(days=45)
        assert _calculate_contract_status(soon) == ContractStatus.EXPIRING_SOON

    def test_exactly_60_days_is_expiring_soon(self):
        boundary = date.today() + timedelta(days=60)
        assert _calculate_contract_status(boundary) == ContractStatus.EXPIRING_SOON

    def test_61_days_away_is_active(self):
        safe = date.today() + timedelta(days=61)
        assert _calculate_contract_status(safe) == ContractStatus.ACTIVE

    def test_far_future_is_active(self):
        far = date.today() + timedelta(days=500)
        assert _calculate_contract_status(far) == ContractStatus.ACTIVE


class TestContractRegisterEndpoints:

    def test_list_contracts_returns_200(self):
        with patch("grc.router.service.get_contracts", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = []
            response = client.get("/api/v1/grc/contracts")
        assert response.status_code == 200

    def test_expiring_endpoint_returns_200(self):
        with patch(
            "grc.router.service.get_expiring_contracts", new_callable=AsyncMock
        ) as mock_svc:
            mock_svc.return_value = []
            response = client.get("/api/v1/grc/contracts/expiring")
        assert response.status_code == 200

    def test_create_contract_returns_201(self):
        from grc.schemas import ContractRead, ContractType, ContractStatus
        future = date.today() + timedelta(days=365)

        with patch(
            "grc.router.service.create_contract", new_callable=AsyncMock
        ) as mock_svc:
            mock_svc.return_value = ContractRead(
                id="20",
                contract_reference="BGV-MTN-2027",
                title="Recruitment & Verification",
                counterparty="MTN Nigeria",
                contract_type=ContractType.CLIENT,
                end_date=future,
                status=ContractStatus.ACTIVE,
            )
            response = client.post(
                "/api/v1/grc/contracts",
                json={
                    "contract_reference": "BGV-MTN-2027",
                    "title": "Recruitment & Verification",
                    "counterparty": "MTN Nigeria",
                    "contract_type": "Client",
                    "end_date": future.isoformat(),
                    "owner_id": "test-entra-oid",
                },
            )

        assert response.status_code == 201
        assert response.json()["contract_reference"] == "BGV-MTN-2027"
