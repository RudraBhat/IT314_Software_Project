"""One incident through every stage the reporter sees, driven only through the real API.

The reporter's progress bar has four stages: Submitted, Verified, Dispatched, Resolved. Each other test covers a
piece of this; this one chains them and checks what the reporter would actually be shown after every step.
"""

import uuid

import pytest

pytestmark = pytest.mark.db

DM = "/api/v1/dm"
REPORT = {
    "scenario": "urban_flooding",
    "description": "Severe waterlogging on the main market road, water entered shops.",
    "reported_urgency": "HIGH",
    "people_affected": 15,
    "location_source": "GPS",
    "latitude": 23.0225,
    "longitude": 72.5714,
    "address_text": "Near Usmanpura Underpass",
}


def _mine(client, citizen, incident_id) -> dict:
    """The incident as the reporter sees it."""
    response = client.get(f"/api/v1/me/incidents/{incident_id}", headers=citizen["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _stages(view: dict) -> list[str]:
    return [entry["status"] for entry in view["timeline"]]


def _version(client, staff, incident_id) -> int:
    return client.get(f"{DM}/incidents/{incident_id}", headers=staff["headers"]).json()["version"]


def test_an_incident_travels_all_four_stages_and_the_reporter_sees_each(client, make, sql):
    citizen = make.citizen()
    dispatcher = make.staff("DISPATCH")
    closer = make.staff("CLOSURE")
    agency, team = make.agency(), make.resource()

    # Stage 1: Submitted.
    created = client.post("/api/v1/incidents", json=REPORT, headers={**citizen["headers"], "Idempotency-Key": str(uuid.uuid4())})
    assert created.status_code == 201, created.text
    iid = created.json()["incident_id"]
    view = _mine(client, citizen, iid)
    assert view["status"] == "SUBMITTED" and _stages(view) == ["SUBMITTED"]

    # Nothing can be dispatched or resolved before a human has verified it.
    early = client.post(
        f"{DM}/incidents/{iid}/dispatches",
        headers=dispatcher["headers"],
        json={"receiving_agency_id": str(agency["agency_id"]), "instructions": "Send a boat team", "resources": [{"resource_id": str(team["resource_id"]), "quantity": 1}]},
    )
    assert early.status_code == 409 and early.json()["error"]["code"] == "INCIDENT_NOT_VERIFIED"

    # Stage 2: Verified, by a dispatcher, with a priority.
    verified = client.post(
        f"{DM}/incidents/{iid}/verification",
        headers=dispatcher["headers"],
        json={"decision": "VERIFIED", "rationale": "Confirmed by the caller", "priority": "HIGH", "version": _version(client, dispatcher, iid)},
    )
    assert verified.status_code == 200, verified.text
    view = _mine(client, citizen, iid)
    assert view["status"] == "VERIFIED" and _stages(view) == ["SUBMITTED", "VERIFIED"]

    # Stage 3: Dispatched. Asking an agency for help does not move the incident; only a recorded en-route does.
    created_dispatch = client.post(
        f"{DM}/incidents/{iid}/dispatches",
        headers=dispatcher["headers"],
        json={"receiving_agency_id": str(agency["agency_id"]), "instructions": "Send a boat team", "resources": [{"resource_id": str(team["resource_id"]), "quantity": 1}]},
    )
    assert created_dispatch.status_code == 201, created_dispatch.text
    url = f"{DM}/dispatches/{created_dispatch.json()['dispatch_id']}"
    assert _mine(client, citizen, iid)["status"] == "VERIFIED"

    acknowledged = client.post(f"{url}/acknowledgement", headers=dispatcher["headers"], json={"acknowledged_by": "Station Officer Rao", "channel": "PHONE"})
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"
    assert _mine(client, citizen, iid)["status"] == "VERIFIED"

    en_route = client.post(f"{url}/progress", headers=dispatcher["headers"], json={"event": "EN_ROUTE", "reported_by": "Rao", "channel": "RADIO"})
    assert en_route.json()["status"] == "DISPATCHED"
    view = _mine(client, citizen, iid)
    assert view["status"] == "DISPATCHED" and _stages(view) == ["SUBMITTED", "VERIFIED", "DISPATCHED"]

    # Stage 4 is a human decision and is refused while a dispatch is still active.
    blocked = client.post(
        f"{DM}/incidents/{iid}/resolution",
        headers=dispatcher["headers"],
        json={"rationale": "Water has receded", "version": _version(client, dispatcher, iid)},
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "OPEN_DEPENDENCIES"
    assert _mine(client, citizen, iid)["status"] == "DISPATCHED"

    # Completing the dispatch does not resolve the incident by itself: that stays a person's call.
    assert client.post(f"{url}/completion", headers=dispatcher["headers"], json={"confirmed_by": "Rao", "channel": "RADIO"}).json()["status"] == "COMPLETED"
    assert _mine(client, citizen, iid)["status"] == "DISPATCHED"
    assert sql.execute("SELECT quantity_available FROM resources WHERE resource_id = %s", (team["resource_id"],)).fetchone()["quantity_available"] == 1

    # Stage 4: Resolved.
    resolved = client.post(
        f"{DM}/incidents/{iid}/resolution",
        headers=dispatcher["headers"],
        json={"rationale": "Water has receded and the road is clear", "version": _version(client, dispatcher, iid)},
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "RESOLVED"
    view = _mine(client, citizen, iid)
    assert view["status"] == "RESOLVED" and _stages(view) == ["SUBMITTED", "VERIFIED", "DISPATCHED", "RESOLVED"]

    # Closing it afterwards keeps RESOLVED in the history, which is what tells the citizen screen the incident
    # really was resolved (a report closed without that entry is shown as closed without resolution).
    closed = client.post(
        f"{DM}/incidents/{iid}/closure",
        headers=closer["headers"],
        json={"reason": "All work is finished", "version": _version(client, closer, iid)},
    )
    assert closed.status_code == 200, closed.text
    view = _mine(client, citizen, iid)
    assert view["status"] == "CLOSED" and "RESOLVED" in _stages(view)


def test_a_report_closed_without_being_resolved_has_no_resolved_stage(client, make):
    citizen = make.citizen()
    closer = make.staff("CLOSURE")
    created = client.post("/api/v1/incidents", json=REPORT, headers={**citizen["headers"], "Idempotency-Key": str(uuid.uuid4())})
    iid = created.json()["incident_id"]
    closed = client.post(
        f"{DM}/incidents/{iid}/closure",
        headers=closer["headers"],
        json={"reason": "Duplicate of another report", "version": _version(client, closer, iid)},
    )
    assert closed.status_code == 200, closed.text
    view = _mine(client, citizen, iid)
    assert view["status"] == "CLOSED" and "RESOLVED" not in _stages(view)
