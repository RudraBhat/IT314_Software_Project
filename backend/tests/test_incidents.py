"""Dashboard, incident queue, verification workflow, duplicates and closure."""

import pytest

pytestmark = pytest.mark.db

BASE = "/api/v1/dm"


def test_dashboard_counts_follow_real_data(client, make):
    staff = make.staff()
    before = client.get(f"{BASE}/dashboard", headers=staff["headers"]).json()
    make.incident()
    make.incident(status="NEEDS_INFORMATION")
    make.incident(status="VERIFIED", verified_priority="CRITICAL")
    after = client.get(f"{BASE}/dashboard", headers=staff["headers"]).json()
    assert after["incidents"]["total"] - before["incidents"]["total"] == 3
    assert after["incidents"]["pending_verification"] - before["incidents"]["pending_verification"] == 2
    assert after["incidents"]["critical_open"] - before["incidents"]["critical_open"] == 1
    assert after["incidents"]["verified_active"] - before["incidents"]["verified_active"] == 1
    assert after["data_fresh_as_of"] is not None


def test_list_filters_and_pagination(client, make):
    staff = make.staff()
    tag = make.incident()["address_text"].split("-")[1]  # unique fragment
    make.incident(address_text=f"Junction-{tag}-b", scenario="CYCLONE")
    make.incident(address_text=f"Junction-{tag}-c", scenario="CYCLONE", status="REJECTED")

    def query(**params):
        r = client.get(f"{BASE}/incidents", headers=staff["headers"], params={"q": tag, **params})
        assert r.status_code == 200, r.text
        return r.json()

    assert query()["total"] == 3
    assert query(scenario="cyclone")["total"] == 2
    assert query(scenario="cyclone", status="REJECTED")["total"] == 1
    assert query(priority="UNASSIGNED")["total"] == 3
    page = query(limit=2, page=2)
    assert page["pages"] == 2 and len(page["items"]) == 1
    assert all(i["scenario"] in ("cyclone", "urban_flooding") for i in query()["items"])


