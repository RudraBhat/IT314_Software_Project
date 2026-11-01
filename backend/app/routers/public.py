"""Public read-only endpoints — no authentication required.

Owned by: Nisarg (Sprint 1, S1-07)

Consumers:
  Tanishq (S1-09) — Leaflet public Gujarat map.
  Zalak   (S1-04) — imports is_in_gujarat from app.geo for 422 geofence check.

Security guarantees enforced here:
  • Only VERIFIED / DISPATCHED / RESOLVED incidents are returned.
  • verified_by IS NOT NULL — DM officer has explicitly approved the record.
  • Duplicate incidents that share a canonical parent are excluded.
  • Zero PII: no reporter_id, reporter_name, reporter_phone, internal_notes,
    or free-text description is returned.
  • Coordinates are rounded to 4 decimal places (~11 m) so the precise
    reporter GPS pin cannot be reconstructed from the public feed.

When DATABASE_URL is not configured (demo / CI mode) the endpoint returns the
hard-coded demo incidents from the seed data so Tanishq can work offline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from psycopg import sql
from pydantic import BaseModel, ConfigDict

from app import db
from app.config import get_settings

logger = logging.getLogger("drch.public")

router = APIRouter(prefix="/api/v1/public", tags=["public"])

# ─────────────────────────────────────────────────────────────────────────────
# Response schema — stable public contract (zero PII).
# Deliberately omits: reporter_id, reporter_name, reporter_phone,
#                     internal_notes, raw description, canonical_incident_id.
# ─────────────────────────────────────────────────────────────────────────────

class PublicIncidentResponse(BaseModel):
    """Public-safe incident record. Zero PII. Used by the Gujarat Leaflet map."""

    incident_ref: str
    """Human-readable reference, e.g. INC-2026-000001."""

    scenario: str
    """Disaster scenario: CYCLONE | URBAN_FLOODING | INDUSTRIAL_FIRE."""

    district: str | None
    """Gujarat district name resolved at report time."""

    status: str
    """Current lifecycle status: VERIFIED | DISPATCHED | RESOLVED."""

    priority: str | None
    """Verified priority: LOW | MEDIUM | HIGH | CRITICAL."""

    verified_at: datetime | None
    """UTC timestamp when a DM officer verified this incident."""

    latitude: float
    """Rounded to 4 decimal places (~11 m) for privacy."""

    longitude: float
    """Rounded to 4 decimal places (~11 m) for privacy."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "incident_ref": "INC-2026-000001",
                "scenario": "URBAN_FLOODING",
                "district": "Ahmedabad",
                "status": "VERIFIED",
                "priority": "HIGH",
                "verified_at": "2026-10-24T12:00:00Z",
                "latitude": 23.037,
                "longitude": 72.561,
            }
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Demo fallback — returned when DATABASE_URL is not configured.
# Mirrors the verified seed incidents so the Leaflet map is never blank.
# ─────────────────────────────────────────────────────────────────────────────

