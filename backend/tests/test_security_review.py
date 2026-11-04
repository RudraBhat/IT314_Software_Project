"""S3-02 security review regressions: no header-trusted identity, BFF CSRF guard, no PII in /me/* and /public/*."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
BFF_DIR = ROOT / "frontend" / "src" / "app" / "api"

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
# Fields that identify a reporter or expose staff-internal reasoning to a citizen.
INTERNAL_KEYS = {"reporter_id", "reporter_name", "reporter_phone", "reporter_email", "email", "phone",
                 "password_hash", "verified_by", "priority_rationale", "dispatcher_notes", "internal_notes"}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _walk_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk_keys(inner)


def test_sqlite_stand_in_is_gone():
    for name in ("database.py", "models.py", "test_citizen_api.py"):
        assert not (BACKEND / name).exists(), f"legacy stand-in file still present: {name}"
    for name in ("database.py", "models.py", "test_citizen_api.py"):
        assert not (ROOT / name).exists()


def test_no_route_trusts_an_identity_header():
    offenders = []
    for path in list((BACKEND / "app").rglob("*.py")) + [BACKEND / "main.py"]:
        text = path.read_text(encoding="utf-8").lower()
        if "x-user-id" in text or "x_user_id" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"identity header trusted in: {offenders}"


def test_legacy_citizen_routes_are_not_mounted():
    from main import app

    legacy = [p for p in app.openapi()["paths"] if p.startswith("/api/citizen")]
    assert legacy == []


def test_every_bff_proxy_rejects_cross_site_writes():
    routes = sorted(BFF_DIR.rglob("route.ts"))
    assert len(routes) >= 4  # citizen, dm, field, session
    for route in routes:
        text = route.read_text(encoding="utf-8")
        assert "sameOrigin(" in text and "CSRF_REJECTED" in text, f"{route.relative_to(ROOT)} lacks a CSRF origin check"


@pytest.mark.db
def test_me_routes_expose_no_personal_or_internal_data(client, make):
    citizen = make.citizen()
    created = client.post("/api/v1/incidents", json=PAYLOAD, headers={**citizen["headers"], "Idempotency-Key": "s3-02-pii"})
    assert created.status_code in (200, 201), created.text
    iid = created.json()["incident_id"]
    for url in ("/api/v1/me/incidents", f"/api/v1/me/incidents/{iid}", "/api/v1/me/notifications"):
        r = client.get(url, headers=citizen["headers"])
        assert r.status_code == 200, (url, r.text)
        leaked = INTERNAL_KEYS & set(_walk_keys(r.json()))
        assert not leaked, f"{url} leaks {leaked}"


@pytest.mark.db
def test_public_routes_expose_no_personal_data(client, make):
    staff = make.staff()
    make.incident(status="VERIFIED", verified_priority="HIGH", verified_by=staff["user_id"],
                  verified_at="2026-10-24T12:00:00Z", district="Surat", latitude=21.17024,
                  longitude=72.83113, scenario="CYCLONE")
    r = client.get("/api/v1/public/incidents")
    assert r.status_code == 200
    assert not INTERNAL_KEYS & set(_walk_keys(r.json()))
