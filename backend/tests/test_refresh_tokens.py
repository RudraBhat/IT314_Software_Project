"""Refresh tokens: rotation, reuse detection, idle/absolute limits and the per-user session cap."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from app import db, security
from app.services import sessions


def test_limits_differ_for_staff_and_citizens():
    staff = sessions.limits_for("DISASTER_MGMT")
    citizen = sessions.limits_for("NORMAL_USER")
    assert staff.idle < citizen.idle
    assert staff.absolute < citizen.absolute
    assert sessions.limits_for("APP_MGMT") == staff
    assert sessions.limits_for("FIELD_TEAM") == staff


def test_idle_window_never_passes_the_absolute_limit():
    now = datetime.now(UTC)
    absolute = now + timedelta(hours=1)
    assert sessions.next_expiry(now, timedelta(hours=12), absolute) == absolute
    assert sessions.next_expiry(now, timedelta(minutes=30), absolute) == now + timedelta(minutes=30)


def _citizen_login(client, make):
    user = make.user()
    res = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    assert res.status_code == 200
    return user, res.json()


def _refresh(client, token):
    return client.post("/api/v1/auth/refresh", json={"refresh_token": token})


def _set(token, sql):
    with db.transaction() as conn:
        conn.execute(f"UPDATE refresh_tokens SET {sql} WHERE token_hash = %s", (security.hash_token(token),))


@pytest.mark.db
def test_login_returns_a_refresh_token_and_refresh_rotates_it(client, make):
    _, login = _citizen_login(client, make)
    assert login["refresh_token"] and login["refresh_expires_in"] > login["expires_in"]

    res = _refresh(client, login["refresh_token"])
    assert res.status_code == 200
    body = res.json()
    assert body["refresh_token"] != login["refresh_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


@pytest.mark.db
def test_staff_refresh_keeps_mfa_verified(client, make):
    user = make.user("DISASTER_MGMT", ["DISPATCH"])
    first = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]}).json()
    code = pyotp.TOTP(user["totp_secret"]).now()
    ok = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": first["mfa_token"], "code": code}).json()

    refreshed = _refresh(client, ok["refresh_token"]).json()
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {refreshed['access_token']}"}).json()
    assert me["mfa_verified"] is True


@pytest.mark.db
def test_reusing_a_rotated_token_after_the_grace_window_revokes_the_session(client, make):
    _, login = _citizen_login(client, make)
    old = login["refresh_token"]
    newer = _refresh(client, old).json()["refresh_token"]
    _set(old, "revoked_at = now() - interval '1 minute'")

    reused = _refresh(client, old)
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"
    # The successor belongs to the same session, so it is revoked too.
    assert _refresh(client, newer).status_code == 401


@pytest.mark.db
def test_a_concurrent_refresh_inside_the_grace_window_is_allowed(client, make):
    _, login = _citizen_login(client, make)
    assert _refresh(client, login["refresh_token"]).status_code == 200
    assert _refresh(client, login["refresh_token"]).status_code == 200


@pytest.mark.db
def test_idle_limit_ends_the_session(client, make):
    _, login = _citizen_login(client, make)
    _set(login["refresh_token"], "idle_expires_at = now() - interval '1 second'")
    res = _refresh(client, login["refresh_token"])
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "SESSION_EXPIRED"


@pytest.mark.db
def test_absolute_limit_ends_the_session_even_when_active(client, make):
    _, login = _citizen_login(client, make)
    _set(login["refresh_token"], "absolute_expires_at = now() - interval '1 second'")
    assert _refresh(client, login["refresh_token"]).json()["error"]["code"] == "SESSION_EXPIRED"


@pytest.mark.db
def test_logout_revokes_refresh_tokens(client, make):
    _, login = _citizen_login(client, make)
    out = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {login['access_token']}"})
    assert out.status_code == 204
    assert _refresh(client, login["refresh_token"]).status_code == 401


@pytest.mark.db
def test_unknown_token_is_refused(client):
    res = _refresh(client, "x" * 40)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


@pytest.mark.db
def test_session_count_is_capped(client, make):
    user = make.user()
    tokens = []
    for _ in range(6):
        res = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
        tokens.append(res.json()["refresh_token"])
    assert _refresh(client, tokens[0]).status_code == 401  # the oldest session was dropped
    assert _refresh(client, tokens[-1]).status_code == 200
