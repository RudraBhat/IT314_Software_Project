"""Unit tests for Phase 2: Shared Dispatch State Transitions.

Tests row locking, state machine validation, resource release triggers,
progress ledger recording, and cross-transition audit logging.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.auth import Principal
from app.errors import ApiError
from app.services import dispatch as dispatch_svc


def _mock_actor() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="operator@drch.gov.in",
        full_name="Operations Staff",
        role="DISASTER_MGMT",
        mfa_verified=True,
    )


# ── 1. Row Locking & State Conflict Tests ───────────────────────────────


def test_lock_dispatch_raises_not_found_on_missing_id():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    with pytest.raises(ApiError) as exc_info:
        dispatch_svc.lock_dispatch(mock_conn, uuid.uuid4())
    assert exc_info.value.status == 404
    assert exc_info.value.code == "NOT_FOUND"


def test_record_dispatch_conflict_requested_vs_other():
    mock_conn = MagicMock()
    actor = _mock_actor()

    # When dispatch is REQUESTED, attempting EN_ROUTE returns DISPATCH_NOT_ACKNOWLEDGED
    req_dispatch = {"dispatch_id": uuid.uuid4(), "status": "REQUESTED"}
    err1 = dispatch_svc.record_dispatch_conflict(mock_conn, actor, req_dispatch, "EN_ROUTE")
    assert err1.status == 409
    assert err1.code == "DISPATCH_NOT_ACKNOWLEDGED"

    # When dispatch is COMPLETED, attempting ACKNOWLEDGEMENT returns DISPATCH_STATE_CONFLICT
    comp_dispatch = {"dispatch_id": uuid.uuid4(), "status": "COMPLETED"}
    err2 = dispatch_svc.record_dispatch_conflict(mock_conn, actor, comp_dispatch, "ACKNOWLEDGEMENT")
    assert err2.status == 409
    assert err2.code == "DISPATCH_STATE_CONFLICT"


# ── 2. Acknowledgement Transitions ──────────────────────────────────────


def test_apply_acknowledgement_advances_status_and_records_progress():
    dispatch_id = uuid.uuid4()
    mock_conn = MagicMock()
    dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-0001",
        "status": "REQUESTED",
        "incident_id": uuid.uuid4(),
    }
    actor = _mock_actor()

    result = dispatch_svc.apply_acknowledgement(
        mock_conn,
        actor,
        dispatch_id,
        channel="RADIO",
        note="Acknowledged on tactical radio channel 4",
        dispatch=dispatch,
    )

    assert result["status"] == "ACKNOWLEDGED"
    assert "Operations Staff (via radio)" in result["acknowledged_by"]

    # Verify SQL updates were executed
    executed_sql = [call[0][0] for call in mock_conn.execute.call_args_list]
    assert any("UPDATE dispatch_orders" in s for s in executed_sql)
    assert any("UPDATE agency_messages" in s for s in executed_sql)
    assert any("INSERT INTO dispatch_progress" in s for s in executed_sql)


def test_apply_acknowledgement_fails_if_not_requested():
    dispatch_id = uuid.uuid4()
    mock_conn = MagicMock()
    dispatch = {
        "dispatch_id": dispatch_id,
        "status": "DISPATCHED",
        "incident_id": uuid.uuid4(),
    }
    actor = _mock_actor()

    with pytest.raises(ApiError) as exc_info:
        dispatch_svc.apply_acknowledgement(mock_conn, actor, dispatch_id, dispatch=dispatch)
    assert exc_info.value.status == 409
    assert exc_info.value.code == "DISPATCH_STATE_CONFLICT"


# ── 3. Rejection & Resource Release ─────────────────────────────────────


def test_apply_rejection_releases_resources_and_records_state(monkeypatch):
    mock_release = MagicMock()
    monkeypatch.setattr("app.services.resources.release_all_for_dispatch", mock_release)

    dispatch_id = uuid.uuid4()
    mock_conn = MagicMock()
    dispatch = {
        "dispatch_id": dispatch_id,
        "status": "REQUESTED",
        "incident_id": uuid.uuid4(),
    }
    actor = _mock_actor()

    result = dispatch_svc.apply_rejection(
        mock_conn,
        actor,
        dispatch_id,
        reason="Unit vehicle broke down en route to base",
        dispatch=dispatch,
    )

    assert result["status"] == "REJECTED"
    assert mock_release.called
    assert mock_release.call_args[0][2] == dispatch_id


def test_apply_rejection_fails_if_terminal_state():
    dispatch_id = uuid.uuid4()
    mock_conn = MagicMock()
    dispatch = {
        "dispatch_id": dispatch_id,
        "status": "COMPLETED",
        "incident_id": uuid.uuid4(),
    }
    actor = _mock_actor()

    with pytest.raises(ApiError) as exc_info:
        dispatch_svc.apply_rejection(mock_conn, actor, dispatch_id, reason="Too late", dispatch=dispatch)
    assert exc_info.value.status == 409
    assert exc_info.value.code == "DISPATCH_STATE_CONFLICT"


# ── 4. Progress Transitions (EN_ROUTE, ON_SCENE) ────────────────────────


def test_apply_progress_en_route_advances_dispatch_and_incident(monkeypatch):
    mock_lock_inc = MagicMock(return_value={"incident_id": uuid.uuid4(), "status": "VERIFIED"})
    mock_update_inc = MagicMock()
    monkeypatch.setattr("app.services.incidents.lock_incident", mock_lock_inc)
    monkeypatch.setattr("app.services.incidents.update_incident", mock_update_inc)

    dispatch_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    mock_conn = MagicMock()
    dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-0002",
        "status": "ACKNOWLEDGED",
        "incident_id": incident_id,
    }
    actor = _mock_actor()

    result = dispatch_svc.apply_progress(
        mock_conn,
        actor,
        dispatch_id,
        event="EN_ROUTE",
        note="Departing staging base with boat unit",
        channel="RADIO",
        dispatch=dispatch,
    )

    assert result["status"] == "DISPATCHED"
    assert mock_update_inc.called
    assert mock_update_inc.call_args[1]["to_status"] == "DISPATCHED"


def test_apply_progress_on_scene_records_update_without_incident_status_change(monkeypatch):
    mock_update_inc = MagicMock()
    monkeypatch.setattr("app.services.incidents.update_incident", mock_update_inc)

    dispatch_id = uuid.uuid4()
    mock_conn = MagicMock()
    dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-0002",
        "status": "DISPATCHED",
        "incident_id": uuid.uuid4(),
    }
    actor = _mock_actor()

    result = dispatch_svc.apply_progress(
        mock_conn,
        actor,
        dispatch_id,
        event="ON_SCENE",
        note="Arrived at flooded junction. Commencing deployment.",
        dispatch=dispatch,
    )

    assert result["status"] == "DISPATCHED"
    assert not mock_update_inc.called


# ── 5. Completion Transitions & Incident Lifecycle Rule ────────────────


def test_apply_completion_releases_resources_and_leaves_incident_open(monkeypatch):
    mock_release = MagicMock()
    monkeypatch.setattr("app.services.resources.release_all_for_dispatch", mock_release)

    dispatch_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    mock_conn = MagicMock()
    dispatch = {
        "dispatch_id": dispatch_id,
        "dispatch_ref": "DISP-2026-0003",
        "status": "DISPATCHED",
        "incident_id": incident_id,
    }
    actor = _mock_actor()

    result = dispatch_svc.apply_completion(
        mock_conn,
        actor,
        dispatch_id,
        summary="Successfully evacuated 32 civilians to flood relief shelter.",
        confirmed_by="Captain Varma",
        civilians_evacuated=32,
        dispatch=dispatch,
    )

    assert result["status"] == "COMPLETED"
    assert mock_release.called
    assert mock_release.call_args[0][2] == dispatch_id

    # State update strictly sets dispatch status to COMPLETED
    executed_updates = [call[0] for call in mock_conn.execute.call_args_list if "UPDATE dispatch_orders" in str(call[0][0])]
    assert len(executed_updates) == 1
    assert executed_updates[0][1][0] == "COMPLETED"
