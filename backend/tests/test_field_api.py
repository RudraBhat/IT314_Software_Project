"""Unit and integration tests for Phase 3: Field Operations REST API.

Tests route registration, responder profile retrieval, mission assignment listing,
tactical operational transitions (acknowledgement, rejection, progress reporting,
reinforcement requests, mission completion), strict cross-team isolation (404),
and lifecycle state conflict handling.
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.auth import FieldPrincipal
from app.errors import ApiError
from app.routers.field import (
    _get_verified_team_dispatch,
    field_acknowledge_dispatch,
    field_complete_dispatch,
    field_reject_dispatch,
    field_report_progress,
    field_request_team,
    get_field_assignments,
    get_field_profile,
)
from app.schemas.field import (
    FieldAcknowledgementResponse,
    FieldAssignmentResponse,
    FieldCompletionRequest,
    FieldProfileResponse,
    FieldProgressRequest,
    FieldProgressResponse,
    FieldRejectionRequest,
    FieldTeamRequest,
    FieldTeamRequestResponse,
)
from main import app as main_app

# ── Test Fixtures & Factories ──────────────────────────────────────────


@pytest.fixture
def responder_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def responder_team_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def responder_agency_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def field_principal(
    responder_user_id: uuid.UUID,
    responder_team_id: uuid.UUID,
    responder_agency_id: uuid.UUID,
) -> FieldPrincipal:
    return FieldPrincipal(
        user_id=responder_user_id,
        email="unit1.lead@sdrf.gov.in",
        full_name="Team Leader Alpha",
        role="FIELD_TEAM",
        member_id=uuid.uuid4(),
        team_resource_id=responder_team_id,
        team_name="SDRF Quick Response 1",
        agency_id=responder_agency_id,
        agency_name="State Disaster Response Force",
        callsign="QR1-LEAD",
        is_leader=True,
        capabilities={"boat": True, "water_rescue": True},
        ip="127.0.0.1",
    )


# ── 0. Route Registration in Main App ───────────────────────────────────


def test_field_router_is_mounted_in_main_app():
    """Verify field operations routes are mounted under /api/v1/field in OpenAPI schema."""
    paths = main_app.openapi()["paths"]
    assert "/api/v1/field/me" in paths
    assert "/api/v1/field/assignments" in paths
    assert "/api/v1/field/dispatches/{dispatch_id}/acknowledgement" in paths
    assert "/api/v1/field/dispatches/{dispatch_id}/rejection" in paths
    assert "/api/v1/field/dispatches/{dispatch_id}/progress" in paths
    assert "/api/v1/field/dispatches/{dispatch_id}/team-requests" in paths
    assert "/api/v1/field/dispatches/{dispatch_id}/completion" in paths


# ── 1. Profile Endpoint Tests ───────────────────────────────────────────


def test_get_field_profile_from_db(field_principal: FieldPrincipal):
    mock_row = {
        "user_id": field_principal.user_id,
        "email": field_principal.email,
        "full_name": field_principal.full_name,
        "phone": "+919876543210",
        "role": "FIELD_TEAM",
        "member_id": field_principal.member_id,
        "callsign": field_principal.callsign,
        "is_leader": True,
        "team_resource_id": field_principal.team_resource_id,
        "team_name": field_principal.team_name,
        "status": "AVAILABLE",
        "capability": {"boat": True, "water_rescue": True},
        "agency_id": field_principal.agency_id,
        "agency_name": field_principal.agency_name,
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.get_settings") as mock_settings,
    ):
        mock_settings.return_value.database_url = "postgresql://mock:5432/db"
        profile = get_field_profile(field_principal)

    assert isinstance(profile, FieldProfileResponse)
    assert profile.user_id == field_principal.user_id
    assert profile.callsign == "QR1-LEAD"
    assert profile.is_leader is True
    assert profile.team_name == "SDRF Quick Response 1"
    assert profile.capabilities == {"boat": True, "water_rescue": True}


def test_get_field_profile_fallback_when_db_not_configured(field_principal: FieldPrincipal):
    with patch("app.routers.field.get_settings") as mock_settings:
        mock_settings.return_value.database_url = ""
        profile = get_field_profile(field_principal)

    assert isinstance(profile, FieldProfileResponse)
    assert profile.user_id == field_principal.user_id
    assert profile.callsign == "QR1-LEAD"
    assert profile.status == "AVAILABLE"


# ── 2. Mission Assignment Listing Tests ─────────────────────────────────


def test_get_field_assignments_active_and_all(
    field_principal: FieldPrincipal,
    responder_team_id: uuid.UUID,
):
    dispatch_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    mock_assignments = [
        {
            "dispatch_id": dispatch_id,
            "dispatch_ref": "DISP-2026-000101",
            "status": "REQUESTED",
            "priority": "P1",
            "incident_id": incident_id,
            "incident_ref": "INC-2026-000888",
            "scenario": "flood",
            "district": "Ahmedabad",
            "address_text": "Vasna Barrage road",
            "landmark": "Near toll plaza",
            "latitude": 23.01,
            "longitude": 72.58,
            "instructions": "Deploy 2 inflatable rescue boats immediately.",
            "dispatched_at": datetime.now(UTC),
            "acknowledged_at": None,
            "overdue": False,
        }
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_assignments

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.get_settings") as mock_settings,
    ):
        mock_settings.return_value.database_url = "postgresql://mock:5432/db"
        mock_settings.return_value.dispatch_ack_timeout_minutes = 15

        assignments = get_field_assignments(field_principal, active=True)

    assert len(assignments) == 1
    assert isinstance(assignments[0], FieldAssignmentResponse)
    assert assignments[0].dispatch_ref == "DISP-2026-000101"
    assert assignments[0].status == "REQUESTED"
    assert assignments[0].scenario == "flood"
    assert assignments[0].latitude == 23.01


# ── 3. Operational State Transitions ────────────────────────────────────


def test_field_acknowledge_dispatch_success(
    field_principal: FieldPrincipal,
    responder_team_id: uuid.UUID,
):
    dispatch_id = uuid.uuid4()
    mock_dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000102",
        "status": "REQUESTED",
        "incident_id": uuid.uuid4(),
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_dispatch

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.apply_acknowledgement") as mock_ack,
    ):
        mock_ack.return_value = {
            "dispatch_id": dispatch_id,
            "dispatch_ref": "DISP-2026-000102",
            "status": "ACKNOWLEDGED",
        }

        res = field_acknowledge_dispatch(dispatch_id, field_principal)

    assert isinstance(res, FieldAcknowledgementResponse)
    assert res.status == "ACKNOWLEDGED"
    assert res.dispatch_ref == "DISP-2026-000102"
    mock_ack.assert_called_once()


def test_field_reject_dispatch_success(
    field_principal: FieldPrincipal,
    responder_team_id: uuid.UUID,
):
    dispatch_id = uuid.uuid4()
    mock_dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000103",
        "status": "REQUESTED",
        "incident_id": uuid.uuid4(),
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_dispatch

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.apply_rejection") as mock_rej,
    ):
        mock_rej.return_value = {
            "dispatch_id": dispatch_id,
            "dispatch_ref": "DISP-2026-000103",
            "status": "REJECTED",
        }

        body = FieldRejectionRequest(reason="Rescue boat trailer axle breakdown during transit")
        res = field_reject_dispatch(dispatch_id, body, field_principal)

    assert res["status"] == "REJECTED"
    assert res["dispatch_ref"] == "DISP-2026-000103"
    mock_rej.assert_called_once()


def test_field_report_progress_en_route(
    field_principal: FieldPrincipal,
    responder_team_id: uuid.UUID,
):
    dispatch_id = uuid.uuid4()
    mock_dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000104",
        "status": "ACKNOWLEDGED",
        "incident_id": uuid.uuid4(),
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_dispatch

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.apply_progress") as mock_prog,
    ):
        mock_prog.return_value = {
            "dispatch_id": dispatch_id,
            "dispatch_ref": "DISP-2026-000104",
            "status": "DISPATCHED",
            "progress_id": uuid.uuid4(),
        }

        body = FieldProgressRequest(
            status="EN_ROUTE",
            note="Convoy moving through SG Highway, ETA 12 minutes",
            latitude=23.03,
            longitude=72.52,
        )
        res = field_report_progress(dispatch_id, body, field_principal)

    assert isinstance(res, FieldProgressResponse)
    assert res.status == "EN_ROUTE"
    assert res.dispatch_id == dispatch_id
    assert res.note == body.note
    mock_prog.assert_called_once()


def test_field_request_backup_team_success(
    field_principal: FieldPrincipal,
    responder_team_id: uuid.UUID,
):
    dispatch_id = uuid.uuid4()
    request_id = uuid.uuid4()
    mock_dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000105",
        "status": "DISPATCHED",
        "incident_id": uuid.uuid4(),
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.side_effect = [
        mock_dispatch,
        {"request_id": request_id, "created_at": datetime.now(UTC)},
    ]
    mock_conn.execute.return_value.fetchall.return_value = [
        {"user_id": uuid.uuid4()}
    ]

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.audit.record") as mock_audit,
        patch("app.routers.field.notify") as mock_notify,
    ):
        body = FieldTeamRequest(
            required_capability="medical_first_aid",
            note="Multiple casualties rescued with severe hypothermia; need on-site medical triaging",
        )
        res = field_request_team(dispatch_id, body, field_principal)

    assert isinstance(res, FieldTeamRequestResponse)
    assert res.request_id == request_id
    assert res.required_capability == "medical_first_aid"
    assert res.status == "OPEN"
    mock_audit.assert_called_once()
    mock_notify.assert_called_once()


def test_field_complete_dispatch_success(
    field_principal: FieldPrincipal,
    responder_team_id: uuid.UUID,
):
    dispatch_id = uuid.uuid4()
    mock_dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000106",
        "status": "DISPATCHED",
        "incident_id": uuid.uuid4(),
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_dispatch

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.apply_completion") as mock_comp,
    ):
        mock_comp.return_value = {
            "dispatch_id": dispatch_id,
            "dispatch_ref": "DISP-2026-000106",
            "status": "COMPLETED",
        }

        body = FieldCompletionRequest(
            summary="Evacuated all stranded citizens from residential sector 4. Handed over to relief shelter.",
            civilians_evacuated=42,
            civilians_treated=6,
        )
        res = field_complete_dispatch(dispatch_id, body, field_principal)

    assert res["status"] == "COMPLETED"
    assert res["dispatch_ref"] == "DISP-2026-000106"
    assert res["civilians_evacuated"] == 42
    assert res["civilians_treated"] == 6
    mock_comp.assert_called_once()


# ── 4. Strict Cross-Team Isolation (Security Rule) ──────────────────────


def test_cross_team_dispatch_access_returns_404_not_found(
    field_principal: FieldPrincipal,
):
    """When a responder attempts to access or mutate a dispatch belonging to another team,

    the query returns None and the helper raises ApiError with 404 DISPATCH_NOT_FOUND.
    This eliminates data discovery and enumeration vectors across teams.
    """
    foreign_dispatch_id = uuid.uuid4()

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    @contextmanager
    def mock_tx():
        yield mock_conn

    # 1. Direct verification helper check
    with pytest.raises(ApiError) as exc_info:
        _get_verified_team_dispatch(mock_conn, field_principal, foreign_dispatch_id)
    assert exc_info.value.status == 404
    assert exc_info.value.code == "NOT_FOUND"

    # 2. Endpoint wrapper check
    with patch("app.db.transaction", mock_tx):
        with pytest.raises(ApiError) as exc_info:
            field_acknowledge_dispatch(foreign_dispatch_id, field_principal)
        assert exc_info.value.status == 404

        with pytest.raises(ApiError) as exc_info:
            field_reject_dispatch(
                foreign_dispatch_id,
                FieldRejectionRequest(reason="Valid reason"),
                field_principal,
            )
        assert exc_info.value.status == 404

        with pytest.raises(ApiError) as exc_info:
            field_report_progress(
                foreign_dispatch_id,
                FieldProgressRequest(status="EN_ROUTE"),
                field_principal,
            )
        assert exc_info.value.status == 404

        with pytest.raises(ApiError) as exc_info:
            field_request_team(
                foreign_dispatch_id,
                FieldTeamRequest(required_capability="boat"),
                field_principal,
            )
        assert exc_info.value.status == 404

        with pytest.raises(ApiError) as exc_info:
            field_complete_dispatch(
                foreign_dispatch_id,
                FieldCompletionRequest(summary="Valid summary text"),
                field_principal,
            )
        assert exc_info.value.status == 404


# ── 5. Lifecycle Conflict Handling ──────────────────────────────────────


def test_lifecycle_conflict_returns_409(
    field_principal: FieldPrincipal,
    responder_team_id: uuid.UUID,
):
    dispatch_id = uuid.uuid4()
    mock_dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-000107",
        "status": "COMPLETED",
        "incident_id": uuid.uuid4(),
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_dispatch

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.apply_acknowledgement") as mock_ack,
    ):
        mock_ack.side_effect = ApiError(
            409,
            "DISPATCH_STATE_CONFLICT",
            "Cannot acknowledge an already completed dispatch",
        )

        with pytest.raises(ApiError) as exc_info:
            field_acknowledge_dispatch(dispatch_id, field_principal)

    assert exc_info.value.status == 409
    assert exc_info.value.code == "DISPATCH_STATE_CONFLICT"


# ── 6. Validation Error Checks ──────────────────────────────────────────


def test_rejection_requires_valid_reason():
    # Empty reason
    with pytest.raises(ValidationError):
        FieldRejectionRequest(reason="")

    # Reason too short (< 3 chars)
    with pytest.raises(ValidationError):
        FieldRejectionRequest(reason="no")


def test_completion_requires_valid_summary():
    # Empty summary
    with pytest.raises(ValidationError):
        FieldCompletionRequest(summary="")

    # Negative civilians treated
    with pytest.raises(ValidationError):
        FieldCompletionRequest(summary="Valid summary", civilians_treated=-5)

    # Negative civilians evacuated
    with pytest.raises(ValidationError):
        FieldCompletionRequest(summary="Valid summary", civilians_evacuated=-1)


# ── 7. Active Assignment Verification (released_at IS NULL) ─────────────


def test_released_historical_assignment_rejected(field_principal: FieldPrincipal):
    """Historical resource assignments with released_at set must be rejected with 404."""
    dispatch_id = uuid.uuid4()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    with pytest.raises(ApiError) as exc_info:
        _get_verified_team_dispatch(mock_conn, field_principal, dispatch_id)

    assert exc_info.value.status == 404
    assert exc_info.value.code == "NOT_FOUND"

    sql_called = mock_conn.execute.call_args[0][0]
    assert "ra.released_at IS NULL" in sql_called


def test_active_unreleased_assignment_authorized(field_principal: FieldPrincipal):
    """Active resource assignment with released_at IS NULL returns dispatch record."""
    dispatch_id = uuid.uuid4()
    mock_row = {"dispatch_id": dispatch_id, "status": "REQUESTED"}
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    result = _get_verified_team_dispatch(mock_conn, field_principal, dispatch_id)
    assert result["dispatch_id"] == dispatch_id

    sql_called = mock_conn.execute.call_args[0][0]
    assert "ra.released_at IS NULL" in sql_called



@pytest.mark.db
def test_field_user_mfa_required(client, make):
    user = make.field_team_user()
    r = client.get("/api/v1/field/assignments", headers=make.token(user, mfa=False))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "MFA_REQUIRED"
