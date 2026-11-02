"""Emergency team recommendation rules and PostGIS spatial ranking engine.

Owned by: Nisarg (Sprint 1: S1-11, Sprint 2: S2-02)

Core capabilities:
1. Scenario-to-capability rules table mapping emergency types to required team competencies.
2. PostGIS spatial query calculating ST_Distance in km for AVAILABLE teams.
3. Multi-factor ranking:
   - Primary: Capability match count and coverage ratio (specialized rescue first).
   - Secondary: Great-circle / PostGIS distance in km (proximity).
4. Explanatory reasoning for dispatchers (matched capabilities, distance, availability).
5. Offline in-memory fallback using authoritative Gujarat seed teams when PostGIS is not running.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from pydantic import BaseModel, Field

from app import db

logger = logging.getLogger("drch.recommendations")

# ─────────────────────────────────────────────────────────────────────────────
# 1. SCENARIO-TO-CAPABILITY RULES TABLE (S1-11 Requirement)
# Standard capability keys agreed with Siddh for Sprint 1
# ─────────────────────────────────────────────────────────────────────────────

SCENARIO_CAPABILITY_RULES: dict[str, list[str]] = {
    "URBAN_FLOODING": ["boat", "water_rescue", "flood_rescue"],
    "FLOOD": ["boat", "water_rescue", "flood_rescue"],
    "INDUSTRIAL_FIRE": ["fire", "water_tender", "hazmat"],
    "FIRE": ["fire", "water_tender", "hazmat"],
    "CYCLONE": ["search_and_rescue", "cyclone_response"],
}

# Secondary/bonus capability tags that enhance field effectiveness
SECONDARY_CAPABILITIES: dict[str, list[str]] = {
    "URBAN_FLOODING": ["diver_squad", "inflatable_boats", "medical"],
    "INDUSTRIAL_FIRE": ["chemical_foam", "gas_leak", "smoke_extraction", "high_rise_rescue"],
    "CYCLONE": ["boat", "heavy_extrication", "water_rescue", "heavy_machinery"],
}


def normalize_scenario(scenario: str) -> str:
    """Normalize scenario string to uppercase standard key."""
    s = scenario.strip().upper()
    if s in ("FLOOD", "URBAN_FLOODING"):
        return "URBAN_FLOODING"
    if s in ("FIRE", "INDUSTRIAL_FIRE"):
        return "INDUSTRIAL_FIRE"
    return s


def get_required_capabilities(scenario: str) -> list[str]:
    """Retrieve list of mandatory capability keys for a given scenario."""
    norm = normalize_scenario(scenario)
    return SCENARIO_CAPABILITY_RULES.get(norm, ["search_and_rescue"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. DATA MODELS
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




def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two coordinates in kilometers."""
    r = 6371.0  # Earth's radius in km
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
# 4. SCORING & RANKING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def score_and_rank_teams(
    raw_teams: list[dict[str, Any]],
    latitude: float,
    longitude: float,
    scenario: str,
    limit: int = 5,
) -> list[RecommendedTeam]:
    """
    Score and rank available teams based on:
    1. Mandatory capability coverage (higher match count ranks higher).
    2. Secondary capability bonus.
    3. Spatial distance in kilometers (closer teams rank higher).
    """
    norm_scenario = normalize_scenario(scenario)
    required = get_required_capabilities(norm_scenario)
    secondary = SECONDARY_CAPABILITIES.get(norm_scenario, [])

    scored: list[dict[str, Any]] = []

    for t in raw_teams:
        # Strictly exclude unavailable teams or depleted reserves
        if t.get("status") != "AVAILABLE" or (t.get("quantity_available") or 0) <= 0:
            continue

        tags = t.get("capability_tags") or {}
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError, ValueError):
                tags = {}

        # 1. Match mandatory capabilities
        matched_req = [cap for cap in required if tags.get(cap) is True]
        matched_sec = [cap for cap in secondary if tags.get(cap) is True]

        match_count = len(matched_req)
        match_pct = round((match_count / len(required)) * 100.0, 1) if required else 0.0

        # Distance
        dist_km = t.get("distance_km")
        if dist_km is None:
            dist_km = haversine_km(latitude, longitude, t["latitude"], t["longitude"])
        dist_km = round(float(dist_km), 2)

        # Build human-readable explanations
        reasons: list[str] = []
        if match_count == len(required):
            reasons.append(f"Full capability match: {', '.join(matched_req)}")
        elif match_count > 0:
            reasons.append(f"Partial capability match ({match_count}/{len(required)}): {', '.join(matched_req)}")
        else:
            reasons.append("Proximity reserve team (no specific capability match)")

        if matched_sec:
            reasons.append(f"Specialized equipment bonus: {', '.join(matched_sec)}")

        reasons.append(f"Distance to scene: {dist_km:.1f} km")
        reasons.append(f"Status: AVAILABLE ({t.get('quantity_available', 1)} unit ready)")

        # Composite multi-factor score:
        # 1. Base bonus for having at least one critical capability match (+100)
        # 2. Mandatory capability matches (+35 per match)
        # 3. Specialized secondary equipment (+5 per match)
        # 4. Spatial distance penalty (-0.15 per km, so 100 km = -15 pts)
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

    # Sort descending by composite score
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


# ─────────────────────────────────────────────────────────────────────────────
# 5. POSTGIS SPATIAL QUERY (Production Implementation)
# ─────────────────────────────────────────────────────────────────────────────

_POSTGIS_RECOMMEND_SQL = """
SELECT r.resource_id,
       r.name,
       r.agency_id,
       a.name AS agency_name,
       r.status,
       r.quantity_available,
       r.capability_tags,
       ST_Distance(
           r.current_geom,
           ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
       ) / 1000.0 AS distance_km
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
    """Execute PostGIS spatial distance query against active TEAM resources."""
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
            "capability_tags": r["capability_tags"],
            "distance_km": float(r["distance_km"]),
        })
    return teams


# ─────────────────────────────────────────────────────────────────────────────
# 6. UNIFIED ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

def get_recommended_teams(
    latitude: float,
    longitude: float,
    scenario: str,
    limit: int = 5,
    conn: Any = None,
) -> list[RecommendedTeam]:
    """Rank AVAILABLE TEAM resources for an incident (advisory only: nothing is reserved).

    Ranks by capability match (primary) then distance in km (secondary). Returns an empty
    list when no team is available; there is deliberately no built-in fallback roster, so
    dispatchers are never shown teams that do not exist in the database.
    """
    if conn is not None:
        teams = fetch_available_teams_postgis(conn, latitude, longitude)
    else:
        with db.transaction() as auto_conn:
            teams = fetch_available_teams_postgis(auto_conn, latitude, longitude)
    return score_and_rank_teams(teams, latitude, longitude, scenario, limit=limit)
