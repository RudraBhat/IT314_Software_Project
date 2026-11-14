"""Server-side donation endings (S3-11, owner Shlok): cancel, expiry and late captures.

Every path ends in PENDING, CONFIRMED or FAILED, and nothing is CONFIRMED without a verified payment:
- POST /donations/{id}/cancel turns an unpaid order into FAILED / ABANDONED (idempotent; refused once confirmed).
- An order still unpaid after PENDING_TTL becomes FAILED / EXPIRED the next time it is touched.
- A verified payment that arrives after the order failed (cancelled, expired or a failed first attempt)
  still confirms it and issues a receipt, so captured money is never lost.
- The failure reason is visible to the donor in GET /me/donations.
"""

import hashlib
import hmac
import json
import os
import uuid

import pytest

pytestmark = pytest.mark.db

BASE = "/api/v1/donations"
TEST_MOCK_SECRET = "unit-test-gateway-secret-0123456789"


@pytest.fixture(autouse=True)
def _gateway_secret(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_GATEWAY_SECRET", TEST_MOCK_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _create(client, campaign, headers=None, amount=2500):
    body = {"campaign_id": str(campaign["campaign_id"]), "amount": amount, "currency": "INR"}
    if headers is None:
        body["guest_email"] = "donor@example.in"
    res = client.post(BASE, json=body, headers={"Idempotency-Key": f"end-{uuid.uuid4()}", **(headers or {})})
    assert res.status_code == 201, res.text
    return res.json()


def _sign(order_id, payment_id, amount="2500.00", currency="INR"):
    message = f"{order_id}|{payment_id}|{amount}|{currency}".encode()
    return hmac.new(TEST_MOCK_SECRET.encode(), message, hashlib.sha256).hexdigest()


def _webhook(client, order_id, payment_id, *, event="payment.captured", amount=250000):
    body = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "event": event,
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount, "currency": "INR", "status": "captured",
        }}},
    }
    raw = json.dumps(body).encode()
    sig = hmac.new(os.environ["MOCK_GATEWAY_SECRET"].encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/api/v1/payments/webhook/mock", content=raw,
                       headers={"Content-Type": "application/json", "X-Mock-Signature": sig})


def _row(sql, donation_id):
    return sql.execute(
        "SELECT status, failure_reason, failed_at, receipt_no FROM donations WHERE donation_id = %s", (donation_id,)
    ).fetchone()


def _age(sql, donation_id, minutes):
    sql.execute("UPDATE donations SET created_at = now() - make_interval(mins => %s) WHERE donation_id = %s",
                (minutes, donation_id))


def test_cancel_turns_an_unpaid_order_into_failed_abandoned(client, campaign, sql):
    order = _create(client, campaign)
    res = client.post(f"{BASE}/{order['donation_id']}/cancel")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "FAILED" and res.json()["failure_reason"] == "ABANDONED"
    row = _row(sql, order["donation_id"])
    assert row["status"] == "FAILED" and row["failure_reason"] == "ABANDONED" and row["failed_at"] is not None
    assert row["receipt_no"] is None
    audited = sql.execute(
        "SELECT count(*) AS n FROM audit_logs WHERE action = 'DONATION_FAILED' AND entity_id = %s",
        (order["donation_id"],),
    ).fetchone()["n"]
    assert audited == 1


def test_cancel_is_idempotent(client, campaign, sql):
    order = _create(client, campaign)
    first = client.post(f"{BASE}/{order['donation_id']}/cancel")
    second = client.post(f"{BASE}/{order['donation_id']}/cancel")
    assert first.status_code == second.status_code == 200
    assert second.json()["failure_reason"] == "ABANDONED"
    audited = sql.execute(
        "SELECT count(*) AS n FROM audit_logs WHERE action = 'DONATION_FAILED' AND entity_id = %s",
        (order["donation_id"],),
    ).fetchone()["n"]
    assert audited == 1, "a repeated cancel must not write a second audit row"


def test_a_confirmed_donation_cannot_be_cancelled(client, campaign, sql):
    order = _create(client, campaign)
    pay = client.post(f"{BASE}/{order['donation_id']}/sandbox-payment").json()
    assert client.post(f"{BASE}/{order['donation_id']}/verify", json=pay).status_code == 200
    res = client.post(f"{BASE}/{order['donation_id']}/cancel")
    assert res.status_code == 409 and res.json()["error"]["code"] == "DONATION_ALREADY_CONFIRMED"
    assert _row(sql, order["donation_id"])["status"] == "CONFIRMED"


