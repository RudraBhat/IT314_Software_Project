"""Comprehensive automated test suite for Spatial Team Recommendations and Decision Workflows.

Covers:
10. Spatial recommendation ranking closest capable team first for each scenario.
11. Strict exclusion of unavailable (DEPLOYED, MAINTENANCE, UNAVAILABLE) and depleted (qty <= 0) teams.
12. Approving a team request (generates dispatch draft) and declining (requires mandatory rationale).
13. Edge Case: Graceful fallback to district centroids from in-memory cache when point coordinates are null.
14. Safety Rule: Advisory recommendations strictly require dispatcher confirmation and never auto-dispatch.
"""

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.auth import Principal
from app.errors import ApiError
from app.geo import get_district_centroid
from app.routers.dm.recommendations import (
    decide_team_request,
    get_incident_team_recommendations,
)
from app.schemas.recommendations import (
    TeamRecommendationResponse,
    TeamRequestDecisionRequest,
    TeamRequestDecisionResponse,
)
from app.services.recommendations import (
    recommend_candidate_teams,
)


@pytest.fixture
def dispatcher_principal() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="dispatcher@drch.gujarat.gov.in",
        full_name="Senior Command Dispatcher",
        role="DISASTER_MGMT",
        mfa_verified=True,
        permissions=frozenset({"DISPATCH"}),
        ip="127.0.0.1",
    )


# ── 10. Scenario-Based Spatial Proximity Ranking ─────────────────────────


def test_spatial_recommendation_ranks_closest_capable_first():
    """10. Spatial recommendation ranks closest capable team first for each disaster scenario."""
    # Scenario: URBAN_FLOODING in Ahmedabad
    flood_recs = recommend_candidate_teams(
        latitude=23.0373,
        longitude=72.5613,
        scenario="URBAN_FLOODING",
        limit=3,
    )
    assert len(flood_recs) >= 1
    assert flood_recs[0].rank == 1
    assert any(c in flood_recs[0].capability_match for c in ("boat", "flood_rescue", "water_rescue"))
    assert flood_recs[0].distance_km < 15.0

    # Scenario: INDUSTRIAL_FIRE in Surat Hazira
    fire_recs = recommend_candidate_teams(
        latitude=21.1025,
        longitude=72.6841,
        scenario="INDUSTRIAL_FIRE",
        limit=3,
    )
    assert len(fire_recs) >= 1
    assert fire_recs[0].rank == 1
    assert any(c in fire_recs[0].capability_match for c in ("hazmat", "fire_tender", "chemical_foam", "fire"))
    assert fire_recs[0].distance_km < 10.0

    # Scenario: CYCLONE in Jamnagar / Coastal Saurashtra
    cyclone_recs = recommend_candidate_teams(
        latitude=22.4707,
        longitude=70.0577,
        scenario="CYCLONE",
        limit=3,
    )
    assert len(cyclone_recs) >= 1
    assert cyclone_recs[0].rank == 1
    assert any(
        c in cyclone_recs[0].capability_match
        for c in ("cyclone_response", "search_and_rescue", "debris_clearing", "high_wind_rescue")
    )

    # Scenario: EARTHQUAKE in Bhuj / Kutch
    quake_recs = recommend_candidate_teams(
        latitude=23.2420,
        longitude=69.6669,
        scenario="EARTHQUAKE",
        limit=3,
    )
    assert len(quake_recs) >= 1
    assert quake_recs[0].rank == 1
    assert any(
        c in quake_recs[0].capability_match
        for c in ("search_and_rescue", "collapse_rescue", "structural_shoring", "canine_unit")
    )


# ── 11. Strict Exclusion of Unavailable & Dispatched Teams ───────────────


