"""Public read-only endpoints - no authentication.

Contract: docs/api_contracts.md section 1. Owner: Nisarg (S1-07); consumed by the public map (S1-09).

Privacy rules enforced in SQL:
  * only VERIFIED / DISPATCHED / RESOLVED incidents that a DM officer verified;
  * duplicate child incidents are hidden;
  * no reporter identity, no free text, no internal notes;
  * coordinates rounded to 4 decimal places (about 11 m);
  * simulated rows (is_simulated) are hidden unless APP_ENV=development.

There is deliberately NO demo fallback: if the database fails the global error
handler answers 503 and the client shows an error state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from psycopg import sql
from pydantic import BaseModel

from app import db
from app.common import Scenario, scenario_db
from app.config import get_settings
from app.errors import ApiError

router = APIRouter(prefix="/api/v1/public", tags=["public"])


class PublicIncident(BaseModel):
    reference: str
    scenario: str  # cyclone | industrial_fire | urban_flooding
    district: str | None
    status: str  # VERIFIED | DISPATCHED | RESOLVED
    verified_priority: str | None  # CRITICAL | HIGH | MEDIUM | LOW
    verified_at: datetime | None
    latitude: float
    longitude: float
    is_simulated: bool = False


class PublicCampaign(BaseModel):
    campaign_id: str
    title: str
    purpose: str
    scenario: str | None
    target_amount: float | None
    currency: str
    status: str


class PublicAlert(BaseModel):
    alert_id: str
    source: str
    event_type: str
    severity: str
    area_text: str | None
    is_fallback: bool
    effective_at: datetime | None
    expires_at: datetime | None


_INCIDENT_SELECT = """
    SELECT i.incident_ref AS reference,
           lower(i.scenario::text) AS scenario,
           i.district,
           i.status::text AS status,
           i.verified_priority::text AS verified_priority,
           i.verified_at,
           ROUND(i.latitude::numeric, 4)::float AS latitude,
           ROUND(i.longitude::numeric, 4)::float AS longitude,
           i.is_simulated
    FROM incidents i
    WHERE i.status IN ('VERIFIED', 'DISPATCHED', 'RESOLVED')
      AND i.verified_by IS NOT NULL
      AND i.latitude IS NOT NULL AND i.longitude IS NOT NULL
      AND (i.canonical_incident_id IS NULL OR i.canonical_incident_id = i.incident_id)
"""


def _parse_bbox(raw: str) -> tuple[float, float, float, float]:
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in raw.split(","))
    except ValueError:
        raise ApiError(422, "VALIDATION_FAILED", "bbox must be min_lon,min_lat,max_lon,max_lat") from None
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ApiError(422, "VALIDATION_FAILED", "bbox coordinates are out of range or inverted")
    return min_lon, min_lat, max_lon, max_lat


@router.get("/incidents", response_model=list[PublicIncident], summary="Verified incidents for the public map")
def list_public_incidents(
    district: Annotated[str | None, Query(max_length=100)] = None,
    scenario: Scenario | None = None,
    bbox: Annotated[str | None, Query(description="min_lon,min_lat,max_lon,max_lat")] = None,
):
    clauses: list[sql.Composable] = [sql.SQL(_INCIDENT_SELECT)]
    params: dict = {}
    if get_settings().app_env != "development":
        clauses.append(sql.SQL(" AND i.is_simulated = FALSE"))
    if district:
        clauses.append(sql.SQL(" AND lower(i.district) = lower(%(district)s)"))
        params["district"] = district.strip()
    if scenario:
        clauses.append(sql.SQL(" AND i.scenario = %(scenario)s::scenario_type"))
        params["scenario"] = scenario_db(scenario)
    if bbox:
        min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
        clauses.append(
            sql.SQL(" AND i.geom && ST_MakeEnvelope(%(x1)s, %(y1)s, %(x2)s, %(y2)s, 4326)::geography")
        )
        params.update(x1=min_lon, y1=min_lat, x2=max_lon, y2=max_lat)
    clauses.append(sql.SQL(" ORDER BY i.verified_at DESC NULLS LAST LIMIT 1000"))
    with db.transaction() as conn:
        return conn.execute(sql.Composed(clauses), params).fetchall()


@router.get("/campaigns", response_model=list[PublicCampaign], summary="Active donation campaigns")
def list_public_campaigns():
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT campaign_id::text AS campaign_id, title, purpose, lower(scenario::text) AS scenario,
                   target_amount::float AS target_amount, currency::text AS currency, status::text AS status
            FROM donation_campaigns WHERE status = 'ACTIVE' ORDER BY created_at DESC
            """
        ).fetchall()
    return rows


@router.get("/alerts", response_model=list[PublicAlert], summary="Active early warnings and external alerts")
def list_public_alerts():
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT alert_id::text AS alert_id, source, event_type, severity, area_text, is_fallback,
                   effective_at, expires_at
            FROM external_alerts
            WHERE expires_at IS NULL OR expires_at > now()
            ORDER BY effective_at DESC NULLS LAST LIMIT 200
            """
        ).fetchall()
    return rows
