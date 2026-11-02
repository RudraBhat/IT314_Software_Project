"""Authentication and authorisation dependencies.

Role and permissions are always resolved from the database on each request
(SRS s.7.6, s.15.1). Nothing the client sends about its role is trusted.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import audit, db
from app.errors import ApiError
from app.security import ACCESS, decode_token

DM_ROLE = "DISASTER_MGMT"
PERMISSIONS = ("PUBLISHER", "MODERATOR", "CLOSURE", "DISPATCH", "SUPERVISOR")

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    mfa_verified: bool
    permissions: frozenset[str] = field(default_factory=frozenset)
    ip: str | None = None

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def _unauthenticated() -> ApiError:
    return ApiError(401, "NOT_AUTHENTICATED", "Authentication required")


def load_principal(
    user_id: uuid.UUID, token_version: int, mfa: bool, ip: str | None = None
) -> Principal | None:
    with db.transaction() as conn:
        row = conn.execute(
            """
            SELECT u.user_id, u.email, u.full_name, u.status, r.code AS role,
                   a.token_version, a.mfa_enabled, a.locked_until
            FROM users u
            JOIN roles r ON r.role_id = u.role_id
            JOIN user_auth a ON a.user_id = u.user_id
            WHERE u.user_id = %s
            """,
            (user_id,),
        ).fetchone()
        if (
            row is None
            or row["status"] != "ACTIVE"
            or row["token_version"] != token_version
            or (row["locked_until"] is not None and row["locked_until"] > datetime.now(UTC))
        ):
            return None
        permissions: frozenset[str] = frozenset()
        if row["role"] == DM_ROLE:
            perms = conn.execute(
                "SELECT permission::text AS p FROM staff_permissions WHERE user_id = %s",
                (user_id,),
            ).fetchall()
            permissions = frozenset(p["p"] for p in perms)
    return Principal(
        user_id=row["user_id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        mfa_verified=mfa and bool(row["mfa_enabled"]),
        permissions=permissions,
        ip=ip,
    )


def current_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthenticated()
    claims = decode_token(creds.credentials, ACCESS)
    if claims is None:
        raise _unauthenticated()
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise _unauthenticated() from None
    ip = request.client.host if request.client else None
    principal = load_principal(user_id, int(claims["tv"]), claims.get("mfa") is True, ip)
    if principal is None:
        raise _unauthenticated()
    return principal


def optional_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal | None:
    """None for anonymous callers; a token that is present but invalid is still a 401."""
    if creds is None:
        return None
    return current_principal(request, creds)


def _deny(principal: Principal, request: Request, code: str, message: str, needed: str | None = None):
    audit.record_standalone(
        actor=principal,
        action="ACCESS_DENIED",
        entity_type="route",
        result="DENIED",
        rationale=f"{request.method} {request.url.path}" + (f" requires {needed}" if needed else ""),
        ip=principal.ip,
    )
    return ApiError(403, code, message)


CurrentUser = Annotated[Principal, Depends(current_principal)]
MaybeUser = Annotated[Principal | None, Depends(optional_principal)]


def require_dm(request: Request, principal: CurrentUser) -> Principal:
    if principal.role != DM_ROLE:
        raise _deny(principal, request, "ROLE_REQUIRED", "Disaster Management role required")
    if not principal.mfa_verified:
        # /dm routes additionally require MFA (SRS s.15.1).
        raise ApiError(401, "MFA_REQUIRED", "Multi-factor authentication is required")
    return principal


DMUser = Annotated[Principal, Depends(require_dm)]

CITIZEN_ROLE = "NORMAL_USER"
FIELD_ROLE = "FIELD_TEAM"


def require_citizen(request: Request, principal: CurrentUser) -> Principal:
    if principal.role != CITIZEN_ROLE:
        raise _deny(principal, request, "ROLE_REQUIRED", "Citizen role required")
    return principal


def require_field(request: Request, principal: CurrentUser) -> Principal:
    if principal.role != FIELD_ROLE:
        raise _deny(principal, request, "ROLE_REQUIRED", "Field team role required")
    return principal


Citizen = Annotated[Principal, Depends(require_citizen)]
FieldUser = Annotated[Principal, Depends(require_field)]


def require_permission(permission: str):
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission {permission}")

    def dependency(request: Request, principal: DMUser) -> Principal:
        if not principal.has(permission):
            raise _deny(
                principal,
                request,
                "PERMISSION_REQUIRED",
                f"The {permission.lower()} permission is required for this action",
                needed=permission,
            )
        return principal

    return dependency


# Typed dependencies for routes (FastAPI's Annotated style).
Publisher = Annotated[Principal, Depends(require_permission("PUBLISHER"))]
Moderator = Annotated[Principal, Depends(require_permission("MODERATOR"))]
Closer = Annotated[Principal, Depends(require_permission("CLOSURE"))]
Dispatcher = Annotated[Principal, Depends(require_permission("DISPATCH"))]
Supervisor = Annotated[Principal, Depends(require_permission("SUPERVISOR"))]
