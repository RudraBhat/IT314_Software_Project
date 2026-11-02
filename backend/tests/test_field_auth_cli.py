"""Unit tests for Phase 1: Field Operations schemas, authentication, and CLI tools.

Tests data contracts, field role authorization, team context resolution,
and responder account provisioning without requiring a live database.
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.auth import FieldPrincipal, Principal, require_field
from app.cli import create_field
from app.errors import ApiError
from app.schemas.field import (
    FieldAssignmentResponse,
    FieldCompletionRequest,
    FieldProfileResponse,
    FieldProgressRequest,
    FieldTeamRequest,
)
from app.schemas.recommendations import (
    CandidateTeam,
    TeamRecommendationResponse,
)


def _mock_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/field/me",
        "headers": [],
        "client": ("127.0.0.1", 54321),
    }
    return Request(scope)


# ── 1. Schema Validation Tests ──────────────────────────────────────────


def test_field_profile_schema_validation():
    user_id = uuid.uuid4()
    member_id = uuid.uuid4()
    team_id = uuid.uuid4()
    agency_id = uuid.uuid4()

    valid_data = {
        "user_id": user_id,
        "email": "field.unit1@drch.gov.in",
        "full_name": "Field Unit Alpha",
        "phone": "+919876543210",
        "role": "FIELD_TEAM",
        "callsign": "ALPHA-1",
        "is_leader": True,
        "member_id": member_id,
        "team_resource_id": team_id,
        "team_name": "SDRF Unit 1",
        "agency_id": agency_id,
        "agency_name": "State Disaster Response Force",
        "capabilities": {"boat": True, "rescue": True},
        "status": "AVAILABLE",
    }
    profile = FieldProfileResponse(**valid_data)
    assert profile.callsign == "ALPHA-1"
    assert profile.is_leader is True
    assert profile.capabilities["boat"] is True

    # Missing mandatory field should fail validation
    invalid_data = valid_data.copy()
    invalid_data.pop("team_resource_id")
    with pytest.raises(ValidationError):
        FieldProfileResponse(**invalid_data)


def test_field_assignment_schema_validation():
    now = datetime.now(UTC)
    assignment = FieldAssignmentResponse(
        dispatch_id=uuid.uuid4(),
        dispatch_ref="DISP-2026-0001",
        status="DISPATCHED",
        priority="HIGH",
        incident_id=uuid.uuid4(),
        incident_ref="INC-2026-0001",
        scenario="urban_flooding",
        district="Ahmedabad",
        latitude=23.0225,
        longitude=72.5714,
        instructions="Evacuate waterlogged society near riverfront.",
        dispatched_at=now,
    )
    assert assignment.dispatch_ref == "DISP-2026-0001"
    assert assignment.priority == "HIGH"
    assert assignment.latitude == 23.0225


def test_field_progress_schema_validation():
    # Valid progress update
    req = FieldProgressRequest(
        status="EN_ROUTE",
        note="Leaving staging base with rescue vehicles.",
        latitude=23.03,
        longitude=72.58,
    )
    assert req.status == "EN_ROUTE"

    # Out-of-bounds latitude should raise ValidationError
    with pytest.raises(ValidationError):
        FieldProgressRequest(status="ON_SCENE", latitude=95.0, longitude=72.0)

    # Invalid status literal should raise ValidationError
    with pytest.raises(ValidationError):
        FieldProgressRequest(status="INVALID_STATUS")


def test_field_team_request_schema_validation():
    req = FieldTeamRequest(
        required_capability="dewatering_pump",
        note="Water levels rising rapidly, need 2 high-capacity pumps.",
    )
    assert req.required_capability == "dewatering_pump"

    with pytest.raises(ValidationError):
        FieldTeamRequest(required_capability="x")  # min_length=2


def test_field_completion_request_schema():
    req = FieldCompletionRequest(
        summary="Evacuated 45 residents successfully to local municipal school.",
        civilians_evacuated=45,
        civilians_treated=3,
    )
    assert req.civilians_evacuated == 45

    # Short summary (< 5 chars) should fail
    with pytest.raises(ValidationError):
        FieldCompletionRequest(summary="done")


def test_team_recommendations_schema_validation():
    team = CandidateTeam(
        resource_id=uuid.uuid4(),
        team_name="NDRF Battalion 6 (Vadodara)",
        agency="National Disaster Response Force",
        distance_km=14.5,
        capability_match=["boat", "flood_rescue"],
        rank=1,
        reasons="Closest available specialized water rescue unit",
        status="AVAILABLE",
    )
    resp = TeamRecommendationResponse(
        incident_id=uuid.uuid4(),
        scenario="urban_flooding",
        requires_confirmation=True,
        recommendations=[team],
    )
    assert resp.requires_confirmation is True
    assert len(resp.recommendations) == 1
    assert resp.recommendations[0].rank == 1


# ── 2. Authorization & Team Context Tests ───────────────────────────────


def test_require_field_rejects_non_field_role(monkeypatch):
    monkeypatch.setattr("app.audit.record_standalone", MagicMock())
    req = _mock_request()
    staff_principal = Principal(
        user_id=uuid.uuid4(),
        email="staff@drch.gov.in",
        full_name="Staff Officer",
        role="DISASTER_MGMT",
        mfa_verified=True,
    )
    with pytest.raises(ApiError) as exc_info:
        require_field(req, staff_principal)
    assert exc_info.value.status == 403
    assert exc_info.value.code == "ROLE_REQUIRED"


def test_require_field_rejects_citizen_role(monkeypatch):
    monkeypatch.setattr("app.audit.record_standalone", MagicMock())
    req = _mock_request()
    citizen_principal = Principal(
        user_id=uuid.uuid4(),
        email="citizen@example.com",
        full_name="Citizen User",
        role="NORMAL_USER",
        mfa_verified=False,
    )
    with pytest.raises(ApiError) as exc_info:
        require_field(req, citizen_principal)
    assert exc_info.value.status == 403
    assert exc_info.value.code == "ROLE_REQUIRED"


def test_require_field_fallback_when_database_not_configured(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()

    req = _mock_request()
    field_principal = Principal(
        user_id=uuid.uuid4(),
        email="field1@drch.gov.in",
        full_name="Field Lead",
        role="FIELD_TEAM",
        mfa_verified=False,
    )

    try:
        fp = require_field(req, field_principal)
        assert isinstance(fp, FieldPrincipal)
        assert fp.role == "FIELD_TEAM"
        assert fp.team_name == "Demo Field Unit 1"
        assert fp.is_leader is True
    finally:
        get_settings.cache_clear()


def test_require_field_raises_when_no_team_membership(monkeypatch):
    from app import db
    from app.config import get_settings

    monkeypatch.setattr("app.audit.record_standalone", MagicMock())
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")
    get_settings.cache_clear()

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    @contextmanager
    def mock_tx():
        yield mock_conn

    monkeypatch.setattr(db, "transaction", mock_tx)

    req = _mock_request()
    field_principal = Principal(
        user_id=uuid.uuid4(),
        email="unassigned@drch.gov.in",
        full_name="Unassigned Responder",
        role="FIELD_TEAM",
        mfa_verified=False,
    )

    try:
        with pytest.raises(ApiError) as exc_info:
            require_field(req, field_principal)
        assert exc_info.value.status == 403
        assert exc_info.value.code == "NO_TEAM_ASSIGNED"
    finally:
        get_settings.cache_clear()


def test_require_field_resolves_team_membership_successfully(monkeypatch):
    from app import db
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    member_id = uuid.uuid4()
    team_resource_id = uuid.uuid4()
    agency_id = uuid.uuid4()

    mock_row = {
        "member_id": member_id,
        "team_resource_id": team_resource_id,
        "callsign": "BRAVO-2",
        "is_leader": False,
        "team_name": "Rapid Flood Rescue Team",
        "agency_id": agency_id,
        "agency_name": "Gujarat Fire & Emergency Services",
        "capability": {"boat": True, "swimmers": 6},
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    monkeypatch.setattr(db, "transaction", mock_tx)

    req = _mock_request()
    field_principal = Principal(
        user_id=user_id,
        email="responder@drch.gov.in",
        full_name="Team Responder",
        role="FIELD_TEAM",
        mfa_verified=False,
    )

    try:
        fp = require_field(req, field_principal)
        assert fp.member_id == member_id
        assert fp.team_resource_id == team_resource_id
        assert fp.team_name == "Rapid Flood Rescue Team"
        assert fp.callsign == "BRAVO-2"
        assert fp.is_leader is False
        assert fp.capabilities["swimmers"] == 6
    finally:
        get_settings.cache_clear()


# ── 3. CLI Account Provisioning Tests ────────────────────────────────────


def test_cli_create_field_fails_if_team_not_found(monkeypatch):
    from app import db

    mock_conn = MagicMock()
    # First check: email does not exist
    # Second check: team not found
    mock_conn.execute.return_value.fetchone.side_effect = [None, None]

    @contextmanager
    def mock_tx():
        yield mock_conn

    monkeypatch.setattr(db, "transaction", mock_tx)
    monkeypatch.setenv("DRCH_FIELD_PASSWORD", "SecurePass1234!")

    args = MagicMock()
    args.email = "responder@example.org"
    args.name = "Test Responder"
    args.team = "NonExistentTeam"
    args.callsign = "TEST-1"
    args.leader = False
    args.phone = "+919876543210"
    args.designation = "Field Officer"

    with pytest.raises(SystemExit) as exc_info:
        create_field(args)
    assert "not found in resources table" in str(exc_info.value)


def test_cli_create_field_provisions_account_successfully(monkeypatch, capsys):
    from app import db

    team_id = uuid.uuid4()
    mock_conn = MagicMock()
    # 1. email check -> None (not duplicate)
    # 2. team check -> valid team row
    # 3. users insert -> returning user_id
    mock_team_row = {"resource_id": team_id, "name": "Sabarmati Rescue Unit", "agency_id": uuid.uuid4()}
    user_id = uuid.uuid4()

    mock_conn.execute.return_value.fetchone.side_effect = [
        None,
        mock_team_row,
        {"user_id": user_id},
    ]

    @contextmanager
    def mock_tx():
        yield mock_conn

    monkeypatch.setattr(db, "transaction", mock_tx)
    monkeypatch.setenv("DRCH_FIELD_PASSWORD", "SecurePass1234!")

    args = MagicMock()
    args.email = "responder.new@example.org"
    args.name = "Arjun Patel"
    args.team = "Sabarmati"
    args.callsign = "SABAR-1"
    args.leader = True
    args.phone = "+919876543210"
    args.designation = "Team Lead"

    create_field(args)
    captured = capsys.readouterr()
    assert "Created Field Team account responder.new@example.org" in captured.out
    assert "Sabarmati Rescue Unit" in captured.out
    assert "[Callsign: SABAR-1]" in captured.out
    assert "(Team Leader)" in captured.out
