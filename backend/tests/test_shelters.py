"""Shelters: dispatchers maintain them, citizens read the open ones, every change is audited."""

import uuid

import pytest

pytestmark = pytest.mark.db

DM = "/api/v1/dm/shelters"
PUBLIC = "/api/v1/public/shelters"


def _body(**changes) -> dict:
    tag = uuid.uuid4().hex[:8]
    return {
        "name": f"Test Shelter {tag}",
        "type": "SHELTER",
        "address_text": "Government school, Ahmedabad",
        "district": "Ahmedabad",
        "latitude": 23.02251,
        "longitude": 72.57141,
        "total_capacity": 200,
        "current_occupancy": 50,
        "contact_number": "+91 79 1234 5678",
        "status": "OPERATIONAL",
        "notes": "Water and food available",
        "reason": "New relief shelter opened",
        **changes,
    }


def _public(client) -> dict:
    r = client.get(PUBLIC)
    assert r.status_code == 200, r.text
    return {s["id"]: s for s in r.json()}


def test_dispatcher_creates_a_shelter_that_citizens_then_see(client, make, sql):
    staff = make.staff("DISPATCH")
    r = client.post(DM, headers=staff["headers"], json=_body())
    assert r.status_code == 201, r.text
    created = r.json()
    sid = created["shelter_id"]

    shown = _public(client)[sid]
    assert shown["name"] == created["name"] and shown["available_beds"] == 150 and shown["status"] == "OPERATIONAL"
    assert (shown["lat"], shown["lon"]) == (23.0225, 72.5714), "public coordinates are rounded to 4 decimals"
    assert not {"created_by", "updated_by", "reason"} & set(shown)

    entry = sql.execute(
        "SELECT actor_id, rationale, after_state FROM audit_logs WHERE entity_id = %s AND action = 'SHELTER_CREATED'", (sid,)
    ).fetchone()
    assert entry["actor_id"] == staff["user_id"] and entry["rationale"] == "New relief shelter opened"
    assert entry["after_state"]["name"] == created["name"]


def test_full_shelters_stay_listed_and_closed_ones_disappear(client, make):
    staff = make.staff("DISPATCH")
    sid = client.post(DM, headers=staff["headers"], json=_body()).json()["shelter_id"]

    def update(**changes):
        full = client.get(DM, headers=staff["headers"]).json()["items"]
        current = next(s for s in full if s["shelter_id"] == sid)
        body = {
            **{k: current[k] for k in ("name", "type", "address_text", "district", "latitude", "longitude",
                                       "total_capacity", "current_occupancy", "contact_number", "status", "notes")},
            "reason": "Occupancy changed during the day",
            **changes,
        }
        return client.put(f"{DM}/{sid}", headers=staff["headers"], json=body)

    assert update(status="FULL", current_occupancy=200).status_code == 200
    assert _public(client)[sid]["status"] == "FULL" and _public(client)[sid]["available_beds"] == 0
    assert update(status="CLOSED").status_code == 200
    assert sid not in _public(client)
    assert any(s["shelter_id"] == sid for s in client.get(DM, headers=staff["headers"]).json()["items"])
    assert all(s["shelter_id"] != sid for s in client.get(DM, headers=staff["headers"], params={"include_closed": "false"}).json()["items"])


def test_update_is_audited_with_before_and_after(client, make, sql):
    staff = make.staff("SUPERVISOR")
    created = client.post(DM, headers=staff["headers"], json=_body(current_occupancy=10)).json()
    sid = created["shelter_id"]
    body = _body(name=created["name"], current_occupancy=75, reason="Evening headcount")
    assert client.put(f"{DM}/{sid}", headers=staff["headers"], json=body).status_code == 200
    entry = sql.execute(
        "SELECT before_state, after_state, rationale FROM audit_logs WHERE entity_id = %s AND action = 'SHELTER_UPDATED'", (sid,)
    ).fetchone()
    assert entry["before_state"]["current_occupancy"] == 10 and entry["after_state"]["current_occupancy"] == 75
    assert entry["rationale"] == "Evening headcount"


def test_invalid_shelters_are_rejected(client, make):
    staff = make.staff("DISPATCH")
    for bad in (
        _body(current_occupancy=500),  # more people than beds
        _body(latitude=123),
        _body(type="HOTEL"),
        _body(status="BROKEN"),
        _body(contact_number="call me maybe"),
        _body(reason="no"),
        _body(name="x"),
    ):
        assert client.post(DM, headers=staff["headers"], json=bad).status_code == 422, bad
    assert client.put(f"{DM}/{uuid.uuid4()}", headers=staff["headers"], json=_body()).status_code == 404


def test_only_dispatch_or_supervisor_staff_manage_shelters(make, client):
    assert client.get(DM).status_code == 401
    assert client.post(DM, json=_body()).status_code == 401
    assert client.get(DM, headers=make.staff("PUBLISHER")["headers"]).status_code == 403  # staff without the permission
    assert client.post(DM, headers=make.staff("MODERATOR")["headers"], json=_body()).status_code == 403
    for headers in (make.citizen()["headers"], make.field_team_user()["headers"], make.token(make.user("APP_MGMT"))):
        assert client.get(DM, headers=headers).status_code == 403
    assert client.get(DM, headers=make.staff("SUPERVISOR")["headers"]).status_code == 200


def test_the_public_list_needs_no_sign_in_and_hides_internal_fields(client):
    r = client.get(PUBLIC)
    assert r.status_code == 200
    for shelter in r.json():
        assert not {"created_by", "updated_by", "shelter_id", "created_at"} & set(shelter)
