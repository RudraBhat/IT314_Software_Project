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
    """Submit a report; every call carries an Idempotency-Key (fresh unless one is given)."""
    headers = {**citizen["headers"], "Idempotency-Key": key or str(uuid.uuid4())}
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


def test_report_reaches_the_database_even_when_demo_mode_is_set(client, make, sql, monkeypatch):
    """Regression: a stray DEMO_MODE=true once routed reports into process memory, out of the dispatch queue."""
    monkeypatch.setenv("DEMO_MODE", "true")
    citizen = make.citizen()
    r = _post(client, citizen, key=str(uuid.uuid4()))
    assert r.status_code == 201, r.text
    stored = sql.execute(
        "SELECT reporter_id FROM incidents WHERE incident_id = %s", (r.json()["incident_id"],)
    ).fetchone()
    assert stored is not None and stored["reporter_id"] == citizen["user_id"]


def test_idempotency_key_returns_same_incident(client, make):
    citizen = make.citizen()
    key = str(uuid.uuid4())
    first = _post(client, citizen, key=key)
    second = _post(client, citizen, key=key)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["incident_id"] == second.json()["incident_id"]


def test_missing_idempotency_key_is_rejected_and_creates_nothing(client, make, sql):
    """Issue #103: a retry without a key must not be able to create a duplicate report."""
    citizen = make.citizen()
    for headers in (dict(citizen["headers"]), {**citizen["headers"], "Idempotency-Key": ""}):
        r = client.post("/api/v1/incidents", json=PAYLOAD, headers=headers)
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    count = sql.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE reporter_id = %s", (citizen["user_id"],)
    ).fetchone()["n"]
    assert count == 0


def test_same_key_twice_creates_only_one_incident(client, make, sql):
    citizen = make.citizen()
    key = str(uuid.uuid4())
    ids = {_post(client, citizen, key=key).json()["incident_id"] for _ in range(3)}
    assert len(ids) == 1
    count = sql.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE reporter_id = %s", (citizen["user_id"],)
    ).fetchone()["n"]
    assert count == 1


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
    assert r.json()["status"] == "SUBMITTED"

    # Issue #99: the report returns to the verification queue with the reply on its timeline.
    mine = client.get(f"/api/v1/me/incidents/{iid}", headers=citizen["headers"]).json()
    assert mine["status"] == "SUBMITTED"
    assert any(t["message"] == "Which landmark is nearest?" for t in mine["timeline"])
    assert mine["timeline"][-1] == {**mine["timeline"][-1], "status": "SUBMITTED",
                                    "message": "Reporter reply: It is near the temple"}

    detail = client.get(f"/api/v1/dm/incidents/{iid}", headers=staff["headers"]).json()
    assert detail["status"] == "SUBMITTED"
    assert any(h["reason"] == "Reporter reply: It is near the temple" for h in detail["history"])

    # A second reply is refused cleanly: nothing is being asked any more.
    again = client.post(f"/api/v1/me/incidents/{iid}/information", headers=citizen["headers"],
                        json={"message": "Also near the bus stop"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "NOT_AWAITING_INFORMATION"


def test_reply_must_be_3_to_2000_characters(client, make):
    citizen = make.citizen()
    iid = _needs_information(client, make, citizen)
    for message in ("  a ", "x" * 2001):
        r = client.post(f"/api/v1/me/incidents/{iid}/information", headers=citizen["headers"],
                        json={"message": message})
        assert r.status_code == 422, r.text


def _needs_information(client, make, citizen):
    iid = _post(client, citizen).json()["incident_id"]
    staff = make.staff()
    version = client.get(f"/api/v1/dm/incidents/{iid}", headers=staff["headers"]).json()["version"]
    assert client.post(f"/api/v1/dm/incidents/{iid}/information-requests", headers=staff["headers"],
                       json={"question": "Where exactly?", "version": version}).status_code == 201
    return iid


def test_information_response_can_correct_the_location(client, make, sql):
    citizen = make.citizen()
    iid = _needs_information(client, make, citizen)
    r = client.post(f"/api/v1/me/incidents/{iid}/information-response", headers=citizen["headers"],
                    json={"latitude": 21.1702, "longitude": 72.8311, "address_text": "Ring Road, Surat"})
    assert r.status_code == 201 and r.json()["status"] == "SUBMITTED"
    row = sql.execute("SELECT status, district, latitude::float AS lat FROM incidents WHERE incident_id = %s", (iid,)).fetchone()
    assert row["status"] == "SUBMITTED" and row["district"] == "Surat" and abs(row["lat"] - 21.1702) < 1e-4
    history = sql.execute(
        "SELECT to_status FROM incident_status_history WHERE incident_id = %s ORDER BY history_id DESC LIMIT 1", (iid,)
    ).fetchone()
    assert history["to_status"] == "SUBMITTED"


def test_information_response_is_refused_outside_needs_information(client, make):
    citizen = make.citizen()
    iid = _post(client, citizen).json()["incident_id"]
    r = client.post(f"/api/v1/me/incidents/{iid}/information-response", headers=citizen["headers"],
                    json={"message": "Trying to answer without a request"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_AWAITING_INFORMATION"


def test_information_response_validation_and_ownership(client, make):
    owner, other = make.citizen(), make.citizen()
    iid = _needs_information(client, make, owner)
    url = f"/api/v1/me/incidents/{iid}/information-response"
    assert client.post(url, headers=owner["headers"], json={}).status_code == 422
    assert client.post(url, headers=owner["headers"], json={"latitude": 26.9, "longitude": 75.8}).status_code == 422
    assert client.post(url, headers=other["headers"], json={"message": "Not my report"}).status_code == 404


def test_timeline_has_readable_labels(client, make):
    citizen = make.citizen()
    iid = _post(client, citizen).json()["incident_id"]
    mine = client.get(f"/api/v1/me/incidents/{iid}", headers=citizen["headers"]).json()
    assert mine["status_label"] == "Report submitted"
    assert all(t["label"] and t["label"] != t["status"] for t in mine["timeline"])
    listing = client.get("/api/v1/me/incidents", headers=citizen["headers"]).json()
    assert listing["items"][0]["timeline"][0]["label"] == "Report submitted"


def test_information_response_is_rate_limited(client, make, monkeypatch):
    from app import ratelimit

    citizen = make.citizen()
    iid = _post(client, citizen).json()["incident_id"]
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    ratelimit.reset()
    try:
        codes = [client.post(f"/api/v1/me/incidents/{iid}/information-response", headers=citizen["headers"],
                             json={"message": "hello there"}).status_code for _ in range(22)]
    finally:
        ratelimit.reset()
    assert codes[:20] == [409] * 20 and codes[20:] == [429, 429]


def test_mark_notification_read_is_owner_scoped(client, make):
    a, b = make.citizen(), make.citizen()
    _post(client, a)
    nid = client.get("/api/v1/me/notifications", headers=a["headers"]).json()["items"][0]["notification_id"]
    assert client.post(f"/api/v1/me/notifications/{nid}/read", headers=b["headers"]).status_code == 404
    assert client.post(f"/api/v1/me/notifications/{nid}/read", headers=a["headers"]).status_code == 200
