"""Administrator audit log viewer: GET /api/v1/admin/audit and POST /api/v1/admin/audit/verify."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.db

AUDIT = "/api/v1/admin/audit"
VERIFY = "/api/v1/admin/audit/verify"
ACCOUNTS = "/api/v1/admin/accounts"
REASON = {"reason": "Left the organisation; access no longer needed"}
ALLOWED_ENTITY_TYPES = {"user", "route", "audit"}


def _admin(make):
    admin = make.user("APP_MGMT")
    return admin, make.token(admin)


def _audit(client, headers, **params):
    r = client.get(AUDIT, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_account_changes_show_who_did_what_to_whom_and_why(make, client):
    admin, headers = _admin(make)
    staff = make.staff("DISPATCH")
    assert client.post(f"{ACCOUNTS}/{staff['user_id']}/disable", headers=headers, json=REASON).status_code == 200

    body = _audit(client, headers, user_id=str(staff["user_id"]), action="ACCOUNT_DISABLED")
    assert body["total"] == 1
    item = body["items"][0]
    assert item["actor"]["email"] == admin["email"] and item["actor"]["role"] == "APP_MGMT" and item["actor"]["name"]
    assert item["target"]["email"] == staff["email"] and item["target"]["role"] == "DISASTER_MGMT"
    assert item["rationale"] == REASON["reason"] and item["result"] == "SUCCESS"
    assert item["before"]["status"] == "ACTIVE" and item["after"]["status"] == "DISABLED"
    assert "ACCOUNT_DISABLED" in body["facets"]["actions"]


def test_a_citizen_is_never_identified(make, client):
    _, headers = _admin(make)
    citizen = make.citizen()
    assert client.patch("/api/v1/me/profile", headers=citizen["headers"], json={"preferred_language": "gu", "full_name": "Secret Citizen Name"}).status_code == 200

    response = client.get(AUDIT, headers=headers, params={"user_id": str(citizen["user_id"])})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    item = next(i for i in body["items"] if i["action"] == "PROFILE_UPDATED")
    assert item["actor"] == {"user_id": None, "role": "NORMAL_USER", "name": None, "email": None}
    assert item["target"] == {"role": "NORMAL_USER", "name": None, "email": None}
    assert item["ip"] is None and item["before"] is None and item["after"] is None
    assert citizen["email"] not in response.text and "Secret Citizen Name" not in response.text
    # searching by a citizen's email must not find their rows either
    assert _audit(client, headers, q=citizen["email"])["total"] == 0


def test_operational_entries_are_never_listed(make, client):
    _, headers = _admin(make)
    citizen = make.citizen()
    created = client.post(
        "/api/v1/incidents",
        headers={**citizen["headers"], "Idempotency-Key": str(uuid.uuid4())},
        json={"scenario": "urban_flooding", "description": "Severe waterlogging on the main market road.", "latitude": 23.0225, "longitude": 72.5714},
    )
    assert created.status_code == 201, created.text
    body = _audit(client, headers, limit=100)
    assert body["items"] and {i["entity_type"] for i in body["items"]} <= ALLOWED_ENTITY_TYPES
    assert not any(i["action"].startswith(("INCIDENT_", "DISPATCH_", "DONATION_")) for i in body["items"])
    mine = _audit(client, headers, user_id=str(citizen["user_id"]))
    assert all(i["entity_type"] in ALLOWED_ENTITY_TYPES for i in mine["items"])


def test_denied_requests_are_listed_with_the_staff_member(make, client):
    _, headers = _admin(make)
    dispatcher = make.staff("DISPATCH")
    assert client.get(ACCOUNTS, headers=dispatcher["headers"]).status_code == 403
    body = _audit(client, headers, user_id=str(dispatcher["user_id"]), result="DENIED")
    item = body["items"][0]
    assert item["action"] == "ACCESS_DENIED" and item["entity_type"] == "route" and item["result"] == "DENIED"
    assert item["actor"]["email"] == dispatcher["email"] and "/api/v1/admin/accounts" in item["rationale"]


def test_filters_paging_order_and_dates(make, client):
    _, headers = _admin(make)
    staff = make.staff("DISPATCH")
    uid = str(staff["user_id"])
    for url in ("disable", "enable"):
        assert client.post(f"{ACCOUNTS}/{staff['user_id']}/{url}", headers=headers, json=REASON).status_code == 200

    page1 = _audit(client, headers, user_id=uid, limit=1, page=1)
    page2 = _audit(client, headers, user_id=uid, limit=1, page=2)
    assert page1["total"] == 2 and page1["pages"] == 2
    assert page1["items"][0]["action"] == "ACCOUNT_ENABLED" and page2["items"][0]["action"] == "ACCOUNT_DISABLED"  # newest first

    assert _audit(client, headers, user_id=uid, action="ACCOUNT_DISABLED")["total"] == 1
    assert _audit(client, headers, user_id=uid, result="FAILURE")["total"] == 0
    assert _audit(client, headers, user_id=uid, q="enabled")["total"] == 1  # matches the action text
    today = datetime.now(UTC).date()
    inside = _audit(client, headers, user_id=uid, **{"from": str(today - timedelta(days=1)), "to": str(today + timedelta(days=1))})
    assert inside["total"] == 2
    assert _audit(client, headers, user_id=uid, to="2020-01-01")["total"] == 0
    assert client.get(AUDIT, headers=headers, params={"from": "2026-02-01", "to": "2026-01-01"}).status_code == 422


@pytest.mark.parametrize("params", [{"result": "BOGUS"}, {"limit": 0}, {"user_id": "not-a-uuid"}, {"from": "yesterday"}])
def test_invalid_filters_are_rejected(make, client, params):
    _, headers = _admin(make)
    assert client.get(AUDIT, headers=headers, params=params).status_code == 422


def test_verify_reports_a_broken_chain_and_records_the_check(make, client, monkeypatch):
    admin, headers = _admin(make)
    monkeypatch.setattr("app.audit.verify_audit_chain", lambda conn: (False, 3, "Tampering detected at audit_id 5: broken chain link."))
    r = client.post(VERIFY, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False and body["mismatches"] == 3 and body["records"] is None and "Tampering" in body["message"]
    entry = _audit(client, headers, user_id=str(admin["user_id"]), action="AUDIT_CHAIN_VERIFIED")["items"][0]
    assert entry["result"] == "FAILURE" and entry["entity_type"] == "audit"


def test_verify_reports_an_intact_chain(make, client, monkeypatch):
    _, headers = _admin(make)
    monkeypatch.setattr("app.audit.verify_audit_chain", lambda conn: (True, 42, "Audit chain intact: 42 record(s) cryptographically verified."))
    body = client.post(VERIFY, headers=headers).json()
    assert body["valid"] is True and body["records"] == 42 and body["mismatches"] is None


def test_verify_runs_the_real_check(make, client):
    _, headers = _admin(make)
    body = client.post(VERIFY, headers=headers).json()
    assert isinstance(body["valid"], bool) and isinstance(body["message"], str) and body["verified_at"]


def test_only_an_mfa_verified_administrator_can_read_or_verify(make, client):
    admin = make.user("APP_MGMT")
    for call in (lambda h: client.get(AUDIT, headers=h), lambda h: client.post(VERIFY, headers=h)):
        assert call({}).status_code == 401
        assert call(make.token(admin, mfa=False)).status_code == 401
        assert call(make.citizen()["headers"]).status_code == 403
        assert call(make.field_team_user()["headers"]).status_code == 403
        assert call(make.staff("SUPERVISOR")["headers"]).status_code == 403
