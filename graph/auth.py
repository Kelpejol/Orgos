# =============================================================================
# graph/auth.py — Microsoft Graph API access token management
# Acquires and caches the client credentials token for backend-to-Graph calls.
# This is NOT the frontend user auth — that is auth/validator.py.
# Depends on: config.py, graph/exceptions.py, httpx
# =============================================================================

import logging
import time
from typing import Optional

import httpx

from config import settings
from graph.exceptions import GraphAuthError

logger = logging.getLogger(__name__)

# In-memory token cache — survives for the lifetime of the process
_token_cache: dict = {
    "access_token": None,
    "expires_at": 0.0,
}

# Buffer in seconds — refresh token before it actually expires
_EXPIRY_BUFFER_SECONDS = 60


async def get_graph_access_token() -> str:
    """
    Returns a valid Microsoft Graph API access token.

    Uses the OAuth2 client credentials flow (not on behalf of a user).
    Caches the token in memory and refreshes it when it is within
    _EXPIRY_BUFFER_SECONDS of expiry.

    This token is used by graph/client.py for all SharePoint List operations.

    Returns:
        str: A valid Bearer token for the Authorization header

    Raises:
        GraphAuthError: If token acquisition fails (bad credentials, network error)
    """
    now = time.time()

    # Return cached token if it is still valid
    if (
        _token_cache["access_token"] is not None
        and _token_cache["expires_at"] > now + _EXPIRY_BUFFER_SECONDS
    ):
        logger.debug("Using cached Graph API access token")
        return _token_cache["access_token"]

    logger.info("Acquiring new Graph API access token via client credentials flow")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                settings.graph_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.client_id,
                    "client_secret": settings.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )

            if response.status_code != 200:
                body = response.json()
                error_desc = body.get(
                    "error_description", body.get("error", "Unknown token error")
                )
                logger.error(f"Token acquisition failed: {error_desc}")
                raise GraphAuthError(
                    f"Failed to acquire Graph API token: {error_desc}"
                )

            body = response.json()
            access_token: str = body["access_token"]
            expires_in: int = body.get("expires_in", 3600)

            # Cache the token
            _token_cache["access_token"] = access_token
            _token_cache["expires_at"] = now + expires_in

            logger.info(
                f"Graph API token acquired successfully, expires in {expires_in}s"
            )
            return access_token

    except httpx.ConnectError as exc:
        raise GraphAuthError(
            "Cannot reach Microsoft login endpoint — check network connectivity"
        ) from exc
    except httpx.TimeoutException as exc:
        raise GraphAuthError("Token acquisition timed out") from exc


def invalidate_token_cache() -> None:
    """
    Force the next call to get_graph_access_token() to acquire a fresh token.
    Use this in tests or when a 401 response is received from Graph API.
    """
    _token_cache["access_token"] = None
    _token_cache["expires_at"] = 0.0
    logger.debug("Graph API token cache invalidated")


def get_auth_header() -> dict:
    """
    Synchronous helper — returns the Authorization header dict.
    Only use when you already have a cached token (i.e., not on first call).
    For async contexts always use: await get_graph_access_token()
    """
    token = _token_cache.get("access_token")
    if token is None:
        raise GraphAuthError("No cached token available. Call get_graph_access_token() first.")
    return {"Authorization": f"Bearer {token}"}
