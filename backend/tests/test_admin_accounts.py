"""Administrator staff account directory: GET /api/v1/admin/accounts."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
import pytest

pytestmark = pytest.mark.db

URL = "/api/v1/admin/accounts"
SAFE_KEYS = {
    "user_id", "email", "full_name", "role", "designation", "status", "mfa_enabled", "last_login_at",
    "is_locked", "permissions", "team_name", "created_at", "is_you", "active_sessions",
}


def _admin(make):
    admin = make.user("APP_MGMT")
    return admin, make.token(admin)


def _find(client, headers, **params):
    r = client.get(URL, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_sees_staff_accounts_with_only_safe_fields(make, client):
    admin, headers = _admin(make)
    body = _find(client, headers, q=admin["email"])
    assert body["total"] == 1
    item = body["items"][0]
    assert set(item) == SAFE_KEYS, "no phone, password hash, MFA secret or session data may be listed"
    assert item["email"] == admin["email"] and item["role"] == "APP_MGMT"
    assert item["status"] == "ACTIVE" and item["mfa_enabled"] is True and item["is_you"] is True
    assert item["is_locked"] is False


def test_citizens_are_never_listed(make, client):
    _, headers = _admin(make)
    citizen = make.citizen()
    assert _find(client, headers, q=citizen["email"])["total"] == 0


def test_dispatcher_permissions_and_field_team_are_shown(make, client):
    _, headers = _admin(make)
    dispatcher = make.user("DISASTER_MGMT", permissions=("DISPATCH", "PUBLISHER"))
    responder = make.field_team_user()
    d = _find(client, headers, q=dispatcher["email"])["items"][0]
    assert d["role"] == "DISASTER_MGMT" and d["permissions"] == ["DISPATCH", "PUBLISHER"] and d["is_you"] is False
    f = _find(client, headers, q=responder["email"])["items"][0]
    assert f["role"] == "FIELD_TEAM" and f["team_name"]


def test_filters_by_role_status_and_search(make, client, sql):
    _, headers = _admin(make)
    tag = uuid.uuid4().hex[:10]
    dispatcher = make.user("DISASTER_MGMT")
    pending = make.user("FIELD_TEAM")
    sql.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (f"Alpha {tag}", dispatcher["user_id"]))
    sql.execute("UPDATE users SET full_name = %s, status = 'PENDING_SETUP' WHERE user_id = %s", (f"Beta {tag}", pending["user_id"]))
    assert _find(client, headers, q=tag)["total"] == 2
    only_dm = _find(client, headers, q=tag, role="DISASTER_MGMT")
    assert [i["user_id"] for i in only_dm["items"]] == [str(dispatcher["user_id"])]
    only_pending = _find(client, headers, q=tag, status="PENDING_SETUP")
    assert [i["user_id"] for i in only_pending["items"]] == [str(pending["user_id"])]
    assert _find(client, headers, q=tag, role="APP_MGMT")["total"] == 0
    assert _find(client, headers, q=f"alpha {tag}")["total"] == 1  # case-insensitive


def test_search_treats_percent_and_underscore_literally(make, client):
    _, headers = _admin(make)
    assert _find(client, headers, q="%")["total"] == 0
    assert _find(client, headers, q="zzzz_not_a_wildcard_%_zzzz")["total"] == 0


def test_paging(make, client, sql):
    _, headers = _admin(make)
    tag = uuid.uuid4().hex[:10]
    for i in range(3):
        user = make.user("DISASTER_MGMT")
        sql.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (f"Pager {tag} {i}", user["user_id"]))
    first = _find(client, headers, q=tag, limit=2, page=1)
    second = _find(client, headers, q=tag, limit=2, page=2)
    assert first["total"] == 3 and first["pages"] == 2 and len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert not {i["user_id"] for i in first["items"]} & {i["user_id"] for i in second["items"]}


def test_locked_account_is_flagged(make, client, sql):
    _, headers = _admin(make)
    user = make.user("DISASTER_MGMT")
    sql.execute("UPDATE user_auth SET locked_until = now() + interval '1 hour' WHERE user_id = %s", (user["user_id"],))
    assert _find(client, headers, q=user["email"])["items"][0]["is_locked"] is True
    sql.execute("UPDATE user_auth SET locked_until = now() - interval '1 hour' WHERE user_id = %s", (user["user_id"],))
    assert _find(client, headers, q=user["email"])["items"][0]["is_locked"] is False


def test_summary_counts_all_staff_whatever_the_filter(make, client):
    _, headers = _admin(make)
    # The database is shared, so compare inside one response rather than across two snapshots.
    narrow = _find(client, headers, role="FIELD_TEAM", status="DISABLED")
    everything = narrow["summary"]
    assert everything["total"] > narrow["total"], "the summary must ignore the filters"
    assert set(everything) == {"total", "by_role", "by_status"}
    assert everything["total"] >= 1 and everything["by_role"]["APP_MGMT"] >= 1 and everything["by_status"]["ACTIVE"] >= 1
    assert "NORMAL_USER" not in everything["by_role"]


@pytest.mark.parametrize("params", [{"role": "NORMAL_USER"}, {"status": "BOGUS"}, {"limit": 0}, {"page": 0}])
def test_invalid_filters_are_rejected(make, client, params):
    _, headers = _admin(make)
    assert client.get(URL, headers=headers, params=params).status_code == 422


def test_only_an_mfa_verified_administrator_can_open_it(make, client):
    admin = make.user("APP_MGMT")
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=make.token(admin, mfa=False)).status_code == 401
    assert client.get(URL, headers=make.citizen()["headers"]).status_code == 403
    assert client.get(URL, headers=make.field_team_user()["headers"]).status_code == 403
    assert client.get(URL, headers=make.staff("DISPATCH")["headers"]).status_code == 403
    supervisor = make.staff("SUPERVISOR")
    assert client.get(URL, headers=supervisor["headers"]).status_code == 403  # dispatch supervisors do not get the directory


# --------------------------------------------------------------------------- disable / enable

REASON = {"reason": "Left the organisation; access no longer needed"}


def _disable(client, headers, user_id, body=REASON):
    return client.post(f"{URL}/{user_id}/disable", headers=headers, json=body)


def _enable(client, headers, user_id, body=REASON):
    return client.post(f"{URL}/{user_id}/enable", headers=headers, json=body)


def test_disable_blocks_sign_in_ends_sessions_and_is_audited(make, client, sql):
    admin, headers = _admin(make)
    staff = make.staff("DISPATCH")
    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 200

    r = _disable(client, headers, staff["user_id"])
    assert r.status_code == 200 and r.json() == {"user_id": str(staff["user_id"]), "status": "DISABLED"}

    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 401  # session ended
    login = client.post("/api/v1/auth/login", json={"email": staff["email"], "password": staff["password"]})
    assert login.status_code == 401 and login.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert _find(client, headers, q=staff["email"])["items"][0]["status"] == "DISABLED"

    row = sql.execute(
        "SELECT actor_id, rationale, before_state, after_state FROM audit_logs "
        "WHERE entity_id = %s AND action = 'ACCOUNT_DISABLED'",
        (staff["user_id"],),
    ).fetchone()
    assert row["actor_id"] == admin["user_id"] and row["rationale"] == REASON["reason"]
    assert row["before_state"]["status"] == "ACTIVE" and row["after_state"]["status"] == "DISABLED"


def test_enable_restores_access_but_not_the_old_session(make, client):
    _, headers = _admin(make)
    staff = make.staff("DISPATCH")
    _disable(client, headers, staff["user_id"])
    r = _enable(client, headers, staff["user_id"], {"reason": "Returned from leave"})
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    login = client.post("/api/v1/auth/login", json={"email": staff["email"], "password": staff["password"]})
    assert login.status_code == 200 and login.json()["mfa_required"] is True
    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 401  # old token stays dead


def test_enable_clears_a_lockout(make, client, sql):
    _, headers = _admin(make)
    staff = make.staff("DISPATCH")
    sql.execute("UPDATE user_auth SET locked_until = now() + interval '1 hour', failed_login_count = 5 WHERE user_id = %s", (staff["user_id"],))
    _disable(client, headers, staff["user_id"])
    _enable(client, headers, staff["user_id"])
    row = sql.execute("SELECT locked_until, failed_login_count FROM user_auth WHERE user_id = %s", (staff["user_id"],)).fetchone()
    assert row["locked_until"] is None and row["failed_login_count"] == 0


def test_account_that_never_finished_setup_returns_to_pending_setup(make, client, sql):
    _, headers = _admin(make)
    invited = make.user("DISASTER_MGMT", mfa=False)
    sql.execute("UPDATE users SET status = 'DISABLED' WHERE user_id = %s", (invited["user_id"],))
    r = _enable(client, headers, invited["user_id"])
    assert r.status_code == 200 and r.json()["status"] == "PENDING_SETUP"


def test_an_administrator_can_disable_another_administrator(make, client):
    _, headers = _admin(make)
    other = make.user("APP_MGMT")
    assert _disable(client, headers, other["user_id"]).status_code == 200
    assert client.get(URL, headers=make.token(other)).status_code == 401


def test_you_cannot_disable_yourself(make, client):
    admin, headers = _admin(make)
    r = _disable(client, headers, admin["user_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "CANNOT_DISABLE_SELF"
    assert client.get(URL, headers=headers).status_code == 200


def test_citizens_and_unknown_accounts_cannot_be_managed(make, client):
    _, headers = _admin(make)
    assert _disable(client, headers, make.citizen()["user_id"]).status_code == 404
    assert _disable(client, headers, uuid.uuid4()).status_code == 404
    assert _enable(client, headers, uuid.uuid4()).status_code == 404


def test_state_conflicts_and_reason_rules(make, client):
    _, headers = _admin(make)
    staff = make.staff("DISPATCH")
    not_disabled = _enable(client, headers, staff["user_id"])
    assert not_disabled.status_code == 409 and not_disabled.json()["error"]["code"] == "NOT_DISABLED"
    assert _disable(client, headers, staff["user_id"]).status_code == 200
    again = _disable(client, headers, staff["user_id"])
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_DISABLED"
    for bad in ({}, {"reason": "no"}, {"reason": "x" * 501}):
        assert _enable(client, headers, staff["user_id"], bad).status_code == 422


def test_the_last_active_administrator_is_protected():
    from app.errors import ApiError
    from app.routers.admin import _ensure_another_active_admin

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Conn:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, *_a, **_k):
            return Result(self.rows)

    with pytest.raises(ApiError) as exc:
        _ensure_another_active_admin(Conn([]), uuid.uuid4())
    assert exc.value.status == 409 and exc.value.code == "LAST_ADMIN"
    _ensure_another_active_admin(Conn([{"user_id": uuid.uuid4()}]), uuid.uuid4())  # another admin exists: allowed


def test_only_an_mfa_verified_administrator_can_disable_or_enable(make, client):
    target = make.staff("DISPATCH")
    admin = make.user("APP_MGMT")
    for action in (_disable, _enable):
        assert action(client, {}, target["user_id"]).status_code == 401
        assert action(client, make.token(admin, mfa=False), target["user_id"]).status_code == 401
        assert action(client, make.citizen()["headers"], target["user_id"]).status_code == 403
        assert action(client, make.field_team_user()["headers"], target["user_id"]).status_code == 403
        assert action(client, make.staff("SUPERVISOR")["headers"], target["user_id"]).status_code == 403
    assert client.get("/api/v1/dm/dashboard", headers=target["headers"]).status_code == 200  # nothing changed


# --------------------------------------------------------------------------- reset a person's sign-in

NEW_PASSWORD = "Brand-New-Passw0rd!"
RESET_REASON = {"reason": "Lost their phone, authenticator no longer available"}


def _reset(client, headers, user_id, body=RESET_REASON):
    return client.post(f"{URL}/{user_id}/reset-credentials", headers=headers, json=body)


def _setup_token(email: str) -> str:
    from app.services import email as email_service

    mails = [m for m in email_service.get_outbox() if m["to"] == email and "reset" in m["subject"].lower()]
    assert mails, "the reset email must have been sent"
    return re.search(r"token=([\w-]+)", mails[-1]["text"]).group(1)


def test_reset_clears_the_sign_in_ends_sessions_and_is_audited(make, client, sql):
    admin, headers = _admin(make)
    staff = make.staff("DISPATCH")
    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 200

    r = _reset(client, headers, staff["user_id"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user_id", "status", "invitation_expires_at", "email_configured"}, "no secret or link in the response"
    assert body["status"] == "PENDING_SETUP"

    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 401  # session ended
    login = client.post("/api/v1/auth/login", json={"email": staff["email"], "password": staff["password"]})
    assert login.status_code == 403 and login.json()["error"]["code"] == "ACCOUNT_NOT_SETUP"
    auth = sql.execute("SELECT mfa_enabled, mfa_secret FROM user_auth WHERE user_id = %s", (staff["user_id"],)).fetchone()
    assert auth["mfa_enabled"] is False and auth["mfa_secret"] is None
    assert _find(client, headers, q=staff["email"])["items"][0]["status"] == "PENDING_SETUP"

    entry = sql.execute(
        "SELECT actor_id, rationale, before_state, after_state FROM audit_logs WHERE entity_id = %s AND action = 'ACCOUNT_CREDENTIALS_RESET'",
        (staff["user_id"],),
    ).fetchone()
    assert entry["actor_id"] == admin["user_id"] and entry["rationale"] == RESET_REASON["reason"]
    assert entry["before_state"]["mfa_enabled"] is True and entry["after_state"]["status"] == "PENDING_SETUP"


def test_the_person_recovers_with_the_emailed_link(make, client):
    _, headers = _admin(make)
    staff = make.staff("DISPATCH")
    assert _reset(client, headers, staff["user_id"]).status_code == 200
    token = _setup_token(staff["email"])

    assert client.get("/api/v1/auth/invitation/verify", params={"token": token}).json()["valid"] is True
    accepted = client.post("/api/v1/auth/invitation/accept", json={"token": token, "password": NEW_PASSWORD})
    assert accepted.status_code == 200, accepted.text
    secret = accepted.json()["mfa_secret"]
    activated = client.post(
        "/api/v1/auth/invitation/verify-totp",
        json={"mfa_setup_token": accepted.json()["mfa_setup_token"], "code": pyotp.TOTP(secret).now()},
    )
    assert activated.status_code == 200, activated.text

    assert client.post("/api/v1/auth/login", json={"email": staff["email"], "password": staff["password"]}).status_code == 401  # old password
    first = client.post("/api/v1/auth/login", json={"email": staff["email"], "password": NEW_PASSWORD})
    assert first.status_code == 200 and first.json()["mfa_required"] is True
    later_code = pyotp.TOTP(secret).at(datetime.now(UTC) + timedelta(seconds=30))
    verified = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": first.json()["mfa_token"], "code": later_code})
    assert verified.status_code == 200, verified.text
    assert client.get("/api/v1/dm/dashboard", headers={"Authorization": f"Bearer {verified.json()['access_token']}"}).status_code == 200
    # the link works only once
    assert client.post("/api/v1/auth/invitation/accept", json={"token": token, "password": NEW_PASSWORD}).status_code == 400


def test_the_email_says_what_happened_and_the_link_is_the_only_secret(make, client):
    from app.services import email as email_service

    _, headers = _admin(make)
    staff = make.staff("DISPATCH")
    _reset(client, headers, staff["user_id"])
    mail = [m for m in email_service.get_outbox() if m["to"] == staff["email"]][-1]
    assert "reset" in mail["subject"].lower() and "administrator reset" in mail["text"]
    assert "/setup-account?token=" in mail["text"] and "expires in" in mail["text"]


def test_an_administrator_can_reset_another_administrator(make, client):
    _, headers = _admin(make)
    other = make.user("APP_MGMT")
    assert _reset(client, headers, other["user_id"]).status_code == 200
    assert client.get(URL, headers=make.token(other)).status_code == 401


def test_reset_guards(make, client):
    admin, headers = _admin(make)
    me = _reset(client, headers, admin["user_id"])
    assert me.status_code == 409 and me.json()["error"]["code"] == "CANNOT_RESET_SELF"
    assert _reset(client, headers, make.citizen()["user_id"]).status_code == 404
    assert _reset(client, headers, uuid.uuid4()).status_code == 404

    staff = make.staff("DISPATCH")
    assert client.post(f"{URL}/{staff['user_id']}/disable", headers=headers, json=REASON).status_code == 200
    disabled = _reset(client, headers, staff["user_id"])
    assert disabled.status_code == 409 and disabled.json()["error"]["code"] == "ACCOUNT_DISABLED"

    other = make.staff("DISPATCH")
    assert _reset(client, headers, other["user_id"]).status_code == 200
    again = _reset(client, headers, other["user_id"])
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_PENDING"
    for bad in ({}, {"reason": "no"}):
        assert _reset(client, headers, make.staff("DISPATCH")["user_id"], bad).status_code == 422


def test_only_an_mfa_verified_administrator_can_reset_a_sign_in(make, client):
    target = make.staff("DISPATCH")
    admin = make.user("APP_MGMT")
    assert _reset(client, {}, target["user_id"]).status_code == 401
    assert _reset(client, make.token(admin, mfa=False), target["user_id"]).status_code == 401
    assert _reset(client, make.citizen()["headers"], target["user_id"]).status_code == 403
    assert _reset(client, make.field_team_user()["headers"], target["user_id"]).status_code == 403
    assert _reset(client, make.staff("SUPERVISOR")["headers"], target["user_id"]).status_code == 403
    assert client.get("/api/v1/dm/dashboard", headers=target["headers"]).status_code == 200  # nothing changed


# --------------------------------------------------------------------------- sign out everywhere

SIGN_OUT_REASON = {"reason": "Laptop was lost on the train"}


def _sign_out(client, headers, user_id, body=SIGN_OUT_REASON):
    return client.post(f"{URL}/{user_id}/sign-out", headers=headers, json=body)


def _staff_session(client, staff) -> dict:
    """Sign a staff member in through the real login so a refresh token exists."""
    first = client.post("/api/v1/auth/login", json={"email": staff["email"], "password": staff["password"]}).json()
    code = pyotp.TOTP(staff["totp_secret"]).now()
    done = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": first["mfa_token"], "code": code})
    assert done.status_code == 200, done.text
    return done.json()


def test_sign_out_ends_every_session_but_keeps_the_account_usable(make, client, sql):
    admin, headers = _admin(make)
    staff = make.user("DISASTER_MGMT", ["DISPATCH"])
    session = _staff_session(client, staff)
    bearer = {"Authorization": f"Bearer {session['access_token']}"}
    assert client.get("/api/v1/dm/dashboard", headers=bearer).status_code == 200
    assert _find(client, headers, q=staff["email"])["items"][0]["active_sessions"] == 1

    r = _sign_out(client, headers, staff["user_id"])
    assert r.status_code == 200
    assert r.json() == {"user_id": str(staff["user_id"]), "status": "ACTIVE", "signed_out": True}

    assert client.get("/api/v1/dm/dashboard", headers=bearer).status_code == 401  # access token dead
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert refreshed.status_code == 401  # and it cannot quietly renew
    live = sql.execute(
        "SELECT count(*) AS n FROM refresh_tokens WHERE user_id = %s AND revoked_at IS NULL", (staff["user_id"],)
    ).fetchone()["n"]
    assert live == 0
    after = _find(client, headers, q=staff["email"])["items"][0]
    assert after["status"] == "ACTIVE" and after["active_sessions"] == 0  # not disabled, no live session

    entry = sql.execute(
        "SELECT actor_id, rationale FROM audit_logs WHERE entity_id = %s AND action = 'ACCOUNT_SIGNED_OUT'",
        (staff["user_id"],),
    ).fetchone()
    assert entry["actor_id"] == admin["user_id"] and entry["rationale"] == SIGN_OUT_REASON["reason"]

    # They can sign straight back in with their password and authenticator.
    again = client.post("/api/v1/auth/login", json={"email": staff["email"], "password": staff["password"]})
    assert again.status_code == 200 and again.json()["mfa_required"] is True


def test_sign_out_guards(make, client):
    admin, headers = _admin(make)
    me = _sign_out(client, headers, admin["user_id"])
    assert me.status_code == 409 and me.json()["error"]["code"] == "CANNOT_SIGN_OUT_SELF"
    assert _sign_out(client, headers, make.citizen()["user_id"]).status_code == 404
    assert _sign_out(client, headers, uuid.uuid4()).status_code == 404

    pending = make.staff("DISPATCH")
    assert _reset(client, headers, pending["user_id"]).status_code == 200
    refused = _sign_out(client, headers, pending["user_id"])
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "NOT_ACTIVE"

    for bad in ({}, {"reason": "no"}):
        assert _sign_out(client, headers, make.staff("DISPATCH")["user_id"], bad).status_code == 422


def test_only_an_mfa_verified_administrator_can_sign_someone_out(make, client):
    target = make.staff("DISPATCH")
    admin = make.user("APP_MGMT")
    assert _sign_out(client, {}, target["user_id"]).status_code == 401
    assert _sign_out(client, make.token(admin, mfa=False), target["user_id"]).status_code == 401
    assert _sign_out(client, make.citizen()["headers"], target["user_id"]).status_code == 403
    assert _sign_out(client, make.field_team_user()["headers"], target["user_id"]).status_code == 403
    assert _sign_out(client, make.staff("SUPERVISOR")["headers"], target["user_id"]).status_code == 403
    assert client.get("/api/v1/dm/dashboard", headers=target["headers"]).status_code == 200  # nothing changed


# --------------------------------------------------------------------------- system status


def test_system_status_reports_health_without_secrets(make, client):
    _, headers = _admin(make)
    r = client.get("/api/v1/admin/system", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["database"]["status"] == "ok" and body["database"]["latency_ms"] >= 0
    assert set(body["accounts"]) == {"invitations_open", "invitations_expired", "locked", "active_without_mfa"}
    assert isinstance(body["email"]["configured"], bool) and isinstance(body["mfa_key_valid"], bool)
    text = r.text.lower()
    for secret in ("smtp_password", "jwt_secret", "database_url", "postgresql://"):
        assert secret not in text


def test_system_status_counts_a_locked_account(make, client, sql):
    _, headers = _admin(make)
    user = make.user("DISASTER_MGMT")
    sql.execute("UPDATE user_auth SET locked_until = now() + interval '1 hour' WHERE user_id = %s", (user["user_id"],))
    assert client.get("/api/v1/admin/system", headers=headers).json()["accounts"]["locked"] >= 1


def test_only_an_mfa_verified_administrator_sees_system_status(make, client):
    assert client.get("/api/v1/admin/system").status_code == 401
    assert client.get("/api/v1/admin/system", headers=make.token(make.user("APP_MGMT"), mfa=False)).status_code == 401
    for headers in (make.citizen()["headers"], make.field_team_user()["headers"], make.staff("SUPERVISOR")["headers"]):
        assert client.get("/api/v1/admin/system", headers=headers).status_code == 403


# --------------------------------------------------------------------------- edit permissions


def _perms(client, headers, user_id, permissions, reason="Moved to the night shift"):
    return client.put(f"{URL}/{user_id}/permissions", headers=headers, json={"permissions": permissions, "reason": reason})


def test_permissions_change_at_once_and_are_audited(make, client, sql):
    admin, headers = _admin(make)
    staff = make.staff("DISPATCH")
    assert client.get("/api/v1/dm/dashboard", headers=staff["headers"]).status_code == 200

    r = _perms(client, headers, staff["user_id"], ["PUBLISHER", "MODERATOR", "PUBLISHER"])
    assert r.status_code == 200 and r.json()["permissions"] == ["MODERATOR", "PUBLISHER"]
    assert _find(client, headers, q=staff["email"])["items"][0]["permissions"] == ["MODERATOR", "PUBLISHER"]

    entry = sql.execute(
        "SELECT actor_id, rationale, before_state, after_state FROM audit_logs WHERE entity_id = %s AND action = 'PERMISSIONS_CHANGED'",
        (staff["user_id"],),
    ).fetchone()
    assert entry["actor_id"] == admin["user_id"] and entry["rationale"] == "Moved to the night shift"
    assert entry["before_state"]["permissions"] == ["DISPATCH"] and entry["after_state"]["permissions"] == ["MODERATOR", "PUBLISHER"]
    # the person is not signed out; the new access applies on their very next request
    me = client.get("/api/v1/me", headers=staff["headers"])
    assert me.status_code == 200 and me.json()["permissions"] == ["MODERATOR", "PUBLISHER"]


def test_permissions_can_be_emptied(make, client):
    _, headers = _admin(make)
    staff = make.staff("DISPATCH", "CLOSURE")
    assert _perms(client, headers, staff["user_id"], []).json()["permissions"] == []


def test_permission_edit_guards(make, client):
    _, headers = _admin(make)
    staff = make.staff("DISPATCH")
    assert _perms(client, headers, staff["user_id"], ["DISPATCH"]).json()["error"]["code"] == "NO_CHANGE"
    assert _perms(client, headers, staff["user_id"], ["ROOT"]).status_code == 422
    assert _perms(client, headers, staff["user_id"], ["PUBLISHER"], "no").status_code == 422
    assert _perms(client, headers, make.field_team_user()["user_id"], ["DISPATCH"]).json()["error"]["code"] == "NO_PERMISSIONS_FOR_ROLE"
    assert _perms(client, headers, make.citizen()["user_id"], ["DISPATCH"]).status_code == 404
    assert _perms(client, headers, uuid.uuid4(), ["DISPATCH"]).status_code == 404


def test_only_an_mfa_verified_administrator_can_edit_permissions(make, client):
    target = make.staff("DISPATCH")
    body = {"permissions": ["PUBLISHER"], "reason": "Not allowed to do this"}
    url = f"{URL}/{target['user_id']}/permissions"
    assert client.put(url, json=body).status_code == 401
    assert client.put(url, headers=make.token(make.user("APP_MGMT"), mfa=False), json=body).status_code == 401
    for headers in (make.citizen()["headers"], make.field_team_user()["headers"], target["headers"], make.staff("SUPERVISOR")["headers"]):
        assert client.put(url, headers=headers, json=body).status_code == 403


# --------------------------------------------------------------------------- export


def _export(client, headers, **params):
    return client.get(f"{URL}/export", headers=headers, params=params)


def test_export_is_a_csv_of_the_filtered_directory_and_is_audited(make, client, sql):
    import csv
    import io

    admin, headers = _admin(make)
    tag = uuid.uuid4().hex[:8]
    staff = make.user("DISASTER_MGMT", permissions=("DISPATCH", "PUBLISHER"))
    sql.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (f"Export {tag}", staff["user_id"]))

    r = _export(client, headers, q=tag)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(r.text.lstrip(chr(0xFEFF)))))
    assert rows[0][:3] == ["Name", "Email", "Role"] and len(rows) == 2
    assert rows[1][0] == f"Export {tag}" and rows[1][2] == "DISASTER_MGMT" and rows[1][8] == "DISPATCH PUBLISHER"

    entry = sql.execute(
        "SELECT actor_id, after_state FROM audit_logs WHERE action = 'ACCOUNTS_EXPORTED' AND actor_id = %s ORDER BY audit_id DESC LIMIT 1",
        (admin["user_id"],),
    ).fetchone()
    assert entry["after_state"]["rows"] == 1 and entry["after_state"]["filters"]["q"] == tag


def test_export_never_includes_secrets_or_citizens(make, client):
    _, headers = _admin(make)
    citizen = make.citizen()
    text = _export(client, headers).text.lower()
    assert citizen["email"].lower() not in text
    for hidden in ("password", "mfa_secret", "phone", "$argon2"):
        assert hidden not in text


def test_export_neutralises_spreadsheet_formulas(make, client, sql):
    import csv
    import io

    _, headers = _admin(make)
    tag = uuid.uuid4().hex[:8]
    staff = make.user("DISASTER_MGMT")
    sql.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (f"=HYPERLINK(\"x\") {tag}", staff["user_id"]))
    rows = list(csv.reader(io.StringIO(_export(client, headers, q=tag).text.lstrip(chr(0xFEFF)))))
    assert rows[1][0].startswith("'=HYPERLINK")


def test_export_rejects_bad_filters_and_non_admins(make, client):
    _, headers = _admin(make)
    assert _export(client, headers, role="NORMAL_USER").status_code == 422
    assert client.get(f"{URL}/export").status_code == 401
    assert client.get(f"{URL}/export", headers=make.token(make.user("APP_MGMT"), mfa=False)).status_code == 401
    for other in (make.citizen()["headers"], make.field_team_user()["headers"], make.staff("SUPERVISOR")["headers"]):
        assert client.get(f"{URL}/export", headers=other).status_code == 403
