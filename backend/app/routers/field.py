"""Field Operations REST API for frontline disaster response teams.

Provides endpoints for field team profile retrieval, active mission assignments,
operational state transitions (acknowledgement, progress, rejection, completion),
and reinforcement backup team requests with strict cross-team isolation.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from psycopg import sql

from app import audit, db
from app.auth import FieldPrincipal, FieldUser
from app.common import notify
from app.config import get_settings
from app.errors import ApiError, not_found
from app.schemas.field import (
    FieldAcknowledgementResponse,
    FieldAssignmentResponse,
    FieldCompletionRequest,
    FieldProfileResponse,
    FieldProgressRequest,
    FieldProgressResponse,
    FieldRejectionRequest,
    FieldTeamRequest,
    FieldTeamRequestResponse,
)
from app.services.dispatch import (
    apply_acknowledgement,
    apply_completion,
    apply_progress,
    apply_rejection,
)

logger = logging.getLogger("drch.field")

router = APIRouter(prefix="/api/v1/field", tags=["field-operations"])

_ASSIGNMENT_SELECT = """
SELECT d.dispatch_id, d.dispatch_ref, d.status, d.priority,
       i.incident_id, i.incident_ref, lower(i.scenario::text) AS scenario,
       i.district, i.address_text, i.landmark,
       ST_Y(i.geom::geometry) AS latitude, ST_X(i.geom::geometry) AS longitude,
       d.instructions, d.created_at AS dispatched_at, d.acknowledged_at,
       (d.status = 'REQUESTED' AND d.created_at < now() - make_interval(mins => %(timeout)s)) AS overdue
