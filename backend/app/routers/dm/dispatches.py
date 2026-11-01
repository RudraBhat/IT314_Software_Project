"""Emergency dispatch (DM-FR-09) and inter-agency messages (DM-FR-10).

Agencies have no accounts. Staff record what an agency reported (or a trusted
integration does); every state change stores who recorded it. A state only
advances on a recorded event - nothing is inferred (s.7.5).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg import sql
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import Dispatcher, DMUser, Principal, Supervisor
from app.common import Filters, Page, Priority, Rationale, page_body
from app.config import get_settings
from app.errors import ApiError, conflict, not_found
from app.services.dispatch import escalate
from app.services.incidents import ensure_open, lock_incident, update_incident
from app.services.resources import TERMINAL_DISPATCH, release_all_for_dispatch, reserve

router = APIRouter()

_DISPATCH_SELECT = """
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


def _timeout() -> int:
    return get_settings().dispatch_ack_timeout_minutes


def _fetch(conn, dispatch_id) -> dict:
    row = conn.execute(
        sql.SQL("{} WHERE d.dispatch_id = %(id)s").format(sql.SQL(_DISPATCH_SELECT)),
        {"id": dispatch_id, "timeout": _timeout()},
    ).fetchone()
    if row is None:
        raise not_found("Dispatch")
    return row


def _lock(conn, dispatch_id) -> dict:
    row = conn.execute(
        "SELECT * FROM dispatch_orders WHERE dispatch_id = %s FOR UPDATE", (dispatch_id,)
    ).fetchone()
    if row is None:
        raise not_found("Dispatch")
    return row


# -------------------------------------------------------------------- creation


class ResourceLine(BaseModel):
    resource_id: uuid.UUID
    quantity: Decimal = Field(Decimal(1), gt=0, max_digits=12, decimal_places=2)


class DispatchCreate(BaseModel):
    receiving_agency_id: uuid.UUID
    instructions: str = Field(min_length=5, max_length=4000)
    priority: Priority | None = None
    resources: list[ResourceLine] = Field(min_length=1, max_length=20)


@router.post("/incidents/{incident_id}/dispatches", status_code=201)
def create_dispatch(
    *,
    incident_id: uuid.UUID,
    body: DispatchCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
    principal: Dispatcher,
):
    ids = [line.resource_id for line in body.resources]
    if len(set(ids)) != len(ids):
        raise ApiError(422, "VALIDATION_FAILED", "Each resource may appear only once")
    with db.transaction() as conn:
        if idempotency_key:
            existing = conn.execute(
                """
                SELECT dispatch_id, incident_id, receiving_agency_id, instructions, priority
                FROM dispatch_orders
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                # Idempotency must be scoped to the same incident.
                if existing["incident_id"] != incident_id:
                    raise conflict(
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key already used for a dispatch on a different incident",
                        {"incident_id": str(existing["incident_id"])},
                    )
                # Verify that request semantics match the original dispatch order.
                if existing["receiving_agency_id"] != body.receiving_agency_id:
                    raise conflict(
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key reused with different receiving agency",
                    )
                # A retry with the same key for the same incident returns the original order.
                return JSONResponse(status_code=200, content=jsonable_encoder(_fetch(conn, existing["dispatch_id"])))
        incident = lock_incident(conn, incident_id)
        ensure_open(incident)
        if incident["status"] not in ("VERIFIED", "DISPATCHED"):
            raise conflict(
                "INCIDENT_NOT_VERIFIED",
                "Only verified incidents can be dispatched (s.7.5)",
                {"status": incident["status"]},
            )
        if incident["verified_priority"] is None:
            raise conflict("PRIORITY_REQUIRED", "Assign a priority before dispatching")
        agency = conn.execute(
            "SELECT agency_id, name, is_active FROM agencies WHERE agency_id = %s", (body.receiving_agency_id,)
        ).fetchone()
        if agency is None or not agency["is_active"]:
            raise ApiError(422, "UNKNOWN_AGENCY", "The receiving agency does not exist or is inactive")

        ref = conn.execute(
            "SELECT 'DISP-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('dispatch_ref_seq')::text, 6, '0') AS ref"
        ).fetchone()["ref"]
        dispatch = conn.execute(
            """
            INSERT INTO dispatch_orders
                (dispatch_ref, incident_id, created_by, receiving_agency_id, status, instructions,
                 priority, idempotency_key)
            VALUES (%s, %s, %s, %s, 'REQUESTED', %s, %s, %s)
            RETURNING *
            """,
            (
                ref,
                incident_id,
                principal.user_id,
                agency["agency_id"],
                body.instructions.strip(),
                body.priority or incident["verified_priority"],
                idempotency_key,
            ),
        ).fetchone()
        # Lock resources in a stable order so concurrent dispatches cannot deadlock.
        for line in sorted(body.resources, key=lambda r: str(r.resource_id)):
            reserve(conn, principal, resource_id=line.resource_id, dispatch=dispatch, quantity=line.quantity)

        # Transmission: no messaging integration is configured, so the order is queued and
        # staff relay it; the message stays QUEUED until an integration reports delivery.
        conn.execute(
            """
            INSERT INTO agency_messages (sender_id, recipient_agency_id, incident_id, dispatch_id, subject, body)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                principal.user_id,
                agency["agency_id"],
                incident_id,
                dispatch["dispatch_id"],
                f"Dispatch order {ref} ({incident['incident_ref']})",
                body.instructions.strip(),
            ),
        )
        audit.record(
            conn,
            actor=principal,
            action="DISPATCH_CREATED",
            entity_type="dispatch_order",
            entity_id=dispatch["dispatch_id"],
            after={
                "dispatch_ref": ref,
                "incident_id": str(incident_id),
                "agency": agency["name"],
                "resources": [line.model_dump(mode="json") for line in body.resources],
            },
            ip=principal.ip,
        )
        audit.record(
            conn,
            actor=principal,
            action="DISPATCH_CREATED",
            entity_type="incident",
            entity_id=incident_id,
            rationale=f"{ref} requested from {agency['name']}",
            ip=principal.ip,
        )
        return _fetch(conn, dispatch["dispatch_id"])


