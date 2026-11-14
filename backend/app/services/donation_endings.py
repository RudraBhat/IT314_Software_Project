"""Server-side endings for donations that never complete (S3-11). Owner: Shlok.

A donation stays PENDING until a verified payment confirms it. It ends as FAILED when:

* the donor cancels the unpaid order (``ABANDONED``, ``POST /donations/{id}/cancel``);
* the gateway reports that the payment failed (``GATEWAY_DECLINED``, webhook ``payment.failed``);
* nobody pays within ``PENDING_TTL`` (``EXPIRED``). Expiry is applied lazily, whenever donations
  are created, read or acted on, so no background worker is needed.

FAILED is not final for money: a later verified payment of the right amount and currency still
confirms the donation (a gateway can capture after the donor closed the window, or after a failed
first attempt on the same order). A captured payment is therefore never left unrecorded, and
nothing is ever CONFIRMED without a verified signature.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from app import audit

PENDING_TTL = timedelta(minutes=30)
FAILURE_REASONS = ("ABANDONED", "GATEWAY_DECLINED", "EXPIRED")


def ttl_minutes() -> int:
    return int(PENDING_TTL.total_seconds() // 60)


def expire_stale_donations(conn, *, donation_id: uuid.UUID | None = None) -> int:
    """Mark PENDING donations older than PENDING_TTL as FAILED / EXPIRED, with an audit row each.

    With ``donation_id`` only that donation is considered (used before acting on one row).
    Returns how many donations expired.
    """
    rows = conn.execute(
        """
        UPDATE donations
        SET status = 'FAILED', failure_reason = 'EXPIRED', failed_at = now()
        WHERE status = 'PENDING'
          AND created_at < now() - %(ttl)s
          AND (%(id)s::uuid IS NULL OR donation_id = %(id)s::uuid)
        RETURNING donation_id
        """,
        {"ttl": PENDING_TTL, "id": donation_id},
    ).fetchall()
    for row in rows:
        audit.record(
            conn, actor=None, action="DONATION_EXPIRED", entity_type="donation", entity_id=row["donation_id"],
            result="FAILURE", rationale=f"No verified payment within {ttl_minutes()} minutes",
            after={"status": "FAILED", "failure_reason": "EXPIRED"},
        )
    return len(rows)


def mark_failed(conn, row: dict, reason: str, *, actor, rationale: str, ip: str | None = None) -> dict:
    """PENDING -> FAILED with a reason, in the caller's transaction (the row is already locked)."""
    if reason not in FAILURE_REASONS:
        raise ValueError(f"unknown failure reason {reason!r}")
    updated = conn.execute(
        """
        UPDATE donations
        SET status = 'FAILED', failure_reason = %s, failed_at = now()
        WHERE donation_id = %s AND status = 'PENDING'
        RETURNING *
        """,
        (reason, row["donation_id"]),
    ).fetchone()
    if updated is None:  # not PENDING any more: nothing to change
        return row
    audit.record(
        conn, actor=actor, action="DONATION_FAILED", entity_type="donation", entity_id=row["donation_id"],
        result="FAILURE", rationale=rationale, after={"status": "FAILED", "failure_reason": reason}, ip=ip,
    )
    return updated
