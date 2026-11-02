"""Shared state transitions and escalation for dispatch orders (DM-FR-09 / S2-01).

Used by dispatcher routes (routers/dm/dispatches.py) and field-team
routes (routers/field.py). Enforces row locking, audit chaining,
and state invariants.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from app import audit, db
from app.auth import Principal
from app.config import get_settings
from app.errors import ApiError, conflict, not_found
from app.services.incidents import lock_incident, update_incident
from app.services.resources import TERMINAL_DISPATCH, release_all_for_dispatch

logger = logging.getLogger("drch.dispatch")

# Arbitrary constant key so only one worker escalates at a time.
_ESCALATION_LOCK = 314_0013

# Valid transition map for dispatch lifecycle
DISPATCH_TRANSITIONS: dict[str, set[str]] = {
    "REQUESTED": {"ACKNOWLEDGED", "REJECTED"},
    "ACKNOWLEDGED": {"DISPATCHED", "FAILED"},
    "DISPATCHED": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "REJECTED": set(),
    "FAILED": set(),
}

DISPATCH_SELECT = """
SELECT d.dispatch_id, d.dispatch_ref, d.incident_id, i.incident_ref,
       lower(i.scenario::text) AS scenario, d.status, d.priority, d.instructions,
       d.receiving_agency_id, a.name AS agency_name, d.acknowledged_by, d.acknowledged_at,
       d.created_at, d.updated_at, u.full_name AS created_by_name,
       (d.status = 'REQUESTED' AND d.created_at < now() - make_interval(mins => %(timeout)s)) AS overdue,
       EXISTS (SELECT 1 FROM audit_logs l WHERE l.entity_type = 'dispatch_order'
               AND l.entity_id = d.dispatch_id AND l.action = 'DISPATCH_ESCALATED') AS escalated
