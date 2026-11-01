"""Append-only audit trail (audit_logs). Rows are hash-chained and immutable in the database."""

import ipaddress
import logging
import uuid
from typing import TYPE_CHECKING, Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from app import db

if TYPE_CHECKING:
    from app.auth import Principal

logger = logging.getLogger("drch.audit")


def _valid_ip(ip: str | None) -> str | None:
    """audit_logs.ip_address is INET; hostnames (e.g. behind some proxies) are not stored."""
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def record(
    conn: Connection,
    *,
    actor: "Principal | None",
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None = None,
    result: str = "SUCCESS",
    rationale: str | None = None,
    before: Any = None,
    after: Any = None,
    ip: str | None = None,
) -> None:
    """Write an audit row inside the caller's transaction, so it commits or rolls back with the action."""
    conn.execute(
        """
        INSERT INTO audit_logs
            (actor_id, actor_role, action, entity_type, entity_id, result,
             rationale, before_state, after_state, ip_address)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            actor.user_id if actor else None,
            actor.role if actor else None,
            action,
            entity_type,
            entity_id,
            result,
            rationale,
            Jsonb(before) if before is not None else None,
            Jsonb(after) if after is not None else None,
            _valid_ip(ip),
        ),
    )


def record_standalone(**kwargs: Any) -> None:
    """Audit an event in its own transaction, e.g. a denied request whose main work never runs (EH-11)."""
    try:
        with db.transaction() as conn:
            record(conn, **kwargs)
    except Exception:  # auditing a denial must never turn a 403 into a 500
        logger.exception("Failed to write standalone audit entry")