def test_unavailable_or_dispatched_teams_strictly_excluded():
    """11. Unavailable, deployed, maintenance, or zero-reserve teams are strictly excluded."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "resource_id": uuid.uuid4(),
            "name": "Currently Deployed Team",
            "agency_id": uuid.uuid4(),
            "agency_name": "SDRF",
            "status": "DISPATCHED",
            "quantity_available": 1,
            "capabilities": {"boat": True},
            "distance_km": 2.5,
        },
        {
            "resource_id": uuid.uuid4(),
            "name": "Maintenance Boat Team",
            "agency_id": uuid.uuid4(),
            "agency_name": "SDRF",
            "status": "MAINTENANCE",
            "quantity_available": 1,
            "capabilities": {"boat": True},
            "distance_km": 1.2,
        },
        {
            "resource_id": uuid.uuid4(),
            "name": "Depleted Unit (Zero Reserve)",
            "agency_id": uuid.uuid4(),
            "agency_name": "NDRF",
            "status": "AVAILABLE",
            "quantity_available": 0,
            "capabilities": {"boat": True},
            "distance_km": 0.8,
        },
        {
            "resource_id": uuid.uuid4(),
            "name": "Operational Ready Team",
            "agency_id": uuid.uuid4(),
            "agency_name": "NDRF",
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capabilities": {"boat": True},
            "distance_km": 4.0,
        },
    ]

    recs = recommend_candidate_teams(
        latitude=23.0,
        longitude=72.5,
        scenario="URBAN_FLOODING",
        conn=mock_conn,
    )

    assert len(recs) == 1
    assert recs[0].team_name == "Operational Ready Team"
    assert recs[0].status == "AVAILABLE"


# ── 12. Team Request Decision: Approve & Decline Workflows ──────────────


def test_approving_team_request_transitions_status_and_drafts_dispatch(
    dispatcher_principal: Principal,
):
    """12a. Approving a team request transitions status and returns pre-filled dispatch draft."""
    request_id = uuid.uuid4()
    mock_row = {
        "request_id": request_id,
        "dispatch_id": uuid.uuid4(),
        "dispatch_ref": "DISP-2026-000456",
        "incident_id": uuid.uuid4(),
        "incident_ref": "INC-2026-000789",
        "scenario": "URBAN_FLOODING",
        "priority": "P1",
        "latitude": 23.02,
        "longitude": 72.57,
        "requested_by": uuid.uuid4(),
        "required_capability": "boat",
        "status": "OPEN",
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.audit.record") as mock_audit,
        patch("app.routers.dm.recommendations.notify") as mock_notify,
    ):
        body = TeamRequestDecisionRequest(
            action="APPROVE",
            rationale="Approved immediate watercraft reinforcement",
        )
        res = decide_team_request(
            request_id=request_id,
            body=body,
            principal=dispatcher_principal,
        )

    assert isinstance(res, TeamRequestDecisionResponse)
    assert res.status == "APPROVED"
    assert res.decision_rationale == body.rationale
    assert res.dispatch_draft is not None
    assert res.dispatch_draft["required_capability"] == "boat"
    assert "Reinforce DISP-2026-000456" in res.dispatch_draft["instructions"]
    mock_audit.assert_called_once()
    mock_notify.assert_called_once()


def test_declining_team_request_requires_mandatory_rationale(
    dispatcher_principal: Principal,
):
    """12b. Declining a team request strictly requires an operational rationale."""
    request_id = uuid.uuid4()
    mock_row = {
        "request_id": request_id,
        "dispatch_id": uuid.uuid4(),
        "dispatch_ref": "DISP-2026-000456",
        "incident_id": uuid.uuid4(),
        "incident_ref": "INC-2026-000789",
        "scenario": "URBAN_FLOODING",
        "priority": "P1",
        "latitude": 23.02,
        "longitude": 72.57,
        "requested_by": uuid.uuid4(),
        "required_capability": "boat",
        "status": "OPEN",
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        # Empty rationale must raise 422
        body_empty = TeamRequestDecisionRequest(action="DECLINE", rationale="   ")
        with pytest.raises(ApiError) as exc_info:
            decide_team_request(request_id=request_id, body=body_empty, principal=dispatcher_principal)
        assert exc_info.value.status == 422
        assert exc_info.value.code == "RATIONALE_REQUIRED"


# ── 13. Edge Case: Fallback to District Centroid ─────────────────────────


def test_district_centroid_fallback_when_coordinates_null(
    dispatcher_principal: Principal,
):
    """13. If an incident lacks point coordinates, fallback to district centroid from app.geo."""
    # Verify in-memory centroid resolution
    surat_centroid = get_district_centroid("Surat")
    assert surat_centroid is not None
    assert round(surat_centroid[0], 1) == 21.2
    assert round(surat_centroid[1], 1) == 72.8

    incident_id = uuid.uuid4()
    # Incident has null point coordinates but known district
    mock_incident_without_point = {
        "incident_id": incident_id,
        "incident_ref": "INC-2026-000999",
        "scenario": "INDUSTRIAL_FIRE",
        "status": "VERIFIED",
        "district": "Surat",
        "latitude": None,
        "longitude": None,
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_incident_without_point
    mock_conn.execute.return_value.fetchall.return_value = []

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        res = get_incident_team_recommendations(
            incident_id=incident_id,
            principal=dispatcher_principal,
        )

    assert isinstance(res, TeamRecommendationResponse)
    assert res.incident_id == incident_id
    assert res.requires_confirmation is True
    # Successfully ranked teams around Surat centroid
    assert len(res.recommendations) > 0
    assert res.recommendations[0].agency is not None


# ── 14. Safety Rule: Advisory Never Auto-Dispatches ──────────────────────


def test_advisory_recommendation_never_creates_dispatch(
    dispatcher_principal: Principal,
):
    """14. Advisory recommendations must set requires_confirmation: True and not create dispatches."""
    incident_id = uuid.uuid4()
    mock_incident = {
        "incident_id": incident_id,
        "incident_ref": "INC-2026-000888",
        "scenario": "CYCLONE",
        "status": "VERIFIED",
        "district": "Jamnagar",
        "latitude": 22.47,
        "longitude": 70.05,
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_incident
    mock_conn.execute.return_value.fetchall.return_value = []

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.services.dispatch.apply_acknowledgement") as mock_ack,
    ):
        res = get_incident_team_recommendations(
            incident_id=incident_id,
            principal=dispatcher_principal,
        )

    # Strictly advisory: flag is True, no side effects
    assert res.requires_confirmation is True
    mock_ack.assert_not_called()
