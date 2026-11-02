"""Unit and integration tests for Phase 4: Spatial Team Recommendations and Dispatcher Decisions.

Tests scenario-to-capability rule mapping, PostGIS spatial distance ranking,
multi-factor score formula: Score = (Overlap * 10) - (Distance * 0.05),
strictly advisory incident recommendation endpoints (requires_confirmation: True),
and field team backup request triage workflows (approve with dispatch draft, decline with mandatory rationale, conflict handling).
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.auth import Principal
from app.errors import ApiError
from app.routers.dm.recommendations import (
    decide_team_request,
    get_incident_team_recommendations,
    list_team_requests,
)
from app.schemas.recommendations import (
    TeamRecommendationResponse,
    TeamRequestDecisionRequest,
    TeamRequestDecisionResponse,
    TeamRequestItem,
)
from app.services.recommendations import (
    get_required_capabilities,
    normalize_scenario,
    recommend_candidate_teams,
)
from main import app as main_app

# ── Test Fixtures & Actors ──────────────────────────────────────────────


@pytest.fixture
def dispatcher_principal() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="dispatcher.lead@drch.gov.in",
        full_name="Dispatcher Senior Officer",
        role="DISASTER_MGMT",
        mfa_verified=True,
        permissions=frozenset({"DISPATCH", "SUPERVISOR"}),
        ip="127.0.0.1",
    )


@pytest.fixture
def non_dispatcher_principal() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="staff.analyst@drch.gov.in",
        full_name="Staff Data Analyst",
        role="DISASTER_MGMT",
        mfa_verified=True,
        permissions=frozenset({"VIEWER"}),
        ip="127.0.0.1",
    )


# ── 0. Route Registration in Main App ───────────────────────────────────


def test_recommendations_and_team_request_routes_registered():
    """Verify Phase 4 DM routes are mounted under /api/v1/dm in OpenAPI schema."""
    paths = main_app.openapi()["paths"]
    assert "/api/v1/dm/incidents/{incident_id}/team-recommendations" in paths
    assert "/api/v1/dm/team-requests" in paths
    assert "/api/v1/dm/team-requests/{request_id}/decision" in paths


# ── 1. Scenario-to-Capability Rule Matrix Tests ─────────────────────────


def test_scenario_to_capability_matrix():
    """Verify disaster scenarios map to the required capabilities."""
    # 1. Urban Flooding
    urban_flood_caps = get_required_capabilities("urban_flooding")
    assert "boat" in urban_flood_caps
    assert "flood_rescue" in urban_flood_caps
    assert "water_rescue" in urban_flood_caps
    assert "dewatering_pump" in urban_flood_caps

    # 2. Cyclone
    cyclone_caps = get_required_capabilities("cyclone")
    assert "debris_clearing" in cyclone_caps
    assert "shelter_management" in cyclone_caps
    assert "high_wind_rescue" in cyclone_caps
    assert "medical_first_aid" in cyclone_caps

    # 3. Industrial Fire
    fire_caps = get_required_capabilities("industrial_fire")
    assert "hazmat" in fire_caps
    assert "fire_tender" in fire_caps
    assert "chemical_foam" in fire_caps
    assert "breathing_apparatus" in fire_caps

    # 4. Earthquake
    quake_caps = get_required_capabilities("earthquake")
    assert "search_and_rescue" in quake_caps
    assert "collapse_rescue" in quake_caps
    assert "structural_shoring" in quake_caps
    assert "canine_unit" in quake_caps
    assert "trauma_care" in quake_caps


def test_scenario_normalization():
    """Verify scenario aliases normalize properly."""
    assert normalize_scenario("urban_flooding") == "URBAN_FLOODING"
    assert normalize_scenario("flood") == "URBAN_FLOODING"
    assert normalize_scenario("industrial_fire") == "INDUSTRIAL_FIRE"
    assert normalize_scenario("chemical_fire") == "INDUSTRIAL_FIRE"
    assert normalize_scenario("cyclone") == "CYCLONE"
    assert normalize_scenario("earthquake") == "EARTHQUAKE"


# ── 2. Spatial PostGIS Ranking Engine & Scoring Formula ─────────────────


def test_scoring_formula_and_ranking():
    """Verify ranking adheres to Score = (Overlap * 10) - (Distance * 0.05)."""
    team_a_id = uuid.uuid4()
    team_b_id = uuid.uuid4()
    team_c_id = uuid.uuid4()

    mock_db_teams = [
        {
            # Overlap: 2 (boat, flood_rescue), Dist: 10 km -> Score = 20 - 0.5 = 19.5
            "resource_id": team_a_id,
            "name": "Team A - Specialized Rescue",
            "agency_id": uuid.uuid4(),
            "agency_name": "SDRF",
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capabilities": {"boat": True, "flood_rescue": True},
            "distance_km": 10.0,
        },
        {
            # Overlap: 3 (boat, flood_rescue, water_rescue), Dist: 50 km -> Score = 30 - 2.5 = 27.5
            "resource_id": team_b_id,
            "name": "Team B - High Capability",
            "agency_id": uuid.uuid4(),
            "agency_name": "NDRF",
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capabilities": {"boat": True, "flood_rescue": True, "water_rescue": True},
            "distance_km": 50.0,
        },
        {
            # Overlap: 0, Dist: 2 km -> Score = 0 - 0.1 = -0.1
            "resource_id": team_c_id,
            "name": "Team C - Nearby General Unit",
            "agency_id": uuid.uuid4(),
            "agency_name": "Civil Defense",
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capabilities": {"general_patrol": True},
            "distance_km": 2.0,
        },
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "resource_id": t["resource_id"],
            "name": t["name"],
            "agency_id": t["agency_id"],
            "agency_name": t["agency_name"],
            "status": t["status"],
            "quantity_available": t["quantity_available"],
            "capabilities": t["capabilities"],
            "distance_km": t["distance_km"],
        }
        for t in mock_db_teams
    ]

    ranked = recommend_candidate_teams(
        latitude=23.0,
        longitude=72.5,
        scenario="URBAN_FLOODING",
        limit=5,
        conn=mock_conn,
    )

    assert len(ranked) == 3
    # Team B has highest score (27.5) -> Rank 1
    assert ranked[0].resource_id == team_b_id
    assert ranked[0].rank == 1
    assert "Partial capability match" in ranked[0].reasons or "Exact capability match" in ranked[0].reasons
    assert ranked[0].distance_km == 50.0

    # Team A has second highest score (19.5) -> Rank 2
    assert ranked[1].resource_id == team_a_id
    assert ranked[1].rank == 2

    # Team C has lowest score (-0.1) -> Rank 3
    assert ranked[2].resource_id == team_c_id
    assert ranked[2].rank == 3
    assert "Available proximity reserve team" in ranked[2].reasons


def test_unavailable_and_depleted_teams_excluded():
    """Teams with status != AVAILABLE or quantity_available <= 0 must be excluded."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "resource_id": uuid.uuid4(),
            "name": "Engaged Team",
            "agency_id": uuid.uuid4(),
            "agency_name": "NDRF",
            "status": "DEPLOYED",
            "quantity_available": 1,
            "capabilities": {"boat": True},
            "distance_km": 3.0,
        },
        {
            "resource_id": uuid.uuid4(),
            "name": "Depleted Team",
            "agency_id": uuid.uuid4(),
            "agency_name": "NDRF",
            "status": "AVAILABLE",
            "quantity_available": 0,
            "capabilities": {"boat": True},
            "distance_km": 4.0,
        },
        {
            "resource_id": uuid.uuid4(),
            "name": "Available Team",
            "agency_id": uuid.uuid4(),
            "agency_name": "NDRF",
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capabilities": {"boat": True},
            "distance_km": 5.0,
        },
    ]

    ranked = recommend_candidate_teams(
        latitude=23.0,
        longitude=72.5,
        scenario="URBAN_FLOODING",
        conn=mock_conn,
    )

    assert len(ranked) == 1
    assert ranked[0].team_name == "Available Team"


