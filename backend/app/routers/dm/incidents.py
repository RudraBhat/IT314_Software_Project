"""Incident queue, detail, verification, priority, duplicates and closure (DM-FR-02..04, 06, 15)."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from psycopg import sql
from pydantic import BaseModel, Field, model_validator

from app import audit, db
from app.auth import Closer, DMUser, Principal
from app.common import (
    Filters,
    IncidentStatus,
    Page,
    Priority,
    Rationale,
    Scenario,
    Version,
    notify,
    page_body,
    scenario_db,
)
from app.errors import ApiError, conflict, not_found
from app.services.duplicate_similarity import METHOD as SIMILARITY_METHOD
from app.services.duplicate_similarity import WEIGHTS as SIMILARITY_WEIGHTS
from app.services.duplicate_similarity import score_candidates
from app.services.incidents import (
    check_version,
    ensure_open,
    lock_incident,
    open_dependencies,
    reopen_target,
    require_status,
    update_incident,
)

router = APIRouter()

DUPLICATE_RADIUS_M = 1000
DUPLICATE_WINDOW_HOURS = 6

# A citizen's "please withdraw my report" is stored as a status-history row (see routers/citizen.py).
# It only matters while the report can still be withdrawn; after dispatch or closure it is stale.
_WITHDRAWAL_PENDING = """(i.status IN ('SUBMITTED','NEEDS_INFORMATION','VERIFIED') AND EXISTS (
        SELECT 1 FROM incident_status_history w
        WHERE w.incident_id = i.incident_id AND w.reason LIKE 'Reporter asked to withdraw%%'))"""

_LIST_COLUMNS = """
    i.incident_id, i.incident_ref, lower(i.scenario::text) AS scenario, i.status,
    i.verified_priority, i.reported_urgency, i.people_affected, i.address_text, i.landmark,
    i.latitude, i.longitude, i.location_source, i.canonical_incident_id,
    i.submitted_at, i.updated_at, i.closed_at, i.version,
    (SELECT COUNT(*) FROM evidence_files e WHERE e.incident_id = i.incident_id) AS evidence_count,
    (SELECT COUNT(*) FROM dispatch_orders d WHERE d.incident_id = i.incident_id
        AND d.status IN ('REQUESTED','ACKNOWLEDGED','DISPATCHED')) AS active_dispatches,
    """ + _WITHDRAWAL_PENDING + """ AS withdrawal_requested
