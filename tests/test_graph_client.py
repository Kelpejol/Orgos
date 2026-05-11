# =============================================================================
# tests/test_graph_client.py — Tests for the Graph API client layer
# Tests token acquisition, request formation, error handling.
# All httpx calls are mocked — no real Graph API calls.
# =============================================================================

import pytest
import httpx
import respx

from graph.auth import get_graph_access_token, invalidate_token_cache
from graph.exceptions import (
    GraphAuthError,
    GraphNotFoundError,
    GraphRateLimitError,
    SharePointListNotConfiguredError,
    raise_for_graph_status,
)


# =============================================================================
#  Token acquisition
# =============================================================================

class TestTokenAcquisition:
    """Tests for graph/auth.py — client credentials token flow."""

    @pytest.mark.asyncio
    async def test_acquires_token_successfully(self):
        """Happy path: valid credentials return an access token."""
        invalidate_token_cache()

        with respx.mock:
            respx.post(
                "https://login.microsoftonline.com/your-tenant-id-here/oauth2/v2.0/token"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "test-access-token-abc123",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )
            )

            token = await get_graph_access_token()

        assert token == "test-access-token-abc123"

    @pytest.mark.asyncio
    async def test_caches_token_on_second_call(self):
        """Second call within expiry window should not make a new HTTP request."""
        invalidate_token_cache()

        call_count = 0

        with respx.mock:
            def mock_token_endpoint(request):
                nonlocal call_count
                call_count += 1
                return httpx.Response(
                    200,
                    json={"access_token": "cached-token", "expires_in": 3600},
                )

            respx.post(
                "https://login.microsoftonline.com/your-tenant-id-here/oauth2/v2.0/token"
            ).mock(side_effect=mock_token_endpoint)

            await get_graph_access_token()
            await get_graph_access_token()

        assert call_count == 1, "Token should be cached after first call"

    @pytest.mark.asyncio
    async def test_raises_graph_auth_error_on_invalid_credentials(self):
        """Bad credentials should raise GraphAuthError."""
        invalidate_token_cache()

        with respx.mock:
            respx.post(
                "https://login.microsoftonline.com/your-tenant-id-here/oauth2/v2.0/token"
            ).mock(
                return_value=httpx.Response(
                    401,
                    json={
                        "error": "invalid_client",
                        "error_description": "AADSTS70011: The provided client secret is incorrect.",
                    },
                )
            )

            with pytest.raises(GraphAuthError):
                await get_graph_access_token()


# =============================================================================
#  Error handling
# =============================================================================

class TestGraphErrorHandling:
    """Tests for graph/exceptions.py — error dispatch logic."""

    def test_raises_auth_error_on_401(self):
        with pytest.raises(GraphAuthError):
            raise_for_graph_status(401, {"error": {"message": "Unauthorized"}}, "test")

    def test_raises_not_found_on_404(self):
        with pytest.raises(GraphNotFoundError):
            raise_for_graph_status(404, {"error": {"message": "Not found"}}, "item 42")

    def test_raises_rate_limit_on_429(self):
        with pytest.raises(GraphRateLimitError):
            raise_for_graph_status(429, {}, "test")

    def test_sharepoint_not_configured_error_has_503_status(self):
        exc = SharePointListNotConfiguredError("Document Register")
        assert exc.status_code == 503
        assert "Document Register" in exc.message

    def test_graph_auth_error_has_401_status(self):
        exc = GraphAuthError("Bad token")
        assert exc.status_code == 401