# ── 3. Advisory Recommendation Endpoint Tests ───────────────────────────


def test_get_incident_team_recommendations_advisory(dispatcher_principal: Principal):
    incident_id = uuid.uuid4()
    mock_incident = {
        "incident_id": incident_id,
        "incident_ref": "INC-2026-009111",
        "scenario": "URBAN_FLOODING",
        "status": "VERIFIED",
        "latitude": 23.0225,
        "longitude": 72.5714,
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_incident
    mock_conn.execute.return_value.fetchall.return_value = []

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        res = get_incident_team_recommendations(
            incident_id=incident_id,
            principal=dispatcher_principal,
            limit=3,
        )

    assert isinstance(res, TeamRecommendationResponse)
    assert res.incident_id == incident_id
    assert res.scenario == "URBAN_FLOODING"
    # Safety rule: MUST require dispatcher confirmation
    assert res.requires_confirmation is True
    assert len(res.recommendations) <= 3


def test_get_incident_team_recommendations_not_found(dispatcher_principal: Principal):
    incident_id = uuid.uuid4()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx), pytest.raises(ApiError) as exc_info:
        get_incident_team_recommendations(
            incident_id=incident_id,
            principal=dispatcher_principal,
        )
    assert exc_info.value.status == 404
    assert exc_info.value.code == "NOT_FOUND"


