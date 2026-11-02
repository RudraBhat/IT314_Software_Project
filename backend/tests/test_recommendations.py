"""Comprehensive Unit Tests for S1-11 Team-Recommendation Engine."""

from app.services.recommendations import (
    get_recommended_teams,
    get_required_capabilities,
    score_and_rank_teams,
)


def test_scenario_rule_mapping():
    """Verify emergency scenario to capability rule mapping."""
    assert "boat" in get_required_capabilities("URBAN_FLOODING")
    assert "water_rescue" in get_required_capabilities("FLOOD")
    assert "fire" in get_required_capabilities("INDUSTRIAL_FIRE")
    assert "cyclone_response" in get_required_capabilities("CYCLONE")
    assert "search_and_rescue" in get_required_capabilities("EARTHQUAKE")


def test_seed_incidents_top_teams():
    """Verify top recommended response teams across Gujarat disaster scenarios."""
    # 1. Ahmedabad flood
    flood_recs = get_recommended_teams(23.0373, 72.5613, "URBAN_FLOODING", limit=3)
    assert len(flood_recs) == 3
    assert flood_recs[0].rank == 1
    assert "boat" in flood_recs[0].matched_capabilities or "flood_rescue" in flood_recs[0].matched_capabilities
    assert flood_recs[0].distance_km < 10.0  # Ahmedabad local team

    # 2. Surat Hazira fire
    fire_recs = get_recommended_teams(21.1025, 72.6841, "INDUSTRIAL_FIRE", limit=3)
    assert len(fire_recs) == 3
    assert fire_recs[0].distance_km < 1.0  # Hazira team is right there
    assert "fire" in fire_recs[0].matched_capabilities or "hazmat" in fire_recs[0].matched_capabilities

    # 3. Kutch cyclone
    cyclone_recs = get_recommended_teams(23.1139, 70.0278, "CYCLONE", limit=3)
    assert len(cyclone_recs) == 3
    assert "cyclone_response" in cyclone_recs[0].matched_capabilities

    # 4. Bhuj earthquake
    quake_recs = get_recommended_teams(23.2420, 69.6669, "EARTHQUAKE", limit=3)
    assert len(quake_recs) == 3
    assert quake_recs[0].distance_km < 1.0  # Local Bhuj team


def test_unavailable_and_zero_quantity_excluded():
    """Units with UNAVAILABLE or 0 available quantity must not be recommended."""
    test_teams = [
        {
            "resource_id": "r-unavail",
            "name": "Broken Boat Unit",
            "agency_id": "a-1",
            "agency_name": "Agency 1",
            "latitude": 23.0,
            "longitude": 72.5,
            "status": "UNAVAILABLE",
            "quantity_available": 1,
            "capability_tags": {"boat": True},
        },
        {
            "resource_id": "r-zero-qty",
            "name": "Depleted Boat Unit",
            "agency_id": "a-1",
            "agency_name": "Agency 1",
            "latitude": 23.0,
            "longitude": 72.5,
            "status": "AVAILABLE",
            "quantity_available": 0,
            "capability_tags": {"boat": True},
        },
        {
            "resource_id": "r-ready",
            "name": "Ready Boat Unit",
            "agency_id": "a-1",
            "agency_name": "Agency 1",
            "latitude": 23.0,
            "longitude": 72.5,
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capability_tags": {"boat": True},
        },
    ]

    recs = score_and_rank_teams(test_teams, 23.0, 72.5, "URBAN_FLOODING")
    ids = [r.resource_id for r in recs]
    assert "r-unavail" not in ids
    assert "r-zero-qty" not in ids
    assert "r-ready" in ids


def test_maintenance_status_excluded():
    """Units on MAINTENANCE status must be strictly excluded from dispatch ranking."""
    mock_units = [
        {
            "resource_id": "r-maint",
            "name": "Maintenance Fire Tender",
            "agency_id": "a-1",
            "agency_name": "AFES",
            "latitude": 23.0,
            "longitude": 72.5,
            "status": "MAINTENANCE",
            "quantity_available": 1,
            "capability_tags": {"fire": True},
        },
        {
            "resource_id": "r-avail",
            "name": "Active Fire Tender",
            "agency_id": "a-1",
            "agency_name": "AFES",
            "latitude": 23.0,
            "longitude": 72.5,
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capability_tags": {"fire": True},
        },
    ]
    ranked = score_and_rank_teams(mock_units, 23.0, 72.5, "INDUSTRIAL_FIRE")
    ids = [u.resource_id for u in ranked]
    assert "r-maint" not in ids
    assert "r-avail" in ids