FROM dispatch_orders d
JOIN incidents i ON i.incident_id = d.incident_id
"""


def _timeout() -> int:
    return get_settings().dispatch_ack_timeout_minutes


def _get_verified_team_dispatch(
    conn, principal: FieldPrincipal, dispatch_id: uuid.UUID
) -> dict[str, Any]:
    """Validate that the dispatch exists and is strictly assigned to the responder's team.

    Security rule: Requesting another team's dispatch ID returns 404 NOT_FOUND (never 403),
    preventing cross-team information disclosure and enumeration attacks.
    """
    row = conn.execute(
        """
        SELECT d.*
        FROM dispatch_orders d
        WHERE d.dispatch_id = %(dispatch_id)s
          AND EXISTS (
              SELECT 1 FROM resource_assignments ra
              WHERE ra.dispatch_id = d.dispatch_id
                AND ra.resource_id = %(team_id)s
                AND ra.released_at IS NULL
          )
        FOR UPDATE OF d
        """,
        {"dispatch_id": dispatch_id, "team_id": principal.team_resource_id},
    ).fetchone()
    if row is None:
        raise not_found("Dispatch")
    return dict(row)


def _run_field_event(
    dispatch_id: uuid.UUID, principal: FieldPrincipal, handler
) -> Any:
    """Execute a field lifecycle action within a transaction with conflict logging."""
    error: ApiError | None = None
    res = None
    with db.transaction() as conn:
        dispatch = _get_verified_team_dispatch(conn, principal, dispatch_id)
        try:
            res = handler(conn, dispatch)
        except ApiError as exc:
            if exc.code not in ("DISPATCH_NOT_ACKNOWLEDGED", "DISPATCH_STATE_CONFLICT"):
                raise
            error = exc
    if error:
        raise error
    return res


# ── Profile & Assignments ───────────────────────────────────────────────


@router.get("/me", response_model=FieldProfileResponse)
def get_field_profile(principal: FieldUser) -> FieldProfileResponse:
    """Return responder identity, team metadata, agency, and assigned capabilities."""
    if not get_settings().database_url:
        return FieldProfileResponse(
            user_id=principal.user_id,
            email=principal.email,
            full_name=principal.full_name,
            phone="+919876543210",
            role=principal.role,
            callsign=principal.callsign,
            is_leader=principal.is_leader,
            member_id=principal.member_id,
            team_resource_id=principal.team_resource_id,
            team_name=principal.team_name,
            agency_id=principal.agency_id,
            agency_name=principal.agency_name,
            capabilities=principal.capabilities,
            status="AVAILABLE",
        )

    with db.transaction() as conn:
        row = conn.execute(
            """
            SELECT u.user_id, u.email, u.full_name, u.phone, r.code AS role,
                   m.member_id, m.callsign, m.is_leader,
                   res.resource_id AS team_resource_id, res.name AS team_name, res.status, res.capability,
                   a.agency_id, a.name AS agency_name
            FROM users u
            JOIN roles r ON r.role_id = u.role_id
            JOIN field_team_members m ON m.user_id = u.user_id
            JOIN resources res ON res.resource_id = m.resource_id
            LEFT JOIN agencies a ON a.agency_id = res.agency_id
            WHERE u.user_id = %s
            """,
            (principal.user_id,),
        ).fetchone()

    if row is None:
        raise not_found("Field Profile")

    return FieldProfileResponse(
        user_id=row["user_id"],
        email=row["email"],
        full_name=row["full_name"],
        phone=row["phone"],
        role=row["role"],
        callsign=row["callsign"],
        is_leader=bool(row["is_leader"]),
        member_id=row["member_id"],
        team_resource_id=row["team_resource_id"],
        team_name=row["team_name"],
        agency_id=row["agency_id"],
        agency_name=row["agency_name"],
        capabilities=row["capability"] or {},
        status=row["status"],
    )


@router.get("/assignments", response_model=list[FieldAssignmentResponse])
def get_field_assignments(
    principal: FieldUser,
    active: Annotated[bool, Query(description="Filter active operational dispatches only")] = False,
) -> list[FieldAssignmentResponse]:
    """List operational dispatches assigned to the responder's team."""
    if not get_settings().database_url:
        return []

    active_condition = "AND ra.released_at IS NULL AND d.status IN ('REQUESTED', 'ACKNOWLEDGED', 'DISPATCHED')" if active else ""

    query_str = f"""
    {_ASSIGNMENT_SELECT}
    WHERE EXISTS (
        SELECT 1 FROM resource_assignments ra
        WHERE ra.dispatch_id = d.dispatch_id
          AND ra.resource_id = %(team_id)s
          {active_condition}
    )
    ORDER BY (d.status = 'REQUESTED') DESC, d.created_at DESC
    """
    params: dict[str, Any] = {
        "team_id": principal.team_resource_id,
        "timeout": _timeout(),
    }

    with db.transaction() as conn:
        rows = conn.execute(sql.SQL(query_str), params).fetchall()

    return [
        FieldAssignmentResponse(
            dispatch_id=r["dispatch_id"],
            dispatch_ref=r["dispatch_ref"],
            status=r["status"],
            priority=r["priority"],
            incident_id=r["incident_id"],
            incident_ref=r["incident_ref"],
            scenario=r["scenario"],
            district=r["district"],
            address_text=r["address_text"],
            landmark=r["landmark"],
            latitude=r["latitude"],
            longitude=r["longitude"],
            instructions=r["instructions"] or "",
            dispatched_at=r["dispatched_at"],
            acknowledged_at=r["acknowledged_at"],
            overdue=bool(r["overdue"]),
        )
        for r in rows
    ]


# ── Tactical Operations & State Transitions ─────────────────────────────


@router.post(
    "/dispatches/{dispatch_id}/acknowledgement",
    response_model=FieldAcknowledgementResponse,
)
def field_acknowledge_dispatch(
    dispatch_id: uuid.UUID,
    principal: FieldUser,
) -> FieldAcknowledgementResponse:
    """Field responder acknowledges receipt and deployment for an assignment."""
    def handler(conn, dispatch):
        note = f"Acknowledged by {principal.full_name}"
        if principal.callsign:
            note += f" [{principal.callsign}]"
        updated = apply_acknowledgement(
            conn,
            principal,
            dispatch_id,
            channel="MOBILE_APP",
            note=note,
            acknowledged_by=principal.full_name,
            dispatch=dispatch,
        )
        return FieldAcknowledgementResponse(
            status="ACKNOWLEDGED",
            dispatch_ref=updated["dispatch_ref"],
            acknowledged_at=datetime.now(UTC),
        )

    return _run_field_event(dispatch_id, principal, handler)


@router.post("/dispatches/{dispatch_id}/rejection")
def field_reject_dispatch(
    dispatch_id: uuid.UUID,
    body: FieldRejectionRequest,
    principal: FieldUser,
) -> dict[str, Any]:
    """Field responder refuses assignment with mandatory operational reason."""
    def handler(conn, dispatch):
        updated = apply_rejection(
            conn,
            principal,
            dispatch_id,
            reason=body.reason,
            reported_by=principal.full_name,
            channel="MOBILE_APP",
            dispatch=dispatch,
        )
        return {
            "status": "REJECTED",
            "dispatch_ref": updated["dispatch_ref"],
            "updated_at": datetime.now(UTC),
        }

    return _run_field_event(dispatch_id, principal, handler)


