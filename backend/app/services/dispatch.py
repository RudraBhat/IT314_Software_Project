"""Dispatch escalation (DM-NFR-13): an unacknowledged dispatch escalates to supervisors instead of waiting."""

import logging

from app import audit, db
from app.auth import Principal
from app.common import notify
from app.config import get_settings

logger = logging.getLogger("drch.dispatch")

# Arbitrary constant key so only one worker escalates at a time.
_ESCALATION_LOCK = 314_0013


def escalate(conn, principal: Principal | None, dispatch: dict, reason: str) -> int:
    """Record the escalation and notify every supervisor. Returns the number notified."""
    audit.record(
        conn,
        actor=principal,
        action="DISPATCH_ESCALATED",
        entity_type="dispatch_order",
        entity_id=dispatch["dispatch_id"],
        rationale=reason,
        after={"status": dispatch["status"]},
        ip=principal.ip if principal else None,
    )
    supervisors = conn.execute(
        """
        SELECT p.user_id FROM staff_permissions p
        JOIN users u ON u.user_id = p.user_id
        JOIN roles r ON r.role_id = u.role_id
        WHERE p.permission = 'SUPERVISOR' AND u.status = 'ACTIVE' AND r.code = 'DISASTER_MGMT'
        """
    ).fetchall()
    for s in supervisors:
        notify(
            conn,
            user_id=s["user_id"],
            event_code="DISPATCH_ESCALATED",
            title=f"Dispatch {dispatch['dispatch_ref']} escalated",
            body=reason,
            related_id=dispatch["dispatch_id"],
        )
    return len(supervisors)


def escalate_overdue() -> int:
    """Escalate REQUESTED dispatches past the acknowledgement timeout, once each."""
    timeout = get_settings().dispatch_ack_timeout_minutes
    with db.transaction() as conn:
        locked = conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS ok", (_ESCALATION_LOCK,)).fetchone()
        if not locked["ok"]:
            return 0
        overdue = conn.execute(
            """
            SELECT d.* FROM dispatch_orders d
            WHERE d.status = 'REQUESTED'
              AND d.created_at < now() - make_interval(mins => %s)
              AND NOT EXISTS (
                  SELECT 1 FROM audit_logs l
                  WHERE l.entity_type = 'dispatch_order' AND l.entity_id = d.dispatch_id
                    AND l.action = 'DISPATCH_ESCALATED')
            FOR UPDATE SKIP LOCKED
            """,
            (timeout,),
        ).fetchall()
        for dispatch in overdue:
            escalate(
                conn,
                None,
                dispatch,
                f"No acknowledgement within {timeout} minutes (automatic escalation)",
            )
    if overdue:
        logger.info("Escalated %d overdue dispatch(es)", len(overdue))
    return len(overdue)
