# =============================================================================
# tests/grc/test_compliance_calendar.py — Compliance Calendar tests
# Focus: status calculation logic (Overdue / Due Soon / Upcoming / Completed).
# This is the most important business logic in Tier 1 — it must be bulletproof.
# =============================================================================

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from main import app
from auth.validator import CurrentUser, get_current_user
from grc.service import _calculate_obligation_status
from grc.schemas import ObligationStatus


def override_auth():
    return CurrentUser(
        oid="test-oid", name="Test", email="test@dragnet.com.ng",
        tenant_id="test-tenant", roles=["OrgOS.Admin"],
    )

app.dependency_overrides[get_current_user] = override_auth
client = TestClient(app)


class TestObligationStatusCalculation:
    """
    Pure unit tests for _calculate_obligation_status.
    This function is called on every read — it must be correct.
    """

    def test_past_due_date_is_overdue(self):
        yesterday = date.today() - timedelta(days=1)
        assert _calculate_obligation_status(yesterday) == ObligationStatus.OVERDUE

    def test_today_is_due_soon(self):
        """Due today = Due Soon (0 days delta, within 30-day window)."""
        assert _calculate_obligation_status(date.today()) == ObligationStatus.DUE_SOON

    def test_29_days_away_is_due_soon(self):
        soon = date.today() + timedelta(days=29)
        assert _calculate_obligation_status(soon) == ObligationStatus.DUE_SOON

    def test_30_days_away_is_due_soon(self):
        """Boundary: exactly 30 days is still Due Soon."""
        boundary = date.today() + timedelta(days=30)
        assert _calculate_obligation_status(boundary) == ObligationStatus.DUE_SOON

    def test_31_days_away_is_upcoming(self):
        """One day past the threshold = Upcoming."""
        upcoming = date.today() + timedelta(days=31)
        assert _calculate_obligation_status(upcoming) == ObligationStatus.UPCOMING

    def test_far_future_is_upcoming(self):
        far_future = date.today() + timedelta(days=365)
        assert _calculate_obligation_status(far_future) == ObligationStatus.UPCOMING

    def test_10_days_overdue(self):
        ten_days_ago = date.today() - timedelta(days=10)
        assert _calculate_obligation_status(ten_days_ago) == ObligationStatus.OVERDUE


class TestComplianceCalendarEndpoints:
    """Tests for the overdue and due-soon filter endpoints."""

    def test_overdue_endpoint_returns_only_overdue(self):
        """GET /compliance/overdue must only return Overdue items."""
        from grc.schemas import ObligationRead, ObligationType, ObligationRecurrence
        yesterday = date.today() - timedelta(days=1)

        with patch(
            "grc.router.service.get_overdue_obligations", new_callable=AsyncMock
        ) as mock_svc:
            mock_svc.return_value = [
                ObligationRead(
                    id="1",
                    obligation_name="PAYE Remittance",
                    type=ObligationType.STATUTORY,
                    authority="LIRS",
                    due_date=yesterday,
                    recurrence=ObligationRecurrence.MONTHLY,
                    status=ObligationStatus.OVERDUE,
                )
            ]
            response = client.get("/api/v1/grc/compliance/overdue")

        assert response.status_code == 200
        data = response.json()
        assert all(item["status"] == "Overdue" for item in data)

    def test_due_soon_endpoint_returns_200(self):
        """GET /compliance/due-soon should always return 200."""
        with patch(
            "grc.router.service.get_due_soon_obligations", new_callable=AsyncMock
        ) as mock_svc:
            mock_svc.return_value = []
            response = client.get("/api/v1/grc/compliance/due-soon")

        assert response.status_code == 200

    def test_create_obligation_returns_201(self):
        """POST /compliance creates obligation and returns 201."""
        from grc.schemas import ObligationRead, ObligationType, ObligationRecurrence
        next_month = date.today() + timedelta(days=31)

        with patch(
            "grc.router.service.create_obligation", new_callable=AsyncMock
        ) as mock_svc:
            mock_svc.return_value = ObligationRead(
                id="10",
                obligation_name="FIRS VAT Filing",
                type=ObligationType.STATUTORY,
                authority="FIRS",
                due_date=next_month,
                recurrence=ObligationRecurrence.MONTHLY,
                status=ObligationStatus.UPCOMING,
            )
            response = client.post(
                "/api/v1/grc/compliance",
                json={
                    "obligation_name": "FIRS VAT Filing",
                    "type": "Statutory",
                    "authority": "FIRS",
                    "due_date": next_month.isoformat(),
                    "recurrence": "Monthly",
                    "owner_id": "test-entra-oid",
                },
            )

        assert response.status_code == 201