# ── 4. Team-Request Decisions API Tests ──────────────────────────────────


def test_list_team_requests_open(dispatcher_principal: Principal):
    mock_items = [
        {
            "request_id": uuid.uuid4(),
            "dispatch_id": uuid.uuid4(),
            "dispatch_ref": "DISP-2026-000101",
            "incident_id": uuid.uuid4(),
            "incident_ref": "INC-2026-000888",
            "requested_by": uuid.uuid4(),
            "requested_by_name": "Field Leader 1",
            "team_name": "SDRF Unit 1",
            "required_capability": "boat",
            "note": "Water levels rising above ground floor",
            "status": "OPEN",
            "decision_rationale": None,
            "decided_by_name": None,
            "decided_at": None,
            "created_at": datetime.now(UTC),
        }
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_items

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        items = list_team_requests(principal=dispatcher_principal, status="OPEN")

    assert len(items) == 1
    assert isinstance(items[0], TeamRequestItem)
    assert items[0].required_capability == "boat"
    assert items[0].status == "OPEN"


def test_decide_team_request_approve_with_dispatch_draft(
    dispatcher_principal: Principal,
):
    request_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    target_team_id = uuid.uuid4()

    mock_req_row = {
        "request_id": request_id,
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000101",
        "incident_id": incident_id,
        "incident_ref": "INC-2026-000888",
        "scenario": "URBAN_FLOODING",
        "priority": "P1",
        "latitude": 23.02,
        "longitude": 72.57,
        "requested_by": uuid.uuid4(),
        "required_capability": "medical_first_aid",
        "status": "OPEN",
    }

    mock_resource = {
        "resource_id": target_team_id,
        "name": "108 ALS Disaster Ambulance Alpha",
        "agency_id": uuid.uuid4(),
        "capabilities": {"medical_first_aid": True},
    }

    mock_conn = MagicMock()
    # 1. Fetch team_request row, 2. Fetch target resource
    mock_conn.execute.return_value.fetchone.side_effect = [
        mock_req_row,
        mock_resource,
    ]

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
            rationale="Approved deployment of ALS ambulance unit for patient care",
            target_resource_id=target_team_id,
        )
        res = decide_team_request(
            request_id=request_id,
            body=body,
            principal=dispatcher_principal,
        )

    assert isinstance(res, TeamRequestDecisionResponse)
    assert res.request_id == request_id
    assert res.status == "APPROVED"
    assert res.decision_rationale == body.rationale
    assert res.dispatch_draft is not None
    assert res.dispatch_draft["incident_id"] == str(incident_id)
    assert res.dispatch_draft["required_capability"] == "medical_first_aid"
    assert res.dispatch_draft["suggested_resource_id"] == str(target_team_id)
    mock_audit.assert_called_once()
    mock_notify.assert_called_once()


