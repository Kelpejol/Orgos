# An ended sign-in (no erp_auth cookie, or an expired one) is a 401 the screen can recognise,
# so it renews the sign-in through the ERP instead of showing "Unable to load data". Other
# failures (e.g. SharePoint refusing OrgOS's own credentials) are never marked this way.
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import pytest

from auth import validator
from auth.validator import SESSION_HEADER, get_current_user
from config import settings
from main import app


@pytest.fixture(autouse=True)
def _real_auth():
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.pop(get_current_user, None)
    with patch.object(settings, "skip_auth", False):
        yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def test_no_sign_in_is_marked_as_an_ended_session():
    resp = TestClient(app).get("/api/v1/lifecycle/documents")
    assert resp.status_code == 401 and resp.headers.get(SESSION_HEADER) == "ended"
    session = TestClient(app).get("/api/auth/session")
    assert session.status_code == 401 and session.headers.get(SESSION_HEADER) == "ended"


async def test_an_expired_token_is_marked_as_an_ended_session():
    with patch.object(validator, "_get_jwks", new=AsyncMock(return_value={"keys": []})), \
         patch.object(validator, "_find_signing_key", new=AsyncMock(return_value={"kty": "RSA"})):
        with pytest.raises(HTTPException) as e:
            await validator.validate_entra_id_token("not-a-real-token")
    assert e.value.status_code == 401 and e.value.headers == {SESSION_HEADER: "ended"}


def test_the_browser_may_read_the_header():
    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert SESSION_HEADER in cors.kwargs["expose_headers"]
