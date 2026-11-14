"""Secure email invitations and password reset.

Guard tests run without a database; the flow tests need the PostgreSQL test database.
"""

import uuid

import pyotp
import pytest
from starlette.requests import Request

from app import security
from app.auth import APP_MGMT_ROLE, DM_ROLE, FIELD_TEAM_ROLE, PERMISSIONS, Principal
from app.errors import ApiError
from app.routers import auth as auth_router
from app.services import email as email_service


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 54321), "headers": []})


def _principal(role: str, permissions) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email=f"{role.lower()}@test.drch",
        full_name=role,
        role=role,
        mfa_verified=True,
        permissions=frozenset(permissions),
        ip="127.0.0.1",
    )


@pytest.fixture(autouse=True)
def clean_outbox():
    email_service.clear_outbox()
    yield
    email_service.clear_outbox()


def _token_from_outbox(marker: str) -> str:
    return email_service.get_outbox()[-1]["text"].split(marker)[1].split()[0]


# ----------------------------------------------------------------------- guards (no database)


def test_supervisor_cannot_create_admin():
    body = auth_router.InviteUserRequest(email="a@test.drch", full_name="New Admin", role=APP_MGMT_ROLE)
    with pytest.raises(ApiError) as exc:
        auth_router.invite_user(body, _principal(DM_ROLE, ["SUPERVISOR"]), _request())
    assert exc.value.status == 403 and exc.value.code == "PRIVILEGE_ESCALATION"


def test_citizens_cannot_be_invited():
    body = auth_router.InviteUserRequest(email="c@test.drch", full_name="Citizen", role="NORMAL_USER")
    with pytest.raises(ApiError) as exc:
        auth_router.invite_user(body, _principal(APP_MGMT_ROLE, PERMISSIONS), _request())
    assert exc.value.status == 400 and exc.value.code == "CANNOT_INVITE_CITIZEN"


def test_supervisor_cannot_grant_permissions_they_lack():
    body = auth_router.InviteUserRequest(email="s@test.drch", full_name="Staff", role=DM_ROLE, permissions=["CLOSURE"])
    with pytest.raises(ApiError) as exc:
        auth_router.invite_user(body, _principal(DM_ROLE, ["SUPERVISOR", "DISPATCH"]), _request())
    assert exc.value.status == 403 and exc.value.code == "PRIVILEGE_ESCALATION"


def test_field_team_invitation_without_a_team_is_rejected():
    """Issue #101: the invitation must not create a responder that can never be assigned."""
    body = auth_router.InviteUserRequest(email="f@test.drch", full_name="Responder", role=FIELD_TEAM_ROLE)
    with pytest.raises(ApiError) as exc:
        auth_router.invite_user(body, _principal(APP_MGMT_ROLE, PERMISSIONS), _request())
    assert exc.value.status == 422 and exc.value.code == "TEAM_REQUIRED"


def test_team_fields_are_refused_for_non_field_roles():
    body = auth_router.InviteUserRequest(
        email="d@test.drch", full_name="Dispatcher", role=DM_ROLE, team_resource_id=uuid.uuid4()
    )
    with pytest.raises(ApiError) as exc:
        auth_router.invite_user(body, _principal(APP_MGMT_ROLE, PERMISSIONS), _request())
    assert exc.value.status == 422 and exc.value.code == "TEAM_NOT_APPLICABLE"


def test_token_hash_is_deterministic_sha256():
    assert security.hash_token("abc-123456") == security.hash_token("abc-123456")
    assert len(security.hash_token("abc-123456")) == 64


# ----------------------------------------------------------------------- invitation flow (database)


def _invite(client, headers, role, email, **extra):
    return client.post(
        "/api/v1/auth/invitations",
        headers=headers,
        json={"email": email, "full_name": "Invited Person", "role": role, **extra},
    )


