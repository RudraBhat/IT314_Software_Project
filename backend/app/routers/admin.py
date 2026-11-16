"""Administrator (APP_MGMT) area: the staff account directory.

Administrators manage accounts but have no operational access. This router lists the platform's
staff accounts (Disaster Management staff, Field Team responders and administrators) so an admin can
see who has access, in what state, and when each person last signed in.

Privacy: citizens are never listed here, and no phone number, password hash, MFA secret or session
detail is returned. Every route needs the APP_MGMT role with verified MFA (AdminUser).
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from psycopg import sql

from app import db
from app.auth import APP_MGMT_ROLE, DM_ROLE, FIELD_ROLE, AdminUser
from app.common import Filters, Page, page_body

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
