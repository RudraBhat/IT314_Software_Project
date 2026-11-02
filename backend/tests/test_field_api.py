"""Field-team API: scoped assignments and the dispatch lifecycle (contract s.3)."""

import pytest

pytestmark = pytest.mark.db


def _setup(client, make):
    """A verified incident, a dispatch reserving the field user's team, and a staff dispatcher."""
    staff = make.staff("DISPATCH")
    agency = make.agency()
    field = make.field_team_user()
    incident = make.incident(status="VERIFIED", verified_priority="HIGH", verified_by=staff["user_id"])
    r = client.post(
        f"/api/v1/dm/incidents/{incident['incident_id']}/dispatches",
        headers=staff["headers"],
        json={"receiving_agency_id": str(agency["agency_id"]), "instructions": "Deploy boat squad",
              "resources": [{"resource_id": str(field["resource_id"]), "quantity": 1}]},
    )
    assert r.status_code == 201, r.text
    return staff, field, r.json()["dispatch_id"], incident


def test_assignments_are_scoped_to_the_team(client, make):
    _, field, dispatch_id, _ = _setup(client, make)
    mine = client.get("/api/v1/field/assignments", headers=field["headers"]).json()
    assert [d["dispatch_id"] for d in mine] == [dispatch_id]
    other = make.field_team_user()
    assert client.get("/api/v1/field/assignments", headers=other["headers"]).json() == []
    r = client.post(f"/api/v1/field/dispatches/{dispatch_id}/acknowledgement", headers=other["headers"])
    assert r.status_code == 404


def test_full_lifecycle_updates_incident_and_releases_resources(client, make, sql):
    _, field, dispatch_id, incident = _setup(client, make)
    base = f"/api/v1/field/dispatches/{dispatch_id}"
    assert client.post(f"{base}/acknowledgement", headers=field["headers"]).json()["status"] == "ACKNOWLEDGED"
    r = client.post(f"{base}/progress", headers=field["headers"], json={"status": "EN_ROUTE"})
    assert r.json()["status"] == "DISPATCHED"
    assert sql.execute("SELECT status FROM incidents WHERE incident_id=%s", (incident["incident_id"],)).fetchone()["status"] == "DISPATCHED"
    assert client.post(f"{base}/progress", headers=field["headers"], json={"status": "ON_SCENE", "note": "arrived"}).status_code == 200
    req = client.post(f"{base}/team-requests", headers=field["headers"],
                      json={"required_capability": "medical_ambulance", "note": "need paramedics"})
    assert req.status_code == 201 and req.json()["status"] == "OPEN"
    done = client.post(f"{base}/completion", headers=field["headers"], json={"summary": "14 people evacuated"})
    assert done.json()["status"] == "COMPLETED"
    res = sql.execute("SELECT quantity_available, quantity_total FROM resources WHERE resource_id=%s", (field["resource_id"],)).fetchone()
    assert res["quantity_available"] == res["quantity_total"]
    assert client.get("/api/v1/field/assignments", headers=field["headers"]).json() == []


def test_out_of_order_report_is_a_conflict(client, make):
    _, field, dispatch_id, _ = _setup(client, make)
    r = client.post(f"/api/v1/field/dispatches/{dispatch_id}/completion", headers=field["headers"], json={"summary": "done early"})
    assert r.status_code == 409


def test_role_enforced(client, make):
    staff = make.staff("DISPATCH")
    citizen = make.citizen()
    assert client.get("/api/v1/field/assignments").status_code == 401
    assert client.get("/api/v1/field/assignments", headers=staff["headers"]).status_code == 403
    assert client.get("/api/v1/field/me", headers=citizen["headers"]).status_code == 403


def test_field_user_mfa_required(client, make):
    user = make.field_team_user()
    unmfa_headers = make.token(user, mfa=False)
    r = client.get("/api/v1/field/assignments", headers=unmfa_headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "MFA_REQUIRED"
