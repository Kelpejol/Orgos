# =============================================================================
# auth/router.py — Dragnet ERP Tier-1 session endpoints
# GET/DELETE /api/auth/session, POST /api/auth/revoke
# Mounted WITHOUT the /api/v1 prefix — these are infra/session routes, not
# versioned business API, matching the ERP Module-Tier-1 spec literally.
# OrgOS never constructs or sets the erp_auth cookie — only the ERP backend
# does that. This router only ever reads it (GET) or clears it (DELETE, and
# defensively inside GET on validation failure).
# Depends on: auth/validator.py (reuses validate_entra_id_token — no
# duplicate JWT validation logic lives here)
# =============================================================================

import logging
from threading import Timer

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from auth.validator import ROLE_ADMIN, validate_entra_id_token
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# In-memory revoked-users blocklist, keyed by lowercase email. Mirrors the
# ERP reference implementation's Set<string> + 2h auto-clear — the cookie
# itself isn't invalidated, so a revoked user is blocked on their *next*
# session check, then the blocklist entry is consumed (single-shot).
_revoked_emails: set[str] = set()


def _schedule_unrevoke(email: str, delay_seconds: float = 2 * 60 * 60) -> None:
    timer = Timer(delay_seconds, _revoked_emails.discard, args=(email,))
    timer.daemon = True
    timer.start()


class RevokeRequest(BaseModel):
    email: str
    secret: str


@router.get("/session")
async def get_session(request: Request, response: Response) -> dict:
    """Verify the erp_auth cookie. Called by the frontend on every page load."""
    if settings.skip_auth and settings.is_development:
        logger.warning("SKIP_AUTH is enabled — returning a fixed dev session.")
        return {
            "name": "Dev User",
            "email": "dev@dragnet.com.ng",
            "roles": [ROLE_ADMIN],
            "oid": "dev-bypass-oid",
            "expiresOn": 0,
        }

    token = request.cookies.get("erp_auth")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No session")

    try:
        user = await validate_entra_id_token(token)
    except HTTPException:
        response.delete_cookie("erp_auth")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    email = user.email.lower()
    if email in _revoked_emails:
        _revoked_emails.discard(email)
        response.delete_cookie("erp_auth")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked")

    return {
        "name": user.name,
        "email": user.email,
        "roles": user.roles,
        "oid": user.oid,
        "expiresOn": user.exp * 1000,
    }


@router.delete("/session")
async def delete_session(response: Response) -> dict:
    """Clear the local erp_auth cookie. Called on logout."""
    response.delete_cookie("erp_auth")
    return {"ok": True}


@router.post("/revoke")
async def revoke_session(body: RevokeRequest) -> dict:
    """
    Called by the ERP when a user's org_roles change. Blocks the user's next
    session check, forcing re-authentication with fresh roles.
    """
    if not settings.revoke_secret or body.secret != settings.revoke_secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid secret")
    if not body.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email required")

    email = body.email.lower()
    _revoked_emails.add(email)
    _schedule_unrevoke(email)
    return {"revoked": True}