@router.post(
    "/dispatches/{dispatch_id}/progress",
    response_model=FieldProgressResponse,
)
def field_report_progress(
    dispatch_id: uuid.UUID,
    body: FieldProgressRequest,
    principal: FieldUser,
) -> FieldProgressResponse:
    """Field responder reports operational progress milestone (EN_ROUTE, ON_SCENE, UPDATE)."""
    def handler(conn, dispatch):
        updated = apply_progress(
            conn,
            principal,
            dispatch_id,
            event=body.status,
            note=body.note,
            reported_by=principal.full_name,
            channel="MOBILE_APP",
            latitude=body.latitude,
            longitude=body.longitude,
            dispatch=dispatch,
        )
        return FieldProgressResponse(
            progress_id=updated.get("progress_id") or uuid.uuid4(),
            dispatch_id=dispatch_id,
            status=body.status,
            note=body.note,
            recorded_at=datetime.now(UTC),
        )

    return _run_field_event(dispatch_id, principal, handler)


@router.post(
    "/dispatches/{dispatch_id}/team-requests",
    response_model=FieldTeamRequestResponse,
    status_code=201,
)
def field_request_team(
    dispatch_id: uuid.UUID,
    body: FieldTeamRequest,
    principal: FieldUser,
) -> FieldTeamRequestResponse:
    """Field responder requests specialized reinforcement or backup units."""
    with db.transaction() as conn:
        dispatch = _get_verified_team_dispatch(conn, principal, dispatch_id)

        row = conn.execute(
            """
            INSERT INTO team_requests (dispatch_id, requested_by, required_capability, note, status)
            VALUES (%s, %s, %s, %s, 'OPEN')
            RETURNING request_id, created_at
            """,
            (
                dispatch_id,
                principal.user_id,
                body.required_capability.strip(),
                body.note,
            ),
        ).fetchone()

        audit.record(
            conn,
            actor=principal,
            action="TEAM_BACKUP_REQUESTED",
            entity_type="dispatch_order",
            entity_id=dispatch_id,
            rationale=f"Requested {body.required_capability}: {body.note or 'No notes'}",
            after={
                "required_capability": body.required_capability,
                "team_name": principal.team_name,
            },
            ip=principal.ip,
        )

        # Notify active dispatchers of the backup request
        dispatchers = conn.execute(
            """
            SELECT p.user_id FROM staff_permissions p
            JOIN users u ON u.user_id = p.user_id
            WHERE p.permission = 'DISPATCH' AND u.status = 'ACTIVE'
            """
        ).fetchall()
        for d in dispatchers:
            notify(
                conn,
                user_id=d["user_id"],
                event_code="TEAM_BACKUP_REQUESTED",
                title=f"Backup requested for {dispatch['dispatch_ref']}",
                body=f"Team {principal.team_name} requests capability '{body.required_capability}'.",
                related_id=dispatch_id,
            )

        return FieldTeamRequestResponse(
            request_id=row["request_id"],
            dispatch_id=dispatch_id,
            required_capability=body.required_capability,
            note=body.note,
            status="OPEN",
            created_at=row["created_at"],
        )


@router.post("/dispatches/{dispatch_id}/completion")
def field_complete_dispatch(
    dispatch_id: uuid.UUID,
    body: FieldCompletionRequest,
    principal: FieldUser,
) -> dict[str, Any]:
    """Field responder submits final mission summary and completes the tactical assignment."""
    def handler(conn, dispatch):
        updated = apply_completion(
            conn,
            principal,
            dispatch_id,
            summary=body.summary,
            confirmed_by=principal.full_name,
            channel="MOBILE_APP",
            civilians_evacuated=body.civilians_evacuated,
            civilians_treated=body.civilians_treated,
            dispatch=dispatch,
        )
        return {
            "status": "COMPLETED",
            "dispatch_ref": updated["dispatch_ref"],
            "civilians_evacuated": body.civilians_evacuated,
            "civilians_treated": body.civilians_treated,
            "updated_at": datetime.now(UTC),
        }

    return _run_field_event(dispatch_id, principal, handler)
