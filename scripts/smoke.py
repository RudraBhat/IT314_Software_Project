#!/usr/bin/env python3
"""ResQ core-loop smoke test - STRICT: any unexpected response fails the run (no "Notice:" fallbacks).

  1. /health and /api/v1/health respond; database is "ok"
  2. Citizen registers (contract password policy) and gets a session
  3. Citizen submits a Gujarat incident with an Idempotency-Key (replay returns the same incident)
  4. An incident outside Gujarat is refused (422 OUTSIDE_GUJARAT)
  5. The new incident is NOT on the public map while SUBMITTED
  6. Dispatcher signs in with password + TOTP and verifies the incident
  7. The verified incident IS on the public map, with no PII and 4-decimal coordinates
  8. The citizen's timeline shows SUBMITTED then VERIFIED

Usage:  python scripts/smoke.py [--base-url http://localhost:8000]
Required environment (no defaults - secrets are never baked in):
  SMOKE_STAFF_EMAIL, SMOKE_STAFF_PASSWORD, SMOKE_STAFF_TOTP_SECRET   (a DISASTER_MGMT user created with app.cli)
Optional: API_URL / SMOKE_BASE_URL
"""

import argparse
import os
import sys
import uuid

import httpx
import pyotp

BASE_URL = (os.getenv("SMOKE_BASE_URL") or os.getenv("API_URL") or "http://localhost:8000").rstrip("/")
PII_KEYS = {"reporter_id", "reporter_name", "reporter_phone", "description", "address_text", "incident_id", "email", "phone"}


def log(msg: str) -> None:
    print(f"[SMOKE] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"\n[SMOKE FAILURE] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def expect(res: httpx.Response, status: int, what: str) -> dict:
    if res.status_code != status:
        fail(f"{what}: expected HTTP {status}, got {res.status_code}: {res.text[:300]}")
    return res.json() if res.content else {}


def run(base_url: str) -> None:
    missing = [n for n in ("SMOKE_STAFF_EMAIL", "SMOKE_STAFF_PASSWORD", "SMOKE_STAFF_TOTP_SECRET") if not os.getenv(n)]
    if missing:
        fail("missing required environment variables: " + ", ".join(missing))
    client = httpx.Client(base_url=base_url, timeout=90.0)  # 90 s covers a Render cold start
    log(f"target {base_url}")

    expect(client.get("/health"), 200, "liveness")
    health = expect(client.get("/api/v1/health"), 200, "readiness")
    if health.get("database") != "ok":
        fail(f"database is not reachable: {health}")

    email, password = f"smoke.{uuid.uuid4().hex[:10]}@example.in", "Smoke-Pass-2026!"
    reg = expect(client.post("/api/v1/auth/register", json={"email": email, "password": password, "full_name": "Smoke Citizen"}), 201, "register")
    citizen = {"Authorization": f"Bearer {reg['access_token']}"}
    log("citizen registered")

    key = f"smoke-{uuid.uuid4()}"
    payload = {"scenario": "urban_flooding", "description": "Smoke test: road flooded at Subhash Bridge approach.",
               "reported_urgency": "HIGH", "people_affected": 8, "location_source": "GPS",
               "latitude": 23.0610, "longitude": 72.5810, "address_text": "Subhash Bridge, Ahmedabad"}
    created = expect(client.post("/api/v1/incidents", json=payload, headers={**citizen, "Idempotency-Key": key}), 201, "submit incident")
    ref, incident_id = created["incident_ref"], created["incident_id"]
    replay = expect(client.post("/api/v1/incidents", json=payload, headers={**citizen, "Idempotency-Key": key}), 200, "idempotent replay")
    if replay["incident_id"] != incident_id:
        fail("idempotent replay created a second incident")
    log(f"incident {ref} submitted")

    outside = client.post("/api/v1/incidents", json={**payload, "latitude": 26.9124, "longitude": 75.7873}, headers=citizen)
    if outside.status_code != 422 or outside.json()["error"]["code"] != "OUTSIDE_GUJARAT":
        fail(f"a Jaipur location must be refused with OUTSIDE_GUJARAT, got {outside.status_code}: {outside.text[:200]}")

    if ref in {i["reference"] for i in expect(client.get("/api/v1/public/incidents"), 200, "public feed")}:
        fail("an unverified incident is visible on the public map")

    step1 = expect(client.post("/api/v1/auth/login", json={"email": os.environ["SMOKE_STAFF_EMAIL"], "password": os.environ["SMOKE_STAFF_PASSWORD"]}), 200, "staff login")
    if not step1.get("mfa_required"):
        fail("staff login must require MFA")
    mfa = expect(client.post("/api/v1/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": pyotp.TOTP(os.environ["SMOKE_STAFF_TOTP_SECRET"]).now()}), 200, "MFA verify")
    staff = {"Authorization": f"Bearer {mfa['access_token']}"}

    detail = expect(client.get(f"/api/v1/dm/incidents/{incident_id}", headers=staff), 200, "DM incident detail")
    expect(client.post(f"/api/v1/dm/incidents/{incident_id}/verification", headers=staff,
                       json={"decision": "VERIFIED", "rationale": "Smoke test verification", "priority": "HIGH", "version": detail["version"]}),
           200, "verify incident")
    log("incident verified by dispatcher")

    feed = expect(client.get("/api/v1/public/incidents"), 200, "public feed")
    mine = [i for i in feed if i["reference"] == ref]
    if len(mine) != 1:
        fail("the verified incident is missing from the public map")
    if PII_KEYS & set(mine[0]):
        fail(f"PII leaked on the public feed: {PII_KEYS & set(mine[0])}")
    for field in ("latitude", "longitude"):
        if len(str(mine[0][field]).split(".")[-1]) > 4:
            fail(f"{field} has more than 4 decimal places")

    timeline = expect(client.get(f"/api/v1/me/incidents/{incident_id}", headers=citizen), 200, "citizen timeline")["timeline"]
    if [t["status"] for t in timeline] != ["SUBMITTED", "VERIFIED"]:
        fail(f"unexpected citizen timeline: {timeline}")

    print("\n[SMOKE PASSED] core loop verified end to end", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the ResQ core-loop smoke test")
    parser.add_argument("--base-url", default=BASE_URL)
    run(parser.parse_args().base_url)