def test_another_citizen_cannot_cancel_my_donation(client, campaign, make, sql):
    owner, other = make.citizen(), make.citizen()
    order = _create(client, campaign, headers=owner["headers"])
    res = client.post(f"{BASE}/{order['donation_id']}/cancel", headers=other["headers"])
    assert res.status_code == 404
    assert _row(sql, order["donation_id"])["status"] == "PENDING"


def test_a_stale_unpaid_order_expires_and_cannot_use_the_sandbox_payment(client, campaign, sql):
    order = _create(client, campaign)
    _age(sql, order["donation_id"], 31)
    res = client.post(f"{BASE}/{order['donation_id']}/sandbox-payment")
    assert res.status_code == 409 and res.json()["error"]["code"] == "DONATION_NOT_PENDING"
    row = _row(sql, order["donation_id"])
    assert row["status"] == "FAILED" and row["failure_reason"] == "EXPIRED"
    audited = sql.execute(
        "SELECT count(*) AS n FROM audit_logs WHERE action = 'DONATION_EXPIRED' AND entity_id = %s",
        (order["donation_id"],),
    ).fetchone()["n"]
    assert audited == 1


def test_a_recent_unpaid_order_is_not_expired(client, campaign, sql):
    order = _create(client, campaign)
    _age(sql, order["donation_id"], 5)
    assert client.post(f"{BASE}/{order['donation_id']}/sandbox-payment").status_code == 200
    assert _row(sql, order["donation_id"])["status"] == "PENDING"


def test_a_verified_payment_still_confirms_an_expired_order(client, campaign, sql):
    order = _create(client, campaign)
    _age(sql, order["donation_id"], 45)
    payment_id = f"pay_mock_latecap_{uuid.uuid4().hex[:8]}"
    res = client.post(f"{BASE}/{order['donation_id']}/verify",
                      json={"gateway_payment_id": payment_id, "signature": _sign(order["gateway_order_id"], payment_id)})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "CONFIRMED" and res.json()["receipt_no"]
    row = _row(sql, order["donation_id"])
    assert row["status"] == "CONFIRMED" and row["failure_reason"] is None and row["failed_at"] is None


def test_a_tampered_signature_never_confirms_a_failed_order(client, campaign, sql):
    order = _create(client, campaign)
    client.post(f"{BASE}/{order['donation_id']}/cancel")
    payment_id = f"pay_mock_forged_{uuid.uuid4().hex[:8]}"
    res = client.post(f"{BASE}/{order['donation_id']}/verify",
                      json={"gateway_payment_id": payment_id, "signature": "0" * 64})
    assert res.status_code == 400
    assert _row(sql, order["donation_id"])["status"] == "FAILED"


def test_capture_after_a_failed_attempt_confirms_the_order(client, campaign, sql):
    order = _create(client, campaign)
    failed = _webhook(client, order["gateway_order_id"], f"pay_mock_attempt1_{uuid.uuid4().hex[:8]}", event="payment.failed")
    assert failed.json()["outcome"] == "FAILED"
    assert _row(sql, order["donation_id"])["failure_reason"] == "GATEWAY_DECLINED"
    captured = _webhook(client, order["gateway_order_id"], f"pay_mock_attempt2_{uuid.uuid4().hex[:8]}")
    assert captured.json()["outcome"] == "CONFIRMED"
    row = _row(sql, order["donation_id"])
    assert row["status"] == "CONFIRMED" and row["receipt_no"] and row["failure_reason"] is None


def test_a_wrong_amount_capture_does_not_confirm_a_failed_order(client, campaign, sql):
    order = _create(client, campaign)
    client.post(f"{BASE}/{order['donation_id']}/cancel")
    res = _webhook(client, order["gateway_order_id"], f"pay_mock_short_{uuid.uuid4().hex[:8]}", amount=100)
    assert res.json()["outcome"] == "AMOUNT_MISMATCH"
    assert _row(sql, order["donation_id"])["status"] == "FAILED"


def test_me_donations_shows_the_failure_reason(client, campaign, make):
    donor = make.citizen()
    order = _create(client, campaign, headers=donor["headers"])
    client.post(f"{BASE}/{order['donation_id']}/cancel", headers=donor["headers"])
    items = client.get("/api/v1/me/donations", headers=donor["headers"]).json()["items"]
    mine = next(i for i in items if str(i["donation_id"]) == str(order["donation_id"]))
    assert mine["status"] == "FAILED" and mine["failure_reason"] == "ABANDONED"


def test_the_database_refuses_a_failure_reason_on_a_pending_donation(campaign, sql):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        sql.execute(
            "INSERT INTO donations (campaign_id, amount, status, is_anonymous, idempotency_key, failure_reason) "
            "VALUES (%s, 10, 'PENDING', TRUE, %s, 'EXPIRED')",
            (campaign["campaign_id"], f"chk-{uuid.uuid4()}"),
        )
