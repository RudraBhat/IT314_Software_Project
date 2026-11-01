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


def verify_audit_chain(conn: Connection) -> tuple[bool, int, str]:
    """Verify cryptographic SHA-256 hash chaining over the immutable audit_logs table (AM-FR-05).

    Returns:
        (is_valid, verified_count, message)
    """
    count_row = conn.execute("SELECT COUNT(*) AS total FROM audit_logs").fetchone()
    total = count_row["total"] if count_row else 0
    if total == 0:
        return True, 0, "Audit log is empty; hash chain intact."

    query = """
    WITH verified AS (
        SELECT audit_id,
               prev_hash,
               LAG(row_hash, 1, repeat('0', 64)) OVER (ORDER BY audit_id) AS expected_prev,
               row_hash,
               encode(digest(
                   prev_hash ||
                   occurred_at::text ||
                   COALESCE(actor_id::text, 'SYSTEM') ||
                   action ||
                   entity_type ||
                   COALESCE(entity_id::text, '') ||
                   result::text ||
                   COALESCE(rationale, ''),
                   'sha256'), 'hex') AS computed_hash
        FROM audit_logs
    )
    SELECT audit_id, prev_hash, expected_prev, row_hash, computed_hash
    FROM verified
    WHERE prev_hash != expected_prev OR row_hash != computed_hash;
    """
    mismatches = conn.execute(query).fetchall()
    if mismatches:
        first = mismatches[0]
        return (
            False,
            len(mismatches),
            f"Tampering detected at audit_id {first['audit_id']}: hash mismatch or broken chain link.",
        )

    return True, total, f"Audit chain intact: {total} record(s) cryptographically verified."
