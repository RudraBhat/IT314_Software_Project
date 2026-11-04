"""Staff management routes — DM workspace (SUPERVISOR permission required).

Allows a logged-in Disaster Management supervisor to:
  POST /api/v1/dm/staff          — provision a new DM staff account (generates MFA secret)
  GET  /api/v1/dm/staff          — list all DM staff accounts (names, emails, permissions)
  PUT  /api/v1/dm/staff/{uid}/permissions — replace a staff member's permissions
  POST /api/v1/dm/staff/{uid}/reset-mfa  — issue a fresh TOTP secret (revokes sessions)

Only accounts with the SUPERVISOR permission may call these endpoints.
The backend enforces this; the frontend only shows the UI to supervisors.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app import audit, db, security
from app.auth import DM_ROLE, PERMISSIONS, Supervisor
from app.config import get_settings
from app.errors import ApiError
from app.services import email as email_service

router = APIRouter()

MIN_PASSWORD_LENGTH = 12

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateStaffRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    phone: str | None = Field(default=None, max_length=30)
    designation: str | None = Field(default=None, max_length=120)
    permissions: list[str] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, perms: list[str]) -> list[str]:
        unknown = [p for p in perms if p not in PERMISSIONS]
        if unknown:
            raise ValueError(f"Unknown permission(s): {', '.join(unknown)}")
        return sorted(set(perms))


class SetPermissionsRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, perms: list[str]) -> list[str]:
        unknown = [p for p in perms if p not in PERMISSIONS]
        if unknown:
            raise ValueError(f"Unknown permission(s): {', '.join(unknown)}")
        return sorted(set(perms))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_permissions(conn, user_id: uuid.UUID, perms: list[str]) -> None:
    conn.execute("DELETE FROM staff_permissions WHERE user_id = %s", (user_id,))
    for perm in perms:
        conn.execute(
            "INSERT INTO staff_permissions (user_id, permission) VALUES (%s, %s)",
            (user_id, perm),
        )


def _enrol_mfa(conn, user_id: uuid.UUID, email: str) -> dict:
    secret = security.new_totp_secret()
    conn.execute(
        "UPDATE user_auth SET mfa_enabled = TRUE, mfa_secret = %s, token_version = token_version + 1 WHERE user_id = %s",
        (security.encrypt_mfa_secret(secret), user_id),
    )
    return {
        "mfa_secret": secret,
        "mfa_uri": security.provisioning_uri(secret, email),
    }


def _find_dm_staff(conn, user_id: uuid.UUID):
    row = conn.execute(
        """
        SELECT u.user_id, u.email, r.code AS role
        FROM users u JOIN roles r USING (role_id)
        WHERE u.user_id = %s
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Staff account not found")
    if row["role"] != DM_ROLE:
        raise ApiError(400, "NOT_DM_STAFF", "This account is not a Disaster Management staff member")
    return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/staff", status_code=201)
def create_staff(body: CreateStaffRequest, principal: Supervisor):
    """Provision a new DM staff account. Returns the TOTP secret once."""

    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = %s::citext", (body.email,)).fetchone():
            raise ApiError(409, "EMAIL_TAKEN", f"An account with email {body.email} already exists")

        if body.password:
            # Backwards compatibility: Direct provisioning with password
            password_hash = security.hash_password(body.password)
            user_id = conn.execute(
                """
                INSERT INTO users (role_id, email, full_name, phone, designation, status)
                SELECT role_id, %s, %s, %s, %s, 'ACTIVE' FROM roles WHERE code = %s
                RETURNING user_id
                """,
                (body.email, body.full_name, body.phone, body.designation, DM_ROLE),
            ).fetchone()["user_id"]

            conn.execute(
                "INSERT INTO user_auth (user_id, password_hash) VALUES (%s, %s)",
                (user_id, password_hash),
            )
            _set_permissions(conn, user_id, body.permissions)
            mfa = _enrol_mfa(conn, user_id, body.email)

            audit.record(
                conn,
                actor=principal,
                action="STAFF_PROVISIONED",
                entity_type="user",
                entity_id=user_id,
                rationale=f"Provisioned via DM workspace by {principal.email if principal else 'system'}",
                after={"role": DM_ROLE, "permissions": body.permissions},
            )

            return {
                "user_id": str(user_id),
                "email": body.email,
                "full_name": body.full_name,
                "permissions": body.permissions,
                "mfa_secret": mfa["mfa_secret"],
                "mfa_uri": mfa["mfa_uri"],
                "message": (
                    "Account created. Share the MFA secret with the new staff member to enrol "
                    "in their authenticator app. It will not be shown again."
                ),
            }

        # Secure Email Invitation Workflow (password omitted)
        token = security.generate_secure_token(32)
        token_hash = security.hash_token(token)
        expires_at = datetime.now(UTC) + timedelta(hours=get_settings().invitation_token_hours)

        user_id = conn.execute(
            """
            INSERT INTO users (role_id, email, full_name, phone, designation, status)
            SELECT role_id, %s, %s, %s, %s, 'PENDING_SETUP' FROM roles WHERE code = %s
            RETURNING user_id
            """,
            (body.email, body.full_name, body.phone, body.designation, DM_ROLE),
        ).fetchone()["user_id"]

        conn.execute(
            """
            INSERT INTO user_auth (
                user_id, password_hash, mfa_enabled, mfa_secret,
                invitation_token_hash, invitation_expires_at, invited_by
            )
            VALUES (%s, NULL, FALSE, NULL, %s, %s, %s)
            """,
            (user_id, token_hash, expires_at, principal.user_id if principal else None),
        )
        _set_permissions(conn, user_id, body.permissions)

        audit.record(
            conn,
            actor=principal,
            action="ACCOUNT_INVITED",
            entity_type="user",
            entity_id=user_id,
            rationale=f"Staff invited via DM workspace by {principal.email if principal else 'system'}",
            after={"role": DM_ROLE, "permissions": body.permissions},
        )

    email_service.send_invitation_email(body.email, body.full_name, "Disaster Management Staff", token)
    return {
        "user_id": str(user_id),
        "email": body.email,
        "full_name": body.full_name,
        "permissions": body.permissions,
        "status": "PENDING_SETUP",
        "message": "Invitation email dispatched to staff member.",
    }


