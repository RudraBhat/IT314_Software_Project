"""Citizen account functions: profile, language and alert preferences, password change, read-all notifications."""

import uuid

import pytest

pytestmark = pytest.mark.db

PROFILE = "/api/v1/me/profile"
PASSWORD = "/api/v1/me/password"
CURRENT = "citizen-test-pass"  # the default password make.citizen() creates


def test_profile_shows_own_details_and_defaults(client, make):
    citizen = make.citizen()
    r = client.get(PROFILE, headers=citizen["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] and body["preferred_language"] == "en"
    assert body["alerts"]["in_app"] is True
    assert not {"password_hash", "token_version", "mfa_secret"} & set(body)


def test_profile_update_changes_fields_and_cannot_turn_off_in_app_alerts(client, make, sql):
    citizen = make.citizen()
    r = client.patch(PROFILE, headers=citizen["headers"], json={
        "full_name": "Asha Patel", "phone": "+919876543210", "preferred_language": "gu",
        "email_alerts": False, "sms_alerts": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Asha Patel" and body["phone"] == "+919876543210" and body["preferred_language"] == "gu"
    assert body["alerts"] == {"in_app": True, "email": False, "sms": True}
    assert client.get(PROFILE, headers=citizen["headers"]).json()["preferred_language"] == "gu"
    row = sql.execute(
        "SELECT result FROM audit_logs WHERE entity_id = %s AND action = 'PROFILE_UPDATED'", (citizen["user_id"],)
    ).fetchone()
    assert row["result"] == "SUCCESS"


def test_profile_update_only_touches_what_is_sent_and_never_the_email(client, make):
    citizen = make.citizen()
    before = client.get(PROFILE, headers=citizen["headers"]).json()
    r = client.patch(PROFILE, headers=citizen["headers"], json={"preferred_language": "hi", "email": "other@example.in"})
    assert r.status_code == 200
    after = r.json()
    assert after["email"] == before["email"] and after["full_name"] == before["full_name"]
    assert after["preferred_language"] == "hi"


@pytest.mark.parametrize("payload", [{"preferred_language": "fr"}, {"phone": "abc"}, {"full_name": "   "}])
def test_profile_rejects_invalid_values(client, make, payload):
    citizen = make.citizen()
    assert client.patch(PROFILE, headers=citizen["headers"], json=payload).status_code == 422


def test_password_change_ends_sessions_and_new_password_works(client, make):
    citizen = make.citizen()
    r = client.post(PASSWORD, headers=citizen["headers"], json={"current_password": CURRENT, "new_password": "Brand-new1!pass"})
    assert r.status_code == 200 and r.json() == {"changed": True, "sign_in_required": True}
    assert client.get(PROFILE, headers=citizen["headers"]).status_code == 401  # old token revoked
    email = citizen["email"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": CURRENT}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "Brand-new1!pass"}).status_code == 200


def test_password_change_checks_current_password_and_policy(client, make, sql):
    citizen = make.citizen()
    wrong = client.post(PASSWORD, headers=citizen["headers"], json={"current_password": "nope", "new_password": "Brand-new1!pass"})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    failed = sql.execute(
        "SELECT result FROM audit_logs WHERE entity_id = %s AND action = 'PASSWORD_CHANGE_FAILED'", (citizen["user_id"],)
    ).fetchone()
    assert failed["result"] == "FAILURE"
    weak = client.post(PASSWORD, headers=citizen["headers"], json={"current_password": CURRENT, "new_password": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "WEAK_PASSWORD"
    assert client.get(PROFILE, headers=citizen["headers"]).status_code == 200  # nothing changed, session still valid


def test_new_password_must_differ_from_the_current_one(client, make):
    citizen = make.citizen(password="Valid-pass1!")
    same = client.post(PASSWORD, headers=citizen["headers"], json={"current_password": "Valid-pass1!", "new_password": "Valid-pass1!"})
    assert same.status_code == 422 and same.json()["error"]["code"] == "PASSWORD_UNCHANGED"


def test_account_routes_need_a_citizen(client, make):
    assert client.get(PROFILE).status_code == 401
    assert client.post(PASSWORD, json={"current_password": "a", "new_password": "b"}).status_code == 401
    staff = make.staff()
    assert client.get(PROFILE, headers=staff["headers"]).status_code == 403


def test_mark_all_notifications_read(client, make):
    citizen = make.citizen()
    payload = {
        "scenario": "urban_flooding", "description": "Severe waterlogging on the main market road.",
        "latitude": 23.0225, "longitude": 72.5714,
    }
    headers = {**citizen["headers"], "Idempotency-Key": str(uuid.uuid4())}
    assert client.post("/api/v1/incidents", json=payload, headers=headers).status_code == 201
    unread = client.get("/api/v1/me/notifications", headers=citizen["headers"]).json()["items"]
    assert unread and all(n["read_at"] is None for n in unread)
    done = client.post("/api/v1/me/notifications/read-all", headers=citizen["headers"])
    assert done.status_code == 200 and done.json()["marked_read"] == len(unread)
    assert all(n["read_at"] for n in client.get("/api/v1/me/notifications", headers=citizen["headers"]).json()["items"])
    assert client.post("/api/v1/me/notifications/read-all", headers=citizen["headers"]).json()["marked_read"] == 0


# --------------------------------------------------------------------------- withdrawal request

REPORT = {
    "scenario": "urban_flooding", "description": "Severe waterlogging on the main market road.",
    "latitude": 23.0225, "longitude": 72.5714,
}


def _report(client, citizen) -> str:
    headers = {**citizen["headers"], "Idempotency-Key": str(uuid.uuid4())}
    r = client.post("/api/v1/incidents", json=REPORT, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["incident_id"]


def test_withdrawal_request_is_recorded_without_changing_the_status(client, make):
    citizen = make.citizen()
    iid = _report(client, citizen)
    r = client.post(f"/api/v1/me/incidents/{iid}/withdrawal-request", headers=citizen["headers"], json={"reason": "False alarm"})
    assert r.status_code == 201 and r.json()["status"] == "SUBMITTED"
    mine = client.get(f"/api/v1/me/incidents/{iid}", headers=citizen["headers"]).json()
    assert mine["status"] == "SUBMITTED" and mine["withdrawal_requested"] is True
    assert [t["status"] for t in mine["timeline"]] == ["SUBMITTED"]  # no duplicate timeline entry
    detail = client.get(f"/api/v1/dm/incidents/{iid}", headers=make.staff()["headers"]).json()
    assert any("asked to withdraw" in (h["reason"] or "") and "False alarm" in h["reason"] for h in detail["history"])
    again = client.post(f"/api/v1/me/incidents/{iid}/withdrawal-request", headers=citizen["headers"], json={})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_REQUESTED"


def test_withdrawal_refused_after_dispatch_and_for_other_citizens(client, make, sql):
    owner, other = make.citizen(), make.citizen()
    iid = _report(client, owner)
    assert client.post(f"/api/v1/me/incidents/{iid}/withdrawal-request", headers=other["headers"], json={}).status_code == 404
    sql.execute(
        "UPDATE incidents SET status = 'DISPATCHED', verified_priority = 'HIGH', verified_at = now() WHERE incident_id = %s",
        (iid,),
    )
    r = client.post(f"/api/v1/me/incidents/{iid}/withdrawal-request", headers=owner["headers"], json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_WITHDRAWABLE"


# --------------------------------------------------------------------------- account deletion

def test_account_deletion_needs_the_password_and_no_open_reports(client, make, sql):
    citizen = make.citizen(password="Valid-pass1!")
    url = "/api/v1/me/account/deletion"
    wrong = client.post(url, headers=citizen["headers"], json={"password": "nope"})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    failed = sql.execute(
        "SELECT result FROM audit_logs WHERE entity_id = %s AND action = 'ACCOUNT_DELETION_FAILED'", (citizen["user_id"],)
    ).fetchone()
    assert failed["result"] == "FAILURE"
    _report(client, citizen)
    blocked = client.post(url, headers=citizen["headers"], json={"password": "Valid-pass1!"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "OPEN_REPORTS"


def test_account_deletion_erases_personal_details_and_ends_access(client, make, sql):
    citizen = make.citizen(password="Valid-pass1!")
    iid = _report(client, citizen)
    sql.execute(
        "UPDATE incidents SET status = 'RESOLVED', verified_priority = 'HIGH', verified_at = now() WHERE incident_id = %s",
        (iid,),
    )
    client.patch("/api/v1/me/profile", headers=citizen["headers"], json={"phone": "+919876543210"})
    done = client.post("/api/v1/me/account/deletion", headers=citizen["headers"], json={"password": "Valid-pass1!"})
    assert done.status_code == 200 and done.json() == {"deleted": True, "sign_in_required": True}
    row = sql.execute(
        "SELECT email, full_name, phone, status FROM users WHERE user_id = %s", (citizen["user_id"],)
    ).fetchone()
    assert row["email"].endswith("@deleted.invalid") and row["full_name"] == "Deleted user"
    assert row["phone"] is None and row["status"] == "DISABLED"
    assert client.get(PROFILE, headers=citizen["headers"]).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": citizen["email"], "password": "Valid-pass1!"}).status_code == 401
    kept = sql.execute("SELECT 1 FROM incidents WHERE incident_id = %s", (iid,)).fetchone()
    assert kept is not None  # the report stays on record for the audit trail
    audit_row = sql.execute(
        "SELECT result FROM audit_logs WHERE entity_id = %s AND action = 'ACCOUNT_DELETED'", (citizen["user_id"],)
    ).fetchone()
    assert audit_row["result"] == "SUCCESS"


# --------------------------------------------------------------------------- email copy of notifications

def _wait_for_mail(email: str, timeout: float = 5.0) -> list[dict]:
    import time

    from app.services import email as email_service

    deadline = time.time() + timeout
    while time.time() < deadline:
        found = [m for m in email_service.get_outbox() if m["to"] == email]
        if found:
            return found
        time.sleep(0.2)
    return []


def test_notification_is_emailed_when_email_alerts_are_on(client, make):
    citizen = make.citizen()
    _report(client, citizen)  # queues the "Report received" notification
    mail = _wait_for_mail(citizen["email"])
    assert mail and "Report received" in mail[-1]["subject"] and "my-reports" in mail[-1]["text"]


def test_no_email_copy_when_email_alerts_are_off(client, make):
    import time

    from app.services import email as email_service

    citizen = make.citizen()
    assert client.patch(PROFILE, headers=citizen["headers"], json={"email_alerts": False}).status_code == 200
    _report(client, citizen)
    time.sleep(1.5)
    assert [m for m in email_service.get_outbox() if m["to"] == citizen["email"]] == []


def test_email_copy_is_sent_after_commit_and_dropped_on_rollback(make):
    import time

    from app import db
    from app.common import notify
    from app.services import email as email_service

    citizen = make.citizen()
    with pytest.raises(RuntimeError), db.transaction() as conn:
        notify(conn, user_id=citizen["user_id"], event_code="INCIDENT_RECEIVED", title="Rolled back", body="Never sent.")
        raise RuntimeError("the action failed after queuing the notification")
    with db.transaction() as conn:
        notify(conn, user_id=citizen["user_id"], event_code="INCIDENT_RECEIVED", title="Committed", body="Sent.")
    mail = _wait_for_mail(citizen["email"])
    time.sleep(0.5)
    subjects = [m["subject"] for m in email_service.get_outbox() if m["to"] == citizen["email"]]
    assert mail and any("Committed" in s for s in subjects)
    assert not any("Rolled back" in s for s in subjects)

