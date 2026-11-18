#!/usr/bin/env python3
"""Automated cyclone scenario, citizen report to closure, over HTTP (S3-01). Owner: Dhruv.

One run drives the real API in the order a rehearsal would:

   1. health and database readiness
   2. a new citizen registers and reports a cyclone incident in Porbandar (Idempotency-Key)
   3. the dispatcher signs in (password + TOTP) and verifies it with priority HIGH
   4. the verified incident is on the public map with no personal data and 4-decimal coordinates
   5. the dispatcher reads the advisory team recommendations (they never create a dispatch)
   6. the dispatcher dispatches the field responder's team
   7. the field responder (password + TOTP) sees the assignment, acknowledges, reports EN_ROUTE and ON_SCENE,
      and completes it
   8. the dispatcher resolves and then closes the incident
   9. the citizen's timeline shows SUBMITTED -> VERIFIED -> DISPATCHED -> RESOLVED -> CLOSED

Run it three times in a row against staging (the S3-01 "done when"):

  python scripts/scenario_run.py --base-url https://<staging-backend>.onrender.com --runs 3

Required environment (names only; values come from the person running it, never from git):
  SMOKE_STAFF_EMAIL, SMOKE_STAFF_PASSWORD, SMOKE_STAFF_TOTP_SECRET          dispatcher with DISPATCH and CLOSURE
  SCENARIO_FIELD_EMAIL, SCENARIO_FIELD_PASSWORD, SCENARIO_FIELD_TOTP_SECRET a field responder whose team is AVAILABLE
Optional: SMOKE_BASE_URL / API_URL.

Each run creates a real citizen, incident and dispatch and closes them, so use staging, not production.
The team is released when the dispatch completes, so consecutive runs can reuse it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import httpx
import pyotp

BASE_URL = (os.getenv("SMOKE_BASE_URL") or os.getenv("API_URL") or "http://localhost:8000").rstrip("/")
REQUIRED_ENV = (
    "SMOKE_STAFF_EMAIL", "SMOKE_STAFF_PASSWORD", "SMOKE_STAFF_TOTP_SECRET",
    "SCENARIO_FIELD_EMAIL", "SCENARIO_FIELD_PASSWORD", "SCENARIO_FIELD_TOTP_SECRET",
)
PII_KEYS = {"reporter_id", "reporter_name", "reporter_phone", "description", "address_text", "incident_id", "email", "phone"}
EXPECTED_TIMELINE = ["SUBMITTED", "VERIFIED", "DISPATCHED", "RESOLVED", "CLOSED"]
# Porbandar coast: inside Gujarat, a realistic cyclone landfall area.
LOCATION = {"latitude": 21.6417, "longitude": 69.6293, "address_text": "Chowpatty seafront, Porbandar"}


class ScenarioError(RuntimeError):
    pass


def missing_env(environ=os.environ) -> list[str]:
    return [name for name in REQUIRED_ENV if not environ.get(name)]


def expect(res: httpx.Response, status: int, what: str) -> dict:
    if res.status_code != status:
        raise ScenarioError(f"{what}: expected HTTP {status}, got {res.status_code}: {res.text[:300]}")
    return res.json() if res.content else {}


def timeline_matches(statuses: list[str]) -> bool:
    """The citizen timeline must contain the expected states in order (repeated states are allowed)."""
    collapsed = [s for i, s in enumerate(statuses) if i == 0 or s != statuses[i - 1]]
    return collapsed == EXPECTED_TIMELINE


def sign_in(client: httpx.Client, prefix: str) -> dict:
    """Password + TOTP sign-in for a staff or field account; returns auth headers."""
    email, password, secret = (os.environ[f"{prefix}_{part}"] for part in ("EMAIL", "PASSWORD", "TOTP_SECRET"))
    step1 = expect(client.post("/api/v1/auth/login", json={"email": email, "password": password}), 200, f"{prefix} login")
    if not step1.get("mfa_required"):
        raise ScenarioError(f"{prefix} login must require MFA")
    mfa = expect(client.post("/api/v1/auth/mfa/verify",
                             json={"mfa_token": step1["mfa_token"], "code": pyotp.TOTP(secret).now()}),
                 200, f"{prefix} MFA verify")
    return {"Authorization": f"Bearer {mfa['access_token']}"}


def run_once(client: httpx.Client, run_no: int, log) -> dict:
    steps: dict[str, float] = {}
    started = time.perf_counter()

    def mark(name: str) -> None:
        steps[name] = round(time.perf_counter() - started, 2)
        log(f"run {run_no}: {name}")

    expect(client.get("/health"), 200, "liveness")
    if expect(client.get("/api/v1/health"), 200, "readiness").get("database") != "ok":
        raise ScenarioError("database is not reachable")
    mark("health")

    email = f"scenario.{uuid.uuid4().hex[:10]}@example.in"
    reg = expect(client.post("/api/v1/auth/register",
                             json={"email": email, "password": "Scenario-Pass-2026!", "full_name": "Scenario Citizen"}),
                 201, "citizen register")
    citizen = {"Authorization": f"Bearer {reg['access_token']}"}
    report = {"scenario": "cyclone", "reported_urgency": "HIGH", "people_affected": 15, "location_source": "GPS",
              "description": "SCENARIO TEST: roofs blown off near the seafront, families need shelter.", **LOCATION}
    created = expect(client.post("/api/v1/incidents", json=report,
                                 headers={**citizen, "Idempotency-Key": f"scenario-{uuid.uuid4()}"}),
                     201, "submit cyclone report")
    incident_id, ref = created["incident_id"], created["incident_ref"]
    mark("citizen report")

    staff = sign_in(client, "SMOKE_STAFF")
    detail = expect(client.get(f"/api/v1/dm/incidents/{incident_id}", headers=staff), 200, "incident detail")
    expect(client.post(f"/api/v1/dm/incidents/{incident_id}/verification", headers=staff,
                       json={"decision": "VERIFIED", "priority": "HIGH", "version": detail["version"],
                             "rationale": "Scenario test: confirmed by the coastal control room"}),
           200, "verify")
    mark("verified")

    public = [i for i in expect(client.get("/api/v1/public/incidents"), 200, "public map") if i["reference"] == ref]
    if len(public) != 1:
        raise ScenarioError("the verified incident is missing from the public map")
    if PII_KEYS & set(public[0]):
        raise ScenarioError(f"personal data on the public map: {PII_KEYS & set(public[0])}")
    for coord in ("latitude", "longitude"):
        if len(str(public[0][coord]).split(".")[-1]) > 4:
            raise ScenarioError(f"public {coord} has more than 4 decimals")
    mark("public map")

    recs = expect(client.get(f"/api/v1/dm/incidents/{incident_id}/team-recommendations", headers=staff),
                  200, "team recommendations")
    if recs.get("requires_confirmation") is not True:
        raise ScenarioError("recommendations must require dispatcher confirmation")
    mark("recommendations")

    field = sign_in(client, "SCENARIO_FIELD")
    profile = expect(client.get("/api/v1/field/me", headers=field), 200, "field profile")
    if not profile.get("agency_id"):
        raise ScenarioError("the field responder's team has no agency; assign one before running the scenario")
    dispatch = expect(client.post(
        f"/api/v1/dm/incidents/{incident_id}/dispatches",
        headers={**staff, "Idempotency-Key": f"scenario-{uuid.uuid4()}"},
        json={"receiving_agency_id": profile["agency_id"],
              "instructions": "Scenario test: open the shelter and check the seafront houses.",
              "resources": [{"resource_id": profile["team_resource_id"], "quantity": 1}]},
    ), 201, "create dispatch")
    dispatch_id = dispatch["dispatch_id"]
    mark("dispatched")

    assignments = expect(client.get("/api/v1/field/assignments", headers=field), 200, "field assignments")
    if dispatch_id not in {a["dispatch_id"] for a in assignments}:
        raise ScenarioError("the field responder does not see the new assignment")
    base = f"/api/v1/field/dispatches/{dispatch_id}"
    expect(client.post(f"{base}/acknowledgement", headers=field), 200, "acknowledge")
    for event in ("EN_ROUTE", "ON_SCENE"):
        expect(client.post(f"{base}/progress", headers=field, json={"status": event, "note": f"Scenario test: {event}"}),
               200, f"progress {event}")
    expect(client.post(f"{base}/completion", headers=field,
                       json={"summary": "Scenario test: 15 people moved to the school shelter.", "civilians_evacuated": 15}),
           200, "complete")
    mark("field flow")

    version = expect(client.get(f"/api/v1/dm/incidents/{incident_id}", headers=staff), 200, "incident detail")["version"]
    resolved = expect(client.post(f"/api/v1/dm/incidents/{incident_id}/resolution", headers=staff,
                                  json={"rationale": "Scenario test: everyone sheltered", "version": version}),
                      200, "resolve")
    expect(client.post(f"/api/v1/dm/incidents/{incident_id}/closure", headers=staff,
                       json={"reason": "Scenario test complete", "version": resolved["version"],
                             "public_summary": "Families sheltered; area safe."}),
           200, "close")
    mark("closed")

    timeline = expect(client.get(f"/api/v1/me/incidents/{incident_id}", headers=citizen), 200, "citizen timeline")
    statuses = [t["status"] for t in timeline["timeline"]]
    if not timeline_matches(statuses):
        raise ScenarioError(f"unexpected citizen timeline: {statuses}")
    mark("citizen timeline")
    return {"run": run_no, "incident_ref": ref, "seconds": steps["citizen timeline"], "steps": steps}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ResQ cyclone scenario end to end")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--runs", type=int, default=1, help="consecutive runs (S3-01 asks for 3)")
    parser.add_argument("--json", action="store_true", help="print a JSON summary at the end")
    args = parser.parse_args()
    missing = missing_env()
    if missing:
        print("missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2

    def log(message: str) -> None:
        if not args.json:
            print(f"[SCENARIO] {message}", flush=True)

    results, failures = [], 0
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=90.0) as client:  # covers a Render cold start
        for run_no in range(1, args.runs + 1):
            try:
                results.append({**run_once(client, run_no, log), "passed": True})
            except (ScenarioError, httpx.HTTPError) as exc:
                failures += 1
                results.append({"run": run_no, "passed": False, "error": str(exc)})
                log(f"run {run_no} FAILED: {exc}")

    if args.json:
        print(json.dumps({"base_url": args.base_url, "runs": results}, indent=2))
    else:
        passed = args.runs - failures
        print(f"\n[SCENARIO] {passed}/{args.runs} runs passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
