"""Agency directory maintenance: supervisors add, edit and deactivate the contacts dispatches go to."""

import uuid

import pytest

pytestmark = pytest.mark.db

DM = "/api/v1/dm"
URL = f"{DM}/agencies"


def _body(**changes) -> dict:
    return {
        "name": f"Test Agency {uuid.uuid4().hex[:8]}",
        "agency_type": "FIRE",
        "contact_email": "control@agency.test",
        "contact_phone": "07923250100",
        "is_active": True,
        "reason": "Added after the district review",
        **changes,
    }


def _create(client, staff, **changes):
    return client.post(URL, headers=staff["headers"], json=_body(**changes))


def _listed(client, staff) -> dict:
    items = client.get(f"{DM}/agency-contacts", headers=staff["headers"]).json()["items"]
    return {str(a["agency_id"]): a for a in items}


def test_a_supervisor_adds_an_agency_that_dispatch_staff_can_then_see(client, make, sql):
    supervisor, dispatcher = make.staff("SUPERVISOR"), make.staff("DISPATCH")
    name = f"Vadodara Rescue Cell {uuid.uuid4().hex[:8]}"  # unique per run: agencies persist in the shared test database
    r = _create(client, supervisor, name=f"  {name}  ", contact_phone=" 0265 2830491 ")
    assert r.status_code == 201, r.text
    agency = r.json()
    assert agency["name"] == name and agency["contact_phone"] == "0265 2830491"  # trimmed
    assert agency["is_active"] is True and agency["agency_type"] == "FIRE"

    seen = _listed(client, dispatcher)[agency["agency_id"]]  # read access is open to all dispatch staff
    assert seen["name"] == name and seen["updated_at"]

    entry = sql.execute(
        "SELECT actor_id, entity_type, rationale, after_state FROM audit_logs WHERE entity_id = %s AND action = 'AGENCY_CREATED'",
        (agency["agency_id"],),
    ).fetchone()
    assert entry["actor_id"] == supervisor["user_id"] and entry["entity_type"] == "agency"
    assert entry["rationale"] == "Added after the district review" and entry["after_state"]["name"] == name


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "A"},
        {"agency_type": "ALIENS"},
        {"contact_email": "not-an-email"},
        {"contact_phone": "call me maybe"},
        {"contact_email": None, "contact_phone": None},  # no way to reach them
        {"contact_email": "  ", "contact_phone": None},
        {"reason": "no"},
    ],
)
def test_an_agency_needs_a_valid_name_type_contact_and_reason(client, make, changes):
    assert _create(client, make.staff("SUPERVISOR"), **changes).status_code == 422


def test_an_email_alone_or_a_phone_alone_is_enough(client, make):
    supervisor = make.staff("SUPERVISOR")
    assert _create(client, supervisor, contact_phone=None).status_code == 201
    assert _create(client, supervisor, contact_email=None).status_code == 201


def test_two_agencies_cannot_share_a_name_whatever_the_capitalisation(client, make):
    supervisor = make.staff("SUPERVISOR")
    first = _create(client, supervisor).json()
    again = _create(client, supervisor, name=first["name"].upper())
    assert again.status_code == 409 and again.json()["error"]["code"] == "DUPLICATE_NAME"