# ------------------------------------------------------------- queue and detail


@router.get("/dispatches")
def list_dispatches(
    *,
    page: Page,
    status: Annotated[list[Literal["REQUESTED", "ACKNOWLEDGED", "DISPATCHED", "REJECTED", "FAILED", "COMPLETED"]] | None, Query()] = None,
    overdue: bool = False,
    active: bool = False,
    incident_id: uuid.UUID | None = None,
    principal: DMUser,
):
    f = Filters()
    f.params["timeout"] = _timeout()
    if status:
        f.add("d.status = ANY(%(status)s::dispatch_status[])", status=status)
    if active:
        f.add("d.status IN ('REQUESTED','ACKNOWLEDGED','DISPATCHED')")
    if overdue:
        f.add("d.status = 'REQUESTED' AND d.created_at < now() - make_interval(mins => %(timeout)s)")
    if incident_id:
        f.add("d.incident_id = %(incident)s", incident=incident_id)
    where = f.where()
    with db.transaction() as conn:
        total = conn.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM dispatch_orders d {}").format(where), f.params
        ).fetchone()["n"]
        items = conn.execute(
            sql.SQL(
                "{} {} ORDER BY (d.status = 'REQUESTED') DESC, d.priority, d.created_at DESC "
                "LIMIT %(limit)s OFFSET %(offset)s"
            ).format(sql.SQL(_DISPATCH_SELECT), where),
            {**f.params, "limit": page.limit, "offset": page.offset},
        ).fetchall()
    return {**page_body(items, total, page), "ack_timeout_minutes": _timeout()}


@router.get("/dispatches/{dispatch_id}")
def get_dispatch(dispatch_id: uuid.UUID, principal: DMUser):
    with db.transaction() as conn:
        dispatch = _fetch(conn, dispatch_id)
        dispatch["assignments"] = conn.execute(
            """
            SELECT x.assignment_id, x.resource_id, r.name AS resource_name, r.type, x.quantity,
                   x.assigned_at, x.released_at
            FROM resource_assignments x JOIN resources r ON r.resource_id = x.resource_id
            WHERE x.dispatch_id = %s ORDER BY x.assigned_at
            """,
            (dispatch_id,),
        ).fetchall()
        dispatch["events"] = conn.execute(
            """
            SELECT l.audit_id, l.occurred_at, l.action, l.result, l.rationale, l.after_state,
                   COALESCE(u.full_name, 'System') AS recorded_by
            FROM audit_logs l LEFT JOIN users u ON u.user_id = l.actor_id
            WHERE l.entity_type = 'dispatch_order' AND l.entity_id = %s
            ORDER BY l.audit_id
            """,
            (dispatch_id,),
        ).fetchall()
        dispatch["messages"] = conn.execute(
            """
            SELECT m.message_id, m.subject, m.status, m.created_at, m.acknowledged_at, a.name AS agency_name
            FROM agency_messages m JOIN agencies a ON a.agency_id = m.recipient_agency_id
            WHERE m.dispatch_id = %s ORDER BY m.created_at
            """,
            (dispatch_id,),
        ).fetchall()
    return dispatch


