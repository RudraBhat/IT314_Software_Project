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


@pytest.mark.parametrize("status", ["DISABLED", "PENDING_SETUP"])
def test_staff_refusal_does_not_depend_on_account_status(client, make, sql, google_configured, status):
    """A staff email gets the clear staff answer in every state, not a generic invalid-credentials one."""
    staff = make.staff("DISPATCH")
    sql.execute("UPDATE users SET status = %s WHERE user_id = %s", (status, staff["user_id"]))
    patcher = _tokeninfo({"aud": CLIENT_ID, "email": staff["email"], "email_verified": "true", "name": "x", "sub": "9"})
    try:
        resp = _post(client)
    finally:
        patcher.stop()
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "GOOGLE_STAFF_NOT_ALLOWED"


def test_staff_google_attempt_is_audited_and_creates_no_citizen(client, make, sql, google_configured):
    staff = make.staff("DISPATCH")
    patcher = _tokeninfo({"aud": CLIENT_ID, "email": staff["email"].upper(), "email_verified": "true", "name": "x", "sub": "9"})
    try:
        resp = _post(client)
    finally:
        patcher.stop()
    assert resp.json()["error"]["code"] == "GOOGLE_STAFF_NOT_ALLOWED"  # email case does not matter
    denied = sql.execute(
        "SELECT result FROM audit_logs WHERE action = 'GOOGLE_LOGIN_DENIED' AND entity_id = %s", (staff["user_id"],)
    ).fetchone()
    assert denied is not None and denied["result"] == "DENIED"
    assert sql.execute("SELECT COUNT(*) AS n FROM users WHERE email = %s", (staff["email"],)).fetchone()["n"] == 1


def test_staff_email_cannot_register_as_a_citizen(client, make):
    staff = make.staff("DISPATCH")
    for email in (staff["email"], staff["email"].upper()):
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "Strong-pass1!", "full_name": "Impostor"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "DUPLICATE_EMAIL"


def test_google_only_account_is_told_to_set_a_password_first(client, make, sql):
    citizen = make.citizen()
    sql.execute("UPDATE user_auth SET password_hash = NULL WHERE user_id = %s", (citizen["user_id"],))
    assert client.get("/api/v1/me/profile", headers=citizen["headers"]).json()["has_password"] is False
    change = client.post("/api/v1/me/password", headers=citizen["headers"], json={"current_password": "x", "new_password": "Brand-new1!pass"})
    assert change.status_code == 409 and change.json()["error"]["code"] == "NO_PASSWORD_SET"
    delete = client.post("/api/v1/me/account/deletion", headers=citizen["headers"], json={"password": "x"})
    assert delete.status_code == 409 and delete.json()["error"]["code"] == "NO_PASSWORD_SET"
    assert client.get("/api/v1/me/profile", headers=citizen["headers"]).status_code == 200  # nothing changed, still signed in
