"""Dispatch state machine, concurrency control, and automated escalation service.

Provides unified transaction-safe state transitions for both dispatcher console
and field responder operations. Guarantees row-level locking, resource allocation
safety, audit hash-chain integrity, and state conflict recording.
"""

import logging
import uuid
from typing import Any

from psycopg import sql

from app import audit, db
from app.auth import Principal
from app.common import notify
from app.config import get_settings
from app.errors import ApiError, conflict, not_found
from app.services import incidents, resources

TERMINAL_DISPATCH = resources.TERMINAL_DISPATCH

logger = logging.getLogger("drch.dispatch")

# Constant advisory lock key ensuring only one background escalation runs at a time.
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


def lock_dispatch(conn, dispatch_id: uuid.UUID, dispatch: dict | None = None) -> dict[str, Any]:
    """Acquire exclusive row lock on a dispatch order for state transition."""
    if dispatch is not None:
        return dispatch
    row = conn.execute(
        "SELECT * FROM dispatch_orders WHERE dispatch_id = %s FOR UPDATE", (dispatch_id,)
    ).fetchone()
    if row is None:
        raise not_found("Dispatch")
    return row


def state_conflict(conn, principal: Any | None, dispatch: dict[str, Any], attempted: str) -> ApiError:
    """EH-17: a late or contradictory report is kept in history and flagged, never applied."""
    actor_ip = getattr(principal, "ip", None) if principal else None
    audit.record(
        conn,
        actor=principal,
        action=f"DISPATCH_{attempted}_CONFLICT",
        entity_type="dispatch_order",
        entity_id=dispatch["dispatch_id"],
        result="FAILURE",
        rationale=f"{attempted} reported while dispatch is {dispatch['status']}",
        ip=actor_ip,
    )
    code = "DISPATCH_NOT_ACKNOWLEDGED" if dispatch["status"] == "REQUESTED" else "DISPATCH_STATE_CONFLICT"
    return conflict(code, f"Cannot record {attempted.lower()} while the dispatch is {dispatch['status']}")


# Alias for backward-compatibility with field module
record_dispatch_conflict = state_conflict


def set_dispatch_status(
    conn,
    principal: Any | None,
    dispatch: dict[str, Any],
    status: str,
    action: str,
    rationale: str,
    after: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE dispatch_orders SET status = %s, updated_at = now() WHERE dispatch_id = %s",
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
        ip=getattr(principal, "ip", None) if principal else None,
    )


def record_dispatch_progress(
    conn,
    dispatch_id: uuid.UUID,
    status: str,
    note: str | None,
    recorded_by: Any | None = None,
) -> uuid.UUID | None:
    """Record an operational progress update in the dispatch_progress ledger."""
    user_uuid = None
    if isinstance(recorded_by, uuid.UUID):
        user_uuid = recorded_by
    elif isinstance(recorded_by, str):
        try:
            user_uuid = uuid.UUID(recorded_by)
        except ValueError:
            user_uuid = None
    elif hasattr(recorded_by, "user_id"):
        uid = recorded_by.user_id
        if isinstance(uid, uuid.UUID):
            user_uuid = uid
        elif isinstance(uid, str):
            try:
                user_uuid = uuid.UUID(uid)
            except ValueError:
                user_uuid = None

    try:
        row = conn.execute(
            """
            INSERT INTO dispatch_progress (dispatch_id, status, note, recorded_by)
            VALUES (%s, %s, %s, %s)
            RETURNING progress_id
            """,
            (dispatch_id, status, note, user_uuid),
        ).fetchone()
        return row["progress_id"] if row else None
    except Exception:
        logger.exception("Failed to insert record into dispatch_progress table")
        return None


