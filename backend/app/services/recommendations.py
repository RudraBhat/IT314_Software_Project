"""Emergency team recommendation rules and PostGIS spatial ranking engine.

Core capabilities:
1. Scenario-to-capability rules matrix mapping emergency types to required team competencies.
2. PostGIS spatial query calculating ST_Distance in km for AVAILABLE teams.
3. Multi-factor ranking:
   Score = (Capability Overlap Count * 10) - (Distance (km) * 0.05)
4. Explanatory reasoning for dispatchers (matched capabilities, distance, availability).
5. Offline in-memory fallback using authoritative Gujarat seed teams when PostGIS is not reachable.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.recommendations import CandidateTeam

logger = logging.getLogger("drch.recommendations")

# ─────────────────────────────────────────────────────────────────────────────
# 1. SCENARIO-TO-CAPABILITY RULES MATRIX
# ─────────────────────────────────────────────────────────────────────────────

SCENARIO_CAPABILITY_RULES: dict[str, list[str]] = {
    "URBAN_FLOODING": ["boat", "flood_rescue", "water_rescue", "dewatering_pump"],
    "FLOOD": ["boat", "flood_rescue", "water_rescue", "dewatering_pump"],
    "CYCLONE": [
        "debris_clearing",
        "shelter_management",
        "high_wind_rescue",
        "medical_first_aid",
        "cyclone_response",
        "search_and_rescue",
    ],
    "INDUSTRIAL_FIRE": [
        "hazmat",
        "fire_tender",
        "chemical_foam",
        "breathing_apparatus",
        "fire",
        "water_tender",
    ],
    "FIRE": [
        "hazmat",
        "fire_tender",
        "chemical_foam",
        "breathing_apparatus",
        "fire",
        "water_tender",
    ],
    "EARTHQUAKE": [
        "search_and_rescue",
        "collapse_rescue",
        "structural_shoring",
        "canine_unit",
        "trauma_care",
        "heavy_extrication",
        "medical",
    ],
    "LANDSLIDE": [
        "debris_clearing",
        "search_and_rescue",
        "collapse_rescue",
        "heavy_machinery",
    ],
    "CHEMICAL_SPILL": [
        "hazmat",
        "chemical_foam",
        "breathing_apparatus",
        "gas_leak",
    ],
    "HAZMAT": [
        "hazmat",
        "chemical_foam",
        "breathing_apparatus",
        "gas_leak",
    ],
}

SECONDARY_CAPABILITIES: dict[str, list[str]] = {
    "URBAN_FLOODING": ["diver_squad", "inflatable_boats", "medical"],
    "FLOOD": ["diver_squad", "inflatable_boats", "medical"],
    "CYCLONE": ["boat", "heavy_extrication", "water_rescue", "heavy_machinery"],
    "INDUSTRIAL_FIRE": ["gas_leak", "smoke_extraction", "high_rise_rescue"],
    "FIRE": ["gas_leak", "smoke_extraction", "high_rise_rescue"],
    "EARTHQUAKE": ["triage_support", "critical_care"],
}


def normalize_scenario(scenario: str) -> str:
    """Normalize scenario string to standard uppercase key."""
    s = scenario.strip().upper().replace(" ", "_")
    if s in ("FLOOD", "FLASH_FLOOD", "URBAN_FLOODING", "URBAN_FLOOD"):
        return "URBAN_FLOODING"
    if s in ("FIRE", "INDUSTRIAL_FIRE", "CHEMICAL_FIRE"):
        return "INDUSTRIAL_FIRE"
    if s in ("CYCLONE", "STORM", "TROPICAL_CYCLONE"):
        return "CYCLONE"
    if s in ("EARTHQUAKE", "QUAKE", "BUILDING_COLLAPSE"):
        return "EARTHQUAKE"
    if s in ("LANDSLIDE", "MUDSLIDE"):
        return "LANDSLIDE"
    if s in ("CHEMICAL_SPILL", "HAZMAT", "GAS_LEAK"):
        return "INDUSTRIAL_FIRE"
    return s


def get_required_capabilities(scenario: str) -> list[str]:
    """Retrieve list of required capabilities for a scenario."""
    norm = normalize_scenario(scenario)
    return SCENARIO_CAPABILITY_RULES.get(norm, ["search_and_rescue"])


def extract_capability_tags(raw_capabilities: Any) -> list[str]:
    """Safely parse capabilities from JSONB, dict, list, or string format."""
    if not raw_capabilities:
        return []
    if isinstance(raw_capabilities, str):
        try:
            raw_capabilities = json.loads(raw_capabilities)
        except (json.JSONDecodeError, TypeError, ValueError):
            return [raw_capabilities.lower().strip()]
    if isinstance(raw_capabilities, dict):
        return [k.lower().strip() for k, v in raw_capabilities.items() if v]
    if isinstance(raw_capabilities, list):
        return [str(item).lower().strip() for item in raw_capabilities]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. LEGACY DATA MODEL (Backwards Compatibility)
# ─────────────────────────────────────────────────────────────────────────────


class RecommendedTeam(BaseModel):
    """Ranked team recommendation with distance and match rationale."""

    resource_id: str
    name: str
    agency_id: str
    agency_name: str
    distance_km: float = Field(description="Distance in kilometers from incident")
    matched_capabilities: list[str] = Field(default_factory=list)
    secondary_matches: list[str] = Field(default_factory=list)
    capability_match_count: int = 0
    total_required: int = 0
    match_percentage: float = 0.0
    rank: int = 0
    quantity_available: int = 1
    reasons: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# 3. AUTHORITATIVE GUJARAT SEED TEAMS (In-Memory Fallback)
# ─────────────────────────────────────────────────────────────────────────────

_FALLBACK_TEAMS: list[dict[str, Any]] = [
    {
        "resource_id": "r0000000-0000-0000-0000-000000000001",
        "name": "NDRF 601 Urban Search & Rescue (Vadodara)",
        "agency_id": "a0000000-0000-0000-0000-000000000007",
        "agency_name": "NDRF 6th Battalion (Vadodara)",
        "latitude": 22.3072,
        "longitude": 73.1812,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "search_and_rescue": True,
            "heavy_extrication": True,
            "boat": True,
            "canine_unit": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000002",
        "name": "NDRF 602 Flood & Water Rescue Unit (Ahmedabad Sabarmati)",
        "agency_id": "a0000000-0000-0000-0000-000000000007",
        "agency_name": "NDRF 6th Battalion (Vadodara)",
        "latitude": 23.0225,
        "longitude": 72.5714,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "boat": True,
            "water_rescue": True,
            "flood_rescue": True,
            "inflatable_boats": True,
            "diver_squad": True,
            "dewatering_pump": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000003",
        "name": "NDRF 603 Cyclone Coastal Rescue Unit (Jamnagar)",
        "agency_id": "a0000000-0000-0000-0000-000000000007",
        "agency_name": "NDRF 6th Battalion (Vadodara)",
        "latitude": 22.4707,
        "longitude": 70.0577,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "cyclone_response": True,
            "search_and_rescue": True,
            "debris_clearing": True,
            "shelter_management": True,
            "high_wind_rescue": True,
            "medical_first_aid": True,
            "boat": True,
            "water_rescue": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000004",
        "name": "AFES Fire Tender Unit 1 (Ahmedabad Navrangpura)",
        "agency_id": "a0000000-0000-0000-0000-000000000008",
        "agency_name": "Gujarat Fire and Emergency Services (Ahmedabad HQ)",
        "latitude": 23.0373,
        "longitude": 72.5613,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "fire": True,
            "fire_tender": True,
            "water_tender": True,
            "high_rise_rescue": True,
            "smoke_extraction": True,
            "breathing_apparatus": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000005",
        "name": "AFES Fire Tender Unit 2 (Ahmedabad Maninagar)",
        "agency_id": "a0000000-0000-0000-0000-000000000008",
        "agency_name": "Gujarat Fire and Emergency Services (Ahmedabad HQ)",
        "latitude": 22.9784,
        "longitude": 72.6042,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "fire": True,
            "fire_tender": True,
            "water_tender": True,
            "heavy_extrication": True,
            "smoke_extraction": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000006",
        "name": "Surat Hazira Chemical Hazard & Industrial Fire Team",
        "agency_id": "a0000000-0000-0000-0000-000000000008",
        "agency_name": "Gujarat Fire and Emergency Services (Ahmedabad HQ)",
        "latitude": 21.1025,
        "longitude": 72.6841,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "hazmat": True,
            "fire_tender": True,
            "chemical_foam": True,
            "breathing_apparatus": True,
            "gas_leak": True,
            "industrial_fire": True,
            "fire": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000007",
        "name": "Rajkot Fire & Rescue Quick Reaction Unit",
        "agency_id": "a0000000-0000-0000-0000-000000000008",
        "agency_name": "Gujarat Fire and Emergency Services (Ahmedabad HQ)",
        "latitude": 22.3039,
        "longitude": 70.8022,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "fire": True,
            "fire_tender": True,
            "water_tender": True,
            "high_rise_rescue": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000008",
        "name": "108 ALS Disaster Ambulance Alpha (Ahmedabad Civil)",
        "agency_id": "a0000000-0000-0000-0000-000000000010",
        "agency_name": "EMRI Green Health Services Gujarat (108 Ambulance)",
        "latitude": 23.0525,
        "longitude": 72.6042,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "medical": True,
            "medical_first_aid": True,
            "trauma_care": True,
            "ambulance": True,
            "critical_care": True,
            "triage_support": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000011",
        "name": "SDRF Flood Quick Response Team (Rajkot Aji River)",
        "agency_id": "a0000000-0000-0000-0000-000000000011",
        "agency_name": "SDRF Gujarat Command (State Disaster Response Force)",
        "latitude": 22.3039,
        "longitude": 70.8022,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "boat": True,
            "flood_rescue": True,
            "diver_squad": True,
            "water_rescue": True,
            "inflatable_boats": True,
            "dewatering_pump": True,
        },
    },
    {
        "resource_id": "r0000000-0000-0000-0000-000000000012",
        "name": "SDRF Cyclone & Hazmat Response Unit (Bhuj, Kutch)",
        "agency_id": "a0000000-0000-0000-0000-000000000011",
        "agency_name": "SDRF Gujarat Command (State Disaster Response Force)",
        "latitude": 23.2420,
        "longitude": 69.6669,
        "status": "AVAILABLE",
        "quantity_available": 1,
        "capability_tags": {
            "cyclone_response": True,
            "search_and_rescue": True,
            "heavy_extrication": True,
            "canine_unit": True,
            "structural_shoring": True,
            "collapse_rescue": True,
            "debris_clearing": True,
        },
    },
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two coordinates in kilometers."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


# ─────────────────────────────────────────────────────────────────────────────
# 4. SPATIAL RANKING ENGINE (Phase 4 Scoring Formula)
# ─────────────────────────────────────────────────────────────────────────────

_POSTGIS_RECOMMEND_SQL = """
SELECT r.resource_id,
       r.name,
       r.agency_id,
       a.name AS agency_name,
       r.status,
       r.quantity_available,
       COALESCE(r.capability_tags, r.capability, '{}'::jsonb) AS capabilities,
       ROUND((ST_Distance(r.current_geom::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography) / 1000.0)::numeric, 1) AS distance_km