# --------------------------------------------------------------- state events

Channel = Literal["PHONE", "RADIO", "EMAIL", "IN_PERSON", "INTEGRATION", "OTHER"]


class Acknowledgement(BaseModel):
    acknowledged_by: str = Field(min_length=2, max_length=150, description="Who at the agency confirmed")
    channel: Channel
    note: str | None = Field(None, max_length=1000)


class Rejection(BaseModel):
    reason: str = Rationale
    reported_by: str = Field(min_length=2, max_length=150)
    channel: Channel


class Progress(BaseModel):
    event: Literal["EN_ROUTE", "ON_SCENE", "UPDATE"]
    note: str | None = Field(None, max_length=1000)
    reported_by: str = Field(min_length=2, max_length=150)
    channel: Channel


class Completion(BaseModel):
    confirmed_by: str = Field(min_length=2, max_length=150)
    channel: Channel
    note: str | None = Field(None, max_length=1000)


class Failure(BaseModel):
    reason: str = Rationale


class Escalation(BaseModel):
    reason: str = Rationale


def _state_conflict(conn, principal: Principal, dispatch: dict, attempted: str) -> ApiError:
    """EH-17: a late or contradictory report is kept in history and flagged, never applied."""
    audit.record(
        conn,
        actor=principal,
        action=f"DISPATCH_{attempted}_CONFLICT",
        entity_type="dispatch_order",
        entity_id=dispatch["dispatch_id"],
        result="FAILURE",
        rationale=f"{attempted} reported while dispatch is {dispatch['status']}",
        ip=principal.ip,
    )
    code = "DISPATCH_NOT_ACKNOWLEDGED" if dispatch["status"] == "REQUESTED" else "DISPATCH_STATE_CONFLICT"
    return conflict(code, f"Cannot record {attempted.lower()} while the dispatch is {dispatch['status']}")


def _set_status(conn, principal: Principal, dispatch: dict, status: str, action: str, rationale: str, after: dict):
    conn.execute(
        "UPDATE dispatch_orders SET status = %s WHERE dispatch_id = %s", (status, dispatch["dispatch_id"])
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
        ip=principal.ip,
    )


def _run(dispatch_id: uuid.UUID, handler) -> dict:
    """Run a state event; a recorded conflict is committed even though the request fails."""
    error: ApiError | None = None
    with db.transaction() as conn:
        dispatch = _lock(conn, dispatch_id)
        try:
            handler(conn, dispatch)
        except ApiError as exc:
            if exc.code not in ("DISPATCH_NOT_ACKNOWLEDGED", "DISPATCH_STATE_CONFLICT"):
                raise
            error = exc
    if error:
        raise error
    with db.transaction() as conn:
        return _fetch(conn, dispatch_id)


@router.post("/dispatches/{dispatch_id}/acknowledgement")
def record_acknowledgement(
    dispatch_id: uuid.UUID, body: Acknowledgement, principal: Dispatcher
):
    def handler(conn, dispatch):
        if dispatch["status"] != "REQUESTED":
            raise _state_conflict(conn, principal, dispatch, "ACKNOWLEDGEMENT")
        who = f"{body.acknowledged_by.strip()} (via {body.channel.lower().replace('_', ' ')})"
        conn.execute(
            "UPDATE dispatch_orders SET acknowledged_by = %s, acknowledged_at = %s WHERE dispatch_id = %s",
            (who, datetime.now(UTC), dispatch_id),
        )
        _set_status(conn, principal, dispatch, "ACKNOWLEDGED", "DISPATCH_ACKNOWLEDGED", body.note or who,
                    {"acknowledged_by": who, "channel": body.channel})
        conn.execute(
            """
            UPDATE agency_messages SET status = 'ACKNOWLEDGED', acknowledged_at = now()
            WHERE dispatch_id = %s AND status IN ('QUEUED','SENT','DELIVERED')
            """,
            (dispatch_id,),
        )

    return _run(dispatch_id, handler)


@router.post("/dispatches/{dispatch_id}/rejection")
def record_rejection(
    dispatch_id: uuid.UUID, body: Rejection, principal: Dispatcher
):
    def handler(conn, dispatch):
        if dispatch["status"] not in ("REQUESTED", "ACKNOWLEDGED"):
            raise _state_conflict(conn, principal, dispatch, "REJECTION")
        _set_status(conn, principal, dispatch, "REJECTED", "DISPATCH_REJECTED", body.reason,
                    {"reported_by": body.reported_by, "channel": body.channel})
        release_all_for_dispatch(conn, principal, dispatch_id, f"Dispatch rejected: {body.reason}")

    return _run(dispatch_id, handler)