FROM dispatch_orders d
JOIN incidents i ON i.incident_id = d.incident_id
JOIN users u ON u.user_id = d.created_by
LEFT JOIN agencies a ON a.agency_id = d.receiving_agency_id
"""


def get_dispatch_timeout() -> int:
    return get_settings().dispatch_ack_timeout_minutes


def fetch_dispatch(conn, dispatch_id: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        sql.SQL("{} WHERE d.dispatch_id = %(id)s").format(sql.SQL(DISPATCH_SELECT)),
        {"id": dispatch_id, "timeout": get_dispatch_timeout()},
    ).fetchone()
    if row is None:
        raise not_found("Dispatch")
    return row


def lock_dispatch(conn, dispatch_id: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM dispatch_orders WHERE dispatch_id = %s FOR UPDATE", (dispatch_id,)
    ).fetchone()
    if row is None:
        raise not_found("Dispatch")
    return row


def state_conflict(conn, principal: Principal, dispatch: dict[str, Any], attempted: str) -> ApiError:
    """EH-17: a late or contradictory report is kept in history and flagged, never applied."""
    audit.record(
        conn,
        actor=principal,
        action=f"DISPATCH_{attempted}_CONFLICT",
        entity_type="dispatch_order",
        entity_id=dispatch["dispatch_id"],
        result="FAILURE",
        rationale=f"{attempted} reported while dispatch is {dispatch['status']}",
        ip=principal.ip if principal else None,
    )
    code = "DISPATCH_NOT_ACKNOWLEDGED" if dispatch["status"] == "REQUESTED" else "DISPATCH_STATE_CONFLICT"
    return conflict(code, f"Cannot record {attempted.lower()} while the dispatch is {dispatch['status']}")


def set_dispatch_status(
    conn,
    principal: Principal,
    dispatch: dict[str, Any],
    status: str,
    action: str,
    rationale: str,
    after: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE dispatch_orders SET status = %s WHERE dispatch_id = %s",
        (status, dispatch["dispatch_id"]),
    )
    audit.record(
        conn,
        actor=principal,
        action=action,
        entity_type="dispatch_order",
        entity_id=dispatch["dispatch_id"],
        rationale=rationale,
        before={"status": dispatch["status"]},
        after={"status": status, **after},
        ip=principal.ip if principal else None,
    )


def apply_acknowledgement(
    conn,
    principal: Principal,
    dispatch: dict[str, Any],
    acknowledged_by: str,
    channel: str,
    note: str | None = None,
) -> None:
    """Transition a dispatch from REQUESTED to ACKNOWLEDGED."""
    if dispatch["status"] != "REQUESTED":
        raise state_conflict(conn, principal, dispatch, "ACKNOWLEDGEMENT")
    who = f"{acknowledged_by.strip()} (via {channel.lower().replace('_', ' ')})"
    conn.execute(
        "UPDATE dispatch_orders SET acknowledged_by = %s, acknowledged_at = %s WHERE dispatch_id = %s",
        (who, datetime.now(UTC), dispatch["dispatch_id"]),
    )
    set_dispatch_status(
        conn,
        principal,
        dispatch,
        "ACKNOWLEDGED",
        "DISPATCH_ACKNOWLEDGED",
        note or who,
        {"acknowledged_by": who, "channel": channel},
    )
    conn.execute(
        """
        UPDATE agency_messages SET status = 'ACKNOWLEDGED', acknowledged_at = now()
        WHERE dispatch_id = %s AND status IN ('QUEUED','SENT','DELIVERED')
        """,
        (dispatch["dispatch_id"],),
    )


def apply_rejection(
    conn,
    principal: Principal,
    dispatch: dict[str, Any],
    reason: str,
    reported_by: str,
    channel: str,
) -> None:
    """Transition a dispatch from REQUESTED or ACKNOWLEDGED to REJECTED and release resources."""
    if dispatch["status"] not in ("REQUESTED", "ACKNOWLEDGED"):
        raise state_conflict(conn, principal, dispatch, "REJECTION")
    set_dispatch_status(
        conn,
        principal,
        dispatch,
        "REJECTED",
        "DISPATCH_REJECTED",
        reason,
        {"reported_by": reported_by, "channel": channel},
    )
    release_all_for_dispatch(conn, principal, dispatch["dispatch_id"], f"Dispatch rejected: {reason}")


def apply_progress(
    conn,
    principal: Principal,
    dispatch: dict[str, Any],
    event: str,
    note: str | None = None,
    reported_by: str | None = None,
    channel: str | None = None,
) -> None:
    """Record progress on a dispatch, transitioning to DISPATCHED if EN_ROUTE."""
    if dispatch["status"] not in ("ACKNOWLEDGED", "DISPATCHED"):
        raise state_conflict(conn, principal, dispatch, event)
    rationale = note or event.replace("_", " ").lower()
    after = {"event": event, "reported_by": reported_by, "channel": channel}

    if event == "EN_ROUTE" and dispatch["status"] == "ACKNOWLEDGED":
        set_dispatch_status(
            conn, principal, dispatch, "DISPATCHED", "DISPATCH_EN_ROUTE", rationale, after
        )
        incident = lock_incident(conn, dispatch["incident_id"])
        if incident["status"] == "VERIFIED":
            update_incident(
                conn,
                principal,
                incident,
                action="INCIDENT_DISPATCHED",
                rationale=f"{dispatch['dispatch_ref']} en route",
                to_status="DISPATCHED",
            )
    else:
        audit.record(
            conn,
            actor=principal,
            action=f"DISPATCH_PROGRESS_{event}",
            entity_type="dispatch_order",
            entity_id=dispatch["dispatch_id"],
            rationale=rationale,
            after=after,
            ip=principal.ip if principal else None,
        )


def apply_completion(
    conn,
    principal: Principal,
    dispatch: dict[str, Any],
    confirmed_by: str,
    channel: str,
    note: str | None = None,
) -> None:
    """Transition a dispatch from DISPATCHED to COMPLETED and release resources."""
    if dispatch["status"] != "DISPATCHED":
        raise state_conflict(conn, principal, dispatch, "COMPLETION")
    set_dispatch_status(
        conn,
        principal,
        dispatch,
        "COMPLETED",
        "DISPATCH_COMPLETED",
        note or f"Confirmed by {confirmed_by}",
        {"confirmed_by": confirmed_by, "channel": channel},
    )
    release_all_for_dispatch(conn, principal, dispatch["dispatch_id"], "Dispatch completed")


def apply_failure(
    conn,
    principal: Principal,
    dispatch: dict[str, Any],
    reason: str,
) -> None:
    """Transition a dispatch to FAILED and release resources."""
    if dispatch["status"] in TERMINAL_DISPATCH:
        raise state_conflict(conn, principal, dispatch, "FAILURE")
    set_dispatch_status(conn, principal, dispatch, "FAILED", "DISPATCH_FAILED", reason, {})
    release_all_for_dispatch(conn, principal, dispatch["dispatch_id"], f"Dispatch failed: {reason}")


def run_dispatch_transition(dispatch_id: uuid.UUID, handler) -> dict[str, Any]:
    """Run a state transition event; a recorded conflict is committed even though request fails."""
    error: ApiError | None = None
    with db.transaction() as conn:
        dispatch = lock_dispatch(conn, dispatch_id)
        try:
            handler(conn, dispatch)
        except ApiError as exc:
            if exc.code not in ("DISPATCH_NOT_ACKNOWLEDGED", "DISPATCH_STATE_CONFLICT"):
                raise
            error = exc
    if error:
        raise error
    with db.transaction() as conn:
        return fetch_dispatch(conn, dispatch_id)


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
    result = conn.execute(
        """
        WITH inserted AS (
            INSERT INTO notifications (user_id, event_code, channel, title, body, related_id, status)
            SELECT p.user_id, 'DISPATCH_ESCALATED', 'IN_APP', %s, %s, %s, 'QUEUED'
            FROM staff_permissions p
            JOIN users u ON u.user_id = p.user_id
            JOIN roles r ON r.role_id = u.role_id
            WHERE p.permission = 'SUPERVISOR' AND u.status = 'ACTIVE' AND r.code = 'DISASTER_MGMT'
            RETURNING notification_id
        )
        SELECT count(*) AS count FROM inserted
        """,
        (f"Dispatch {dispatch['dispatch_ref']} escalated", reason, dispatch["dispatch_id"]),
    ).fetchone()
    return result["count"] if result else 0


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
