"""CSV exports of the incident and dispatch queues."""

import csv
import io

import pytest

pytestmark = pytest.mark.db

INCIDENTS = "/api/v1/dm/incidents/export"
DISPATCHES = "/api/v1/dm/dispatches/export"


def _rows(response) -> list[list[str]]:
    assert response.status_code == 200, response.text
    text = response.content.decode("utf-8")
    assert text.startswith(chr(0xFEFF)), "a byte order mark lets Excel read UTF-8"
    return list(csv.reader(io.StringIO(text.lstrip(chr(0xFEFF)))))


def test_the_incident_export_is_a_csv_attachment_with_the_expected_columns(make, client):
    staff = make.staff()
    incident = make.incident(address_text="Riverfront Road, Ahmedabad", landmark="Near the bridge")
    response = client.get(INCIDENTS, headers=staff["headers"], params={"q": incident["incident_ref"]})
    rows = _rows(response)

    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="incidents-')
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-export-truncated"] == "false"
    assert rows[0] == [
        "Reference", "Scenario", "Status", "Priority", "Reported urgency", "People affected", "Address", "Landmark",
        "Latitude", "Longitude", "Submitted", "Updated", "Closed", "Evidence files", "Active dispatches",
    ]
    assert len(rows) == 2
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["Reference"] == incident["incident_ref"] and row["Address"] == "Riverfront Road, Ahmedabad"
    assert row["Status"] == "SUBMITTED" and row["People affected"] == "12" and row["Evidence files"] == "0"
    assert row["Submitted"].endswith(" UTC")


def test_the_incident_export_never_contains_who_reported_it_or_what_they_wrote(make, client):
    staff = make.staff()
    reporter = make.user("NORMAL_USER", mfa=False)
    incident = make.incident(
        reporter_id=reporter["user_id"], description="Please call me urgently, my husband is trapped upstairs."
    )
    body = client.get(INCIDENTS, headers=staff["headers"], params={"q": incident["incident_ref"]}).content.decode("utf-8")
    assert incident["incident_ref"] in body
    assert reporter["email"] not in body and "+910000000000" not in body
    assert "husband" not in body and "Test Normal_User" not in body


def test_text_a_spreadsheet_would_run_as_a_formula_is_defused(make, client):
    staff = make.staff()
    incident = make.incident(address_text="=HYPERLINK(\"http://evil.test\",\"click\")", landmark="@SUM(1+1)")
    rows = _rows(client.get(INCIDENTS, headers=staff["headers"], params={"q": incident["incident_ref"]}))
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["Address"].startswith("'=") and row["Landmark"].startswith("'@")


def test_the_export_uses_the_same_filters_as_the_list(make, client):
    staff = make.staff()
    incident = make.incident()
    ref = incident["incident_ref"]
    for params in (
        {"q": ref},
        {"q": ref, "status": "SUBMITTED"},
        {"q": ref, "status": "CLOSED"},
        {"q": ref, "scenario": "urban_flooding"},
        {"q": ref, "scenario": "cyclone"},
        {"q": ref, "priority": "UNASSIGNED"},
        {"q": ref, "priority": "CRITICAL"},
    ):
        listed = client.get("/api/v1/dm/incidents", headers=staff["headers"], params=params).json()["total"]
        exported = len(_rows(client.get(INCIDENTS, headers=staff["headers"], params=params))) - 1
        assert exported == listed, params


def test_an_export_is_audited_with_its_filters_and_row_count(make, client, sql):
    staff = make.staff()
    incident = make.incident()
    params = {"q": incident["incident_ref"], "status": ["SUBMITTED", "VERIFIED"]}
    assert client.get(INCIDENTS, headers=staff["headers"], params=params).status_code == 200

    entry = sql.execute(
        "SELECT actor_id, entity_type, entity_id, rationale, after_state FROM audit_logs "
        "WHERE action = 'INCIDENTS_EXPORTED' AND actor_id = %s ORDER BY audit_id DESC LIMIT 1",
        (staff["user_id"],),
    ).fetchone()
    assert entry["entity_type"] == "incident" and entry["entity_id"] is None
    assert entry["after_state"]["rows"] == 1 and entry["after_state"]["truncated"] is False
    assert entry["after_state"]["filters"]["q"] == incident["incident_ref"]
    assert entry["after_state"]["filters"]["status"] == ["SUBMITTED", "VERIFIED"]


def test_bad_filters_are_rejected_and_export_is_not_mistaken_for_an_id(make, client):
    staff = make.staff()
    for params in ({"status": "BOGUS"}, {"near_lat": 23.0}, {"from": "yesterday"}, {"scenario": "earthquake"}):
        assert client.get(INCIDENTS, headers=staff["headers"], params=params).status_code == 422, params
    assert client.get(DISPATCHES, headers=staff["headers"], params={"status": "BOGUS"}).status_code == 422
    # "export" must reach the export route, not the {id} route (which would answer 422 for a non-UUID).
    assert client.get(INCIDENTS, headers=staff["headers"], params={"q": "no-such-reference-zz"}).status_code == 200
    assert client.get(DISPATCHES, headers=staff["headers"], params={"active": "true"}).status_code == 200


def test_the_dispatch_export_lists_a_dispatch_with_its_agency_and_state(make, client, sql):
    staff = make.staff()
    field = make.field_team_user()
    dispatch = make.field_dispatch(field, status="REQUESTED")
    rows = _rows(client.get(DISPATCHES, headers=staff["headers"], params={"incident_id": str(dispatch["incident_id"])}))

    assert rows[0] == [
        "Dispatch", "Incident", "Scenario", "Status", "Priority", "Agency", "Requested by", "Requested",
        "Acknowledged", "Overdue", "Escalated",
    ]
    assert len(rows) == 2
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["Dispatch"] == dispatch["dispatch_ref"] and row["Incident"] == dispatch["incident"]["incident_ref"]
    assert row["Status"] == "REQUESTED" and row["Priority"] == "HIGH"
    assert row["Overdue"] in ("yes", "no") and row["Escalated"] == "no"
    assert "Deploy team immediately" not in ",".join(rows[1])  # instructions stay in the system

    entry = sql.execute(
        "SELECT after_state FROM audit_logs WHERE action = 'DISPATCHES_EXPORTED' AND actor_id = %s ORDER BY audit_id DESC LIMIT 1",
        (staff["user_id"],),
    ).fetchone()
    assert entry["after_state"]["rows"] == 1 and entry["after_state"]["filters"]["incident_id"] == str(dispatch["incident_id"])

    none = _rows(client.get(DISPATCHES, headers=staff["headers"], params={"incident_id": str(dispatch["incident_id"]), "status": "COMPLETED"}))
    assert len(none) == 1  # only the header


def test_only_disaster_management_staff_can_export(make, client):
    for url in (INCIDENTS, DISPATCHES):
        admin = make.user("APP_MGMT")
        for headers in ({}, make.citizen()["headers"], make.field_team_user()["headers"], make.token(admin), make.token(make.user("DISASTER_MGMT"), mfa=False)):
            assert client.get(url, headers=headers).status_code in (401, 403)
        assert client.get(url, headers=make.staff()["headers"], params={"q": "no-such-reference-zz"}).status_code == 200
