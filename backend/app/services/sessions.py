"""Refresh-token sessions: issue, rotate and limit.

A session is a family of refresh tokens. Each token is single-use: refreshing
revokes it and issues a successor in the same family. Three limits apply:

* idle limit      the token expires if unused for this long (slides on use)
* absolute limit  the family ends this long after sign-in, however active
* session count   at most MAX_ACTIVE_SESSIONS families per user; the oldest go first

Only SHA-256 hashes are stored. Role, status, lock and token_version are checked
again at every refresh, so a disabled account, password reset, MFA reset or
logout (all of which bump token_version) ends every session at its next refresh.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app import audit, security
from app.config import Settings, get_settings

STAFF_ROLES = ("DISASTER_MGMT", "APP_MGMT", "FIELD_TEAM")


@dataclass(frozen=True)
class Limits:
    idle: timedelta
    absolute: timedelta


def limits_for(role: str, settings: Settings | None = None) -> Limits:
    settings = settings or get_settings()
    if role in STAFF_ROLES:
        return Limits(
            timedelta(hours=settings.refresh_idle_hours_staff),
            timedelta(hours=settings.refresh_max_hours_staff),
        )
    return Limits(
        timedelta(hours=settings.refresh_idle_hours_citizen),
        timedelta(hours=settings.refresh_max_hours_citizen),
    )


def next_expiry(now: datetime, idle: timedelta, absolute_expires_at: datetime) -> datetime:
    """The idle window slides forward but never past the fixed absolute limit."""
    return min(now + idle, absolute_expires_at)


def _insert(
    conn,
    *,
    user_id,
    family_id: uuid.UUID,
    token_version: int,
    mfa: bool,
    idle_expires_at: datetime,
    absolute_expires_at: datetime,
) -> str:
    raw = security.generate_secure_token(48)
    conn.execute(
        """
        INSERT INTO refresh_tokens
            (user_id, family_id, token_hash, token_version, mfa_verified,
             idle_expires_at, absolute_expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, family_id, security.hash_token(raw), token_version, mfa, idle_expires_at, absolute_expires_at),
    )
    return raw


def start_session(conn, account, mfa: bool) -> tuple[str, int]:
    """Begin a new session at sign-in. Returns (refresh token, seconds until its idle limit)."""
    settings = get_settings()
    limits = limits_for(account["role"], settings)
    now = datetime.now(UTC)
    absolute = now + limits.absolute
    idle_expires = next_expiry(now, limits.idle, absolute)
    raw = _insert(
        conn,
        user_id=account["user_id"],
        family_id=uuid.uuid4(),
        token_version=account["token_version"],
        mfa=mfa,
        idle_expires_at=idle_expires,
        absolute_expires_at=absolute,
    )
    _enforce_session_limit(conn, account["user_id"], settings.max_active_sessions)
    return raw, int((idle_expires - now).total_seconds())


def _enforce_session_limit(conn, user_id, max_sessions: int) -> None:
    """Revoke the oldest sessions beyond the per-user limit."""
    conn.execute(
        """
        UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = 'SESSION_LIMIT'
        WHERE user_id = %s AND revoked_at IS NULL AND family_id IN (
            SELECT family_id FROM refresh_tokens
            WHERE user_id = %s AND revoked_at IS NULL
            GROUP BY family_id
            ORDER BY MIN(created_at) DESC
            OFFSET %s
        )
        """,
        (user_id, user_id, max_sessions),
    )


def revoke_all(conn, user_id, reason: str) -> None:
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = %s WHERE user_id = %s AND revoked_at IS NULL",
        (reason, user_id),
    )


@dataclass(frozen=True)
class Rotation:
    """Outcome of a refresh attempt. `error` is set when the caller must answer 401."""

    refresh_token: str | None = None
    expires_in: int = 0
    user_id: uuid.UUID | None = None
    role: str | None = None
    token_version: int = 0
    mfa: bool = False
    error: str | None = None


def rotate(conn, raw_token: str, ip: str | None) -> Rotation:
    """Exchange a refresh token for its successor. Never raises for a bad token: the caller
    answers 401 after the transaction has committed any revocation done here."""
    settings = get_settings()
    now = datetime.now(UTC)
    row = conn.execute(
        """
        SELECT t.*, u.status, r.code AS role, a.token_version AS current_version, a.locked_until
        FROM refresh_tokens t
        JOIN users u ON u.user_id = t.user_id
        JOIN roles r ON r.role_id = u.role_id
        JOIN user_auth a ON a.user_id = t.user_id
        WHERE t.token_hash = %s
        FOR UPDATE OF t
        """,
        (security.hash_token(raw_token),),
    ).fetchone()
    if row is None:
        return Rotation(error="INVALID_REFRESH_TOKEN")

    if row["revoked_at"] is not None:
        grace = timedelta(seconds=settings.refresh_reuse_grace_seconds)
        benign_race = row["revoked_reason"] == "ROTATED" and now - row["revoked_at"] <= grace
        if not benign_race:
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = 'REUSE_DETECTED' "
                "WHERE family_id = %s AND revoked_at IS NULL",
                (row["family_id"],),
            )
            audit.record(
                conn,
                actor=None,
                action="REFRESH_TOKEN_REUSE",
                entity_type="user",
                entity_id=row["user_id"],
                result="DENIED",
                rationale="A rotated refresh token was presented again; the session was revoked",
                ip=ip,
            )
            return Rotation(error="REFRESH_TOKEN_REUSED")

    ended = (
        now >= row["idle_expires_at"]
        or now >= row["absolute_expires_at"]
        or row["status"] != "ACTIVE"
        or row["token_version"] != row["current_version"]
        or (row["locked_until"] is not None and row["locked_until"] > now)
    )
    if ended:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = 'EXPIRED' "
            "WHERE family_id = %s AND revoked_at IS NULL",
            (row["family_id"],),
        )
        return Rotation(error="SESSION_EXPIRED")

    if row["revoked_at"] is None:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = 'ROTATED' WHERE refresh_token_id = %s",
            (row["refresh_token_id"],),
        )
    idle_expires = next_expiry(now, limits_for(row["role"], settings).idle, row["absolute_expires_at"])
    raw = _insert(
        conn,
        user_id=row["user_id"],
        family_id=row["family_id"],
        token_version=row["token_version"],
        mfa=row["mfa_verified"],
        idle_expires_at=idle_expires,
        absolute_expires_at=row["absolute_expires_at"],
    )
    return Rotation(
        refresh_token=raw,
        expires_in=int((idle_expires - now).total_seconds()),
        user_id=row["user_id"],
        role=row["role"],
        token_version=row["token_version"],
        mfa=row["mfa_verified"],
    )