def test_unsupported_scenario_is_rejected(client, make):
    staff = make.staff()
    r = client.get(f"{BASE}/incidents", headers=staff["headers"], params={"scenario": "earthquake"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_SCENARIO"


def test_location_filter(client, make):
    staff = make.staff()
    near = make.incident(latitude=19.0760, longitude=72.8777)
    r = client.get(
        f"{BASE}/incidents",
        headers=staff["headers"],
        params={"near_lat": 19.0761, "near_lon": 72.8778, "radius_km": 1, "limit": 100},
    )
    assert near["incident_ref"] in [i["incident_ref"] for i in r.json()["items"]]


def test_detail_includes_reporter_and_never_secrets(client, make):
    staff = make.staff()
    inc = make.incident()
    r = client.get(f"{BASE}/incidents/{inc['incident_id']}", headers=staff["headers"])
    body = r.json()
    assert r.status_code == 200
    assert body["reporter"]["email"].endswith("@test.drch")
    assert body["allowed_actions"]["verify"] is True
    assert "password_hash" not in r.text


def test_verification_requires_priority(client, make):
    staff = make.staff()
    inc = make.incident()
    r = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/verification",
        headers=staff["headers"],
        json={"decision": "VERIFIED", "rationale": "Photo and two reports agree", "version": 1},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PRIORITY_REQUIRED"


def test_verify_records_history_audit_and_reporter_notification(client, make, sql):
    staff = make.staff()
    inc = make.incident()
    r = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/verification",
        headers=staff["headers"],
        json={"decision": "VERIFIED", "rationale": "Confirmed by field photo", "priority": "HIGH", "version": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"incident_id": str(inc["incident_id"]), "status": "VERIFIED", "version": 2}
    row = sql.execute("SELECT * FROM incidents WHERE incident_id = %s", (inc["incident_id"],)).fetchone()
    assert row["verified_by"] == staff["user_id"] and row["verified_priority"] == "HIGH"
    hist = sql.execute(
        "SELECT from_status, to_status, changed_by FROM incident_status_history WHERE incident_id = %s",
        (inc["incident_id"],),
    ).fetchall()
    assert hist == [{"from_status": "SUBMITTED", "to_status": "VERIFIED", "changed_by": staff["user_id"]}]
    assert sql.execute(
        "SELECT 1 FROM audit_logs WHERE entity_id = %s AND action = 'INCIDENT_VERIFIED'", (inc["incident_id"],)
    ).fetchone()
    assert sql.execute(
        "SELECT 1 FROM notifications WHERE user_id = %s AND event_code = 'INCIDENT_VERIFIED'", (inc["reporter_id"],)
    ).fetchone()


def test_stale_version_is_a_conflict(client, make):
    staff = make.staff()
    inc = make.incident()
    url = f"{BASE}/incidents/{inc['incident_id']}/priority"
    first = client.put(url, headers=staff["headers"], json={"priority": "LOW", "rationale": "first", "version": 1})
    assert first.status_code == 200
    stale = client.put(url, headers=staff["headers"], json={"priority": "HIGH", "rationale": "stale", "version": 1})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_invalid_transitions_are_refused(client, make):
    staff = make.staff()
    verified = make.incident(status="VERIFIED", verified_priority="HIGH")
    r = client.post(
        f"{BASE}/incidents/{verified['incident_id']}/verification",
        headers=staff["headers"],
        json={"decision": "REJECTED", "rationale": "changed my mind", "version": 1},
    )
    assert r.status_code == 409
    submitted = make.incident()
    r = client.post(
        f"{BASE}/incidents/{submitted['incident_id']}/resolution",
        headers=staff["headers"],
        json={"rationale": "nothing to do", "version": 1},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_TRANSITION"


def test_information_request_and_rejection(client, make, sql):
    staff = make.staff()
    inc = make.incident(scenario="CYCLONE")
    r = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/information-requests",
        headers=staff["headers"],
        json={"question": "Which shelter area is affected?", "version": 1},
    )
    assert r.status_code == 201 and r.json()["status"] == "NEEDS_INFORMATION"
    r = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/verification",
        headers=staff["headers"],
        json={"decision": "REJECTED", "rationale": "No response and no evidence", "version": 2},
    )
    assert r.json()["status"] == "REJECTED"
    note = sql.execute(
        "SELECT body FROM notifications WHERE related_id = %s AND event_code = 'INCIDENT_INFORMATION_REQUESTED'",
        (inc["incident_id"],),
    ).fetchone()
    assert note["body"] == "Which shelter area is affected?"


def test_closure_needs_permission_reason_and_resolved_dependencies(client, make, sql):
    plain = make.staff()
    closer = make.staff("CLOSURE")
    inc = make.incident(status="VERIFIED", verified_priority="HIGH")
    agency = make.agency()
    sql.execute(
        "INSERT INTO dispatch_orders (dispatch_ref, incident_id, created_by, receiving_agency_id, priority) "
        "VALUES (%s, %s, %s, %s, 'HIGH')",
        (f"D-{inc['incident_ref']}"[:30], inc["incident_id"], closer["user_id"], agency["agency_id"]),
    )
    url = f"{BASE}/incidents/{inc['incident_id']}/closure"
    body = {"reason": "Flood water receded", "version": 1}
    assert client.post(url, headers=plain["headers"], json=body).status_code == 403
    blocked = client.post(url, headers=closer["headers"], json=body)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "OPEN_DEPENDENCIES"
    assert len(blocked.json()["error"]["details"]["dispatches"]) == 1
    missing = client.post(url, headers=closer["headers"], json={**body, "override": True})
    assert missing.status_code == 422
    ok = client.post(
        url, headers=closer["headers"], json={**body, "override": True, "override_rationale": "Agency confirmed by phone"}
    )
    assert ok.status_code == 200 and ok.json()["status"] == "CLOSED"

    # Closed incidents are frozen...
    frozen = client.put(
        f"{BASE}/incidents/{inc['incident_id']}/priority",
        headers=closer["headers"],
        json={"priority": "LOW", "rationale": "x" * 5, "version": 2},
    )
    assert frozen.status_code == 409 and frozen.json()["error"]["code"] == "INCIDENT_CLOSED"
    # ...until reopened, which restores the previous state and is audited.
    reopened = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/reopen",
        headers=closer["headers"],
        json={"reason": "Water rising again", "version": 2},
    )
    assert reopened.json()["status"] == "VERIFIED"
    row = sql.execute("SELECT closed_at FROM incidents WHERE incident_id = %s", (inc["incident_id"],)).fetchone()
    assert row["closed_at"] is None


