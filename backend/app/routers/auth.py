"""Authentication routes (SRS s.15.3): login, MFA step for staff, logout, own profile."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import audit, db, security
from app.auth import CurrentUser
from app.config import get_settings
from app.errors import ApiError

router = APIRouter(prefix="/api/v1", tags=["auth"])

STAFF_ROLES = ("DISASTER_MGMT", "APP_MGMT")
_GENERIC = "Invalid credentials, or the account is temporarily unavailable"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class MfaVerifyRequest(BaseModel):
    mfa_token: str = Field(min_length=10, max_length=2048)
    code: str = Field(min_length=6, max_length=8)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _load_account(conn, *, email: str | None = None, user_id: uuid.UUID | None = None):
    return conn.execute(
        """
        SELECT u.user_id, u.email, u.full_name, u.status, r.code AS role,
               a.password_hash, a.mfa_enabled, a.mfa_secret, a.failed_login_count,
               a.locked_until, a.token_version
        FROM users u
        JOIN roles r ON r.role_id = u.role_id
        JOIN user_auth a ON a.user_id = u.user_id
        WHERE (%(uid)s::uuid IS NOT NULL AND u.user_id = %(uid)s::uuid)
           OR (%(email)s::citext IS NOT NULL AND u.email = %(email)s::citext)
        FOR UPDATE OF a
        """,
        {"uid": user_id, "email": email},
    ).fetchone()


def _is_locked(account) -> bool:
    return account["locked_until"] is not None and account["locked_until"] > datetime.now(UTC)


def _register_failure(conn, account, ip: str | None, reason: str) -> None:
    settings = get_settings()
    attempts = account["failed_login_count"] + 1
    if attempts >= settings.login_max_attempts:
        conn.execute(
            """
            UPDATE user_auth
            SET failed_login_count = 0,
                locked_until = %s,
                token_version = token_version + 1
            WHERE user_id = %s
            """,
            (datetime.now(UTC) + timedelta(minutes=settings.lockout_minutes), account["user_id"]),
        )
        reason += "; account locked"
    else:
        conn.execute(
            "UPDATE user_auth SET failed_login_count = %s WHERE user_id = %s",
            (attempts, account["user_id"]),
        )
    audit.record(
        conn,
        actor=None,
        action="LOGIN_FAILED",
        entity_type="user",
        entity_id=account["user_id"],
        result="FAILURE",
        rationale=reason,
        ip=ip,
    )


def _complete_login(conn, account, ip: str | None, mfa: bool) -> dict:
    settings = get_settings()
    conn.execute(
        "UPDATE user_auth SET failed_login_count = 0, locked_until = NULL, last_login_at = now() WHERE user_id = %s",
        (account["user_id"],),
    )
    audit.record(
        conn,
        actor=None,
        action="LOGIN_SUCCEEDED",
        entity_type="user",
        entity_id=account["user_id"],
        rationale="password + TOTP" if mfa else "password",
        ip=ip,
    )
    token = security.issue_token(
        account["user_id"],
        account["token_version"],
        security.ACCESS,
        settings.access_token_minutes,
        mfa=mfa,
    )
    return {
        "mfa_required": False,
        "access_token": token,
        "token": token,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "role": account["role"],
        "user": {
            "id": str(account["user_id"]),
            "email": account["email"],
            "name": account["full_name"],
            "role": account["role"],
        },
    }


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=1024)
    full_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


@router.post("/auth/signup", status_code=201)
@router.post("/auth/register", status_code=201)
def signup(body: SignupRequest, request: Request):
    ip = _ip(request)
    email = body.email.strip().lower()
    with db.transaction() as conn:
        existing = conn.execute("SELECT 1 FROM users WHERE email = %s::citext", (email,)).fetchone()
        if existing:
            raise ApiError(409, "EMAIL_TAKEN", f"An account with email {email} already exists")

        user_id = conn.execute(
            """
            INSERT INTO users (role_id, email, full_name, phone, status)
            SELECT role_id, %s, %s, %s, 'ACTIVE' FROM roles WHERE code = 'NORMAL_USER'
            RETURNING user_id
            """,
            (email, body.full_name.strip(), body.phone.strip() if body.phone else None),
        ).fetchone()["user_id"]

        password_hash = security.hash_password(body.password)
        conn.execute(
            "INSERT INTO user_auth (user_id, password_hash, mfa_enabled, mfa_secret) VALUES (%s, %s, FALSE, NULL)",
            (user_id, password_hash),
        )

        audit.record(
            conn,
            actor=None,
            action="CITIZEN_REGISTERED",
            entity_type="user",
            entity_id=user_id,
            result="SUCCESS",
            ip=ip,
        )

        account = _load_account(conn, user_id=user_id)
        return _complete_login(conn, account, ip, mfa=False)


@router.post("/auth/login")
def login(body: LoginRequest, request: Request):
    ip = _ip(request)
    email = body.email.strip().lower()

    settings = get_settings()
    if not settings.database_url:
        if not settings.demo_mode:
            settings.require("database_url")
        # Development / demo fallback when database is not configured
        if email == "commander@resq.gov.in" and body.password in ("admin123password", "admin123"):
            token = security.issue_token(
                uuid.UUID("a0000000-0000-0000-0000-000000000001"),
                1,
                security.MFA,
                get_settings().mfa_token_minutes,
            )
            return {"mfa_required": True, "mfa_token": token}

        security.verify_password(None, body.password)  # equalise timing
        raise ApiError(401, "INVALID_CREDENTIALS", _GENERIC)

    with db.transaction() as conn:
        account = _load_account(conn, email=body.email.strip())
        if account is None:
            security.verify_password(None, body.password)  # equalise timing
            raise ApiError(401, "INVALID_CREDENTIALS", _GENERIC)
        if _is_locked(account) or account["status"] != "ACTIVE":
            raise ApiError(401, "INVALID_CREDENTIALS", _GENERIC)
        if not security.verify_password(account["password_hash"], body.password):
            _register_failure(conn, account, ip, "wrong password")
        elif account["role"] in STAFF_ROLES:
            if not account["mfa_enabled"] or account["mfa_secret"] is None:
                raise ApiError(
                    403,
                    "MFA_NOT_ENROLLED",
                    "Multi-factor authentication is not set up for this staff account. "
                    "Contact Application Management.",
                )
            token = security.issue_token(
                account["user_id"],
                account["token_version"],
                security.MFA,
                get_settings().mfa_token_minutes,
            )
            return {"mfa_required": True, "mfa_token": token}
        else:
            return _complete_login(conn, account, ip, mfa=False)
    # Reached only after a recorded failure; the transaction above has committed it.
    raise ApiError(401, "INVALID_CREDENTIALS", _GENERIC)


@router.post("/auth/mfa/verify")
def verify_mfa(body: MfaVerifyRequest, request: Request):
    ip = _ip(request)
    claims = security.decode_token(body.mfa_token, security.MFA)
    if claims is None:
        raise ApiError(401, "MFA_CHALLENGE_INVALID", "The sign-in challenge expired. Sign in again.")

    settings = get_settings()
    if not settings.database_url:
        if not settings.demo_mode:
            settings.require("database_url")
        if (
            claims["sub"] == "a0000000-0000-0000-0000-000000000001"
            and claims["tv"] == 1
            and body.code in ("123456", "000000")
        ):
            token = security.issue_token(
                uuid.UUID(claims["sub"]),
                claims["tv"],
                security.ACCESS,
                get_settings().access_token_minutes,
                mfa=True,
            )
            return {
                "mfa_required": False,
                "access_token": token,
                "token": token,
                "token_type": "bearer",
                "expires_in": get_settings().access_token_minutes * 60,
                "role": "DISASTER_MGMT",
                "user": {
                    "id": claims["sub"],
                    "email": "commander@resq.gov.in",
                    "name": "Incident Commander",
                    "role": "DISASTER_MGMT",
                },
            }
        raise ApiError(401, "MFA_INVALID", "The verification code is not valid")

    with db.transaction() as conn:
        account = _load_account(conn, user_id=uuid.UUID(claims["sub"]))
        if (
            account is None
            or account["status"] != "ACTIVE"
            or account["token_version"] != claims["tv"]
            or _is_locked(account)
        ):
            raise ApiError(401, "INVALID_CREDENTIALS", _GENERIC)
        secret = security.decrypt_mfa_secret(account["mfa_secret"])
        if secret is not None and security.verify_totp(secret, body.code):
            return _complete_login(conn, account, ip, mfa=True)
        _register_failure(conn, account, ip, "wrong MFA code")
    raise ApiError(401, "MFA_INVALID", "The verification code is not valid")


@router.post("/auth/logout", status_code=204)
def logout(principal: CurrentUser):
    if not get_settings().database_url:
        return
    # Bumping token_version revokes every token issued to this user.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_auth SET token_version = token_version + 1 WHERE user_id = %s",
            (principal.user_id,),
        )
        audit.record(
            conn,
            actor=principal,
            action="LOGOUT",
            entity_type="user",
            entity_id=principal.user_id,
            ip=principal.ip,
        )


@router.get("/me")
@router.get("/auth/me")
def me(principal: CurrentUser):
    return {
        "user_id": principal.user_id,
        "email": principal.email,
        "full_name": principal.full_name,
        "role": principal.role,
        "permissions": sorted(principal.permissions),
        "mfa_verified": principal.mfa_verified,
    }