def apply_acknowledgement(
    conn,
    principal: Any | None,
    target: uuid.UUID | dict[str, Any],
    acknowledged_by: str | None = None,
    channel: str = "OTHER",
    note: str | None = None,
    *,
    dispatch: dict[str, Any] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Transition a dispatch from REQUESTED to ACKNOWLEDGED."""
    if isinstance(target, dict):
        d = target
        dispatch_id = d["dispatch_id"]
    else:
        dispatch_id = target
        d = lock_dispatch(conn, dispatch_id, dispatch=dispatch)

    if d["status"] == "ACKNOWLEDGED":
        logger.info("Dispatch %s already acknowledged; returning idempotent response", d.get("dispatch_ref"))
        return d

    if d["status"] != "REQUESTED":
        raise state_conflict(conn, principal, d, "ACKNOWLEDGEMENT")

    who_raw = acknowledged_by or kwargs.get("acknowledged_by") or (
        getattr(principal, "full_name", None) or str(getattr(principal, "user_id", "Unknown Responder"))
    )
    who = f"{str(who_raw).strip()} (via {channel.lower().replace('_', ' ')})"

    conn.execute(
        "UPDATE dispatch_orders SET acknowledged_by = %s, acknowledged_at = now(), updated_at = now() WHERE dispatch_id = %s",
        (who, dispatch_id),
    )
    set_dispatch_status(
        conn,
        principal,
        d,
        "ACKNOWLEDGED",
        "DISPATCH_ACKNOWLEDGED",
        note or who,
        {"acknowledged_by": who, "channel": channel},
    )
    conn.execute(
        """
        UPDATE agency_messages
        SET status = 'ACKNOWLEDGED', acknowledged_at = now()
        WHERE dispatch_id = %s AND status IN ('QUEUED', 'SENT', 'DELIVERED')
        """,
        (dispatch_id,),
    )
    record_dispatch_progress(conn, dispatch_id, "ACKNOWLEDGED", note or who, principal)
    d["status"] = "ACKNOWLEDGED"
    d["acknowledged_by"] = who
    return d


def apply_rejection(
    conn,
    principal: Any | None,
    target: uuid.UUID | dict[str, Any],
    reason: str | None = None,
    reported_by: str | None = None,
    channel: str = "OTHER",
    *,
    dispatch: dict[str, Any] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Transition a dispatch to REJECTED and release resources."""
    if isinstance(target, dict):
        d = target
        dispatch_id = d["dispatch_id"]
    else:
        dispatch_id = target
        d = lock_dispatch(conn, dispatch_id, dispatch=dispatch)

    if d["status"] in TERMINAL_DISPATCH:
        raise state_conflict(conn, principal, d, "REJECTION")

    reason_val = reason or kwargs.get("reason", "No reason provided")
    reported_val = reported_by or kwargs.get("reported_by") or (
        getattr(principal, "full_name", None) or str(getattr(principal, "user_id", "Unknown"))
    )

    set_dispatch_status(
        conn,
        principal,
        d,
        "REJECTED",
        "DISPATCH_REJECTED",
        reason_val,
        {"reported_by": reported_val, "channel": channel},
    )
    resources.release_all_for_dispatch(conn, principal, dispatch_id, f"Dispatch rejected: {reason_val}")
    record_dispatch_progress(conn, dispatch_id, "REJECTED", reason_val, principal)
    d["status"] = "REJECTED"
    return d


def apply_progress(
    conn,
    principal: Any | None,
    target: uuid.UUID | dict[str, Any],
    event: str | None = None,
    note: str | None = None,
    reported_by: str | None = None,
    channel: str = "OTHER",
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    dispatch: dict[str, Any] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Record an operational progress event; EN_ROUTE transitions status to DISPATCHED."""
    if isinstance(target, dict):
        d = target
        dispatch_id = d["dispatch_id"]
    else:
        dispatch_id = target
        d = lock_dispatch(conn, dispatch_id, dispatch=dispatch)

    event_val = (event or kwargs.get("event", "UPDATE")).upper()
    reason_val = note or kwargs.get("note", f"Progress: {event_val}")
    reported_val = reported_by or kwargs.get("reported_by") or (
        getattr(principal, "full_name", None) or str(getattr(principal, "user_id", "Unknown"))
    )

    if d["status"] not in ("ACKNOWLEDGED", "DISPATCHED"):
        raise state_conflict(conn, principal, d, event_val)

    after: dict[str, Any] = {
        "event": event_val,
        "channel": channel,
        "reported_by": reported_val,
        "note": note,
    }
    if latitude is not None and longitude is not None:
        after["latitude"] = latitude
        after["longitude"] = longitude

    progress_id = record_dispatch_progress(conn, dispatch_id, event_val, reason_val, principal)
    if progress_id:
        d["progress_id"] = progress_id

    if event_val == "EN_ROUTE" and d["status"] == "ACKNOWLEDGED":
        set_dispatch_status(
            conn,
            principal,
            d,
            "DISPATCHED",
            "DISPATCH_EN_ROUTE",
            reason_val,
            after,
        )
        d["status"] = "DISPATCHED"
        incident = incidents.lock_incident(conn, d["incident_id"])
        if incident["status"] == "VERIFIED":
            incidents.update_incident(
                conn,
                principal,
                incident,
                action="INCIDENT_DISPATCHED",
                rationale=f"{d['dispatch_ref']} en route",
                to_status="DISPATCHED",
            )
    else:
        audit.record(
            conn,
            actor=principal,
            action=f"DISPATCH_PROGRESS_{event_val}",
            entity_type="dispatch_order",
            entity_id=dispatch_id,
            rationale=reason_val,
            after=after,
            ip=getattr(principal, "ip", None) if principal else None,
        )

    return d


def apply_completion(
    conn,
    principal: Any | None,
    target: uuid.UUID | dict[str, Any],
    confirmed_by: str | None = None,
    channel: str = "OTHER",
    note: str | None = None,
    *,
    summary: str | None = None,
    civilians_evacuated: int | None = None,
    civilians_treated: int | None = None,
    dispatch: dict[str, Any] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Transition a dispatch from DISPATCHED to COMPLETED and release resources."""
    if isinstance(target, dict):
        d = target
        dispatch_id = d["dispatch_id"]
    else:
        dispatch_id = target
        d = lock_dispatch(conn, dispatch_id, dispatch=dispatch)

    if d["status"] != "DISPATCHED":
        raise state_conflict(conn, principal, d, "COMPLETION")

    who = confirmed_by or kwargs.get("confirmed_by") or (
        getattr(principal, "full_name", None) or str(getattr(principal, "user_id", "Unknown"))
    )
    summary_text = summary or note or kwargs.get("summary") or f"Confirmed by {who}"

    after: dict[str, Any] = {
        "confirmed_by": who,
        "channel": channel,
        "summary": summary_text,
    }
    if civilians_evacuated is not None:
        after["civilians_evacuated"] = civilians_evacuated
    if civilians_treated is not None:
        after["civilians_treated"] = civilians_treated

    set_dispatch_status(
        conn,
        principal,
        d,
        "COMPLETED",
        "DISPATCH_COMPLETED",
        summary_text,
        after,
    )
    resources.release_all_for_dispatch(conn, principal, dispatch_id, "Dispatch completed")
    record_dispatch_progress(conn, dispatch_id, "COMPLETED", summary_text, principal)

    audit.record(
        conn,
        actor=principal,
        action="DISPATCH_COMPLETED",
        entity_type="incident",
        entity_id=d["incident_id"],
        rationale=f"{d['dispatch_ref']} completed mission; incident remains open for dispatcher resolution",
        ip=getattr(principal, "ip", None) if principal else None,
    )

    d["status"] = "COMPLETED"
    return d


def apply_failure(
    conn,
    principal: Any | None,
    target: uuid.UUID | dict[str, Any],
    reason: str | None = None,
    *,
    dispatch: dict[str, Any] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Transition a dispatch to FAILED and release resources."""
    if isinstance(target, dict):
        d = target
        dispatch_id = d["dispatch_id"]
    else:
        dispatch_id = target
        d = lock_dispatch(conn, dispatch_id, dispatch=dispatch)

    if d["status"] in TERMINAL_DISPATCH:
        raise state_conflict(conn, principal, d, "FAILURE")

    reason_val = reason or kwargs.get("reason", "Dispatch failed")

    set_dispatch_status(conn, principal, d, "FAILED", "DISPATCH_FAILED", reason_val, {})
    resources.release_all_for_dispatch(conn, principal, dispatch_id, f"Dispatch failed: {reason_val}")
    record_dispatch_progress(conn, dispatch_id, "FAILED", reason_val, principal)

    d["status"] = "FAILED"
    return d


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
    """Record dispatch escalation and notify every active supervisor."""
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
