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
    _invite(client, make.token(admin), FIELD_TEAM_ROLE, email)
    token = _token_from_outbox("setup-account?token=")
    body = client.post("/api/v1/auth/invitation/accept", json={"token": token, "password": "A-Long-Secure-Pass-1"}).json()

    bad = client.post("/api/v1/auth/invitation/verify-totp", json={"mfa_setup_token": body["mfa_setup_token"], "code": "000000"})
    assert bad.status_code == 401
    status = sql.execute("SELECT status FROM users WHERE email = %s", (email,)).fetchone()["status"]
    assert status == "PENDING_SETUP"


def test_expired_invitation_is_rejected(client, make, sql):
    admin = make.user(APP_MGMT_ROLE)
    email = f"invitee-{uuid.uuid4().hex[:8]}@test.drch"
    _invite(client, make.token(admin), FIELD_TEAM_ROLE, email)
    token = _token_from_outbox("setup-account?token=")
    sql.execute(
        "UPDATE user_auth SET invitation_expires_at = now() - interval '1 minute' "
        "WHERE user_id = (SELECT user_id FROM users WHERE email = %s)",
        (email,),
    )
    assert client.get("/api/v1/auth/invitation/verify", params={"token": token}).status_code == 400


def test_operator_without_supervisor_cannot_invite(client, make):
    operator = make.staff("DISPATCH")
    resp = _invite(client, operator["headers"], FIELD_TEAM_ROLE, f"x-{uuid.uuid4().hex[:8]}@test.drch")
    assert resp.status_code == 403


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