def test_editing_an_agency_records_before_and_after(client, make, sql):
    supervisor = make.staff("SUPERVISOR")
    agency = _create(client, supervisor).json()
    edited = client.put(
        f"{URL}/{agency['agency_id']}",
        headers=supervisor["headers"],
        json=_body(name=agency["name"], contact_phone="1070", reason="The control room number changed"),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["contact_phone"] == "1070"

    entry = sql.execute(
        "SELECT rationale, before_state, after_state FROM audit_logs WHERE entity_id = %s AND action = 'AGENCY_UPDATED'",
        (agency["agency_id"],),
    ).fetchone()
    assert entry["rationale"] == "The control room number changed"
    assert entry["before_state"]["contact_phone"] == "07923250100" and entry["after_state"]["contact_phone"] == "1070"


def test_edit_guards(client, make):
    supervisor = make.staff("SUPERVISOR")
    one, two = _create(client, supervisor).json(), _create(client, supervisor).json()
    same = client.put(f"{URL}/{one['agency_id']}", headers=supervisor["headers"], json=_body(name=one["name"]))
    assert same.status_code == 409 and same.json()["error"]["code"] == "NO_CHANGE"  # identical details
    clash = client.put(f"{URL}/{one['agency_id']}", headers=supervisor["headers"], json=_body(name=two["name"], contact_phone="1070"))
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "DUPLICATE_NAME"
    assert client.put(f"{URL}/{uuid.uuid4()}", headers=supervisor["headers"], json=_body()).status_code == 404
    assert client.put(f"{URL}/not-a-uuid", headers=supervisor["headers"], json=_body()).status_code == 422


def test_deactivating_stops_new_dispatches_and_can_be_undone(client, make, sql):
    supervisor, dispatcher = make.staff("SUPERVISOR"), make.staff("DISPATCH", "SUPERVISOR")
    agency = _create(client, supervisor).json()
    url = f"{URL}/{agency['agency_id']}"

    off = client.put(url, headers=supervisor["headers"], json=_body(name=agency["name"], is_active=False, reason="Contract has ended"))
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert sql.execute(
        "SELECT 1 FROM audit_logs WHERE entity_id = %s AND action = 'AGENCY_DEACTIVATED'", (agency["agency_id"],)
    ).fetchone()

    incident, team = make.incident(status="VERIFIED", verified_priority="HIGH"), make.resource()
    dispatch_body = {
        "receiving_agency_id": agency["agency_id"],
        "instructions": "Send a boat team to the junction",
        "resources": [{"resource_id": str(team["resource_id"]), "quantity": 1}],
    }
    blocked = client.post(f"{DM}/incidents/{incident['incident_id']}/dispatches", headers=dispatcher["headers"], json=dispatch_body)
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "UNKNOWN_AGENCY"

    on = client.put(url, headers=supervisor["headers"], json=_body(name=agency["name"], is_active=True, reason="Contract renewed"))
    assert on.status_code == 200 and on.json()["is_active"] is True
    assert sql.execute(
        "SELECT 1 FROM audit_logs WHERE entity_id = %s AND action = 'AGENCY_REACTIVATED'", (agency["agency_id"],)
    ).fetchone()
    ok = client.post(f"{DM}/incidents/{incident['incident_id']}/dispatches", headers=dispatcher["headers"], json=dispatch_body)
    assert ok.status_code == 201, ok.text


def test_an_agency_with_active_dispatches_cannot_be_deactivated(client, make, sql):
    supervisor = make.staff("SUPERVISOR")
    agency = _create(client, supervisor).json()
    incident = make.incident(status="VERIFIED", verified_priority="HIGH")
    sql.execute(
        "INSERT INTO dispatch_orders (dispatch_ref, incident_id, created_by, receiving_agency_id, priority) VALUES (%s, %s, %s, %s, 'HIGH')",
        (f"D-{incident['incident_ref']}"[:30], incident["incident_id"], supervisor["user_id"], agency["agency_id"]),
    )
    blocked = client.put(
        f"{URL}/{agency['agency_id']}", headers=supervisor["headers"],
        json=_body(name=agency["name"], is_active=False, reason="Trying to switch it off"),
    )
    assert blocked.status_code == 409
    error = blocked.json()["error"]
    assert error["code"] == "AGENCY_IN_USE" and error["details"]["active_dispatches"] == 1
    assert _listed(client, supervisor)[agency["agency_id"]]["is_active"] is True  # unchanged


def test_only_a_supervisor_can_change_the_directory(client, make):
    agency = _create(client, make.staff("SUPERVISOR")).json()
    url = f"{URL}/{agency['agency_id']}"
    admin = make.user("APP_MGMT")
    for headers in (
        {},
        make.citizen()["headers"],
        make.field_team_user()["headers"],
        make.token(admin),
        make.token(make.user("DISASTER_MGMT", ("SUPERVISOR",)), mfa=False),
    ):
        assert client.post(URL, headers=headers, json=_body()).status_code in (401, 403)
        assert client.put(url, headers=headers, json=_body(name=agency["name"], contact_phone="1070")).status_code in (401, 403)
    for permissions in ((), ("DISPATCH",), ("DISPATCH", "CLOSURE", "PUBLISHER", "MODERATOR")):
        staff = make.staff(*permissions)
        denied = client.post(URL, headers=staff["headers"], json=_body())
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "PERMISSION_REQUIRED", permissions
        assert client.put(url, headers=staff["headers"], json=_body(name=agency["name"], contact_phone="1070")).status_code == 403
    assert _listed(client, make.staff("SUPERVISOR"))[agency["agency_id"]]["contact_phone"] == "07923250100"  # nothing changed
