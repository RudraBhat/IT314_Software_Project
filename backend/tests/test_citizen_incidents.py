"""Citizen reporting flow: submit, idempotency, geofence, isolation, timeline, notifications."""

import uuid

import pytest

pytestmark = pytest.mark.db

PAYLOAD = {
    "scenario": "urban_flooding",
    "description": "Severe waterlogging on the main market road, water entered shops.",
    "reported_urgency": "HIGH",
    "people_affected": 15,
    "location_source": "GPS",
    "latitude": 23.0225,
    "longitude": 72.5714,
    "address_text": "Near Usmanpura Underpass",
}


def _post(client, citizen, payload=None, key=None):
    headers = dict(citizen["headers"])
    if key:
        headers["Idempotency-Key"] = key
    return client.post("/api/v1/incidents", json=payload or PAYLOAD, headers=headers)


def test_submit_creates_submitted_incident_visible_to_dm(client, make):
    citizen = make.citizen()
    r = _post(client, citizen)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "SUBMITTED" and body["incident_ref"].startswith("INC-")
    assert body["district"] == "Ahmedabad"
    staff = make.staff()
    queue = client.get(
        "/api/v1/dm/incidents", headers=staff["headers"], params={"q": body["incident_ref"]}
    ).json()
    assert queue["total"] == 1


def test_idempotency_key_returns_same_incident(client, make):
    citizen = make.citizen()
    key = str(uuid.uuid4())
    first = _post(client, citizen, key=key)
    second = _post(client, citizen, key=key)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["incident_id"] == second.json()["incident_id"]


def test_outside_gujarat_is_rejected(client, make):
    citizen = make.citizen()
    for lat, lon in [(26.9124, 75.7873), (19.0760, 72.8777), (24.86, 67.0)]:  # Jaipur, Mumbai, Karachi
        r = _post(client, citizen, {**PAYLOAD, "latitude": lat, "longitude": lon})
        assert r.status_code == 422 and r.json()["error"]["code"] == "OUTSIDE_GUJARAT"


def test_unsupported_scenario_is_rejected(client, make):
    r = _post(client, make.citizen(), {**PAYLOAD, "scenario": "earthquake"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNSUPPORTED_SCENARIO"


def test_requires_citizen_role(client, make):
    assert client.post("/api/v1/incidents", json=PAYLOAD).status_code == 401
    staff = make.staff()
    assert client.post("/api/v1/incidents", json=PAYLOAD, headers=staff["headers"]).status_code == 403


def test_citizen_cannot_see_another_citizens_incident(client, make):
    owner, other = make.citizen(), make.citizen()
    incident_id = _post(client, owner).json()["incident_id"]
    assert client.get(f"/api/v1/me/incidents/{incident_id}", headers=owner["headers"]).status_code == 200
    assert client.get(f"/api/v1/me/incidents/{incident_id}", headers=other["headers"]).status_code == 404
    assert client.get("/api/v1/me/incidents", headers=other["headers"]).json()["total"] == 0


def test_timeline_follows_dm_decisions_and_hides_internal_data(client, make):
    citizen = make.citizen()
    created = _post(client, citizen).json()
    staff = make.staff()
    detail = client.get(f"/api/v1/dm/incidents/{created['incident_id']}", headers=staff["headers"]).json()
    r = client.post(
        f"/api/v1/dm/incidents/{created['incident_id']}/verification",
        headers=staff["headers"],
        json={"decision": "VERIFIED", "rationale": "Confirmed by caller", "priority": "HIGH", "version": detail["version"]},
    )
    assert r.status_code == 200, r.text
    mine = client.get(f"/api/v1/me/incidents/{created['incident_id']}", headers=citizen["headers"]).json()
    assert [t["status"] for t in mine["timeline"]] == ["SUBMITTED", "VERIFIED"]
    assert "priority_rationale" not in mine and "verified_by" not in mine
    notes = client.get("/api/v1/me/notifications", headers=citizen["headers"]).json()
    assert {n["event_code"] for n in notes["items"]} >= {"INCIDENT_RECEIVED", "INCIDENT_VERIFIED"}


def test_reply_to_information_request(client, make):
    citizen = make.citizen()
    created = _post(client, citizen).json()
    iid = created["incident_id"]
    assert client.post(f"/api/v1/me/incidents/{iid}/information", headers=citizen["headers"],
                       json={"message": "It is near the temple"}).status_code == 409
    staff = make.staff()
    version = client.get(f"/api/v1/dm/incidents/{iid}", headers=staff["headers"]).json()["version"]
    assert client.post(f"/api/v1/dm/incidents/{iid}/information-requests", headers=staff["headers"],
                       json={"question": "Which landmark is nearest?", "version": version}).status_code == 201
    r = client.post(f"/api/v1/me/incidents/{iid}/information", headers=citizen["headers"],
                    json={"message": "It is near the temple"})
    assert r.status_code == 201, r.text
    mine = client.get(f"/api/v1/me/incidents/{iid}", headers=citizen["headers"]).json()
    assert any(t["message"] == "Which landmark is nearest?" for t in mine["timeline"])


def test_mark_notification_read_is_owner_scoped(client, make):
    a, b = make.citizen(), make.citizen()
    _post(client, a)
    nid = client.get("/api/v1/me/notifications", headers=a["headers"]).json()["items"][0]["notification_id"]
    assert client.post(f"/api/v1/me/notifications/{nid}/read", headers=b["headers"]).status_code == 404
    assert client.post(f"/api/v1/me/notifications/{nid}/read", headers=a["headers"]).status_code == 200