def _close_and_reopen(client, closer, incident_id, version):
    """Close an incident and reopen it, returning the reopen response."""
    closed = client.post(
        f"{BASE}/incidents/{incident_id}/closure",
        headers=closer["headers"],
        json={"reason": "Closing for the test", "override": True, "override_rationale": "Nothing is open", "version": version},
    )
    assert closed.status_code == 200, closed.text
    return client.post(
        f"{BASE}/incidents/{incident_id}/reopen",
        headers=closer["headers"],
        json={"reason": "It needs more work", "version": closed.json()["version"]},
    )


def test_a_reopened_resolved_incident_can_be_dispatched_again(client, make):
    staff = make.staff("CLOSURE", "DISPATCH")
    inc = make.incident(status="VERIFIED", verified_priority="HIGH")
    resolved = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/resolution",
        headers=staff["headers"],
        json={"rationale": "Water has receded", "version": 1},
    )
    assert resolved.json()["status"] == "RESOLVED"

    reopened = _close_and_reopen(client, staff, inc["incident_id"], resolved.json()["version"])
    assert reopened.status_code == 200 and reopened.json()["status"] == "VERIFIED"  # not stranded as RESOLVED
    detail = client.get(f"{BASE}/incidents/{inc['incident_id']}", headers=staff["headers"]).json()
    assert detail["allowed_actions"]["dispatch"] is True and detail["allowed_actions"]["resolve"] is True


def test_a_reopened_rejected_report_goes_back_for_a_fresh_decision(client, make):
    staff = make.staff("CLOSURE")
    inc = make.incident()
    rejected = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/verification",
        headers=staff["headers"],
        json={"decision": "REJECTED", "rationale": "Looked like a duplicate", "version": 1},
    )
    assert rejected.json()["status"] == "REJECTED"

    reopened = _close_and_reopen(client, staff, inc["incident_id"], rejected.json()["version"])
    assert reopened.status_code == 200 and reopened.json()["status"] == "SUBMITTED"
    verified = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/verification",
        headers=staff["headers"],
        json={"decision": "VERIFIED", "rationale": "It was genuine after all", "priority": "HIGH", "version": reopened.json()["version"]},
    )
    assert verified.status_code == 200 and verified.json()["status"] == "VERIFIED"


def test_duplicate_candidates_link_dismiss_and_merge(client, make, sql):
    staff = make.staff()
    a = make.incident(latitude=21.1702, longitude=72.8311)
    b = make.incident(latitude=21.1705, longitude=72.8313)  # ~40 m away, same scenario
    c = make.incident(latitude=21.1703, longitude=72.8312)
    far = make.incident(latitude=21.30, longitude=72.95)

    r = client.get(f"{BASE}/incidents/{a['incident_id']}/duplicates", headers=staff["headers"]).json()
    ids = {x["incident_id"] for x in r["candidates"]}
    assert str(b["incident_id"]) in ids and str(c["incident_id"]) in ids
    assert str(far["incident_id"]) not in ids
    assert "m apart" in r["candidates"][0]["rationale"]

    def decide(candidate, action):
        return client.post(
            f"{BASE}/incidents/{a['incident_id']}/duplicates/{candidate['incident_id']}/decision",
            headers=staff["headers"],
            json={"action": action, "rationale": "Same junction, same photos"},
        )

    assert decide(b, "LINK").status_code == 200
    assert decide(c, "DISMISS").status_code == 200
    r = client.get(f"{BASE}/incidents/{a['incident_id']}/duplicates", headers=staff["headers"]).json()
    remaining = {x["incident_id"] for x in r["candidates"]}
    assert str(b["incident_id"]) not in remaining and str(c["incident_id"]) not in remaining

    d = make.incident(latitude=21.1702, longitude=72.8311)
    assert decide(d, "MERGE").status_code == 200
    merged = sql.execute("SELECT status, canonical_incident_id FROM incidents WHERE incident_id = %s",
                         (d["incident_id"],)).fetchone()
    assert merged == {"status": "REJECTED", "canonical_incident_id": a["incident_id"]}
    # Originals are never deleted.
    assert sql.execute("SELECT COUNT(*) AS n FROM incidents WHERE incident_id = ANY(%s)",
                       ([a["incident_id"], b["incident_id"], c["incident_id"], d["incident_id"]],)).fetchone()["n"] == 4
