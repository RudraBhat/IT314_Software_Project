"""Internal incident notes: a shared, append-only log for Disaster Management staff only."""

import uuid

import pytest

pytestmark = pytest.mark.db


def _url(incident_id) -> str:
    return f"/api/v1/dm/incidents/{incident_id}/notes"


def test_notes_are_listed_newest_first_with_their_author(make, client):
    first, second = make.staff(), make.staff()
    incident = make.incident()
    assert client.get(_url(incident["incident_id"]), headers=first["headers"]).json() == {"items": []}

    one = client.post(_url(incident["incident_id"]), headers=first["headers"], json={"body": "Called the district office."})
    assert one.status_code == 201
    note = one.json()
    assert set(note) == {"note_id", "body", "created_at", "author_name", "mine"}
    assert note["body"] == "Called the district office." and note["mine"] is True
    assert client.post(_url(incident["incident_id"]), headers=second["headers"], json={"body": "  Boats are on the way.  "}).status_code == 201

    seen = client.get(_url(incident["incident_id"]), headers=first["headers"]).json()["items"]
    assert [n["body"] for n in seen] == ["Boats are on the way.", "Called the district office."]  # trimmed, newest first
    assert [n["mine"] for n in seen] == [False, True]  # the flag is relative to whoever is reading
    assert all(n["author_name"] for n in seen)


def test_a_note_is_audited_without_copying_its_text(make, client, sql):
    staff = make.staff()
    incident = make.incident()
    secret_text = "Caller asked us not to share the exact address."
    note = client.post(_url(incident["incident_id"]), headers=staff["headers"], json={"body": secret_text}).json()

    entry = sql.execute(
        "SELECT actor_id, entity_type, after_state FROM audit_logs WHERE entity_id = %s AND action = 'INCIDENT_NOTE_ADDED'",
        (incident["incident_id"],),
    ).fetchone()
    assert entry["actor_id"] == staff["user_id"] and entry["entity_type"] == "incident"
    assert entry["after_state"] == {"note_id": note["note_id"]}
    assert secret_text not in str(entry["after_state"])


def test_notes_are_kept_per_incident(make, client):
    staff = make.staff()
    mine, other = make.incident(), make.incident()
    client.post(_url(mine["incident_id"]), headers=staff["headers"], json={"body": "Only on the first incident."})
    assert client.get(_url(other["incident_id"]), headers=staff["headers"]).json() == {"items": []}


def test_notes_cannot_be_edited_or_deleted(make, client):
    staff = make.staff()
    incident = make.incident()
    note = client.post(_url(incident["incident_id"]), headers=staff["headers"], json={"body": "Final word."}).json()
    for method in ("put", "patch", "delete"):
        response = getattr(client, method)(f"{_url(incident['incident_id'])}/{note['note_id']}", headers=staff["headers"])
        assert response.status_code in (404, 405)
    assert [n["body"] for n in client.get(_url(incident["incident_id"]), headers=staff["headers"]).json()["items"]] == ["Final word."]


@pytest.mark.parametrize("body", [{}, {"body": ""}, {"body": "   "}, {"body": "x" * 1001}, {"body": 5}])
def test_a_note_must_have_text_of_a_sensible_length(make, client, body):
    staff = make.staff()
    incident = make.incident()
    assert client.post(_url(incident["incident_id"]), headers=staff["headers"], json=body).status_code == 422
    assert client.get(_url(incident["incident_id"]), headers=staff["headers"]).json() == {"items": []}


def test_the_longest_allowed_note_is_accepted(make, client):
    staff = make.staff()
    incident = make.incident()
    assert client.post(_url(incident["incident_id"]), headers=staff["headers"], json={"body": "x" * 1000}).status_code == 201


def test_an_unknown_incident_is_not_found(make, client):
    staff = make.staff()
    ghost = uuid.uuid4()
    assert client.get(_url(ghost), headers=staff["headers"]).status_code == 404
    assert client.post(_url(ghost), headers=staff["headers"], json={"body": "Nobody home."}).status_code == 404


def test_only_disaster_management_staff_can_read_or_write_notes(make, client):
    incident = make.incident()
    url = _url(incident["incident_id"])
    admin = make.user("APP_MGMT")
    for headers in ({}, make.citizen()["headers"], make.field_team_user()["headers"], make.token(admin)):
        assert client.get(url, headers=headers).status_code in (401, 403)
        assert client.post(url, headers=headers, json={"body": "Should not be saved."}).status_code in (401, 403)
    assert client.get(url, headers=make.staff()["headers"]).json() == {"items": []}  # nothing leaked in
