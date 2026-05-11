# =============================================================================
# auth/validator.py — Entra ID token validation
# Validates the bearer token sent by the MSAL React frontend on every request.
# Returns a CurrentUser object with the user's Entra ID identity.
# Depends on: config.py, graph/exceptions.py, python-jose, httpx
# =============================================================================

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings
from graph.exceptions import GraphAuthError

logger = logging.getLogger(__name__)

# HTTP Bearer scheme — extracts token from Authorization: Bearer <token>
_bearer_scheme = HTTPBearer(auto_error=False)

# JWKS cache — Microsoft rotates keys infrequently; refresh every hour
_jwks_cache: dict = {
    "keys": None,
    "fetched_at": 0.0,
    "ttl": 7200.0,  # 2 hours
}


@dataclass
class CurrentUser:
    """
    Represents the authenticated Dragnet staff member.
    Populated from validated Entra ID token claims.
    """

    oid: str         # Entra ID object ID — use this as the stable user identifier
    name: str        # Display name (e.g. "Bobby Ikazoboh")
    email: str       # UPN / email (e.g. "bobby@dragnet.com.ng")
    tenant_id: str   # Tenant ID — confirms this is a Dragnet account
    roles: list[str] # App roles assigned in Entra ID (e.g. ["Compliance.Lead"])


async def _get_jwks() -> list[dict]:
    """
    Fetch and cache Microsoft's public signing keys (JWKS).
    These are used to verify the JWT signature on incoming tokens.
    Keys are cached for 1 hour to avoid fetching on every request.
    """
    now = time.time()

    if (
        _jwks_cache["keys"] is not None
        and now - _jwks_cache["fetched_at"] < _jwks_cache["ttl"]
    ):
        return _jwks_cache["keys"]

    logger.info(f"Fetching JWKS from {settings.jwks_uri}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(settings.jwks_uri)
        response.raise_for_status()
        body = response.json()

    keys = body.get("keys", [])
    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now

    logger.debug(f"JWKS refreshed — {len(keys)} keys cached")
    return keys


async def _find_signing_key(token: str, jwks: dict) -> str:
    """
    Find the signing key for the given token from the JWKS.
    If the key is not found, clears the cache, fetches fresh JWKS, and retries once.
    Microsoft rotates keys periodically — a stale cache causes this failure.
    """
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    def _search(keys):
        for key in keys:
            if key.get("kid") == kid:
                return key
        return None
      # Handle both {keys: [...]} dict and raw [...] list
    keys_list = jwks.get("keys", []) if isinstance(jwks, dict) else jwks
    key = _search(keys_list)
    if key:
        return key

    # Key not found — JWKS is stale, force refresh and retry once
    logger.warning(f"Signing key kid={kid} not in cached JWKS — forcing refresh")
    _jwks_cache["keys"]       = None
    _jwks_cache["fetched_at"] = 0.0
    fresh_jwks = await _get_jwks()
    keys_list = fresh_jwks.get("keys", []) if isinstance(fresh_jwks, dict) else fresh_jwks
    key = _search(keys_list)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signing key not found after JWKS refresh. Try signing out and back in.",
        )
    return key
async def validate_entra_id_token(token: str) -> CurrentUser:
    try:
        jwks = await _get_jwks()
    except Exception as exc:
        logger.error(f"Failed to fetch JWKS: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cannot verify token — JWKS endpoint unreachable",
        )

    signing_key = await _find_signing_key(token, jwks)

    # Try both audience formats — with and without api:// prefix
    last_error = None
    for audience in [settings.client_id, f"api://{settings.client_id}"]:
        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=audience,
                options={
                    "verify_at_hash": False,
                    "verify_iss": False,
                },
            )

            # Manually verify issuer accepts both v1 and v2 formats
            issuer = claims.get("iss", "")
            valid_issuers = [
                f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0",
                f"https://sts.windows.net/{settings.tenant_id}/",
            ]
            if issuer not in valid_issuers:
                raise JWTError(f"Invalid issuer: {issuer}")

            tid = claims.get("tid")
            if tid != settings.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token tenant does not match expected tenant",
                )

            return CurrentUser(
                oid=claims.get("oid", claims.get("sub", "")),
                name=claims.get("name", claims.get("preferred_username", "Unknown")),
                email=claims.get("preferred_username", claims.get("upn", "")),
                tenant_id=tid,
                roles=claims.get("roles", []),
            )
        except JWTError as exc:
            last_error = exc
            continue

    logger.warning(f"Token validation failed: {last_error}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Token invalid or expired: {last_error}",
    )
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    if settings.skip_auth and settings.is_development:
        logger.warning("SKIP_AUTH is enabled — bypassing token validation. Development only.")
        return CurrentUser(
            oid="dev-bypass-oid",
            name="Dev User",
            email="dev@dragnet.com.ng",
            tenant_id=settings.tenant_id,
            roles=["OrgOS.Admin"],
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return await validate_entra_id_token(credentials.credentials)
def require_compliance_lead(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    FastAPI dependency — requires the user to have the Compliance.Lead role.
    Use on endpoints that should only be accessible to compliance team members.
    """
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compliance Lead role required for this action",
        )
    return user