def test_decide_team_request_decline_requires_rationale(
    dispatcher_principal: Principal,
):
    request_id = uuid.uuid4()
    mock_req_row = {
        "request_id": request_id,
        "dispatch_id": uuid.uuid4(),
        "dispatch_ref": "DISP-2026-000101",
        "incident_id": uuid.uuid4(),
        "incident_ref": "INC-2026-000888",
        "scenario": "URBAN_FLOODING",
        "priority": "P1",
        "latitude": 23.02,
        "longitude": 72.57,
        "requested_by": uuid.uuid4(),
        "required_capability": "boat",
        "status": "OPEN",
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_req_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        # Empty rationale must fail with 422
        body = TeamRequestDecisionRequest(action="DECLINE", rationale="")
        with pytest.raises(ApiError) as exc_info:
            decide_team_request(request_id=request_id, body=body, principal=dispatcher_principal)
        assert exc_info.value.status == 422
        assert exc_info.value.code == "RATIONALE_REQUIRED"


def test_decide_team_request_decline_success(dispatcher_principal: Principal):
    request_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()
    mock_req_row = {
        "request_id": request_id,
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000101",
        "incident_id": uuid.uuid4(),
        "incident_ref": "INC-2026-000888",
        "scenario": "URBAN_FLOODING",
        "priority": "P1",
        "latitude": 23.02,
        "longitude": 72.57,
        "requested_by": uuid.uuid4(),
        "required_capability": "hazmat",
        "status": "OPEN",
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_req_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.audit.record") as mock_audit,
        patch("app.routers.dm.recommendations.notify") as mock_notify,
    ):
        body = TeamRequestDecisionRequest(
            action="DECLINE",
            rationale="No chemical hazards detected at site; existing units sufficient",
        )
        res = decide_team_request(
            request_id=request_id,
            body=body,
            principal=dispatcher_principal,
        )

    assert res.status == "DECLINED"
    assert res.decision_rationale == body.rationale
    assert res.dispatch_draft is None
    mock_audit.assert_called_once()
    mock_notify.assert_called_once()


def test_decide_team_request_conflict_if_already_decided(
    dispatcher_principal: Principal,
):
    request_id = uuid.uuid4()
    mock_req_row = {
        "request_id": request_id,
        "status": "APPROVED",  # Already decided!
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_req_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        body = TeamRequestDecisionRequest(action="APPROVE")
        with pytest.raises(ApiError) as exc_info:
            decide_team_request(request_id=request_id, body=body, principal=dispatcher_principal)
        assert exc_info.value.status == 409
        assert exc_info.value.code == "TEAM_REQUEST_ALREADY_DECIDED"


def test_team_request_decision_requires_valid_action():
    with pytest.raises(ValidationError):
        TeamRequestDecisionRequest(action="INVALID_ACTION")


def test_decide_team_request_approve_autosuggests_by_required_capability(
    dispatcher_principal: Principal,
):
    """Auto-suggesting a backup team matches required_capability, not just incident scenario."""
    request_id = uuid.uuid4()
    # Scenario is flood, but field requested a specialized hazmat unit
    mock_req_row = {
        "request_id": request_id,
        "dispatch_id": uuid.uuid4(),
        "dispatch_ref": "DISP-2026-000999",
        "incident_id": uuid.uuid4(),
        "incident_ref": "INC-2026-000999",
        "scenario": "URBAN_FLOODING",
        "priority": "HIGH",
        "latitude": 21.15,
        "longitude": 72.75,
        "district": "Surat",
        "requested_by": uuid.uuid4(),
        "required_capability": "hazmat",
        "status": "OPEN",
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_req_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.audit.record"),
        patch("app.routers.dm.recommendations.notify"),
    ):
        body = TeamRequestDecisionRequest(
            action="APPROVE",
            rationale="Approved hazmat reinforcement",
        )
        res = decide_team_request(
            request_id=request_id,
            body=body,
            principal=dispatcher_principal,
        )

    assert res.status == "APPROVED"
    assert res.dispatch_draft is not None
    assert res.dispatch_draft["required_capability"] == "hazmat"
    # Should suggest the Hazmat team from seed fallback teams, NOT a boat team
    assert "Hazmat" in res.dispatch_draft["suggested_resource_name"] or "Chemical" in res.dispatch_draft["suggested_resource_name"]


def test_decide_team_request_approve_mismatched_capability_raises_422(
    dispatcher_principal: Principal,
):
    """Explicitly selecting a resource lacking the requested capability raises 422."""
    request_id = uuid.uuid4()
    target_team_id = uuid.uuid4()
    mock_req_row = {
        "request_id": request_id,
        "dispatch_id": uuid.uuid4(),
        "dispatch_ref": "DISP-2026-000555",
        "incident_id": uuid.uuid4(),
        "incident_ref": "INC-2026-000555",
        "scenario": "URBAN_FLOODING",
        "priority": "HIGH",
        "latitude": 23.02,
        "longitude": 72.57,
        "requested_by": uuid.uuid4(),
        "required_capability": "hazmat",
        "status": "OPEN",
    }

    # Selected resource only has boat capabilities, lacking hazmat
    mock_resource = {
        "resource_id": target_team_id,
        "name": "NDRF Boat Squad",
        "agency_id": uuid.uuid4(),
        "capabilities": {"boat": True, "water_rescue": True},
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.side_effect = [
        mock_req_row,
        mock_resource,
    ]

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        body = TeamRequestDecisionRequest(
            action="APPROVE",
            target_resource_id=target_team_id,
            rationale="Attempting to assign boat squad for hazmat leak",
        )
        with pytest.raises(ApiError) as exc_info:
            decide_team_request(request_id=request_id, body=body, principal=dispatcher_principal)

        assert exc_info.value.status == 422
        assert exc_info.value.code == "CAPABILITY_MISMATCH"


def test_decide_team_request_approve_nonexistent_resource_raises_404(
    dispatcher_principal: Principal,
):
    """Explicitly selecting a non-existent resource raises 404 Not Found."""
    request_id = uuid.uuid4()
    missing_team_id = uuid.uuid4()
    mock_req_row = {
        "request_id": request_id,
        "dispatch_id": uuid.uuid4(),
        "dispatch_ref": "DISP-2026-000777",
        "incident_id": uuid.uuid4(),
        "incident_ref": "INC-2026-000777",
        "scenario": "URBAN_FLOODING",
        "priority": "HIGH",
        "latitude": 23.02,
        "longitude": 72.57,
        "requested_by": uuid.uuid4(),
        "required_capability": "boat",
        "status": "OPEN",
    }

    mock_conn = MagicMock()
    # 1. Fetch team_request row, 2. Fetch resource returns None
    mock_conn.execute.return_value.fetchone.side_effect = [
        mock_req_row,
        None,
    ]

    @contextmanager
    def mock_tx():
        yield mock_conn

    with patch("app.db.transaction", mock_tx):
        body = TeamRequestDecisionRequest(
            action="APPROVE",
            target_resource_id=missing_team_id,
            rationale="Assign non-existent resource",
        )
        with pytest.raises(ApiError) as exc_info:
            decide_team_request(request_id=request_id, body=body, principal=dispatcher_principal)

        assert exc_info.value.status == 404
        assert exc_info.value.code == "NOT_FOUND"