@router.post("/dispatches/{dispatch_id}/progress")
def record_progress(
    dispatch_id: uuid.UUID, body: Progress, principal: Dispatcher
):
    def handler(conn, dispatch):
        if dispatch["status"] not in ("ACKNOWLEDGED", "DISPATCHED"):
            raise _state_conflict(conn, principal, dispatch, body.event)
        rationale = body.note or body.event.replace("_", " ").lower()
        after = {"event": body.event, "reported_by": body.reported_by, "channel": body.channel}
        if body.event == "EN_ROUTE" and dispatch["status"] == "ACKNOWLEDGED":
            _set_status(conn, principal, dispatch, "DISPATCHED", "DISPATCH_EN_ROUTE", rationale, after)
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
                action=f"DISPATCH_PROGRESS_{body.event}",
                entity_type="dispatch_order",
                entity_id=dispatch_id,
                rationale=rationale,
                after=after,
                ip=principal.ip,
            )

    return _run(dispatch_id, handler)


@router.post("/dispatches/{dispatch_id}/completion")
def record_completion(
    dispatch_id: uuid.UUID, body: Completion, principal: Dispatcher
):
    def handler(conn, dispatch):
        if dispatch["status"] != "DISPATCHED":
            raise _state_conflict(conn, principal, dispatch, "COMPLETION")
        _set_status(conn, principal, dispatch, "COMPLETED", "DISPATCH_COMPLETED",
                    body.note or f"Confirmed by {body.confirmed_by}",
                    {"confirmed_by": body.confirmed_by, "channel": body.channel})
        release_all_for_dispatch(conn, principal, dispatch_id, "Dispatch completed")

    return _run(dispatch_id, handler)


@router.post("/dispatches/{dispatch_id}/failure")
def record_failure(
    dispatch_id: uuid.UUID, body: Failure, principal: Dispatcher
):
    def handler(conn, dispatch):
        if dispatch["status"] in TERMINAL_DISPATCH:
            raise _state_conflict(conn, principal, dispatch, "FAILURE")
        _set_status(conn, principal, dispatch, "FAILED", "DISPATCH_FAILED", body.reason, {})
        release_all_for_dispatch(conn, principal, dispatch_id, f"Dispatch failed: {body.reason}")

    return _run(dispatch_id, handler)


@router.post("/dispatches/{dispatch_id}/escalation")
def escalate_dispatch(
    dispatch_id: uuid.UUID, body: Escalation, principal: Supervisor
):
    with db.transaction() as conn:
        dispatch = _lock(conn, dispatch_id)
        if dispatch["status"] != "REQUESTED":
            raise conflict("DISPATCH_STATE_CONFLICT", "Only unacknowledged dispatches can be escalated")
        escalate(conn, principal, dispatch, body.reason)
        return _fetch(conn, dispatch_id)


# --------------------------------------------------------------- agency messages


class MessageCreate(BaseModel):
    recipient_agency_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=4000)
    dispatch_id: uuid.UUID | None = None


_MESSAGE_SELECT = """
SELECT m.message_id, m.incident_id, m.dispatch_id, m.subject, m.body, m.status, m.created_at,
       m.updated_at, m.acknowledged_at, a.name AS agency_name, a.contact_email, a.contact_phone,
       u.full_name AS sender_name,
       (SELECT jsonb_build_object('recorded_by', COALESCE(ru.full_name, 'System'), 'at', l.occurred_at,
                                  'action', l.action, 'note', l.rationale)
          FROM audit_logs l LEFT JOIN users ru ON ru.user_id = l.actor_id
         WHERE l.entity_type = 'agency_message' AND l.entity_id = m.message_id
           AND l.action IN ('MESSAGE_ACKNOWLEDGED', 'MESSAGE_FAILED')
         ORDER BY l.audit_id DESC LIMIT 1) AS last_recorded_event
FROM agency_messages m
JOIN agencies a ON a.agency_id = m.recipient_agency_id
JOIN users u ON u.user_id = m.sender_id
"""


