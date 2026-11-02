"""Signal queue and promotion (contract s.4.2-4.3)."""

import uuid

import pytest

pytestmark = pytest.mark.db


def _signal(sql, **fields):
    values = {"source": "REPLAY", "source_uid": uuid.uuid4().hex, "content_text": "Water rising rapidly near Ashram Road underpass",
              "ai_label": "URBAN_FLOODING", "ai_confidence": 0.88, "latitude": 23.045, "longitude": 72.568,
              "location_text": "Ashram Road, Ahmedabad", "is_simulated": True}
    values.update(fields)
    cols = ", ".join(values)
    return sql.execute(f"INSERT INTO source_signals ({cols}) VALUES ({', '.join(['%s'] * len(values))}) RETURNING *",
                       list(values.values())).fetchone()


def test_promote_creates_unpublished_incident(client, make, sql):
    sig = _signal(sql)
    staff = make.staff("PUBLISHER")
    r = client.post(f"/api/v1/dm/signals/{sig['signal_id']}/promote", headers=staff["headers"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PROMOTED" and body["incident_status"] == "SUBMITTED"
    assert body["incident_ref"] not in {i["reference"] for i in client.get("/api/v1/public/incidents").json()}
    assert client.post(f"/api/v1/dm/signals/{sig['signal_id']}/promote", headers=staff["headers"]).status_code == 409


def test_promotion_needs_publisher_or_supervisor(client, make, sql):
    sig = _signal(sql)
    assert client.post(f"/api/v1/dm/signals/{sig['signal_id']}/promote", headers=make.staff("DISPATCH")["headers"]).status_code == 403
    assert client.post(f"/api/v1/dm/signals/{sig['signal_id']}/promote", headers=make.staff("SUPERVISOR")["headers"]).status_code == 201


def test_unsupported_or_unlocated_or_foreign_signals_are_refused(client, make, sql):
    staff = make.staff("PUBLISHER")
    for fields, code in [
        ({"ai_label": "EARTHQUAKE"}, "UNSUPPORTED_SCENARIO"),
        ({"latitude": None, "longitude": None}, "NO_LOCATION"),
        ({"latitude": 26.9, "longitude": 75.8}, "OUTSIDE_GUJARAT"),
    ]:
        sig = _signal(sql, **fields)
        r = client.post(f"/api/v1/dm/signals/{sig['signal_id']}/promote", headers=staff["headers"])
        assert r.status_code == 422 and r.json()["error"]["code"] == code, (fields, r.text)


def test_list_and_dismiss(client, make, sql):
    sig = _signal(sql)
    staff = make.staff("PUBLISHER")
    items = client.get("/api/v1/dm/signals?status=PENDING", headers=staff["headers"]).json()
    assert sig["signal_id"].__str__() in {i["signal_id"] for i in items}
    r = client.post(f"/api/v1/dm/signals/{sig['signal_id']}/dismiss", headers=staff["headers"], json={"rationale": "Not credible"})
    assert r.status_code == 200 and r.json()["status"] == "DISMISSED"
    assert client.get("/api/v1/dm/signals", headers=make.staff()["headers"]).status_code == 200
    assert client.get("/api/v1/dm/signals?status=BOGUS", headers=staff["headers"]).status_code == 422
