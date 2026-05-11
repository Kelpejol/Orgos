# =============================================================================
# tests/grc/test_role_register.py — Role Register endpoint tests
# =============================================================================

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from main import app
from auth.validator import CurrentUser, get_current_user


def override_auth():
    return CurrentUser(
        oid="test-oid", name="Test", email="test@dragnet.com.ng",
        tenant_id="test-tenant", roles=["OrgOS.Admin"],
    )

app.dependency_overrides[get_current_user] = override_auth
client = TestClient(app)


class TestRoleRegisterList:

    def test_returns_role_list(self):
        from grc.schemas import RoleRead, RoleSourceSystem
        with patch("grc.router.service.get_roles", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = [
                RoleRead(
                    id="1",
                    role_title="ISMS Lead",
                    department="ISMS",
                    jd_reference="DRG-JD-ISMS-IL-01",
                    source_system=RoleSourceSystem.ENTRA_ID,
                )
            ]
            response = client.get("/api/v1/grc/roles")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["role_title"] == "ISMS Lead"

    def test_filter_by_department(self):
        with patch("grc.router.service.get_roles", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = []
            response = client.get("/api/v1/grc/roles?department=ISMS")

        assert response.status_code == 200
        mock_svc.assert_called_once_with(department="ISMS")

    def test_update_role_holder_returns_200(self):
        """Updating current_holder_id simulates a person change."""
        from grc.schemas import RoleRead, RoleSourceSystem
        with patch("grc.router.service.update_role", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = RoleRead(
                id="1",
                role_title="ISMS Lead",
                department="ISMS",
                jd_reference="DRG-JD-ISMS-IL-01",
                source_system=RoleSourceSystem.ENTRA_ID,
            )
            response = client.patch(
                "/api/v1/grc/roles/1",
                json={"current_holder_id": "new-entra-oid-xyz"},
            )

        assert response.status_code == 200
        mock_svc.assert_called_once()
        call_args = mock_svc.call_args
        assert call_args[0][0] == "1"
        assert call_args[0][1].current_holder_id == "new-entra-oid-xyz"
