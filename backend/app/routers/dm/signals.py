"""Raw signal queue and promotion to incidents (docs/api_contracts.md sections 4.2-4.3). Owner: Shlok.

Signals are unverified items from ingestion. A human must promote one; the new incident starts as
SUBMITTED and is NOT public until a dispatcher verifies it. Promotion needs PUBLISHER or SUPERVISOR.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import DMUser, Principal, _deny
from app.common import Rationale, Scenario, next_incident_ref, scenario_db
from app.errors import ApiError, conflict, not_found
from app.geo import district_for, is_in_gujarat

router = APIRouter()

SUPPORTED = ("CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING")
INGEST_SYSTEM_EMAIL = "ingest-system@drch.gov.in"


def _publisher_or_supervisor(request: Request, principal: DMUser) -> Principal:
    if not (principal.has("PUBLISHER") or principal.has("SUPERVISOR")):
        raise _deny(principal, request, "PERMISSION_REQUIRED",
                    "The publisher or supervisor permission is required", needed="PUBLISHER|SUPERVISOR")
    return principal


Promoter = Annotated[Principal, Depends(_publisher_or_supervisor)]


@router.get("/signals")
def list_signals(
    principal: DMUser,
    status: Literal["PENDING", "PROMOTED", "DISMISSED"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    with db.transaction() as conn:
        return conn.execute(
            """
            SELECT signal_id, source, content_text, language, ai_label, ai_confidence::float AS ai_confidence,
                   status, latitude::float AS latitude, longitude::float AS longitude, is_simulated, created_at
            FROM source_signals
            WHERE (%(status)s::text IS NULL OR status = %(status)s)
            ORDER BY created_at DESC LIMIT %(limit)s
            """,
            {"status": status, "limit": limit},
        ).fetchall()


class PromoteRequest(BaseModel):
    scenario: Scenario | None = Field(default=None, description="Required when the AI label is not a supported scenario")


@router.post("/signals/{signal_id}/promote", status_code=201)
def promote_signal(signal_id: uuid.UUID, principal: Promoter, body: PromoteRequest | None = None):
    with db.transaction() as conn:
        sig = conn.execute("SELECT * FROM source_signals WHERE signal_id = %s FOR UPDATE", (signal_id,)).fetchone()
        if sig is None:
            raise not_found("Signal")
        if sig["status"] != "PENDING":
            raise conflict("SIGNAL_NOT_PENDING", f"Signal is already {sig['status']}")
        scenario = scenario_db(body.scenario) if body and body.scenario else (sig["ai_label"] or "").upper()
        if scenario not in SUPPORTED:
            raise ApiError(422, "UNSUPPORTED_SCENARIO", "Choose cyclone, industrial_fire or urban_flooding to promote")
        lat, lon = sig["latitude"], sig["longitude"]
        if lat is None or lon is None:
            raise ApiError(422, "NO_LOCATION", "The signal has no coordinates; it cannot become an incident")
        if not is_in_gujarat(float(lat), float(lon)):
            raise ApiError(422, "OUTSIDE_GUJARAT", "The signal location is outside Gujarat")
        system_user = conn.execute("SELECT user_id FROM users WHERE email = %s::citext", (INGEST_SYSTEM_EMAIL,)).fetchone()
        if system_user is None:
            raise ApiError(503, "CONFIG_ERROR", "The ingestion system account is missing; run the reference seed")
        ref = next_incident_ref(conn)
        incident = conn.execute(
            """
            INSERT INTO incidents (incident_ref, reporter_id, scenario, description, location_source, latitude,
                                   longitude, address_text, district, source, source_ref, is_simulated)
            VALUES (%s, %s, %s::scenario_type, %s, 'MANUAL', %s, %s, %s, %s, %s, %s, %s)
            RETURNING incident_id, incident_ref, status
            """,
            (ref, system_user["user_id"], scenario, sig["content_text"][:2000], lat, lon, sig["location_text"],
             district_for(float(lat), float(lon)), sig["source"], sig["source_uid"], sig["is_simulated"]),
        ).fetchone()
        conn.execute(
            "INSERT INTO incident_status_history (incident_id, from_status, to_status, changed_by, reason) "
            "VALUES (%s, NULL, 'SUBMITTED', %s, %s)",
            (incident["incident_id"], principal.user_id, f"Promoted from {sig['source']} signal"),
        )
        conn.execute(
            "UPDATE source_signals SET status = 'PROMOTED', promoted_incident_id = %s, updated_at = now() WHERE signal_id = %s",
            (incident["incident_id"], signal_id),
        )
        audit.record(conn, actor=principal, action="SIGNAL_PROMOTED", entity_type="signal", entity_id=signal_id,
                     rationale=f"Promoted to {incident['incident_ref']}", ip=principal.ip)
    return {"signal_id": signal_id, "status": "PROMOTED", "incident_ref": incident["incident_ref"],
            "incident_status": incident["status"]}


class DismissRequest(BaseModel):
    rationale: str = Rationale


@router.post("/signals/{signal_id}/dismiss")
def dismiss_signal(signal_id: uuid.UUID, body: DismissRequest, principal: Promoter):
    with db.transaction() as conn:
        sig = conn.execute("SELECT status FROM source_signals WHERE signal_id = %s FOR UPDATE", (signal_id,)).fetchone()
        if sig is None:
            raise not_found("Signal")
        if sig["status"] != "PENDING":
            raise conflict("SIGNAL_NOT_PENDING", f"Signal is already {sig['status']}")
        conn.execute(
            "UPDATE source_signals SET status = 'DISMISSED', dismiss_rationale = %s, updated_at = now() WHERE signal_id = %s",
            (body.rationale, signal_id),
        )
        audit.record(conn, actor=principal, action="SIGNAL_DISMISSED", entity_type="signal", entity_id=signal_id,
                     rationale=body.rationale, ip=principal.ip)
    return {"signal_id": signal_id, "status": "DISMISSED"}
