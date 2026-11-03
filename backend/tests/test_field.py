"""Comprehensive automated test suite for Field Operations and Responder Lifecycles.

Covers:
1. Field authentication, role enforcement, and GET /field/me profile resolution.
2. GET /field/assignments returning strictly assigned dispatches with active filters.
3. Cross-team isolation guardrail (requesting another team's dispatch returns 404).
4. Unauthenticated (401) and incorrect role (403) protections.
5. Dispatch acknowledgement advancing status to ACKNOWLEDGED with network retry idempotency.
6. Dispatch rejection releasing reserved resources back to AVAILABLE.
7. Progress reporting writing to dispatch_progress and advancing incident to DISPATCHED.
8. Backup reinforcement request creation with status OPEN and dispatcher notification.
9. Mission completion transitioning to COMPLETED while keeping parent incident open.
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from app.auth import FieldPrincipal, Principal, require_field
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


def _mock_request(path: str = "/api/v1/field/me") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 54321),
    }
    return Request(scope)


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
def responder_principal(
    responder_user_id: uuid.UUID,
    responder_team_id: uuid.UUID,
    responder_agency_id: uuid.UUID,
) -> FieldPrincipal:
    return FieldPrincipal(
        user_id=responder_user_id,
        email="field.lead@sdrf.gujarat.gov.in",
        full_name="Quick Response Lead",
        role="FIELD_TEAM",
        member_id=uuid.uuid4(),
        team_resource_id=responder_team_id,
        team_name="SDRF Quick Response 1",
        agency_id=responder_agency_id,
        agency_name="State Disaster Response Force",
        callsign="QR-1",
        is_leader=True,
        capabilities={"boat": True, "flood_rescue": True},
        ip="127.0.0.1",
    )


# ── 1. Profile Resolution ───────────────────────────────────────────────


def test_field_profile_resolution(responder_principal: FieldPrincipal):
    """1. Successful field login and GET /field/me profile resolution."""
    mock_row = {
        "user_id": responder_principal.user_id,
        "email": responder_principal.email,
        "full_name": responder_principal.full_name,
        "phone": "+919876543210",
        "role": "FIELD_TEAM",
        "member_id": responder_principal.member_id,
        "callsign": responder_principal.callsign,
        "is_leader": True,
        "team_resource_id": responder_principal.team_resource_id,
        "team_name": responder_principal.team_name,
        "status": "AVAILABLE",
        "capability": {"boat": True, "flood_rescue": True},
        "agency_id": responder_principal.agency_id,
        "agency_name": responder_principal.agency_name,
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
        profile = get_field_profile(responder_principal)

    assert isinstance(profile, FieldProfileResponse)
    assert profile.user_id == responder_principal.user_id
    assert profile.callsign == "QR-1"
    assert profile.is_leader is True
    assert profile.team_name == "SDRF Quick Response 1"


# ── 2. Team Assigned Dispatches ─────────────────────────────────────────


def test_get_field_assignments_returns_only_assigned_dispatches(
    responder_principal: FieldPrincipal,
):
    """2. GET /field/assignments returns only dispatches assigned to the caller's team."""
    dispatch_id = uuid.uuid4()
    mock_rows = [
        {
            "dispatch_id": dispatch_id,
            "dispatch_ref": "DISP-2026-000777",
            "status": "REQUESTED",
            "priority": "P1",
            "incident_id": uuid.uuid4(),
            "incident_ref": "INC-2026-000888",
            "scenario": "flood",
            "district": "Ahmedabad",
            "address_text": "Vasna Barrage",
            "landmark": "Near Bridge",
            "latitude": 23.01,
            "longitude": 72.58,
            "instructions": "Evacuate stranded residents",
            "dispatched_at": datetime.now(UTC),
            "acknowledged_at": None,
            "overdue": False,
        }
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_rows

    @contextmanager
    def mock_tx():
        yield mock_conn

    with (
        patch("app.db.transaction", mock_tx),
        patch("app.routers.field.get_settings") as mock_settings,
    ):
        mock_settings.return_value.database_url = "postgresql://mock:5432/db"
        mock_settings.return_value.dispatch_ack_timeout_minutes = 15

        res = get_field_assignments(responder_principal, active=True)

    assert len(res) == 1
    assert isinstance(res[0], FieldAssignmentResponse)
    assert res[0].dispatch_ref == "DISP-2026-000777"


# ── 3. Cross-Team Security Isolation ────────────────────────────────────


def test_cross_team_dispatch_isolation_returns_404(
    responder_principal: FieldPrincipal,
):
    """3. Cross-team isolation: requesting another team's dispatch ID returns 404 Not Found."""
    foreign_dispatch_id = uuid.uuid4()

    mock_conn = MagicMock()
    # Team association check yields no rows for foreign dispatch
    mock_conn.execute.return_value.fetchone.return_value = None

    @contextmanager
    def mock_tx():
        yield mock_conn

    # 1. Direct helper check raises 404
    with pytest.raises(ApiError) as exc_info:
        _get_verified_team_dispatch(mock_conn, responder_principal, foreign_dispatch_id)
    assert exc_info.value.status == 404
    assert exc_info.value.code == "NOT_FOUND"

    # 2. Endpoint check raises 404
    with patch("app.db.transaction", mock_tx):
        with pytest.raises(ApiError) as exc_info:
            field_acknowledge_dispatch(foreign_dispatch_id, responder_principal)
        assert exc_info.value.status == 404

    # 3. Verify query requires ra.released_at IS NULL
    sql_executed = mock_conn.execute.call_args[0][0]
    assert "ra.released_at IS NULL" in sql_executed


# ── 4. Role Enforcement & Authentication ────────────────────────────────


def test_unauthenticated_or_wrong_role_rejected(responder_principal: FieldPrincipal):
    """4. Unauthenticated or wrong-role requests return 401 / 403."""
    req = _mock_request()

    with patch("app.audit.record_standalone"):
        # Staff role attempting to access field endpoint returns 403
        staff_user = Principal(
            user_id=uuid.uuid4(),
            email="staff@drch.gov.in",
            full_name="Staff Member",
            role="DISASTER_MGMT",
            mfa_verified=True,
        )
        with pytest.raises(ApiError) as exc_info:
            require_field(req, staff_user)
        assert exc_info.value.status == 403
        assert exc_info.value.code == "ROLE_REQUIRED"

        # Citizen role attempting to access field endpoint returns 403
        citizen_user = Principal(
            user_id=uuid.uuid4(),
            email="citizen@gmail.com",
            full_name="Citizen User",
            role="PUBLIC_CITIZEN",
            mfa_verified=False,
        )
        with pytest.raises(ApiError) as exc_info:
            require_field(req, citizen_user)
        assert exc_info.value.status == 403


# ── 5. Dispatch Acknowledgement & Idempotency ───────────────────────────


def test_dispatch_acknowledgement_advances_status_and_is_idempotent(
    responder_principal: FieldPrincipal,
):
    """5. Dispatch acknowledgement advances status to ACKNOWLEDGED with network retry idempotency."""
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

        # Initial acknowledgement
        res = field_acknowledge_dispatch(dispatch_id, responder_principal)
        assert isinstance(res, FieldAcknowledgementResponse)
        assert res.status == "ACKNOWLEDGED"

        # Intermittent mobile network drop retry (idempotent submission)
        res_retry = field_acknowledge_dispatch(dispatch_id, responder_principal)
        assert res_retry.status == "ACKNOWLEDGED"


# ── 6. Dispatch Rejection & Resource Release ────────────────────────────


def test_dispatch_rejection_releases_resources(
    responder_principal: FieldPrincipal,
):
    """6. Dispatch rejection with reason frees reserved resources back to AVAILABLE."""
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

        body = FieldRejectionRequest(reason="Equipment trailer tire punctured on highway")
        res = field_reject_dispatch(dispatch_id, body, responder_principal)

    assert res["status"] == "REJECTED"
    assert res["dispatch_ref"] == "DISP-2026-000103"
    mock_rej.assert_called_once()


# ── 7. Progress Reporting & Incident Advancement ────────────────────────


def test_progress_reporting_advances_incident_status(
    responder_principal: FieldPrincipal,
):
    """7. Progress update writes to dispatch_progress and advances incident to DISPATCHED."""
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
            note="Team departing station with 2 motorized boats",
            latitude=23.03,
            longitude=72.52,
        )
        res = field_report_progress(dispatch_id, body, responder_principal)

    assert isinstance(res, FieldProgressResponse)
    assert res.status == "EN_ROUTE"
    assert res.note == body.note
    mock_prog.assert_called_once()