"""

_SORTS = {
    "newest": "i.submitted_at DESC",
    "oldest": "i.submitted_at ASC",
    "priority": "i.verified_priority ASC NULLS LAST, i.submitted_at DESC",
    "updated": "i.updated_at DESC",
}


def incident_filters(
    *,
    scenario: Scenario | None = None,
    status: list[IncidentStatus] | None = None,
    priority: list[Priority | Literal["UNASSIGNED"]] | None = None,
    from_: date | None = None,
    to: date | None = None,
    q: str | None = None,
    withdrawal_requested: bool | None = None,
    near_lat: float | None = None,
    near_lon: float | None = None,
    radius_km: float = 10,
) -> Filters:
    f = Filters()
    if scenario:
        f.add("i.scenario = %(scenario)s::scenario_type", scenario=scenario_db(scenario))
    if status:
        f.add("i.status = ANY(%(status)s::incident_status[])", status=status)
    if priority:
        named = [p for p in priority if p != "UNASSIGNED"]
        if "UNASSIGNED" in priority:
            f.add(
                "(i.verified_priority IS NULL OR i.verified_priority = ANY(%(prio)s::priority_level[]))",
                prio=named,
            )
        else:
            f.add("i.verified_priority = ANY(%(prio)s::priority_level[])", prio=named)
    if from_:
        f.add("i.submitted_at >= %(from_)s::date", from_=from_)
    if to:
        f.add("i.submitted_at < (%(to)s::date + 1)", to=to)
    if q:
        f.add(
            "(i.incident_ref ILIKE %(q)s OR i.address_text ILIKE %(q)s OR i.landmark ILIKE %(q)s)",
            q=f"%{q.strip()}%",
        )
    if withdrawal_requested:
        f.add(_WITHDRAWAL_PENDING)
    if near_lat is not None and near_lon is not None:
        f.add(
            "ST_DWithin(i.geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius)s)",
            lat=near_lat,
            lon=near_lon,
            radius=radius_km * 1000,
        )
    elif (near_lat is None) != (near_lon is None):
        raise ApiError(422, "VALIDATION_FAILED", "near_lat and near_lon must be given together")
    return f


@router.get("/incidents")
def list_incidents(
    *,
    page: Page,
    scenario: Scenario | None = None,
    status: Annotated[list[IncidentStatus] | None, Query()] = None,
    priority: Annotated[list[Priority | Literal["UNASSIGNED"]] | None, Query()] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    withdrawal_requested: Annotated[
        bool | None,
        Query(description="true: only reports whose reporter asked to withdraw them"),
    ] = None,
    near_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    near_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[float, Query(gt=0, le=500)] = 10,
    sort: Literal["newest", "oldest", "priority", "updated"] = "newest",
    principal: DMUser,
):
    f = incident_filters(
        scenario=scenario,
        status=status,
        priority=priority,
        from_=from_,
        to=to,
        q=q,
        withdrawal_requested=withdrawal_requested,
        near_lat=near_lat,
        near_lon=near_lon,
        radius_km=radius_km,
    )
    where = f.where()
    with db.read_only() as conn:
        total = conn.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM incidents i {}").format(where), f.params
        ).fetchone()["n"]
        items = conn.execute(
            sql.SQL("SELECT {} FROM incidents i {} ORDER BY {} LIMIT %(limit)s OFFSET %(offset)s").format(
                sql.SQL(_LIST_COLUMNS), where, sql.SQL(_SORTS[sort])
            ),
            {**f.params, "limit": page.limit, "offset": page.offset},
        ).fetchall()
    return page_body(items, total, page)


def _actions(row: dict, principal: Principal) -> dict:
    """What the UI may offer. The server re-checks every one of these on submit."""
    s = row["status"]
    open_ = s != "CLOSED"
    return {
        "verify": s in ("SUBMITTED", "NEEDS_INFORMATION"),
        "request_information": s in ("SUBMITTED", "NEEDS_INFORMATION"),
        "set_priority": s not in ("CLOSED", "REJECTED"),
        "dispatch": s in ("VERIFIED", "DISPATCHED") and principal.has("DISPATCH"),
        "resolve": s in ("VERIFIED", "DISPATCHED"),
        "close": open_ and principal.has("CLOSURE"),
        "reopen": s == "CLOSED" and principal.has("CLOSURE"),
        "ai_triage": open_,
        "message_agencies": open_,
    }


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: uuid.UUID, principal: DMUser):
    with db.read_only() as conn:
        incident = conn.execute(
            sql.SQL(
                """
            SELECT i.incident_id, i.incident_ref, lower(i.scenario::text) AS scenario, i.description,
                   i.reported_urgency, i.people_affected, i.status, i.verified_priority,
                   i.priority_rationale, i.verified_at, v.full_name AS verified_by_name,
                   i.canonical_incident_id, c.incident_ref AS canonical_incident_ref,
                   i.location_source, i.latitude, i.longitude, i.accuracy_m, i.address_text,
                   i.landmark, i.details, i.version, i.submitted_at, i.updated_at, i.closed_at,
                   {pending} AS withdrawal_requested,
                   jsonb_build_object('user_id', r.user_id, 'full_name', r.full_name,
                                      'email', r.email, 'phone', r.phone) AS reporter
            FROM incidents i
            JOIN users r ON r.user_id = i.reporter_id
            LEFT JOIN users v ON v.user_id = i.verified_by
            LEFT JOIN incidents c ON c.incident_id = i.canonical_incident_id
            WHERE i.incident_id = %s
            """
            ).format(pending=sql.SQL(_WITHDRAWAL_PENDING)),
            (incident_id,),
        ).fetchone()
        if incident is None:
            raise not_found("Incident")
        evidence = conn.execute(
            """
            SELECT evidence_id, file_name, mime_type, size_bytes, sha256, scan_state, uploaded_at
            FROM evidence_files WHERE incident_id = %s ORDER BY uploaded_at
            """,
            (incident_id,),
        ).fetchall()
        history = conn.execute(
            """
            SELECT h.history_id, h.from_status, h.to_status, h.reason, h.changed_at,
                   u.full_name AS changed_by_name
            FROM incident_status_history h LEFT JOIN users u ON u.user_id = h.changed_by
            WHERE h.incident_id = %s ORDER BY h.changed_at, h.history_id
            """,
            (incident_id,),
        ).fetchall()
        dispatches = conn.execute(
            """
            SELECT d.dispatch_id, d.dispatch_ref, d.status, d.priority, d.created_at,
                   d.acknowledged_at, d.acknowledged_by, a.name AS agency_name
            FROM dispatch_orders d LEFT JOIN agencies a ON a.agency_id = d.receiving_agency_id
            WHERE d.incident_id = %s ORDER BY d.created_at DESC
            """,
            (incident_id,),
        ).fetchall()
        messages = conn.execute(
            """
            SELECT m.message_id, m.subject, m.body, m.status, m.created_at, m.acknowledged_at,
                   m.dispatch_id, a.name AS agency_name, u.full_name AS sender_name
            FROM agency_messages m
            JOIN agencies a ON a.agency_id = m.recipient_agency_id
            JOIN users u ON u.user_id = m.sender_id
            WHERE m.incident_id = %s ORDER BY m.created_at DESC
            """,
            (incident_id,),
        ).fetchall()
        linked = conn.execute(
            """
            SELECT incident_id, incident_ref, status, lower(scenario::text) AS scenario, submitted_at
            FROM incidents WHERE canonical_incident_id = %s ORDER BY submitted_at
            """,
            (incident_id,),
        ).fetchall()
        audit_trail = conn.execute(
            """
            SELECT l.audit_id, l.occurred_at, l.action, l.result, l.rationale,
                   COALESCE(u.full_name, 'System') AS actor_name
            FROM audit_logs l LEFT JOIN users u ON u.user_id = l.actor_id
            WHERE l.entity_type = 'incident' AND l.entity_id = %s
            ORDER BY l.audit_id DESC LIMIT 100
            """,
            (incident_id,),
        ).fetchall()
        dependencies = open_dependencies(conn, incident_id)

    incident.update(
        evidence=evidence,
        history=history,
        dispatches=dispatches,
        agency_messages=messages,
        linked_duplicates=linked,
        audit_trail=audit_trail,
        open_dependencies=dependencies,
        allowed_actions=_actions(incident, principal),
    )
    return incident


# ---------------------------------------------------------------- verification


class VerificationRequest(Version):
    decision: Literal["VERIFIED", "REJECTED", "NEEDS_INFORMATION"]
    rationale: str = Rationale
    priority: Priority | None = None

    @model_validator(mode="after")
    def _priority_only_when_verifying(self):
        if self.priority and self.decision != "VERIFIED":
            raise ValueError("priority may only be set together with a VERIFIED decision")
        return self


_REPORTER_MESSAGES = {
    "VERIFIED": ("INCIDENT_VERIFIED", "Your report has been verified"),
    "REJECTED": ("INCIDENT_REJECTED", "Your report could not be verified"),
    "NEEDS_INFORMATION": ("INCIDENT_INFORMATION_REQUESTED", "More information is needed for your report"),
}


@router.get("/incidents/{incident_id}/evidence/{evidence_id}/content")
def incident_evidence_content(incident_id: uuid.UUID, evidence_id: uuid.UUID, principal: DMUser):
    """Return an approved photo on this incident for triage (#180).

    Only photos a moderator has approved are served here; pending, quarantined and removed ones are a
    404 (moderators review those through the moderation queue). Each view is audited.
    """
    with db.transaction() as conn:
        row = conn.execute(
            """
            SELECT e.mime_type, b.content
            FROM evidence_files e JOIN evidence_blobs b ON b.evidence_id = e.evidence_id
            WHERE e.evidence_id = %s AND e.incident_id = %s AND e.scan_state = 'CLEAN'
            """,
            (evidence_id, incident_id),
        ).fetchone()
        if row is None:
            raise not_found("Evidence")
        audit.record(
            conn,
            actor=principal,
            action="EVIDENCE_VIEWED",
            entity_type="evidence",
            entity_id=evidence_id,
            after={"incident_id": str(incident_id)},
            ip=principal.ip,
        )
    return Response(
        content=bytes(row["content"]),
        media_type=row["mime_type"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
        },
    )


@router.post("/incidents/{incident_id}/verification")
def record_verification(
    incident_id: uuid.UUID, body: VerificationRequest, principal: DMUser
):
    with db.transaction() as conn:
        row = lock_incident(conn, incident_id)
        check_version(row, body.version)
        ensure_open(row)
        require_status(
            row,
            ("SUBMITTED", "NEEDS_INFORMATION"),
            "Only submitted incidents, or incidents awaiting information, can be verified or rejected",
        )
        fields = {}
        if body.decision == "VERIFIED":
            priority = body.priority or row["verified_priority"]
            if priority is None:
                raise ApiError(
                    422,
                    "PRIORITY_REQUIRED",
                    "Assign a priority with rationale before, or while, verifying an incident",
                )
            fields = {
                "verified_priority": priority,
                "verified_by": principal.user_id,
                "verified_at": datetime.now(UTC),
            }
            if body.priority:
                fields["priority_rationale"] = body.rationale
        updated = update_incident(
            conn,
            principal,
            row,
            action=f"INCIDENT_{body.decision}",
            rationale=body.rationale,
            to_status=body.decision,
            **fields,
        )
        event, title = _REPORTER_MESSAGES[body.decision]
        notify(
            conn,
            user_id=row["reporter_id"],
            event_code=event,
            title=f"{title} ({row['incident_ref']})",
            body=body.rationale if body.decision != "VERIFIED" else "Your incident report has been verified by the response team.",
            related_id=incident_id,
        )
    return {"incident_id": incident_id, "status": updated["status"], "version": updated["version"]}


class InformationRequest(Version):
    question: str = Field(min_length=5, max_length=2000)


@router.post("/incidents/{incident_id}/information-requests", status_code=201)
def request_information(
    incident_id: uuid.UUID, body: InformationRequest, principal: DMUser
):
    with db.transaction() as conn:
        row = lock_incident(conn, incident_id)
        check_version(row, body.version)
        ensure_open(row)
        updated = update_incident(
            conn,
            principal,
            row,
            action="INFORMATION_REQUESTED",
            rationale=body.question,
            to_status="NEEDS_INFORMATION",
        )
        notify(
            conn,
            user_id=row["reporter_id"],
            event_code="INCIDENT_INFORMATION_REQUESTED",
            title=f"More information needed ({row['incident_ref']})",
            body=body.question,
            related_id=incident_id,
        )
    return {"incident_id": incident_id, "status": updated["status"], "version": updated["version"]}


# -------------------------------------------------------------------- priority


class PriorityRequest(Version):
    priority: Priority
    rationale: str = Rationale


@router.put("/incidents/{incident_id}/priority")
def set_priority(incident_id: uuid.UUID, body: PriorityRequest, principal: DMUser):
    with db.transaction() as conn:
        row = lock_incident(conn, incident_id)
        check_version(row, body.version)
        ensure_open(row)
        if row["status"] == "REJECTED":
            raise conflict("INVALID_TRANSITION", "A rejected incident cannot be prioritised")
        updated = update_incident(
            conn,
            principal,
            row,
            action="PRIORITY_SET",
            rationale=body.rationale,
            verified_priority=body.priority,
            priority_rationale=body.rationale,
        )
    return {
        "incident_id": incident_id,
        "verified_priority": updated["verified_priority"],
        "version": updated["version"],
    }


# ---------------------------------------------------- resolution, closure, reopen


class ResolutionRequest(Version):
    rationale: str = Rationale


@router.post("/incidents/{incident_id}/resolution")
def resolve_incident(
    incident_id: uuid.UUID, body: ResolutionRequest, principal: DMUser
):
    with db.transaction() as conn:
        row = lock_incident(conn, incident_id)
        check_version(row, body.version)
        ensure_open(row)
        deps = open_dependencies(conn, incident_id)
        if deps["dispatches"]:
            raise conflict(
                "OPEN_DEPENDENCIES",
                "Complete, reject or fail the active dispatches before resolving",
                deps,
            )
        updated = update_incident(
            conn, principal, row, action="INCIDENT_RESOLVED", rationale=body.rationale, to_status="RESOLVED"
        )
    return {"incident_id": incident_id, "status": updated["status"], "version": updated["version"]}


class ClosureRequest(Version):
    reason: str = Rationale
    public_summary: str | None = Field(None, max_length=2000)
    override: bool = False
    override_rationale: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _override_needs_rationale(self):
        if self.override and not (self.override_rationale and len(self.override_rationale.strip()) >= 3):
            raise ValueError("override_rationale is required when overriding open dependencies")
        return self


@router.post("/incidents/{incident_id}/closure")
def close_incident(
    incident_id: uuid.UUID,
    body: ClosureRequest,
    principal: Closer,
):
    with db.transaction() as conn:
        row = lock_incident(conn, incident_id)
        check_version(row, body.version)
        ensure_open(row)
        deps = open_dependencies(conn, incident_id)
        has_open = bool(deps["dispatches"] or deps["allocations"])
        if has_open and not body.override:
            raise conflict(
                "OPEN_DEPENDENCIES",
                "This incident has open dispatches or aid allocations. Resolve them or close with an override.",
                deps,
            )
        rationale = body.reason
        if has_open:
            rationale += f" [Override: {body.override_rationale}]"
        updated = update_incident(
            conn,
            principal,
            row,
            action="INCIDENT_CLOSED",
            rationale=rationale,
            to_status="CLOSED",
            allow_any_transition=True,
            closed_at=datetime.now(UTC),
        )
        notify(
            conn,
            user_id=row["reporter_id"],
            event_code="INCIDENT_CLOSED",
            title=f"Your report has been closed ({row['incident_ref']})",
            body=body.public_summary or body.reason,
            related_id=incident_id,
        )
    return {"incident_id": incident_id, "status": updated["status"], "version": updated["version"]}


class ReopenRequest(Version):
    reason: str = Rationale


@router.post("/incidents/{incident_id}/reopen")
def reopen_incident(
    incident_id: uuid.UUID,
    body: ReopenRequest,
    principal: Closer,
):
    with db.transaction() as conn:
        row = lock_incident(conn, incident_id)
        check_version(row, body.version)
        if row["status"] != "CLOSED":
            raise conflict("INVALID_TRANSITION", "Only closed incidents can be reopened")
        previous = conn.execute(
            """
            SELECT from_status FROM incident_status_history
            WHERE incident_id = %s AND to_status = 'CLOSED'
            ORDER BY changed_at DESC, history_id DESC LIMIT 1
            """,
            (incident_id,),
        ).fetchone()
        target = reopen_target(previous["from_status"] if previous else None, row["verified_priority"])
        updated = update_incident(
            conn,
            principal,
            row,
            action="INCIDENT_REOPENED",
            rationale=body.reason,
            to_status=target,
            allow_any_transition=True,
            closed_at=None,
        )
    return {"incident_id": incident_id, "status": updated["status"], "version": updated["version"]}


# ------------------------------------------------------------------ duplicates


@router.get("/incidents/{incident_id}/duplicates")
def duplicate_candidates(incident_id: uuid.UUID, principal: DMUser):
    with db.read_only() as conn:
        base = conn.execute(
            "SELECT incident_id, canonical_incident_id, description FROM incidents WHERE incident_id = %s",
            (incident_id,),
        ).fetchone()
        if base is None:
            raise not_found("Incident")
        candidates = conn.execute(
            """
            WITH me AS (SELECT * FROM incidents WHERE incident_id = %(id)s),
            dismissed AS (
                SELECT (after_state->>'candidate_id')::uuid AS other FROM audit_logs
                WHERE action = 'DUPLICATE_DISMISSED' AND entity_type = 'incident' AND entity_id = %(id)s
                UNION
                SELECT entity_id FROM audit_logs
                WHERE action = 'DUPLICATE_DISMISSED' AND entity_type = 'incident'
                  AND after_state->>'candidate_id' = %(id)s::text
            )
            SELECT o.incident_id, o.incident_ref, o.status, lower(o.scenario::text) AS scenario,
                   o.address_text, o.submitted_at, o.people_affected, o.canonical_incident_id,
                   left(o.description, 280) AS description_excerpt, o.description,
                   CASE WHEN o.geom IS NOT NULL AND me.geom IS NOT NULL
                        THEN round(ST_Distance(o.geom, me.geom)::numeric) END AS distance_m,
                   round(abs(EXTRACT(EPOCH FROM (o.submitted_at - me.submitted_at))) / 60) AS minutes_apart,
                   (o.address_text IS NOT NULL AND lower(o.address_text) = lower(me.address_text)) AS same_address
            FROM incidents o, me
            WHERE o.incident_id <> me.incident_id
              AND o.scenario = me.scenario
              AND o.status <> 'CLOSED'
              AND o.canonical_incident_id IS DISTINCT FROM me.incident_id
              AND me.canonical_incident_id IS DISTINCT FROM o.incident_id
              AND abs(EXTRACT(EPOCH FROM (o.submitted_at - me.submitted_at))) <= %(window)s * 3600
              AND (
                    (o.geom IS NOT NULL AND me.geom IS NOT NULL AND ST_DWithin(o.geom, me.geom, %(radius)s))
                 OR (o.address_text IS NOT NULL AND lower(o.address_text) = lower(me.address_text))
              )
              AND o.incident_id NOT IN (SELECT other FROM dismissed WHERE other IS NOT NULL)
            ORDER BY distance_m NULLS LAST, minutes_apart
            LIMIT 20
            """,
            {"id": incident_id, "window": DUPLICATE_WINDOW_HOURS, "radius": DUPLICATE_RADIUS_M},
        ).fetchall()

    scored = score_candidates(
        base["description"], [dict(c) for c in candidates],
        radius_m=DUPLICATE_RADIUS_M, window_hours=DUPLICATE_WINDOW_HOURS,
    )
    for c in scored:
        reasons = ["same scenario", f"reported {c['minutes_apart']} min apart"]
        if c["distance_m"] is not None:
            reasons.append(f"{c['distance_m']} m apart")
        if c["same_address"]:
            reasons.append("same address")
        reasons.append(f"wording similarity {c['text_similarity']:.2f}")
        c["rationale"] = ", ".join(reasons)
    return {
        "method": SIMILARITY_METHOD,
        "advisory": True,
        "rules": {
            "radius_m": DUPLICATE_RADIUS_M,
            "window_hours": DUPLICATE_WINDOW_HOURS,
            "weights": SIMILARITY_WEIGHTS,
            "note": (
                "Candidates come from the scenario, time and distance or address rules; the score adds "
                "character-trigram wording similarity. Default weights, not yet tuned on labelled pairs. "
                "Advisory only: nothing is linked or merged automatically, a human decides every link."
            ),
        },
        "candidates": scored,
    }


class DuplicateDecision(BaseModel):
    action: Literal["LINK", "MERGE", "DISMISS"]
    rationale: str = Rationale


@router.post("/incidents/{incident_id}/duplicates/{candidate_id}/decision")
def decide_duplicate(
    incident_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: DuplicateDecision,
    principal: DMUser,
):
    if incident_id == candidate_id:
        raise ApiError(422, "VALIDATION_FAILED", "An incident cannot be its own duplicate")
    with db.transaction() as conn:
        # Lock both rows in a stable order to avoid deadlocks between concurrent decisions.
        rows = {
            r["incident_id"]: r
            for r in conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ANY(%s) ORDER BY incident_id FOR UPDATE",
                ([incident_id, candidate_id],),
            ).fetchall()
        }
        if len(rows) != 2:
            raise not_found("Incident")
        canonical, candidate = rows[incident_id], rows[candidate_id]
        ensure_open(canonical)
        ensure_open(candidate)

        if body.action == "DISMISS":
            audit.record(
                conn,
                actor=principal,
                action="DUPLICATE_DISMISSED",
                entity_type="incident",
                entity_id=incident_id,
                rationale=body.rationale,
                after={"candidate_id": str(candidate_id)},
                ip=principal.ip,
            )
            return {"action": "DISMISS", "incident_id": incident_id, "candidate_id": candidate_id}

        if canonical["canonical_incident_id"] is not None:
            raise conflict(
                "ALREADY_LINKED",
                "This incident is itself linked as a duplicate. Open its canonical incident instead.",
            )
        if candidate["canonical_incident_id"] not in (None, incident_id):
            raise conflict("ALREADY_LINKED", "The candidate is already linked to another incident")
        if conn.execute(
            "SELECT 1 FROM incidents WHERE canonical_incident_id = %s LIMIT 1", (candidate_id,)
        ).fetchone():
            raise conflict(
                "ALREADY_LINKED",
                "The candidate has its own linked duplicates; link in the other direction instead.",
            )
        if body.action == "MERGE" and candidate["status"] not in ("SUBMITTED", "NEEDS_INFORMATION"):
            raise conflict(
                "INVALID_TRANSITION",
                "Only unverified candidates can be merged; link it instead to keep its workflow",
            )

        conn.execute(
            "UPDATE incidents SET canonical_incident_id = %s, version = version + 1 WHERE incident_id = %s",
            (incident_id, candidate_id),
        )
        candidate = lock_incident(conn, candidate_id)
        audit.record(
            conn,
            actor=principal,
            action="DUPLICATE_LINKED",
            entity_type="incident",
            entity_id=candidate_id,
            rationale=body.rationale,
            after={"canonical_incident_id": str(incident_id)},
            ip=principal.ip,
        )
        audit.record(
            conn,
            actor=principal,
            action="DUPLICATE_LINKED",
            entity_type="incident",
            entity_id=incident_id,
            rationale=body.rationale,
            after={"linked_candidate_id": str(candidate_id)},
            ip=principal.ip,
        )
        if body.action == "MERGE":
            update_incident(
                conn,
                principal,
                candidate,
                action="INCIDENT_REJECTED",
                rationale=f"Duplicate of {canonical['incident_ref']}: {body.rationale}",
                to_status="REJECTED",
            )
    return {"action": body.action, "incident_id": incident_id, "candidate_id": candidate_id}
