"""Administrator (APP_MGMT) area: the staff account directory, disabling or re-enabling accounts, resetting a
person's sign-in and the audit log.

Administrators manage accounts but have no operational access. This router lists the platform's
staff accounts (Disaster Management staff, Field Team responders and administrators) so an admin can
see who has access, in what state, and when each person last signed in, and lets an admin switch an
account off (and back on) with a written reason. Every change is audited.

Privacy: citizens are never listed here, and no phone number, password hash, MFA secret or session
detail is returned. Every route needs the APP_MGMT role with verified MFA (AdminUser).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from psycopg import sql
from pydantic import BaseModel, Field

from app import audit, db, security
from app.auth import APP_MGMT_ROLE, DM_ROLE, FIELD_ROLE, AdminUser
from app.common import Filters, Page, page_body
from app.config import get_settings
from app.errors import ApiError, conflict, not_found
from app.ratelimit import rate_limit
from app.services import email as email_service

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

STAFF_ROLES = [DM_ROLE, FIELD_ROLE, APP_MGMT_ROLE]
StaffRole = Literal["DISASTER_MGMT", "FIELD_TEAM", "APP_MGMT"]
AccountStatus = Literal["ACTIVE", "PENDING_SETUP", "DISABLED", "LOCKED", "PENDING_VERIFICATION"]

_FROM = "FROM users u JOIN roles r ON r.role_id = u.role_id JOIN user_auth a ON a.user_id = u.user_id"


_LIST_QUERY = """
SELECT u.user_id, u.email, u.full_name, r.code AS role, u.designation,
       u.status::text AS status, u.created_at,
       a.mfa_enabled, a.last_login_at, a.locked_until,
       COALESCE(
           (SELECT json_agg(sp.permission::text ORDER BY sp.permission::text)
            FROM staff_permissions sp WHERE sp.user_id = u.user_id),
           '[]'
       ) AS permissions,
       (SELECT res.name FROM field_team_members m
        JOIN resources res ON res.resource_id = m.resource_id
        WHERE m.user_id = u.user_id LIMIT 1) AS team_name
{from_} {where}
ORDER BY u.created_at DESC, u.user_id LIMIT %(limit)s OFFSET %(offset)s
"""


def _like(text: str) -> str:
    """A LIKE pattern that matches the text literally (the user's % and _ are not wildcards)."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/accounts")
def list_accounts(
    *,
    principal: AdminUser,
    page: Page,
    q: Annotated[str | None, Query(max_length=100, description="Part of a name or email address")] = None,
    role: StaffRole | None = None,
    status: AccountStatus | None = None,
):
    """Staff accounts, newest first, with filters and paging.

    Returns the page of accounts, the filtered total, and `summary` counts for all staff accounts
    (unaffected by the filters) so the screen can show how many are active, pending or disabled.
    """
    f = Filters()
    f.add("r.code = ANY(%(staff_roles)s)", staff_roles=STAFF_ROLES)
    if role:
        f.add("r.code = %(role)s", role=role)
    if status:
        f.add("u.status = %(status)s::account_status", status=status)
    if q and q.strip():
        f.add("(u.full_name ILIKE %(q)s OR u.email ILIKE %(q)s)", q=_like(q.strip()))
    where = f.where()

    with db.transaction() as conn:
        total = conn.execute(
            sql.SQL("SELECT COUNT(*) AS n {from_} {where}").format(from_=sql.SQL(_FROM), where=where), f.params
        ).fetchone()["n"]
        rows = conn.execute(
            sql.SQL(_LIST_QUERY).format(from_=sql.SQL(_FROM), where=where),
            {**f.params, "limit": page.limit, "offset": page.offset},
        ).fetchall()
        counts = conn.execute(
            "SELECT r.code AS role, u.status::text AS status, COUNT(*) AS n "
            "FROM users u JOIN roles r ON r.role_id = u.role_id WHERE r.code = ANY(%s) GROUP BY 1, 2",
            (STAFF_ROLES,),
        ).fetchall()

    now = datetime.now(UTC)
    items = [
        {
            "user_id": str(r["user_id"]),
            "email": r["email"],
            "full_name": r["full_name"],
            "role": r["role"],
            "designation": r["designation"],
            "status": r["status"],
            "mfa_enabled": r["mfa_enabled"],
            "last_login_at": r["last_login_at"],
            "is_locked": r["locked_until"] is not None and r["locked_until"] > now,
            "permissions": r["permissions"],
            "team_name": r["team_name"],
            "created_at": r["created_at"],
            "is_you": r["user_id"] == principal.user_id,
        }
        for r in rows
    ]
    summary: dict = {"total": 0, "by_role": {}, "by_status": {}}
    for c in counts:
        summary["total"] += c["n"]
        summary["by_role"][c["role"]] = summary["by_role"].get(c["role"], 0) + c["n"]
        summary["by_status"][c["status"]] = summary["by_status"].get(c["status"], 0) + c["n"]
    return {**page_body(items, total, page), "summary": summary}


# --------------------------------------------------------------------------- disable / enable


class StatusChange(BaseModel):
    reason: str = Field(min_length=5, max_length=500, description="Why the account is being switched off or on")


def _lock_staff_account(conn, user_id: uuid.UUID) -> dict:
    """Lock and return a staff account (citizens are not manageable here: 404)."""
    row = conn.execute(
        """
        SELECT u.user_id, u.email, u.full_name, r.code AS role, u.status::text AS status,
               a.mfa_enabled, a.password_hash IS NOT NULL AS has_password
        FROM users u
        JOIN roles r ON r.role_id = u.role_id
        JOIN user_auth a ON a.user_id = u.user_id
        WHERE u.user_id = %s AND r.code = ANY(%s)
        FOR UPDATE OF u
        """,
        (user_id, STAFF_ROLES),
    ).fetchone()
    if row is None:
        raise not_found("Account")
    return row


def _ensure_another_active_admin(conn, target_id: uuid.UUID) -> None:
    """Never leave the platform without a working administrator.

    The other active administrators are locked while we look, so two admins disabling each other at
    the same moment cannot both succeed.
    """
    others = conn.execute(
        """
        SELECT u.user_id FROM users u JOIN roles r ON r.role_id = u.role_id
        WHERE r.code = %s AND u.status = 'ACTIVE' AND u.user_id <> %s
        FOR UPDATE OF u
        """,
        (APP_MGMT_ROLE, target_id),
    ).fetchall()
    if not others:
        raise conflict("LAST_ADMIN", "This is the last active administrator. Create or enable another one first.")


@router.post("/accounts/{user_id}/disable", dependencies=[rate_limit("admin-account", 30, 3600)])
def disable_account(user_id: uuid.UUID, body: StatusChange, principal: AdminUser):
    """Switch a staff account off: it cannot sign in and every current session ends on its next request.

    Needs a reason (audited). You cannot disable yourself, and the last active administrator cannot be
    disabled. Nothing is deleted; the account can be enabled again.
    """
    if user_id == principal.user_id:
        raise conflict("CANNOT_DISABLE_SELF", "You cannot disable your own account")
    with db.transaction() as conn:
        target = _lock_staff_account(conn, user_id)
        if target["status"] == "DISABLED":
            raise conflict("ALREADY_DISABLED", "This account is already disabled")
        if target["role"] == APP_MGMT_ROLE and target["status"] == "ACTIVE":
            _ensure_another_active_admin(conn, user_id)
        conn.execute("UPDATE users SET status = 'DISABLED' WHERE user_id = %s", (user_id,))
        conn.execute("UPDATE user_auth SET token_version = token_version + 1 WHERE user_id = %s", (user_id,))
        audit.record(
            conn,
            actor=principal,
            action="ACCOUNT_DISABLED",
            entity_type="user",
            entity_id=user_id,
            rationale=body.reason.strip(),
            before={"status": target["status"]},
            after={"status": "DISABLED", "role": target["role"]},
            ip=principal.ip,
        )
    return {"user_id": str(user_id), "status": "DISABLED"}


@router.post("/accounts/{user_id}/enable", dependencies=[rate_limit("admin-account", 30, 3600)])
def enable_account(user_id: uuid.UUID, body: StatusChange, principal: AdminUser):
    """Switch a disabled account back on.

    An account that had finished setup becomes ACTIVE (and any lockout is cleared). One that never
    finished setup goes back to PENDING_SETUP and needs a fresh invitation link from the pending list.
    """
    with db.transaction() as conn:
        target = _lock_staff_account(conn, user_id)
        if target["status"] != "DISABLED":
            raise conflict("NOT_DISABLED", "Only a disabled account can be enabled")
        restored = "ACTIVE" if target["has_password"] and target["mfa_enabled"] else "PENDING_SETUP"
        conn.execute("UPDATE users SET status = %s::account_status WHERE user_id = %s", (restored, user_id))
        conn.execute(
            "UPDATE user_auth SET failed_login_count = 0, locked_until = NULL, token_version = token_version + 1 "
            "WHERE user_id = %s",
            (user_id,),
        )
        audit.record(
            conn,
            actor=principal,
            action="ACCOUNT_ENABLED",
            entity_type="user",
            entity_id=user_id,
            rationale=body.reason.strip(),
            before={"status": "DISABLED"},
            after={"status": restored, "role": target["role"]},
            ip=principal.ip,
        )
    return {"user_id": str(user_id), "status": restored}


# --------------------------------------------------------------------------- reset a person's sign-in

_ROLE_NAME = {
    DM_ROLE: "Disaster Management staff",
    FIELD_ROLE: "Field Team responder",
    APP_MGMT_ROLE: "Application administrator",
}


@router.post("/accounts/{user_id}/reset-credentials", dependencies=[rate_limit("admin-account", 30, 3600)])
def reset_credentials(user_id: uuid.UUID, body: StatusChange, principal: AdminUser):
    """Recover a staff member who lost their password or authenticator.

    The account goes back to PENDING_SETUP: the old password and authenticator are cleared, current sessions
    end, and the person gets an email with a single-use link to choose a new password and enrol a new
    authenticator themselves, so no administrator ever sees a secret. They cannot sign in until they finish.
    Needs a reason (audited). You cannot reset yourself, and the last active administrator cannot be reset.
    """
    if user_id == principal.user_id:
        raise conflict("CANNOT_RESET_SELF", "You cannot reset your own sign-in here. Ask another administrator.")
    settings = get_settings()
    token = security.generate_secure_token(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.invitation_token_hours)
    with db.transaction() as conn:
        target = _lock_staff_account(conn, user_id)
        if target["status"] == "DISABLED":
            raise conflict("ACCOUNT_DISABLED", "This account is disabled. Enable it first.")
        if target["status"] == "PENDING_SETUP":
            raise conflict("ALREADY_PENDING", "This account has not finished setup. Resend its invitation from the pending list.")
        if target["role"] == APP_MGMT_ROLE and target["status"] == "ACTIVE":
            _ensure_another_active_admin(conn, user_id)
        conn.execute("UPDATE users SET status = 'PENDING_SETUP' WHERE user_id = %s", (user_id,))
        conn.execute(
            """
            UPDATE user_auth
            SET mfa_enabled = FALSE, mfa_secret = NULL, token_version = token_version + 1,
                failed_login_count = 0, locked_until = NULL,
                password_reset_token_hash = NULL, password_reset_expires_at = NULL,
                invitation_token_hash = %s, invitation_expires_at = %s, invited_by = %s
            WHERE user_id = %s
            """,
            (security.hash_token(token), expires_at, principal.user_id, user_id),
        )
        audit.record(
            conn,
            actor=principal,
            action="ACCOUNT_CREDENTIALS_RESET",
            entity_type="user",
            entity_id=user_id,
            rationale=body.reason.strip(),
            before={"status": target["status"], "mfa_enabled": target["mfa_enabled"]},
            after={"status": "PENDING_SETUP", "mfa_enabled": False, "role": target["role"]},
            ip=principal.ip,
        )
    email_service.send_credentials_reset_email(
        target["email"], target["full_name"], _ROLE_NAME.get(target["role"], target["role"]), token
    )
    return {
        "user_id": str(user_id),
        "status": "PENDING_SETUP",
        "invitation_expires_at": expires_at,
        "email_configured": bool(settings.smtp_host),
    }


# --------------------------------------------------------------------------- audit log (security and accounts only)

# Administrators have no operational access, so the viewer shows account and security events only: account
# changes and sign-ins (entity "user"), denied requests ("route") and chain checks ("audit"). Incident,
# dispatch, donation and other operational entries are never returned.
AUDIT_ENTITY_TYPES = ["user", "route", "audit"]
AuditResult = Literal["SUCCESS", "FAILURE", "DENIED"]

_AUDIT_QUERY = """
SELECT l.audit_id, l.occurred_at, l.action, l.entity_type, l.entity_id, l.result::text AS result,
       l.rationale, l.actor_role::text AS actor_role, l.ip_address::text AS ip,
       l.before_state, l.after_state, l.actor_id,
       a.full_name AS actor_name, a.email AS actor_email,
       t.full_name AS target_name, t.email AS target_email, tr.code AS target_role
FROM audit_logs l
LEFT JOIN users a ON a.user_id = l.actor_id
LEFT JOIN users t ON l.entity_type = 'user' AND t.user_id = l.entity_id
LEFT JOIN roles tr ON tr.role_id = t.role_id
{where}
ORDER BY l.occurred_at DESC, l.audit_id DESC LIMIT %(limit)s OFFSET %(offset)s
"""

_AUDIT_COUNT = """
SELECT COUNT(*) AS n
FROM audit_logs l
LEFT JOIN users a ON a.user_id = l.actor_id
LEFT JOIN users t ON l.entity_type = 'user' AND t.user_id = l.entity_id
LEFT JOIN roles tr ON tr.role_id = t.role_id
{where}
"""


def _audit_item(r: dict) -> dict:
    """One audit row. A citizen is never identified: no name, email, address or recorded state."""
    citizen_actor = r["actor_role"] == "NORMAL_USER"
    actor = None
    if r["actor_role"] or r["actor_id"]:
        actor = {
            "user_id": None if citizen_actor else (str(r["actor_id"]) if r["actor_id"] else None),
            "role": r["actor_role"],
            "name": None if citizen_actor else r["actor_name"],
            "email": None if citizen_actor else r["actor_email"],
        }
    target = None
    if r["entity_type"] == "user":
        citizen_target = r["target_role"] in (None, "NORMAL_USER")
        target = {
            "role": r["target_role"],
            "name": None if citizen_target else r["target_name"],
            "email": None if citizen_target else r["target_email"],
        }
    return {
        "audit_id": r["audit_id"],
        "occurred_at": r["occurred_at"],
        "action": r["action"],
        "entity_type": r["entity_type"],
        "entity_id": str(r["entity_id"]) if r["entity_id"] else None,
        "result": r["result"],
        "rationale": r["rationale"],
        "actor": actor,
        "target": target,
        "ip": None if citizen_actor else r["ip"],
        "before": None if citizen_actor else r["before_state"],
        "after": None if citizen_actor else r["after_state"],
    }


@router.get("/audit")
def list_audit(
    *,
    principal: AdminUser,
    page: Page,
    q: Annotated[str | None, Query(max_length=100, description="Part of a staff name or email, or of an action")] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    result: AuditResult | None = None,
    user_id: Annotated[uuid.UUID | None, Query(description="Entries made by or about this account")] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
):
    """Account and security audit entries, newest first, with filters and paging.

    Only account and security events are returned (see `AUDIT_ENTITY_TYPES`). Citizens are never named, and
    searching by name or email matches staff only.
    """
    if from_ and to and from_ > to:
        raise ApiError(422, "VALIDATION_FAILED", "The start date must not be after the end date")
    f = Filters()
    f.add("l.entity_type = ANY(%(types)s)", types=AUDIT_ENTITY_TYPES)
    if action:
        f.add("l.action = %(action)s", action=action.strip())
    if result:
        f.add("l.result = %(result)s::audit_result", result=result)
    if user_id:
        f.add("(l.actor_id = %(uid)s OR l.entity_id = %(uid)s)", uid=user_id)
    if from_:
        f.add("l.occurred_at >= %(from_)s::date", from_=from_)
    if to:
        f.add("l.occurred_at < (%(to)s::date + 1)", to=to)
    if q and q.strip():
        f.add(
            "((l.actor_role IS DISTINCT FROM 'NORMAL_USER' AND (a.full_name ILIKE %(q)s OR a.email ILIKE %(q)s)) "
            "OR (tr.code IS DISTINCT FROM 'NORMAL_USER' AND (t.full_name ILIKE %(q)s OR t.email ILIKE %(q)s)) "
            "OR l.action ILIKE %(q)s)",
            q=_like(q.strip()),
        )
    where = f.where()
    with db.transaction() as conn:
        total = conn.execute(sql.SQL(_AUDIT_COUNT).format(where=where), f.params).fetchone()["n"]
        rows = conn.execute(
            sql.SQL(_AUDIT_QUERY).format(where=where), {**f.params, "limit": page.limit, "offset": page.offset}
        ).fetchall()
        actions = conn.execute(
            "SELECT DISTINCT action FROM audit_logs WHERE entity_type = ANY(%s) ORDER BY action LIMIT 200",
            (AUDIT_ENTITY_TYPES,),
        ).fetchall()
    return {**page_body([_audit_item(r) for r in rows], total, page), "facets": {"actions": [a["action"] for a in actions]}}


@router.post("/audit/verify", dependencies=[rate_limit("audit-verify", 6, 3600)])
def verify_audit_log(principal: AdminUser):
    """Check the audit log's SHA-256 hash chain for tampering (the same check as `app.cli verify-audit`).

    The check itself is recorded in the audit log. Rate limited because it reads the whole table.
    """
    with db.transaction() as conn:
        valid, count, message = audit.verify_audit_chain(conn)
        audit.record(
            conn,
            actor=principal,
            action="AUDIT_CHAIN_VERIFIED",
            entity_type="audit",
            result="SUCCESS" if valid else "FAILURE",
            rationale=message,
            ip=principal.ip,
        )
    return {
        "valid": valid,
        "records": count if valid else None,
        "mismatches": None if valid else count,
        "message": message,
        "verified_at": datetime.now(UTC),
    }