@router.post("/incidents/{incident_id}/agency-messages", status_code=201)
def send_agency_message(incident_id: uuid.UUID, body: MessageCreate, principal: DMUser):
    with db.transaction() as conn:
        incident = lock_incident(conn, incident_id)
        ensure_open(incident)
        if body.dispatch_id and conn.execute(
            "SELECT 1 FROM dispatch_orders WHERE dispatch_id = %s AND incident_id = %s",
            (body.dispatch_id, incident_id),
        ).fetchone() is None:
            raise ApiError(422, "VALIDATION_FAILED", "The dispatch does not belong to this incident")
        agencies = conn.execute(
            "SELECT agency_id FROM agencies WHERE agency_id = ANY(%s) AND is_active", (body.recipient_agency_ids,)
        ).fetchall()
        if len(agencies) != len(set(body.recipient_agency_ids)):
            raise ApiError(422, "UNKNOWN_AGENCY", "One or more recipients are unknown or inactive")
        ids = []
        for agency in agencies:
            row = conn.execute(
                """
                INSERT INTO agency_messages (sender_id, recipient_agency_id, incident_id, dispatch_id, subject, body)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING message_id
                """,
                (principal.user_id, agency["agency_id"], incident_id, body.dispatch_id, body.subject.strip(),
                 body.body.strip()),
            ).fetchone()
            ids.append(row["message_id"])
            audit.record(
                conn,
                actor=principal,
                action="MESSAGE_QUEUED",
                entity_type="agency_message",
                entity_id=row["message_id"],
                rationale=body.subject,
                ip=principal.ip,
            )
        items = conn.execute(
            sql.SQL("{} WHERE m.message_id = ANY(%s) ORDER BY a.name").format(sql.SQL(_MESSAGE_SELECT)), (ids,)
        ).fetchall()
    return {
        "items": items,
        "delivery_note": "Queued. No messaging integration is configured; relay the message and record the "
        "agency's response.",
    }


@router.get("/agency-messages")
def list_agency_messages(
    *,
    page: Page,
    incident_id: uuid.UUID | None = None,
    status: Literal["QUEUED", "SENT", "DELIVERED", "ACKNOWLEDGED", "FAILED"] | None = None,
    principal: DMUser,
):
    f = Filters()
    if incident_id:
        f.add("m.incident_id = %(incident)s", incident=incident_id)
    if status:
        f.add("m.status = %(status)s::msg_status", status=status)
    where = f.where()
    with db.transaction() as conn:
        total = conn.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM agency_messages m {}").format(where), f.params
        ).fetchone()["n"]
        items = conn.execute(
            sql.SQL("{} {} ORDER BY m.created_at DESC LIMIT %(limit)s OFFSET %(offset)s").format(
                sql.SQL(_MESSAGE_SELECT), where
            ),
            {**f.params, "limit": page.limit, "offset": page.offset},
        ).fetchall()
    return page_body(items, total, page)


@router.get("/agency-messages/{message_id}")
def get_agency_message(message_id: uuid.UUID, principal: DMUser):
    with db.transaction() as conn:
        row = conn.execute(
            sql.SQL("{} WHERE m.message_id = %s").format(sql.SQL(_MESSAGE_SELECT)), (message_id,)
        ).fetchone()
    if row is None:
        raise not_found("Message")
    return row


class MessageEvent(BaseModel):
    outcome: Literal["ACKNOWLEDGED", "FAILED"]
    note: str = Field(min_length=3, max_length=1000, description="Who confirmed, or why delivery failed")


@router.post("/agency-messages/{message_id}/events")
def record_message_event(message_id: uuid.UUID, body: MessageEvent, principal: DMUser):
    with db.transaction() as conn:
        msg = conn.execute(
            "SELECT * FROM agency_messages WHERE message_id = %s FOR UPDATE", (message_id,)
        ).fetchone()
        if msg is None:
            raise not_found("Message")
        if msg["status"] in ("ACKNOWLEDGED", "FAILED"):
            raise conflict("MESSAGE_STATE_CONFLICT", f"The message is already {msg['status'].lower()}")
        conn.execute(
            """
            UPDATE agency_messages
            SET status = %s, acknowledged_at = CASE WHEN %s = 'ACKNOWLEDGED' THEN now() END
            WHERE message_id = %s
            """,
            (body.outcome, body.outcome, message_id),
        )
        audit.record(
            conn,
            actor=principal,
            action=f"MESSAGE_{body.outcome}",
            entity_type="agency_message",
            entity_id=message_id,
            rationale=body.note,
            before={"status": msg["status"]},
            after={"status": body.outcome},
            ip=principal.ip,
        )
        row = conn.execute(
            sql.SQL("{} WHERE m.message_id = %s").format(sql.SQL(_MESSAGE_SELECT)), (message_id,)
        ).fetchone()
    return row
