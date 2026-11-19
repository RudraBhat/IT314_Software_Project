"""Incident state machine and locking helpers.

Every status change goes through `transition`, which validates the move,
checks the optimistic-lock version, writes incident_status_history and the
audit log in the caller's transaction.
"""

from typing import Any

from psycopg import sql

from app import audit
from app.auth import Principal
from app.errors import ApiError, conflict, not_found

# Staff-driven transitions (SRS s.3 state transparency, s.7.8, s.12).
# CLOSED is reachable from any non-closed state through `close`, and left only through `reopen`.
TRANSITIONS: dict[str, set[str]] = {
    "SUBMITTED": {"VERIFIED", "REJECTED", "NEEDS_INFORMATION"},
    "NEEDS_INFORMATION": {"VERIFIED", "REJECTED", "NEEDS_INFORMATION"},
    "VERIFIED": {"DISPATCHED", "RESOLVED"},
    "DISPATCHED": {"RESOLVED"},
    "RESOLVED": set(),
    "REJECTED": set(),
    "CLOSED": set(),
}

# A reopened incident must land where work can continue. RESOLVED and REJECTED have no way forward, so
# restoring them as they were would strand the incident (nothing could be dispatched or verified again).
# Resolved work resumes as VERIFIED, where it can be dispatched or resolved again; a rejected report goes
# back to SUBMITTED for a fresh decision. Every other state is restored as it was.
_REOPEN_AS = {"RESOLVED": "VERIFIED", "REJECTED": "SUBMITTED"}


def reopen_target(previous: str | None, verified_priority) -> str:
    """The status a closed incident returns to, given the status it was closed from."""
    target = _REOPEN_AS.get(previous or "", previous) or "SUBMITTED"
    if target in ("VERIFIED", "DISPATCHED") and verified_priority is None:
        return "SUBMITTED"  # never resume as verified without the priority that verification requires
    return target


ACTIVE_DISPATCH = ("REQUESTED", "ACKNOWLEDGED", "DISPATCHED")
ACTIVE_ALLOCATION = ("ALLOCATED", "IN_TRANSIT")

# Columns a transition may set alongside the status; anything else is a programming error.
_SETTABLE = {
    "verified_priority",
    "priority_rationale",
    "verified_by",
    "verified_at",
    "closed_at",
    "scenario",
}


def lock_incident(conn, incident_id) -> dict:
    row = conn.execute(
        "SELECT * FROM incidents WHERE incident_id = %s FOR UPDATE", (incident_id,)
    ).fetchone()
    if row is None:
        raise not_found("Incident")
    return row


def check_version(row: dict, expected: int | None) -> None:
    if expected is not None and row["version"] != expected:
        raise conflict(
            "VERSION_CONFLICT",
            "This incident was changed by someone else. Reload and try again.",
            {"current_version": row["version"]},
        )


def ensure_open(row: dict) -> None:
    if row["status"] == "CLOSED":
        raise conflict("INCIDENT_CLOSED", "Closed incidents are read-only. Reopen it first.")


def update_incident(
    conn,
    principal: Principal,
    row: dict,
    *,
    action: str,
    rationale: str | None = None,
    to_status: str | None = None,
    allow_any_transition: bool = False,
    **fields: Any,
) -> dict:
    """Apply field changes (and optionally a status change) with one version bump."""
    unknown = set(fields) - _SETTABLE
    if unknown:
        raise ValueError(f"Not settable: {unknown}")
    from_status = row["status"]
    if (
        to_status is not None
        and not allow_any_transition
        and to_status not in TRANSITIONS.get(from_status, set())
    ):
        raise conflict(
            "INVALID_TRANSITION",
            f"An incident cannot move from {from_status} to {to_status}",
            {"from": from_status, "to": to_status},
        )

    sets = [sql.SQL("version = version + 1")]
    params: list[Any] = []
    if to_status is not None:
        sets.append(sql.SQL("status = %s"))
        params.append(to_status)
    for column, value in fields.items():
        sets.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
        params.append(value)
    query = sql.SQL(
        "UPDATE incidents SET {} WHERE incident_id = %s AND version = %s RETURNING *"
    ).format(sql.SQL(", ").join(sets))
    updated = conn.execute(query, [*params, row["incident_id"], row["version"]]).fetchone()
    if updated is None:  # defensive: the row is locked, so this means a stale read
        raise conflict("VERSION_CONFLICT", "This incident was changed by someone else.")

    # A repeated information request is still a new, recorded event.
    if to_status is not None and (to_status != from_status or to_status == "NEEDS_INFORMATION"):
        conn.execute(
            """
            INSERT INTO incident_status_history (incident_id, from_status, to_status, changed_by, reason)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (row["incident_id"], from_status, to_status, principal.user_id, rationale),
        )
    audit.record(
        conn,
        actor=principal,
        action=action,
        entity_type="incident",
        entity_id=row["incident_id"],
        rationale=rationale,
        before=_snapshot(row),
        after=_snapshot(updated),
        ip=principal.ip,
    )
    return updated


def _snapshot(row: dict) -> dict:
    return {
        "status": row["status"],
        "scenario": row["scenario"],
        "verified_priority": row["verified_priority"],
        "canonical_incident_id": row["canonical_incident_id"],
        "version": row["version"],
    }


def open_dependencies(conn, incident_id) -> dict:
    dispatches = conn.execute(
        """
        SELECT dispatch_id, dispatch_ref, status FROM dispatch_orders
        WHERE incident_id = %s AND status = ANY(%s::dispatch_status[])
        ORDER BY created_at
        """,
        (incident_id, list(ACTIVE_DISPATCH)),
    ).fetchall()
    allocations = conn.execute(
        """
        SELECT c.contribution_id, c.aid_type, c.quantity, c.unit, c.status
        FROM aid_contributions c JOIN aid_needs n ON n.need_id = c.need_id
        WHERE n.incident_id = %s AND c.status = ANY(%s::aid_status[])
        """,
        (incident_id, list(ACTIVE_ALLOCATION)),
    ).fetchall()
    return {"dispatches": dispatches, "allocations": allocations}


def require_status(row: dict, allowed: tuple[str, ...], message: str) -> None:
    if row["status"] not in allowed:
        raise ApiError(409, "INVALID_TRANSITION", message, {"status": row["status"]})