FROM resources r
JOIN agencies a ON a.agency_id = r.agency_id
WHERE r.type = 'TEAM'
  AND r.status = 'AVAILABLE'
  AND r.quantity_available > 0
ORDER BY distance_km ASC;
"""


def fetch_available_teams_postgis(
    conn: Any,
    latitude: float,
    longitude: float,
) -> list[dict[str, Any]]:
    """Execute PostGIS spatial query calculating distance in km for available teams."""
    rows = conn.execute(
        _POSTGIS_RECOMMEND_SQL,
        {"lat": latitude, "lon": longitude},
    ).fetchall()

    teams: list[dict[str, Any]] = []
    for r in rows:
        teams.append({
            "resource_id": r["resource_id"],
            "name": r["name"],
            "agency_id": r["agency_id"],
            "agency_name": r["agency_name"],
            "status": r["status"],
            "quantity_available": r["quantity_available"],
            "capabilities": r["capabilities"],
            "distance_km": float(r["distance_km"]),
        })
    return teams


def recommend_candidate_teams(
    latitude: float,
    longitude: float,
    scenario: str,
    limit: int = 5,
    conn: Any = None,
    required_capabilities: list[str] | str | None = None,
) -> list[CandidateTeam]:
    """Score and rank candidate response teams using Phase 4 criteria.

    Formula: Score = (Capability Overlap Count * 10) - (Distance (km) * 0.05)
    Returns ranked CandidateTeam models with structured operational justification text.
    When required_capabilities is provided, candidate teams are filtered and scored specifically
    against the requested capabilities.
    """
    raw_teams: list[dict[str, Any]] = []

    # Attempt live PostGIS query if database connection is explicitly passed
    if conn is not None:
        try:
            raw_teams = fetch_available_teams_postgis(conn, latitude, longitude)
        except Exception:
            logger.exception("PostGIS team query failed; falling back to in-memory seed teams")

    if not raw_teams:
        # Fallback to authoritative seed teams
        for t in _FALLBACK_TEAMS:
            dist = haversine_km(latitude, longitude, t["latitude"], t["longitude"])
            raw_teams.append({
                "resource_id": t["resource_id"],
                "name": t["name"],
                "agency_id": t["agency_id"],
                "agency_name": t["agency_name"],
                "status": t["status"],
                "quantity_available": t.get("quantity_available", 1),
                "capabilities": t.get("capability_tags", {}),
                "distance_km": round(dist, 1),
            })

    if required_capabilities is not None:
        if isinstance(required_capabilities, str):
            required_set = {required_capabilities.strip().lower()}
        else:
            required_set = {cap.strip().lower() for cap in required_capabilities if cap.strip()}
    else:
        norm_scenario = normalize_scenario(scenario)
        required = get_required_capabilities(norm_scenario)
        required_set = {cap.lower() for cap in required}

    scored_candidates: list[dict[str, Any]] = []

    for t in raw_teams:
        # Strictly exclude unavailable teams or depleted reserves
        if t.get("status") != "AVAILABLE" or (t.get("quantity_available") or 0) <= 0:
            continue

        team_caps = extract_capability_tags(t.get("capabilities"))
        matched = [cap for cap in team_caps if cap in required_set]
        overlap_count = len(matched)
        dist_km = round(float(t.get("distance_km", 0.0)), 1)

        # When specific capabilities are required (e.g. backup reinforcement),
        # exclude candidate teams lacking the requested capability.
        if required_capabilities is not None and overlap_count == 0:
            continue

        # Multi-factor score: (Overlap * 10) - (Distance * 0.05)
        score = (overlap_count * 10.0) - (dist_km * 0.05)

        # Structured operational justification text
        if overlap_count == len(required_set) and overlap_count > 0:
            reasons = f"Exact capability match ({', '.join(matched)}) and closest proximity ({dist_km:.1f} km)"
        elif overlap_count > 0:
            reasons = f"Partial capability match ({', '.join(matched)}) at {dist_km:.1f} km proximity"
        else:
            reasons = f"Available proximity reserve team ({dist_km:.1f} km) with no specific capability match"

        # Coerce resource UUID safely, handling non-standard seed strings gracefully
        raw_res_id = t["resource_id"]
        if isinstance(raw_res_id, uuid.UUID):
            res_uuid = raw_res_id
        else:
            try:
                res_uuid = uuid.UUID(str(raw_res_id))
            except ValueError:
                res_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_res_id))

        raw_agency_id = t.get("agency_id")
        if not raw_agency_id:
            agency_uuid = None
        elif isinstance(raw_agency_id, uuid.UUID):
            agency_uuid = raw_agency_id
        else:
            try:
                agency_uuid = uuid.UUID(str(raw_agency_id))
            except ValueError:
                agency_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_agency_id))

        scored_candidates.append({
            "resource_id": res_uuid,
            "team_name": t["name"],
            "agency_id": agency_uuid,
            "agency": t.get("agency_name", "Public Safety Agency"),
            "distance_km": dist_km,
            "capability_match": matched,
            "reasons": reasons,
            "status": t["status"],
            "capabilities": t.get("capabilities"),
            "score": score,
        })

    # Sort descending by score, ascending by distance
    scored_candidates.sort(key=lambda x: (x["score"], -x["distance_km"]), reverse=True)

    results: list[CandidateTeam] = []
    for rank_idx, cand in enumerate(scored_candidates[:limit], start=1):
        results.append(
            CandidateTeam(
                resource_id=cand["resource_id"],
                team_name=cand["team_name"],
                agency_id=cand["agency_id"],
                agency=cand["agency"],
                distance_km=cand["distance_km"],
                capability_match=cand["capability_match"],
                rank=rank_idx,
                reasons=cand["reasons"],
                status=cand["status"],
                capabilities=cand["capabilities"],
            )
        )

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 5. LEGACY ENTRYPOINTS (Backwards Compatibility with Sprint 1 Tests)
# ─────────────────────────────────────────────────────────────────────────────


def score_and_rank_teams(
    raw_teams: list[dict[str, Any]],
    latitude: float,
    longitude: float,
    scenario: str,
    limit: int = 5,
) -> list[RecommendedTeam]:
    """Legacy scoring function preserved for Sprint 1 backwards compatibility."""
    norm_scenario = normalize_scenario(scenario)
    required = get_required_capabilities(norm_scenario)
    secondary = SECONDARY_CAPABILITIES.get(norm_scenario, [])

    scored: list[dict[str, Any]] = []

    for t in raw_teams:
        if t.get("status") != "AVAILABLE" or (t.get("quantity_available") or 0) <= 0:
            continue

        tags = extract_capability_tags(t.get("capability_tags") or t.get("capabilities"))
        matched_req = [cap for cap in required if cap in tags]
        matched_sec = [cap for cap in secondary if cap in tags]

        match_count = len(matched_req)
        match_pct = round((match_count / len(required)) * 100.0, 1) if required else 0.0

        dist_km = t.get("distance_km")
        if dist_km is None:
            dist_km = haversine_km(latitude, longitude, t["latitude"], t["longitude"])
        dist_km = round(float(dist_km), 2)

        reasons: list[str] = []
        if match_count == len(required):
            reasons.append(f"Full capability match: {', '.join(matched_req)}")
        elif match_count > 0:
            reasons.append(f"Partial capability match ({match_count}/{len(required)}): {', '.join(matched_req)}")
        else:
            reasons.append("Proximity reserve team (no specific capability match)")

        reasons.append(f"Distance to scene: {dist_km:.1f} km")
        reasons.append(f"Status: AVAILABLE ({t.get('quantity_available', 1)} unit ready)")

        base_match_bonus = 100.0 if match_count > 0 else 0.0
        composite_score = (
            base_match_bonus
            + (match_count * 35.0)
            + (len(matched_sec) * 5.0)
            - (dist_km * 0.15)
        )

        scored.append({
            "resource_id": str(t["resource_id"]),
            "name": t["name"],
            "agency_id": str(t["agency_id"]),
            "agency_name": t["agency_name"],
            "distance_km": dist_km,
            "matched_capabilities": matched_req,
            "secondary_matches": matched_sec,
            "capability_match_count": match_count,
            "total_required": len(required),
            "match_percentage": match_pct,
            "quantity_available": int(t.get("quantity_available", 1)),
            "reasons": reasons,
            "composite_score": composite_score,
        })

    scored.sort(key=lambda x: x["composite_score"], reverse=True)

    results: list[RecommendedTeam] = []
    for rank_idx, item in enumerate(scored[:limit], start=1):
        results.append(
            RecommendedTeam(
                resource_id=item["resource_id"],
                name=item["name"],
                agency_id=item["agency_id"],
                agency_name=item["agency_name"],
                distance_km=item["distance_km"],
                matched_capabilities=item["matched_capabilities"],
                secondary_matches=item["secondary_matches"],
                capability_match_count=item["capability_match_count"],
                total_required=item["total_required"],
                match_percentage=item["match_percentage"],
                rank=rank_idx,
                quantity_available=item["quantity_available"],
                reasons=item["reasons"],
            )
        )

    return results


def get_recommended_teams(
    latitude: float,
    longitude: float,
    scenario: str,
    limit: int = 5,
    conn: Any = None,
) -> list[RecommendedTeam]:
    """Legacy helper for backwards compatibility with test_recommendations.py."""
    if conn is not None:
        try:
            db_teams = fetch_available_teams_postgis(conn, latitude, longitude)
            if db_teams:
                return score_and_rank_teams(db_teams, latitude, longitude, scenario, limit=limit)
        except Exception:
            logger.exception("PostGIS team query failed; falling back to in-memory seed teams")

    return score_and_rank_teams(_FALLBACK_TEAMS, latitude, longitude, scenario, limit=limit)
