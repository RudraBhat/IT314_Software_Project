"""Field-team responder API (docs/api_contracts.md section 3). Owner: Nisarg.

A field user only sees dispatches that reserved a resource (team) they belong to
(field_team_members -> resource_assignments -> dispatch_orders). Anything else is
404, so existence is not revealed. State changes reuse services/dispatch.py, which
also enforces the transition rules, row locks, audit chain and EH-17 conflict
recording. Field users never create dispatches and never close incidents.
"""

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import FieldUser
from app.common import notify
from app.errors import not_found
from app.services.dispatch import (
    apply_acknowledgement,
    apply_completion,
    apply_progress,
    apply_rejection,
    run_dispatch_transition,
)

router = APIRouter(prefix="/api/v1/field", tags=["field"])

CHANNEL = "INTEGRATION"  # recorded as "via integration": the field app is the reporting channel


class Rejection(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class Progress(BaseModel):
    status: Literal["EN_ROUTE", "ON_SCENE", "DELAYED"]
    note: str | None = Field(default=None, max_length=1000)


class TeamRequest(BaseModel):
    required_capability: str = Field(min_length=2, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


class Completion(BaseModel):
    summary: str = Field(min_length=3, max_length=2000)


def _require_member(conn, principal, dispatch_id: uuid.UUID) -> None:
    """404 unless this user belongs to a team assigned to the dispatch."""
    row = conn.execute(
        """
        SELECT 1
        FROM resource_assignments ra
        JOIN field_team_members m ON m.resource_id = ra.resource_id
        WHERE ra.dispatch_id = %s AND m.user_id = %s
        LIMIT 1
        """,
        (dispatch_id, principal.user_id),
    ).fetchone()
    if row is None:
        raise not_found("Dispatch")


def _result(conn, dispatch_id: uuid.UUID) -> dict:
    return conn.execute(
        "SELECT status::text AS status, updated_at FROM dispatch_orders WHERE dispatch_id = %s", (dispatch_id,)
    ).fetchone()


@router.get("/me")
def field_profile(principal: FieldUser):
    with db.transaction() as conn:
        teams = conn.execute(
            """
            SELECT r.resource_id, r.name AS team_name, m.callsign, m.is_leader, a.name AS agency
            FROM field_team_members m
            JOIN resources r ON r.resource_id = m.resource_id
            LEFT JOIN agencies a ON a.agency_id = r.agency_id
            WHERE m.user_id = %s ORDER BY r.name
            """,
            (principal.user_id,),
        ).fetchall()
    return {
        "user_id": principal.user_id,
        "full_name": principal.full_name,
        "email": principal.email,
        "role": principal.role,
        "teams": teams,
    }


@router.get("/assignments")
def my_assignments(principal: FieldUser):
    with db.transaction() as conn:
        return conn.execute(
            """
            SELECT DISTINCT d.dispatch_id, d.dispatch_ref, d.status::text AS status,
                   i.incident_ref, lower(i.scenario::text) AS scenario, d.priority::text AS priority,
                   i.address_text, i.landmark, i.latitude, i.longitude, d.instructions,
                   d.created_at AS dispatched_at
            FROM dispatch_orders d
            JOIN incidents i ON i.incident_id = d.incident_id
            JOIN resource_assignments ra ON ra.dispatch_id = d.dispatch_id AND ra.released_at IS NULL
            JOIN field_team_members m ON m.resource_id = ra.resource_id
            WHERE m.user_id = %s AND d.status IN ('REQUESTED', 'ACKNOWLEDGED', 'DISPATCHED')
            ORDER BY d.created_at DESC
            """,
            (principal.user_id,),
        ).fetchall()


@router.post("/dispatches/{dispatch_id}/acknowledgement")
def acknowledge(dispatch_id: uuid.UUID, principal: FieldUser):
    def handler(conn, dispatch):
        _require_member(conn, principal, dispatch_id)
        apply_acknowledgement(conn, principal, dispatch, principal.full_name, CHANNEL, "Acknowledged in field app")

    run_dispatch_transition(dispatch_id, handler)
    with db.transaction() as conn:
        return _result(conn, dispatch_id)


@router.post("/dispatches/{dispatch_id}/rejection")
def reject(dispatch_id: uuid.UUID, body: Rejection, principal: FieldUser):
    def handler(conn, dispatch):
        _require_member(conn, principal, dispatch_id)
        apply_rejection(conn, principal, dispatch, body.reason, principal.full_name, CHANNEL)

    run_dispatch_transition(dispatch_id, handler)
    with db.transaction() as conn:
        return _result(conn, dispatch_id)


@router.post("/dispatches/{dispatch_id}/progress")
def progress(dispatch_id: uuid.UUID, body: Progress, principal: FieldUser):
    event = "UPDATE" if body.status == "DELAYED" else body.status

    def handler(conn, dispatch):
        _require_member(conn, principal, dispatch_id)
        apply_progress(conn, principal, dispatch, event, body.note, principal.full_name, CHANNEL)
        conn.execute(
            "INSERT INTO dispatch_progress (dispatch_id, status, note, recorded_by) VALUES (%s, %s, %s, %s)",
            (dispatch_id, body.status, body.note, principal.user_id),
        )

    run_dispatch_transition(dispatch_id, handler)
    with db.transaction() as conn:
        return _result(conn, dispatch_id)


@router.post("/dispatches/{dispatch_id}/team-requests", status_code=201)
def request_backup(dispatch_id: uuid.UUID, body: TeamRequest, principal: FieldUser):
    """Ask DM staff for another team. Advisory: nothing is reserved or dispatched automatically."""
    with db.transaction() as conn:
        _require_member(conn, principal, dispatch_id)
        request = conn.execute(
            """
            INSERT INTO team_requests (dispatch_id, requested_by, required_capability, note)
            VALUES (%s, %s, %s, %s) RETURNING request_id, status, created_at
            """,
            (dispatch_id, principal.user_id, body.required_capability.strip(), body.note),
        ).fetchone()
        dispatch = conn.execute(
            "SELECT dispatch_ref FROM dispatch_orders WHERE dispatch_id = %s", (dispatch_id,)
        ).fetchone()
        audit.record(
            conn,
            actor=principal,
            action="TEAM_REQUESTED",
            entity_type="dispatch_order",
            entity_id=dispatch_id,
            rationale=f"{body.required_capability}: {body.note or ''}".strip(": "),
            ip=principal.ip,
        )
        for s in conn.execute(
            """
            SELECT p.user_id FROM staff_permissions p JOIN users u ON u.user_id = p.user_id
            WHERE p.permission = 'DISPATCH' AND u.status = 'ACTIVE'
            """
        ).fetchall():
            notify(
                conn,
                user_id=s["user_id"],
                event_code="TEAM_REQUESTED",
                title=f"Backup requested on {dispatch['dispatch_ref']}",
                body=f"{principal.full_name} needs: {body.required_capability}",
                related_id=dispatch_id,
            )
    return request


@router.post("/dispatches/{dispatch_id}/completion")
def complete(dispatch_id: uuid.UUID, body: Completion, principal: FieldUser):
    def handler(conn, dispatch):
        _require_member(conn, principal, dispatch_id)
        apply_completion(conn, principal, dispatch, principal.full_name, CHANNEL, body.summary)

    run_dispatch_transition(dispatch_id, handler)
    with db.transaction() as conn:
        return _result(conn, dispatch_id)