def test_invited_staff_sets_password_and_enrols_totp(client, make):
    admin = make.user(APP_MGMT_ROLE)
    email = f"invitee-{uuid.uuid4().hex[:8]}@test.drch"
    resp = _invite(client, make.token(admin), DM_ROLE, email, permissions=["DISPATCH"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "PENDING_SETUP"

    token = _token_from_outbox("setup-account?token=")
    info = client.get("/api/v1/auth/invitation/verify", params={"token": token})
    assert info.status_code == 200 and info.json()["requires_mfa"] is True

    # An account that has not finished setup cannot log in.
    blocked = client.post("/api/v1/auth/login", json={"email": email, "password": "Whatever-Password-1"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "ACCOUNT_NOT_SETUP"

    accepted = client.post("/api/v1/auth/invitation/accept", json={"token": token, "password": "A-Long-Secure-Pass-1"})
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["mfa_required"] is True and body["mfa_secret"]

    done = client.post(
        "/api/v1/auth/invitation/verify-totp",
        json={"mfa_setup_token": body["mfa_setup_token"], "code": pyotp.TOTP(body["mfa_secret"]).now()},
    )
    assert done.status_code == 200, done.text
    assert done.json()["access_token"]

    # The token is single-use.
    again = client.get("/api/v1/auth/invitation/verify", params={"token": token})
    assert again.status_code == 400 and again.json()["error"]["code"] == "INVITATION_INVALID"


def test_wrong_totp_does_not_activate_the_account(client, make, sql):
    admin = make.user(APP_MGMT_ROLE)
    email = f"invitee-{uuid.uuid4().hex[:8]}@test.drch"
    _invite(client, make.token(admin), FIELD_TEAM_ROLE, email, team_resource_id=str(make.resource()["resource_id"]))
    token = _token_from_outbox("setup-account?token=")
    body = client.post("/api/v1/auth/invitation/accept", json={"token": token, "password": "A-Long-Secure-Pass-1"}).json()

    bad = client.post("/api/v1/auth/invitation/verify-totp", json={"mfa_setup_token": body["mfa_setup_token"], "code": "000000"})
    assert bad.status_code == 401
    status = sql.execute("SELECT status FROM users WHERE email = %s", (email,)).fetchone()["status"]
    assert status == "PENDING_SETUP"


def test_expired_invitation_is_rejected(client, make, sql):
    admin = make.user(APP_MGMT_ROLE)
    email = f"invitee-{uuid.uuid4().hex[:8]}@test.drch"
    _invite(client, make.token(admin), FIELD_TEAM_ROLE, email, team_resource_id=str(make.resource()["resource_id"]))
    token = _token_from_outbox("setup-account?token=")
    sql.execute(
        "UPDATE user_auth SET invitation_expires_at = now() - interval '1 minute' "
        "WHERE user_id = (SELECT user_id FROM users WHERE email = %s)",
        (email,),
    )
    assert client.get("/api/v1/auth/invitation/verify", params={"token": token}).status_code == 400


def test_invited_field_team_user_is_linked_to_the_team_and_can_use_field_routes(client, make, sql):
    """Issue #101 acceptance: invite with a team, accept, enrol TOTP, then GET /field/assignments is 200."""
    admin = make.user(APP_MGMT_ROLE)
    team = make.resource()
    email = f"responder-{uuid.uuid4().hex[:8]}@test.drch"
    resp = _invite(
        client,
        make.token(admin),
        FIELD_TEAM_ROLE,
        email,
        team_resource_id=str(team["resource_id"]),
        callsign="Delta-7",
        is_leader=True,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["team"]["team_resource_id"] == str(team["resource_id"])

    member = sql.execute(
        "SELECT m.resource_id, m.callsign, m.is_leader FROM field_team_members m "
        "JOIN users u ON u.user_id = m.user_id WHERE u.email = %s",
        (email,),
    ).fetchone()
    assert member == {"resource_id": team["resource_id"], "callsign": "Delta-7", "is_leader": True}

    token = _token_from_outbox("setup-account?token=")
    accepted = client.post("/api/v1/auth/invitation/accept", json={"token": token, "password": "A-Long-Secure-Pass-1"}).json()
    done = client.post(
        "/api/v1/auth/invitation/verify-totp",
        json={"mfa_setup_token": accepted["mfa_setup_token"], "code": pyotp.TOTP(accepted["mfa_secret"]).now()},
    )
    assert done.status_code == 200, done.text
    headers = {"Authorization": f"Bearer {done.json()['access_token']}"}

    assignments = client.get("/api/v1/field/assignments", headers=headers)
    assert assignments.status_code == 200, assignments.text
    profile = client.get("/api/v1/field/me", headers=headers)
    assert profile.status_code == 200 and profile.json()["callsign"] == "Delta-7"


def test_field_team_invitation_with_unknown_team_creates_nothing(client, make, sql):
    admin = make.user(APP_MGMT_ROLE)
    email = f"responder-{uuid.uuid4().hex[:8]}@test.drch"
    resp = _invite(client, make.token(admin), FIELD_TEAM_ROLE, email, team_resource_id=str(uuid.uuid4()))
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "TEAM_NOT_FOUND"
    assert sql.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone() is None
    assert email_service.get_outbox() == []


def test_field_team_invitation_over_http_without_team_is_422(client, make):
    admin = make.user(APP_MGMT_ROLE)
    resp = _invite(client, make.token(admin), FIELD_TEAM_ROLE, f"r-{uuid.uuid4().hex[:8]}@test.drch")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "TEAM_REQUIRED"


def test_operator_without_supervisor_cannot_invite(client, make):
    operator = make.staff("DISPATCH")
    resp = _invite(client, operator["headers"], FIELD_TEAM_ROLE, f"x-{uuid.uuid4().hex[:8]}@test.drch")
    assert resp.status_code == 403


# ----------------------------------------------------------------------- invitation management (issue #100)


def _invite_dm(client, headers, email=None):
    email = email or f"invitee-{uuid.uuid4().hex[:8]}@test.drch"
    resp = _invite(client, headers, DM_ROLE, email, permissions=["DISPATCH"])
    assert resp.status_code == 201, resp.text
    return resp.json()["user_id"], email


def test_list_shows_pending_invitations_with_scope(client, make):
    admin = make.token(make.user(APP_MGMT_ROLE))
    supervisor = make.staff("SUPERVISOR", "DISPATCH")["headers"]
    dm_id, _ = _invite_dm(client, admin)
    admin_invite = _invite(client, admin, APP_MGMT_ROLE, f"adm-{uuid.uuid4().hex[:8]}@test.drch").json()["user_id"]

    as_admin = {i["user_id"]: i for i in client.get("/api/v1/auth/invitations", headers=admin).json()["items"]}
    assert as_admin[dm_id]["permissions"] == ["DISPATCH"] and as_admin[dm_id]["expired"] is False
    assert admin_invite in as_admin

    as_supervisor = {i["user_id"] for i in client.get("/api/v1/auth/invitations", headers=supervisor).json()["items"]}
    assert dm_id in as_supervisor and admin_invite not in as_supervisor
    # A supervisor cannot act on an administrator invitation; it is not even revealed.
    assert client.post(f"/api/v1/auth/invitations/{admin_invite}/resend", headers=supervisor).status_code == 404


def test_resend_replaces_the_link(client, make):
    admin = make.token(make.user(APP_MGMT_ROLE))
    user_id, _ = _invite_dm(client, admin)
    old_token = _token_from_outbox("setup-account?token=")

    resp = client.post(f"/api/v1/auth/invitations/{user_id}/resend", headers=admin)
    assert resp.status_code == 200, resp.text
    new_token = _token_from_outbox("setup-account?token=")
    assert new_token != old_token
    assert client.get("/api/v1/auth/invitation/verify", params={"token": old_token}).status_code == 400
    assert client.get("/api/v1/auth/invitation/verify", params={"token": new_token}).status_code == 200


def test_revoke_removes_the_pending_account_and_allows_reinvite(client, make, sql):
    admin = make.token(make.user(APP_MGMT_ROLE))
    user_id, email = _invite_dm(client, admin)
    token = _token_from_outbox("setup-account?token=")

    assert client.delete(f"/api/v1/auth/invitations/{user_id}", headers=admin).status_code == 204
    assert sql.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,)).fetchone() is None
    assert client.get("/api/v1/auth/invitation/verify", params={"token": token}).status_code == 400
    assert client.delete(f"/api/v1/auth/invitations/{user_id}", headers=admin).status_code == 404
    _invite_dm(client, admin, email)  # the email is free again


def test_active_accounts_cannot_be_resent_or_revoked(client, make):
    admin = make.token(make.user(APP_MGMT_ROLE))
    active = make.staff("DISPATCH")
    assert client.post(f"/api/v1/auth/invitations/{active['user_id']}/resend", headers=admin).status_code == 404
    assert client.delete(f"/api/v1/auth/invitations/{active['user_id']}", headers=admin).status_code == 404


def test_team_picker_lists_team_resources_for_inviters_only(client, make):
    team = make.resource()
    admin = make.token(make.user(APP_MGMT_ROLE))
    ids = {t["resource_id"] for t in client.get("/api/v1/auth/invitations/teams", headers=admin).json()["items"]}
    assert str(team["resource_id"]) in ids
    operator = make.staff("DISPATCH")["headers"]
    assert client.get("/api/v1/auth/invitations/teams", headers=operator).status_code == 403
    assert client.get("/api/v1/auth/invitations", headers=operator).status_code == 403


# ----------------------------------------------------------------------- password reset (database)

GENERIC = "If this email is registered and active, a password reset link has been sent."


def test_forgot_password_does_not_reveal_whether_the_email_exists(client, make):
    citizen = make.citizen()
    unknown = client.post("/api/v1/auth/forgot-password", json={"email": "nobody-here@test.drch"})
    known = client.post("/api/v1/auth/forgot-password", json={"email": citizen["email"]})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json()["message"] == known.json()["message"] == GENERIC
    outbox = email_service.get_outbox()
    assert [m["to"] for m in outbox] == [citizen["email"]]


def test_reset_password_is_single_use_and_revokes_sessions(client, make, sql):
    citizen = make.citizen()
    old_headers = citizen["headers"]
    client.post("/api/v1/auth/forgot-password", json={"email": citizen["email"]})
    token = _token_from_outbox("reset-password?token=")

    assert client.get("/api/v1/auth/reset-password/verify", params={"token": token}).status_code == 200
    reset = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "Brand-New-Password-1"})
    assert reset.status_code == 200, reset.text

    again = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "Another-Password-22"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "RESET_TOKEN_INVALID"

    # The old session token was issued before token_version was bumped.
    assert client.get("/api/v1/auth/me", headers=old_headers).status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": citizen["email"], "password": "Brand-New-Password-1"})
    assert login.status_code == 200
    stored = sql.execute(
        "SELECT password_reset_token_hash FROM user_auth WHERE user_id = %s", (citizen["user_id"],)
    ).fetchone()
    assert stored["password_reset_token_hash"] is None