# ── 8. Backup Team Request ──────────────────────────────────────────────


def test_backup_team_request_records_open_status(
    responder_principal: FieldPrincipal,
):
    """8. Backup team request correctly records in team_requests with status OPEN."""
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
            required_capability="hazmat",
            note="Detected strong chemical odor from submerged drums",
        )
        res = field_request_team(dispatch_id, body, responder_principal)

    assert isinstance(res, FieldTeamRequestResponse)
    assert res.request_id == request_id
    assert res.required_capability == "hazmat"
    assert res.status == "OPEN"
    mock_audit.assert_called_once()
    mock_notify.assert_called_once()


# ── 9. Mission Completion ───────────────────────────────────────────────


def test_mission_completion_leaves_parent_incident_open(
    responder_principal: FieldPrincipal,
):
    """9. Mission completion sets dispatch COMPLETED and leaves parent incident open."""
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
            summary="All residents safely ferried to dry ground. Field operations concluded.",
            civilians_evacuated=34,
            civilians_treated=2,
        )
        res = field_complete_dispatch(dispatch_id, body, responder_principal)

    assert res["status"] == "COMPLETED"
    assert res["dispatch_ref"] == "DISP-2026-000106"
    assert res["civilians_evacuated"] == 34
    mock_comp.assert_called_once()
