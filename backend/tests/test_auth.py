"""Authentication, MFA, lockout and role/permission enforcement."""

import pyotp
import pytest

pytestmark = pytest.mark.db


def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_database_health(client):
    assert client.get("/api/v1/health").json()["database"] == "ok"


def test_staff_login_requires_mfa_then_issues_token(client, make):
    user = make.user("DISASTER_MGMT", ["DISPATCH"])
    first = _login(client, user["email"], user["password"])
    assert first.status_code == 200
    assert first.json()["mfa_required"] is True
    assert "access_token" not in first.json()

    bad = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": first.json()["mfa_token"], "code": "000000"})
    assert bad.status_code == 401

    code = pyotp.TOTP(user["totp_secret"]).now()
    ok = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": first.json()["mfa_token"], "code": code})
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "DISASTER_MGMT"
    assert me["permissions"] == ["DISPATCH"]
    assert me["mfa_verified"] is True
    assert "password_hash" not in str(me) and "mfa_secret" not in str(me)


def test_field_team_login_requires_mfa_then_issues_token(client, make):
    user = make.field_team_user()
    first = _login(client, user["email"], user["password"])
    assert first.status_code == 200
    assert first.json()["mfa_required"] is True
    assert "access_token" not in first.json()

    code = pyotp.TOTP(user["totp_secret"]).now()
    ok = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": first.json()["mfa_token"], "code": code})
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "FIELD_TEAM"
    assert me["mfa_verified"] is True


def test_wrong_password_and_unknown_email_look_identical(client, make):
    user = make.user()
    a = _login(client, user["email"], "nope")
    b = _login(client, "nobody@test.drch", "nope")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_lockout_after_repeated_failures(client, make):
    user = make.user("DISASTER_MGMT", ["DISPATCH"])
    # First, log in legitimately and obtain an active token
    login_res = _login(client, user["email"], user["password"])
    code = pyotp.TOTP(user["totp_secret"]).now()
    ok = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": login_res.json()["mfa_token"], "code": code})
    token = ok.json()["access_token"]
    # Token works initially
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200

    # Trigger lockout
    for _ in range(5):
        _login(client, user["email"], "wrong")

    # Even the right password is refused while locked, with the same generic error.
    locked = _login(client, user["email"], user["password"])
    assert locked.status_code == 401
    assert locked.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # Existing token must now be rejected because user is locked out and token_version rotated
    blocked = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 401


def test_staff_without_mfa_cannot_sign_in(client, make):
    user = make.user("DISASTER_MGMT", mfa=False)
    r = _login(client, user["email"], user["password"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "MFA_NOT_ENROLLED"


def test_seed_admin_placeholder_hash_fails_cleanly(client):
    r = _login(client, "admin@drch.gov.in", "anything")
    assert r.status_code == 401


def test_dm_routes_require_authentication(client):
    assert client.get("/api/v1/dm/dashboard").status_code == 401
    r = client.get("/api/v1/dm/dashboard", headers={"Authorization": "Bearer forged.token.value"})
    assert r.status_code == 401


def test_normal_user_is_denied_and_the_denial_is_audited(client, make, sql):
    citizen = make.user("NORMAL_USER", mfa=False)
    r = client.get("/api/v1/dm/incidents", headers=make.token(citizen, mfa=False))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ROLE_REQUIRED"
    row = sql.execute(
        "SELECT result FROM audit_logs WHERE actor_id = %s AND action = 'ACCESS_DENIED'", (citizen["user_id"],)
    ).fetchone()
    assert row["result"] == "DENIED"


def test_dm_token_without_mfa_is_rejected(client, make):
    staff = make.user("DISASTER_MGMT")
    r = client.get("/api/v1/dm/dashboard", headers=make.token(staff, mfa=False))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "MFA_REQUIRED"


def test_missing_permission_returns_403(client, make):
    staff = make.staff()  # no permissions
    r = client.get("/api/v1/dm/moderation/queue", headers=staff["headers"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PERMISSION_REQUIRED"


def test_logout_revokes_existing_tokens(client, make):
    staff = make.staff()
    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=staff["headers"]).status_code == 204
    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 401


def test_suspended_account_token_stops_working(client, make, sql):
    staff = make.staff()
    sql.execute("UPDATE users SET status = 'DISABLED' WHERE user_id = %s", (staff["user_id"],))
    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 401


def test_audit_log_is_append_only(sql):
    import psycopg

    row = sql.execute(
        "INSERT INTO audit_logs (action, entity_type, rationale) VALUES ('TEST_EVENT', 'test', 'x') "
        "RETURNING audit_id, row_hash, prev_hash"
    ).fetchone()
    assert len(row["row_hash"]) == 64 and len(row["prev_hash"]) == 64
    with pytest.raises(psycopg.errors.RaiseException):
        sql.execute("UPDATE audit_logs SET rationale = 'tampered' WHERE audit_id = %s", (row["audit_id"],))
    with pytest.raises(psycopg.errors.RaiseException):
        sql.execute("DELETE FROM audit_logs WHERE audit_id = %s", (row["audit_id"],))
