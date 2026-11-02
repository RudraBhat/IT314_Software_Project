"""Public API (docs/api_contracts.md s.1): privacy, filters, no demo fallback."""

import pytest

pytestmark = pytest.mark.db

FORBIDDEN = {"reporter_id", "reporter_name", "reporter_phone", "description", "address_text",
             "landmark", "details", "incident_id", "canonical_incident_id", "version"}


def _verified(make, **fields):
    staff = make.staff()
    base = {
        "status": "VERIFIED", "verified_priority": "HIGH", "verified_by": staff["user_id"],
        "verified_at": "2026-10-24T12:00:00Z", "district": "Surat", "latitude": 21.17024,
        "longitude": 72.83113, "scenario": "CYCLONE",
    }
    base.update(fields)
    return make.incident(**base)


def test_only_verified_dispatched_resolved_are_public(client, make):
    ok = _verified(make)
    hidden = [make.incident(), make.incident(status="REJECTED"), make.incident(status="NEEDS_INFORMATION"),
              _verified(make, status="CLOSED", closed_at="2026-10-25T00:00:00Z")]
    refs = {i["reference"] for i in client.get("/api/v1/public/incidents").json()}
    assert ok["incident_ref"] in refs
    assert not refs & {h["incident_ref"] for h in hidden}


def test_unverified_by_officer_is_not_public(client, make):
    row = make.incident(status="VERIFIED", verified_priority="HIGH", verified_by=None)
    assert row["incident_ref"] not in {i["reference"] for i in client.get("/api/v1/public/incidents").json()}


def test_no_pii_and_coordinates_rounded(client, make):
    row = _verified(make)
    item = next(i for i in client.get("/api/v1/public/incidents").json() if i["reference"] == row["incident_ref"])
    assert not FORBIDDEN & set(item)
    assert item["latitude"] == 21.1702 and item["longitude"] == 72.8311
    assert item["scenario"] == "cyclone" and item["status"] == "VERIFIED" and item["verified_priority"] == "HIGH"


def test_simulated_rows_hidden_outside_development(client, make, monkeypatch):
    from app.config import get_settings
    row = _verified(make, is_simulated=True)
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    try:
        assert row["incident_ref"] not in {i["reference"] for i in client.get("/api/v1/public/incidents").json()}
    finally:
        get_settings.cache_clear()


def test_filters(client, make):
    a = _verified(make, district="Kutch", scenario="CYCLONE", latitude=23.1139, longitude=70.0278)
    b = _verified(make, district="Surat", scenario="URBAN_FLOODING")
    by_district = {i["reference"] for i in client.get("/api/v1/public/incidents?district=kutch").json()}
    assert a["incident_ref"] in by_district and b["incident_ref"] not in by_district
    by_scn = {i["reference"] for i in client.get("/api/v1/public/incidents?scenario=urban_flooding").json()}
    assert b["incident_ref"] in by_scn and a["incident_ref"] not in by_scn
    box = {i["reference"] for i in client.get("/api/v1/public/incidents?bbox=69.5,22.5,70.5,24").json()}
    assert a["incident_ref"] in box and b["incident_ref"] not in box


def test_bad_parameters_are_422_not_demo_data(client):
    assert client.get("/api/v1/public/incidents?scenario=earthquake").status_code == 422
    assert client.get("/api/v1/public/incidents?bbox=1,2,3").status_code == 422
    assert client.get("/api/v1/public/incidents?bbox=70,25,69,20").status_code == 422


def test_campaigns_and_alerts_shape(client):
    assert client.get("/api/v1/public/campaigns").status_code == 200
    assert client.get("/api/v1/public/alerts").status_code == 200