@router.get("/staff")
def list_staff(principal: Supervisor):
    """List all Disaster Management staff accounts."""

    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT u.user_id, u.email, u.full_name, u.designation, u.status,
                   u.created_at,
                   a.mfa_enabled, a.last_login_at, a.locked_until,
                   COALESCE(
                       json_agg(sp.permission::text ORDER BY sp.permission)
                       FILTER (WHERE sp.permission IS NOT NULL),
                       '[]'
                   ) AS permissions
            FROM users u
            JOIN roles r USING (role_id)
            JOIN user_auth a ON a.user_id = u.user_id
            LEFT JOIN staff_permissions sp ON sp.user_id = u.user_id
            WHERE r.code = %s
            GROUP BY u.user_id, a.mfa_enabled, a.last_login_at, a.locked_until
            ORDER BY u.created_at DESC
            """,
            (DM_ROLE,),
        ).fetchall()

    now = datetime.now(UTC)
    return [
        {
            "user_id": str(r["user_id"]),
            "email": r["email"],
            "full_name": r["full_name"],
            "designation": r["designation"],
            "status": r["status"],
            "mfa_enabled": r["mfa_enabled"],
            "last_login_at": r["last_login_at"],
            "is_locked": r["locked_until"] is not None and r["locked_until"] > now,
            "permissions": r["permissions"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.put("/staff/{user_id}/permissions", status_code=200)
def set_permissions(user_id: uuid.UUID, body: SetPermissionsRequest, principal: Supervisor):
    """Replace a staff member's permissions. Cannot modify your own."""
    if user_id == principal.user_id:
        raise ApiError(400, "SELF_MODIFY", "You cannot change your own permissions")

    with db.transaction() as conn:
        _find_dm_staff(conn, user_id)
        _set_permissions(conn, user_id, body.permissions)
        audit.record(
            conn,
            actor=principal,
            action="PERMISSIONS_SET",
            entity_type="user",
            entity_id=user_id,
            rationale=f"Changed via DM workspace by {principal.email}",
            after={"permissions": body.permissions},
        )
    return {"user_id": str(user_id), "permissions": body.permissions}


@router.post("/staff/{user_id}/reset-mfa", status_code=200)
def reset_mfa(user_id: uuid.UUID, principal: Supervisor):
    """Issue a fresh TOTP secret, revoking all existing sessions for that account."""
    if user_id == principal.user_id:
        raise ApiError(400, "SELF_MODIFY", "Use your own account settings to reset your MFA")

    with db.transaction() as conn:
        row = _find_dm_staff(conn, user_id)
        mfa = _enrol_mfa(conn, user_id, row["email"])
        audit.record(
            conn,
            actor=principal,
            action="MFA_RESET",
            entity_type="user",
            entity_id=user_id,
            rationale=f"Reset via DM workspace by {principal.email}; sessions revoked",
        )
    return {
        "user_id": str(user_id),
        "mfa_secret": mfa["mfa_secret"],
        "mfa_uri": mfa["mfa_uri"],
        "message": "MFA reset. Share the new secret with the staff member. All previous sessions have been revoked.",
    }
