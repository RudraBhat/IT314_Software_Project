"""Google Identity Services sign-in: token verification and the citizen-only rule."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings

CLIENT_ID = "test-google-client-id.apps.googleusercontent.com"
URL = "/api/v1/auth/google"


@pytest.fixture
def google_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _tokeninfo(payload: dict, status: int = 200):
    """Patch Google's tokeninfo call to return `payload`."""
    response = AsyncMock()
    response.status_code = status
    response.json = lambda: payload
    http = AsyncMock()
    http.get.return_value = response
    patcher = patch("app.routers.auth.httpx.AsyncClient")
    cls = patcher.start()
    cls.return_value.__aenter__.return_value = http
    return patcher


def _post(client, credential="real-looking-google-jwt-token-string"):
    return client.post(URL, json={"credential": credential})


def test_not_configured_is_refused(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    resp = _post(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "GOOGLE_AUTH_UNAVAILABLE"


def test_mock_token_is_not_a_backdoor(client, google_configured):
    """A hand-made 'mock-google-token:<email>' string must never authenticate anyone."""
    patcher = _tokeninfo({"error": "invalid_token"}, status=400)
    try:
        resp = _post(client, "mock-google-token:admin@example.com:Admin")
    finally:
        patcher.stop()
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "GOOGLE_AUTH_FAILED"
    assert "access_token" not in resp.json()


def test_audience_mismatch_is_rejected(client, google_configured):
    patcher = _tokeninfo({"aud": "someone-elses-app", "email": "v@example.com", "email_verified": "true", "sub": "1"})
    try:
        resp = _post(client)
    finally:
        patcher.stop()
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "GOOGLE_AUTH_FAILED"


def test_missing_audience_is_rejected(client, google_configured):
    patcher = _tokeninfo({"email": "v@example.com", "email_verified": "true", "sub": "1"})
    try:
        resp = _post(client)
    finally:
        patcher.stop()
    assert resp.status_code == 401


def test_unverified_email_is_rejected(client, google_configured):
    patcher = _tokeninfo({"aud": CLIENT_ID, "email": "u@example.com", "email_verified": "false", "sub": "1"})
    try:
        resp = _post(client)
    finally:
        patcher.stop()
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "GOOGLE_EMAIL_NOT_VERIFIED"


def test_new_google_user_becomes_a_citizen(client, sql, google_configured):
    email = f"google-{uuid.uuid4().hex[:10]}@test.drch"
    patcher = _tokeninfo({"aud": CLIENT_ID, "email": email, "email_verified": "true", "name": "New Citizen", "sub": "9"})
    try:
        resp = _post(client)
    finally:
        patcher.stop()
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]
    role = sql.execute(
        "SELECT r.code FROM users u JOIN roles r ON r.role_id = u.role_id WHERE u.email = %s", (email,)
    ).fetchone()
    assert role["code"] == "NORMAL_USER"


def test_staff_account_cannot_sign_in_with_google(client, make, google_configured):
    staff = make.staff("DISPATCH")
    patcher = _tokeninfo({"aud": CLIENT_ID, "email": staff["email"], "email_verified": "true", "name": "x", "sub": "9"})
    try:
        resp = _post(client)
    finally:
        patcher.stop()
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "GOOGLE_STAFF_NOT_ALLOWED"
    assert "access_token" not in resp.json()
