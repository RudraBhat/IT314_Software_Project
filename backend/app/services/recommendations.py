"""Emergency team recommendation rules and PostGIS spatial ranking engine.

Core capabilities:
1. Scenario-to-capability rules: PRIMARY capabilities a team must bring for the scenario and
   SECONDARY capabilities that support the response but cannot carry it alone.
2. PostGIS spatial query calculating ST_Distance in km for AVAILABLE teams.
3. Multi-factor ranking (S3-14 tuning):
   Score = (Primary capability GROUPS covered * 10) + (Secondary tags * 3) - (Distance (km) * 0.08)
   Teams with at least one PRIMARY match always rank above teams without one, so a nearby
   team that cannot do the job never outranks a capable team further away.
4. Explanatory reasoning for dispatchers (matched capabilities, distance, nearest capable team).
5. Offline in-memory fallback using the Gujarat seed teams ONLY when no database connection is
   passed (no DATABASE_URL). Every such candidate is marked is_fallback=True so it can never be
   mistaken for live availability. When the database answers with no available team the result
   is empty, and when the spatial query fails the error propagates to the caller (which reports
   "recommendations unavailable"): a dispatcher must never be shown teams that do not exist.

Recommendations are strictly advisory: nothing in this module reserves or dispatches a team.
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
        "industrial_fire",
    ],
    "FIRE": [
        "hazmat",
        "fire_tender",
        "chemical_foam",
        "breathing_apparatus",
        "fire",
        "water_tender",
        "industrial_fire",
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
    "CYCLONE": ["boat", "heavy_extrication", "water_rescue", "heavy_machinery", "medical"],
    "INDUSTRIAL_FIRE": ["gas_leak", "smoke_extraction", "high_rise_rescue", "medical"],
    "FIRE": ["gas_leak", "smoke_extraction", "high_rise_rescue", "medical"],
    "EARTHQUAKE": ["triage_support", "critical_care"],
}

# Primary capabilities grouped by the job they do (S3-14). Tags inside one group are
# near-synonyms (a fire tender team is tagged fire, fire_tender and water_tender), so a team
# scores once per GROUP it covers, not once per tag. With per-tag scoring, a tag-rich specialist
# 220 km away was within 0.5 points of fire tenders 10 km from a GIDC fire (and overtook them once
# the seed's industrial_fire tag counted). Scenarios without groups here score
# each primary tag as its own group (Sprint 2 behaviour).
CAPABILITY_GROUPS: dict[str, dict[str, list[str]]] = {
    "URBAN_FLOODING": {
        "water rescue": ["boat", "flood_rescue", "water_rescue"],
        "dewatering": ["dewatering_pump"],
    },
    "INDUSTRIAL_FIRE": {
        "firefighting": ["fire", "fire_tender", "water_tender"],
        "hazmat": ["hazmat", "chemical_foam", "industrial_fire", "breathing_apparatus"],
    },
    "CYCLONE": {
        "rescue": ["search_and_rescue", "cyclone_response", "high_wind_rescue"],
        "debris clearing": ["debris_clearing"],
        "shelter": ["shelter_management"],
        "first aid": ["medical_first_aid"],
    },
}
CAPABILITY_GROUPS["FLOOD"] = CAPABILITY_GROUPS["URBAN_FLOODING"]
CAPABILITY_GROUPS["FIRE"] = CAPABILITY_GROUPS["INDUSTRIAL_FIRE"]

# Ranking weights (S3-14). One covered primary group = 10 points, one secondary tag = 3 points,
# and 0.08 points per km: 125 km of extra travel costs as much as one capability group, so a
# local team that can do the job beats a distant one with only extra supporting tags.
PRIMARY_WEIGHT = 10.0
SECONDARY_WEIGHT = 3.0
DISTANCE_PENALTY_PER_KM = 0.08


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


def get_secondary_capabilities(scenario: str) -> list[str]:
    """Retrieve supporting (secondary) capabilities for a scenario."""
    return SECONDARY_CAPABILITIES.get(normalize_scenario(scenario), [])


def get_capability_groups(scenario: str) -> dict[str, list[str]]:
    """Primary capabilities grouped by job; ungrouped scenarios get one group per tag."""
    norm = normalize_scenario(scenario)
    if norm in CAPABILITY_GROUPS:
        return CAPABILITY_GROUPS[norm]
    return {cap: [cap] for cap in get_required_capabilities(norm)}


def build_reasons(
    matched: list[str],
    secondary: list[str],
    groups_covered: int,
    groups_total: int,
    dist_km: float,
    nearest_capable: bool,
) -> str:
    """Factually accurate justification for one ranked team (never claims 'closest' unless true)."""
    if matched and groups_covered == groups_total:
        text = f"Exact capability match ({', '.join(matched)})"
    elif matched:
        text = (
            f"Partial capability match ({', '.join(matched)}; "
            f"covers {groups_covered} of {groups_total} required capability groups)"
        )
    elif secondary:
        text = f"Supporting capabilities only ({', '.join(secondary)})"
    else:
        text = "Available proximity reserve team with no specific capability match"
    if matched and secondary:
        text += f"; also offers {', '.join(secondary)}"
    text += f" - {dist_km:.1f} km away"
    if nearest_capable:
        text += " (nearest capable team)"
    return text


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
       COALESCE(NULLIF(r.capability_tags, '{}'::jsonb), r.capability, '{}'::jsonb) AS capabilities,
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
    """Score and rank candidate response teams (S3-14 tuned rules).

    Formula: Score = (Primary groups covered * 10) + (Secondary tags * 3) - (Distance (km) * 0.08),
    with every team that has a primary match ranked above every team that has none.
    Returns ranked CandidateTeam models with structured operational justification text.
    When required_capabilities is provided (field backup request), candidate teams are filtered
    and scored only against the requested capabilities.

    With a database connection the PostGIS answer is authoritative, even when it is empty, and
    query errors propagate (the transaction is aborted, so a fallback could only invent teams).
    The in-memory seed teams are used only when no connection is passed (offline demo mode).
    """
    raw_teams: list[dict[str, Any]] = []
    is_fallback = conn is None

    if conn is not None:
        raw_teams = fetch_available_teams_postgis(conn, latitude, longitude)
    else:
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
            required_order = [required_capabilities.strip().lower()]
        else:
            required_order = [cap.strip().lower() for cap in required_capabilities if cap.strip()]
        secondary_order: list[str] = []
        groups = [[cap] for cap in dict.fromkeys(required_order)]
    else:
        norm_scenario = normalize_scenario(scenario)
        required_order = [cap.lower() for cap in get_required_capabilities(norm_scenario)]
        secondary_order = [
            cap.lower() for cap in get_secondary_capabilities(norm_scenario) if cap.lower() not in required_order
        ]
        groups = [[c.lower() for c in tags] for tags in get_capability_groups(norm_scenario).values()]
    required_order = list(dict.fromkeys(required_order))

    scored_candidates: list[dict[str, Any]] = []

    for t in raw_teams:
        # Strictly exclude unavailable teams or depleted reserves
        if t.get("status") != "AVAILABLE" or (t.get("quantity_available") or 0) <= 0:
            continue

        team_caps = set(extract_capability_tags(t.get("capabilities")))
        # Listed in rule order so the output is deterministic and reads like the rules table.
        matched = [cap for cap in required_order if cap in team_caps]
        secondary = [cap for cap in secondary_order if cap in team_caps]
        overlap_count = len(matched)
        groups_covered = sum(1 for tags in groups if team_caps.intersection(tags))
        dist_km = round(float(t.get("distance_km", 0.0)), 1)

        # When specific capabilities are required (e.g. backup reinforcement),
        # exclude candidate teams lacking the requested capability.
        if required_capabilities is not None and overlap_count == 0:
            continue

        score = (
            groups_covered * PRIMARY_WEIGHT
            + len(secondary) * SECONDARY_WEIGHT
            - dist_km * DISTANCE_PENALTY_PER_KM
        )

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
            "secondary_match": secondary,
            "groups_covered": groups_covered,
            "status": t["status"],
            "capabilities": t.get("capabilities"),
            "score": score,
        })

    # Capable teams (>= 1 primary match) first, then by score, then the nearer team.
    scored_candidates.sort(
        key=lambda x: (len(x["capability_match"]) > 0, x["score"], -x["distance_km"]),
        reverse=True,
    )

    capable_km = [c["distance_km"] for c in scored_candidates if c["capability_match"]]
    nearest_capable_km = min(capable_km) if capable_km else None

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
                secondary_match=cand["secondary_match"],
                matched_count=len(cand["capability_match"]),
                score=round(cand["score"], 2),
                rank=rank_idx,
                reasons=build_reasons(
                    cand["capability_match"],
                    cand["secondary_match"],
                    cand["groups_covered"],
                    len(groups),
                    cand["distance_km"],
                    nearest_capable=bool(cand["capability_match"])
                    and cand["distance_km"] == nearest_capable_km,
                ),
                status=cand["status"],
                capabilities=cand["capabilities"],
                is_fallback=is_fallback,
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
    """Legacy helper for backwards compatibility with test_recommendations.py.

    Same data rule as recommend_candidate_teams: with a connection the database answer is
    authoritative (an empty answer stays empty); seed teams are used only offline.
    """
    if conn is not None:
        db_teams = fetch_available_teams_postgis(conn, latitude, longitude)
        return score_and_rank_teams(db_teams, latitude, longitude, scenario, limit=limit)

    return score_and_rank_teams(_FALLBACK_TEAMS, latitude, longitude, scenario, limit=limit)