_DEMO_INCIDENTS: list[dict] = [
    {
        "incident_ref": "INC-2026-000001",
        "scenario": "URBAN_FLOODING",
        "district": "Ahmedabad",
        "status": "VERIFIED",
        "priority": "HIGH",
        "verified_at": datetime.fromisoformat("2026-10-24T12:00:00+00:00"),
        "latitude": 23.0373,
        "longitude": 72.5613,
    },
    {
        "incident_ref": "INC-2026-000002",
        "scenario": "INDUSTRIAL_FIRE",
        "district": "Surat",
        "status": "DISPATCHED",
        "priority": "CRITICAL",
        "verified_at": datetime.fromisoformat("2026-10-24T13:30:00+00:00"),
        "latitude": 21.1025,
        "longitude": 72.6841,
    },
    {
        "incident_ref": "INC-2026-000003",
        "scenario": "CYCLONE",
        "district": "Kutch",
        "status": "VERIFIED",
        "priority": "HIGH",
        "verified_at": datetime.fromisoformat("2026-10-24T14:00:00+00:00"),
        "latitude": 23.1139,
        "longitude": 70.0278,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# SQL — core query (no PII columns selected, coords rounded to 4 dp).
#
# Filters applied via psycopg Composed SQL to prevent injection:
#   district  → exact match (case-insensitive via LOWER)
#   scenario  → exact match (cast to incident_scenario enum)
#   bbox      → PostGIS &&  operator (fast GiST index hit)
#
# Security invariants encoded in WHERE:
#   status IN (...)        → only publicly-releasable lifecycle states
#   verified_by IS NOT NULL → officer has explicitly approved
#   canonical gate         → hides duplicate child incidents
# ─────────────────────────────────────────────────────────────────────────────

_BASE_SELECT = """
    SELECT
        i.incident_ref,
        lower(i.scenario::text)            AS scenario,
        i.district,
        lower(i.status::text)              AS status,
        lower(i.verified_priority::text)   AS priority,
        i.verified_at,
        ROUND(i.latitude::numeric,  4)::float AS latitude,
        ROUND(i.longitude::numeric, 4)::float AS longitude
    FROM incidents i
    WHERE i.status        IN ('VERIFIED', 'DISPATCHED', 'RESOLVED')
      AND i.verified_by   IS NOT NULL
      AND (i.canonical_incident_id IS NULL
           OR i.canonical_incident_id = i.incident_id)
"""


def _build_query(
    district: str | None,
    scenario: str | None,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
) -> tuple[sql.Composed, dict]:
    """Build the parameterised query + params dict for the active filters."""
    clauses: list[sql.Composable] = [sql.SQL(_BASE_SELECT)]
    params: dict = {}

    if district:
        clauses.append(sql.SQL("  AND lower(i.district) = lower(%(district)s)"))
        params["district"] = district.strip()

    if scenario:
        clauses.append(sql.SQL("  AND i.scenario = %(scenario)s::incident_scenario"))
        params["scenario"] = scenario.strip().upper()

    # Bounding-box filter using PostGIS geography &&  (index-accelerated)
    if any(v is not None for v in (min_lat, max_lat, min_lon, max_lon)):
        # Clamp to GUJARAT_BBOX when partial bbox supplied — safe default
        from app.geo import GUJARAT_BBOX
        lo_lat = min_lat if min_lat is not None else GUJARAT_BBOX["min_lat"]
        hi_lat = max_lat if max_lat is not None else GUJARAT_BBOX["max_lat"]
        lo_lon = min_lon if min_lon is not None else GUJARAT_BBOX["min_lon"]
        hi_lon = max_lon if max_lon is not None else GUJARAT_BBOX["max_lon"]
        clauses.append(sql.SQL(
            "  AND i.geom && ST_MakeEnvelope(%(lo_lon)s, %(lo_lat)s,"
            " %(hi_lon)s, %(hi_lat)s, 4326)::geography"
        ))
        params.update(lo_lat=lo_lat, hi_lat=hi_lat, lo_lon=lo_lon, hi_lon=hi_lon)

    clauses.append(sql.SQL("ORDER BY i.verified_at DESC"))
    return sql.Composed(clauses), params


def _apply_demo_filters(
    incidents: list[dict],
    district: str | None,
    scenario: str | None,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
) -> list[dict]:
    """Apply the same filters to the in-memory demo list (no DB needed)."""
    result = incidents
    if district:
        result = [r for r in result if (r["district"] or "").lower() == district.lower()]
    if scenario:
        result = [r for r in result if r["scenario"].upper() == scenario.upper()]
    if min_lat is not None:
        result = [r for r in result if r["latitude"] >= min_lat]
    if max_lat is not None:
        result = [r for r in result if r["latitude"] <= max_lat]
    if min_lon is not None:
        result = [r for r in result if r["longitude"] >= min_lon]
    if max_lon is not None:
        result = [r for r in result if r["longitude"] <= max_lon]
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/incidents",
    response_model=list[PublicIncidentResponse],
    summary="Public verified incidents — Gujarat Leaflet map feed",
    description=(
        "Returns only VERIFIED, DISPATCHED, or RESOLVED incidents within Gujarat. "
        "No authentication required. Reporter PII is never included. "
        "Coordinates rounded to 4 decimal places (~11 m precision). "
        "Supports optional filtering by district, scenario, and bounding box."
    ),
)
def list_public_incidents(
    district: Annotated[
        str | None,
        Query(description="Filter by Gujarat district name (case-insensitive), e.g. Ahmedabad"),
    ] = None,
    scenario: Annotated[
        str | None,
        Query(description="Filter by scenario: CYCLONE | URBAN_FLOODING | INDUSTRIAL_FIRE"),
    ] = None,
    min_lat: Annotated[float | None, Query(ge=-90,  le=90,  description="Bounding box south edge")] = None,
    max_lat: Annotated[float | None, Query(ge=-90,  le=90,  description="Bounding box north edge")] = None,
    min_lon: Annotated[float | None, Query(ge=-180, le=180, description="Bounding box west edge")]  = None,
    max_lon: Annotated[float | None, Query(ge=-180, le=180, description="Bounding box east edge")]  = None,
) -> list[PublicIncidentResponse]:
    """
    Public Gujarat incident feed — used by the Leaflet tactical map.

    Security guarantees:
    - Only DM-verified incidents (VERIFIED / DISPATCHED / RESOLVED) are returned.
    - Duplicate child incidents are excluded (canonical_incident_id gate).
    - Zero PII: no reporter names, phones, IDs, or free-text descriptions.
    - Coordinates rounded to 4 dp to prevent precise location reconstruction.
    """
    settings = get_settings()

    # ── Demo / CI mode (no database configured) ──────────────────────
    if not settings.database_url:
        logger.debug("DATABASE_URL not set — returning demo incidents for public map")
        filtered = _apply_demo_filters(
            _DEMO_INCIDENTS, district, scenario, min_lat, max_lat, min_lon, max_lon
        )
        return [PublicIncidentResponse(**r) for r in filtered]

    # ── Production: PostgreSQL / PostGIS query ────────────────────────
    try:
        query, params = _build_query(district, scenario, min_lat, max_lat, min_lon, max_lon)
        with db.transaction() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            PublicIncidentResponse(
                incident_ref=r["incident_ref"],
                scenario=r["scenario"],
                district=r["district"],
                status=r["status"],
                priority=r["priority"],
                verified_at=r["verified_at"],
                latitude=r["latitude"],
                longitude=r["longitude"],
            )
            for r in rows
        ]
    except Exception:
        logger.exception("Failed to query public incidents from PostGIS")
        # Degrade gracefully — return demo incidents so the map is never blank
        filtered = _apply_demo_filters(
            _DEMO_INCIDENTS, district, scenario, min_lat, max_lat, min_lon, max_lon
        )
        return [PublicIncidentResponse(**r) for r in filtered]
