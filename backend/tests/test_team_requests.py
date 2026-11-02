"""Tests for DM team requests (R-04)."""

import pytest

pytestmark = pytest.mark.db


def _setup(client, make):
    staff = make.staff("DISPATCH")
    agency = make.agency()
    field = make.field_team_user()
    incident = make.incident(status="VERIFIED", verified_priority="HIGH", verified_by=staff["user_id"])
    disp_res = client.post(
        f"/api/v1/dm/incidents/{incident['incident_id']}/dispatches",
        headers=staff["headers"],
        json={
            "receiving_agency_id": str(agency["agency_id"]),
            "instructions": "Initial squad dispatch",
            "resources": [{"resource_id": str(field["resource_id"]), "quantity": 1}],
        },
    )
    assert disp_res.status_code == 201
    dispatch_id = disp_res.json()["dispatch_id"]

    # Acknowledge and mark in progress
    client.post(f"/api/v1/field/dispatches/{dispatch_id}/acknowledgement", headers=field["headers"])
    client.post(f"/api/v1/field/dispatches/{dispatch_id}/progress", headers=field["headers"], json={"status": "EN_ROUTE"})

    # Field team requests backup
    req_res = client.post(
        f"/api/v1/field/dispatches/{dispatch_id}/team-requests",
        headers=field["headers"],
        json={"required_capability": "RESCUE_BOAT", "note": "Water levels rising quickly"},
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["request_id"]
    return staff, field, dispatch_id, request_id


def test_team_request_open_to_approved(client, make):
    staff, _, _, request_id = _setup(client, make)

    # 1. Dispatcher lists open requests
    open_requests = client.get("/api/v1/dm/team-requests?status=OPEN", headers=staff["headers"]).json()
    assert any(r["request_id"] == str(request_id) for r in open_requests)

    # 2. Dispatcher approves
    res = client.post(
        f"/api/v1/dm/team-requests/{request_id}/decision",
        headers=staff["headers"],
        json={"decision": "APPROVED", "rationale": "Additional rescue boat unit requested from SDRF"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "APPROVED"
    assert res.json()["decision_rationale"] == "Additional rescue boat unit requested from SDRF"

    # 3. Check no longer in open requests
    open_requests_after = client.get("/api/v1/dm/team-requests?status=OPEN", headers=staff["headers"]).json()
    assert not any(r["request_id"] == str(request_id) for r in open_requests_after)


def test_double_decision_conflict(client, make):
    staff, _, _, request_id = _setup(client, make)

    # First decision
    res1 = client.post(
        f"/api/v1/dm/team-requests/{request_id}/decision",
        headers=staff["headers"],
        json={"decision": "DECLINED", "rationale": "Resources currently fully committed"},
    )
    assert res1.status_code == 200

    # Second decision should fail with 409
    res2 = client.post(
        f"/api/v1/dm/team-requests/{request_id}/decision",
        headers=staff["headers"],
        json={"decision": "APPROVED", "rationale": "Changing decision"},
    )
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "ALREADY_DECIDED"


def test_non_dispatcher_forbidden(client, make):
    _, _, _, request_id = _setup(client, make)
    non_dispatcher = make.staff("CLOSURE")  # Staff with CLOSURE but not DISPATCH

    res = client.post(
        f"/api/v1/dm/team-requests/{request_id}/decision",
        headers=non_dispatcher["headers"],
        json={"decision": "APPROVED", "rationale": "Approve attempt"},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "PERMISSION_REQUIRED"


def test_field_user_cannot_access_dm_team_requests(client, make):
    _, field, _, _ = _setup(client, make)

    res = client.get("/api/v1/dm/team-requests", headers=field["headers"])
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ROLE_REQUIRED"
