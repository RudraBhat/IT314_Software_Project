"""Donation orders, payment verification, and webhook tests (contract s.6, s.7).

Covers:
- POST /api/v1/donations: order creation, order ID generation, Idempotency-Key validation.
- Donation validation: amount <= 0, invalid currency, inactive campaign, unauthenticated guest rules.
- GET /api/v1/public/campaigns: strictly only ACTIVE campaigns listed.
- POST /api/v1/donations/{id}/verify: valid HMAC signature confirms donation, assigns receipt_no
  and receipt_issued_at in a single transaction.
- Rejection of tampered signatures (donation stays PENDING, failure audited).
- Idempotent replaying of verified payment callbacks (no duplicate confirmation or receipt).
- Rejection of wrong order ID, mismatching payment, or non-existent donation.
- Rejection of unverified state transitions: donations remain PENDING until verified.
- Sandbox labeling (is_sandbox=True) and production hiding of mock payment generation.
- Donor isolation and privacy: signed-in citizen donations private from other citizens.
- POST /api/v1/payments/webhook/{gateway}: signature check, replay idempotency on event id,
  wrong amount/currency refused, webhook-before-callback, payment.failed (issue #102).
- GET /api/v1/me/donations: the caller's own donations and receipts only (issue #102).
- The mock signature binds order, payment, amount and currency (issue #102).
- SHA-256 cryptographic audit hash-chain integrity verification across donation lifecycle.
"""

import hashlib
import hmac
import json
import os
import uuid

import pytest

pytestmark = pytest.mark.db

BASE_DONATIONS = "/api/v1/donations"
TEST_MOCK_SECRET = "unit-test-gateway-secret-0123456789"


@pytest.fixture(autouse=True)
def _gateway_secrets(monkeypatch):
    """Configure deterministic gateway test secrets via environment variables."""
    from app.config import get_settings

    monkeypatch.setenv("MOCK_GATEWAY_SECRET", TEST_MOCK_SECRET)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_mockkey123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test-razorpay-key-secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test-razorpay-webhook-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sign_mock(order_id: str, payment_id: str, amount: str = "2500.00", currency: str = "INR") -> str:
    """Deterministic HMAC-SHA256 signature mirroring MockGateway: binds order, payment, amount, currency."""
    secret = os.getenv("MOCK_GATEWAY_SECRET", "").encode()
    message = f"{order_id}|{payment_id}|{amount}|{currency}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _mock_webhook(client, order_id, payment_id, *, event="payment.captured", amount=250000,
                  currency="INR", event_id=None, signature=None):
    """POST a mock-gateway webhook (same body shape as Razorpay), signed with MOCK_GATEWAY_SECRET."""
    body = {
        "id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "event": event,
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount, "currency": currency, "status": "captured",
        }}},
    }
    raw = json.dumps(body).encode()
    secret = os.getenv("MOCK_GATEWAY_SECRET", "").encode()
    sig = signature or hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return client.post(
        "/api/v1/payments/webhook/mock",
        content=raw,
        headers={"Content-Type": "application/json", "X-Mock-Signature": sig},
    )


def _create_donation(client, campaign, key=None, headers=None, **extra):
    """Helper to post a donation order."""
    body = {
        "campaign_id": str(campaign["campaign_id"]),
        "amount": 2500.00,
        "currency": "INR",
        "guest_name": "Suresh Mehta",
        "guest_email": "suresh.mehta@example.in",
        "is_anonymous": False,
        **extra,
    }
    hdrs = {"Idempotency-Key": key or f"idemp-{uuid.uuid4().hex[:12]}", **(headers or {})}
    return client.post(BASE_DONATIONS, json=body, headers=hdrs)


# ── Order Creation & Idempotency ──────────────────────────────────────────


def test_create_donation_order_and_idempotency(client, campaign):
    """Create-order returns an order ID and gateway details; duplicate key returns same donation."""
    key = f"key-{uuid.uuid4().hex[:12]}"
    res1 = _create_donation(client, campaign, key=key)
    assert res1.status_code == 201, res1.text
    order1 = res1.json()

    assert "donation_id" in order1
    assert order1["gateway_name"] == "MOCK_GATEWAY"
    assert order1["gateway_order_id"].startswith("order_mock_")
    assert float(order1["amount"]) == pytest.approx(2500.00)
    assert order1["currency"] == "INR"
    assert order1["status"] == "PENDING"
    assert order1["is_sandbox"] is True
    assert order1["checkout_key"] is None

    # Same Idempotency-Key returns 200 OK with identical donation record
    res2 = _create_donation(client, campaign, key=key)
    assert res2.status_code == 200, res2.text
    order2 = res2.json()
    assert order2["donation_id"] == order1["donation_id"]
    assert order2["gateway_order_id"] == order1["gateway_order_id"]

    # Reusing Idempotency-Key with different amount returns 409 Conflict
    res_conflict = _create_donation(client, campaign, key=key, amount=5000.00)
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    # Missing Idempotency-Key header is rejected with 422
    body = {
        "campaign_id": str(campaign["campaign_id"]),
        "amount": 1000.00,
        "currency": "INR",
        "guest_email": "donor@example.in",
    }
    res_missing_key = client.post(BASE_DONATIONS, json=body)
    assert res_missing_key.status_code == 422
    assert res_missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_create_donation_validation_rules(client, campaign):
    """Amount <= 0, wrong currency, inactive campaign, and invalid guests are refused."""
    # Amount <= 0 refused
    res_zero = _create_donation(client, campaign, amount=0)
    assert res_zero.status_code == 422, res_zero.text

    res_neg = _create_donation(client, campaign, amount=-250.00)
    assert res_neg.status_code == 422, res_neg.text

    # Wrong currency refused (only INR permitted)
    res_curr = _create_donation(client, campaign, currency="USD")
    assert res_curr.status_code == 422, res_curr.text

    # Guest without email and not anonymous refused
    res_no_email = client.post(
        BASE_DONATIONS,
        json={"campaign_id": str(campaign["campaign_id"]), "amount": 1000.00, "is_anonymous": False},
        headers={"Idempotency-Key": f"key-{uuid.uuid4().hex[:12]}"},
    )
    assert res_no_email.status_code == 422
    assert res_no_email.json()["error"]["code"] == "VALIDATION_FAILED"

    # Non-existent campaign returns 404
    res_no_camp = _create_donation(client, {"campaign_id": uuid.uuid4()})
    assert res_no_camp.status_code == 404


def test_public_campaigns_lists_only_active_campaigns(client, make):
    """Only ACTIVE campaigns appear in GET /api/v1/public/campaigns."""
    active_c = make.campaign(title="Active Cyclone Relief", status="ACTIVE")
    closed_c = make.campaign(title="Closed Earthquake Drive", status="CLOSED")
    draft_c = make.campaign(title="Draft Flood Initiative", status="DRAFT")

    res = client.get("/api/v1/public/campaigns")
    assert res.status_code == 200, res.text
    campaigns = res.json()
    camp_ids = {c["campaign_id"] for c in campaigns}

    assert str(active_c["campaign_id"]) in camp_ids, "Active campaign not found in public list"
    assert str(closed_c["campaign_id"]) not in camp_ids, "Closed campaign leaked into public list"
    assert str(draft_c["campaign_id"]) not in camp_ids, "Draft campaign leaked into public list"

    # Verify closed campaign rejects donation creations
    res_closed_order = _create_donation(client, closed_c)
    assert res_closed_order.status_code == 409
    assert res_closed_order.json()["error"]["code"] == "CAMPAIGN_NOT_ACTIVE"


# ── Verification & Receipt Generation ────────────────────────────────────


def test_verify_valid_signature_confirms_donation_and_issues_receipt(client, campaign, sql):
    """Verify with a valid signature sets CONFIRMED, receipt_no, and receipt_issued_at in one transaction."""
    res_order = _create_donation(client, campaign)
    assert res_order.status_code == 201
    order = res_order.json()
    don_id = order["donation_id"]
    order_id = order["gateway_order_id"]

    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]
    valid_sig = _sign_mock(order_id, payment_id)

    res_verify = client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": payment_id, "signature": valid_sig},
    )
    assert res_verify.status_code == 200, res_verify.text
    data = res_verify.json()

    assert data["donation_id"] == don_id
    assert data["status"] == "CONFIRMED"
    assert data["receipt_no"].startswith("REC-")
    assert data["receipt_issued_at"] is not None
    receipt_no = data["receipt_no"]

    # Verify DB consistency in a single atomic transaction
    row = sql.execute(
        """
        SELECT status, gateway_payment_id, gateway_txn_ref, receipt_no,
               receipt_issued_at, confirmed_at, verified_at
        FROM donations WHERE donation_id = %s
        """,
        (don_id,),
    ).fetchone()
    assert row["status"] == "CONFIRMED"
    assert row["gateway_payment_id"] == payment_id
    assert row["gateway_txn_ref"] == payment_id
    assert row["receipt_no"] == receipt_no
    assert row["receipt_issued_at"] is not None
    assert row["confirmed_at"] is not None
    assert row["verified_at"] is not None

    # Verify audit row
    audit_row = sql.execute(
        "SELECT action, entity_type, entity_id FROM audit_logs WHERE entity_id = %s AND action = 'DONATION_CONFIRMED'",
        (don_id,),
    ).fetchone()
    assert audit_row is not None
    assert audit_row["entity_type"] == "donation"


def test_tampered_signature_is_rejected_and_donation_stays_pending(client, campaign, sql):
    """Tampered signature is rejected (400 INVALID_SIGNATURE) and the donation stays PENDING."""
    res_order = _create_donation(client, campaign)
    assert res_order.status_code == 201
    order = res_order.json()
    don_id = order["donation_id"]

    # Use explicitly tampered signature
    res_bad = client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": "pay_mock_bad_12345", "signature": "0" * 64},
    )
    assert res_bad.status_code == 400
    assert res_bad.json()["error"]["code"] == "INVALID_SIGNATURE"

    # Confirm database row remained strictly PENDING with no receipt issued
    row = sql.execute(
        "SELECT status, receipt_no, confirmed_at FROM donations WHERE donation_id = %s",
        (don_id,),
    ).fetchone()
    assert row["status"] == "PENDING"
    assert row["receipt_no"] is None
    assert row["confirmed_at"] is None

    # Confirm security rejection was audited
    audit_row = sql.execute(
        """
        SELECT action, entity_id, result FROM audit_logs
        WHERE entity_id = %s AND action = 'DONATION_SIGNATURE_REJECTED'
        """,
        (don_id,),
    ).fetchone()
    assert audit_row is not None
    assert audit_row["result"] == "FAILURE"


def test_replay_verified_payment_changes_nothing(client, campaign):
    """Replaying a verified payment is idempotent: returns same receipt and creates no changes."""
    order = _create_donation(client, campaign).json()
    don_id = order["donation_id"]
    order_id = order["gateway_order_id"]

    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]
    sig = _sign_mock(order_id, payment_id)
    verify_payload = {"gateway_payment_id": payment_id, "signature": sig}

    # First verification
    r1 = client.post(f"{BASE_DONATIONS}/{don_id}/verify", json=verify_payload)
    assert r1.status_code == 200
    first_receipt = r1.json()["receipt_no"]
    first_time = r1.json()["receipt_issued_at"]

    # Replay of the exact same payment verification
    r2 = client.post(f"{BASE_DONATIONS}/{don_id}/verify", json=verify_payload)
    assert r2.status_code == 200
    assert r2.json()["receipt_no"] == first_receipt
    assert r2.json()["receipt_issued_at"] == first_time
    assert r2.json()["status"] == "CONFIRMED"


def test_verify_wrong_order_or_payment_is_rejected(client, campaign):
    """Wrong order ID in signature or different payment ID on verified donation is refused."""
    order = _create_donation(client, campaign).json()
    don_id = order["donation_id"]
    order_id = order["gateway_order_id"]

    # 1. Signature calculated for an illegitimate/different order ID
    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]
    wrong_order_sig = _sign_mock("order_mock_foreign_order_999", payment_id)

    res_wrong_order = client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": payment_id, "signature": wrong_order_sig},
    )
    assert res_wrong_order.status_code == 400
    assert res_wrong_order.json()["error"]["code"] == "INVALID_SIGNATURE"

    # 2. Complete genuine verification first
    valid_sig = _sign_mock(order_id, payment_id)
    res_ok = client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": payment_id, "signature": valid_sig},
    )
    assert res_ok.status_code == 200

    # 3. Attempting to verify same confirmed donation with a different payment ID returns 409
    other_pay_id = "pay_mock_different_" + uuid.uuid4().hex[:8]
    other_sig = _sign_mock(order_id, other_pay_id)
    res_conflict = client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": other_pay_id, "signature": other_sig},
    )
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error"]["code"] == "ALREADY_CONFIRMED"

    # 4. Verifying non-existent donation returns 404
    res_not_found = client.post(
        f"{BASE_DONATIONS}/{uuid.uuid4()}/verify",
        json={"gateway_payment_id": payment_id, "signature": valid_sig},
    )
    assert res_not_found.status_code == 404


def test_nothing_becomes_confirmed_without_verification(client, campaign, sql):
    """Nothing becomes CONFIRMED without verification; sandbox-payment endpoint does not mutate status."""
    order = _create_donation(client, campaign).json()
    don_id = order["donation_id"]

    # Check database right after order creation
    row = sql.execute("SELECT status, receipt_no, confirmed_at FROM donations WHERE donation_id = %s", (don_id,)).fetchone()
    assert row["status"] == "PENDING"
    assert row["receipt_no"] is None
    assert row["confirmed_at"] is None

    # Request sandbox payment simulation credentials
    pay_res = client.post(f"{BASE_DONATIONS}/{don_id}/sandbox-payment")
    assert pay_res.status_code == 200
    pay_info = pay_res.json()
    assert "gateway_payment_id" in pay_info
    assert "signature" in pay_info

    # Status must strictly remain PENDING until verify is explicitly called
    row2 = sql.execute("SELECT status, receipt_no, confirmed_at FROM donations WHERE donation_id = %s", (don_id,)).fetchone()
    assert row2["status"] == "PENDING"
    assert row2["receipt_no"] is None
    assert row2["confirmed_at"] is None


def test_response_labelled_sandbox_and_production_isolation(client, campaign, monkeypatch):
    """Responses are labeled is_sandbox=True; sandbox-payment endpoint is hidden in production."""
    from app.config import get_settings

    order = _create_donation(client, campaign).json()
    assert order["is_sandbox"] is True
    assert order["gateway_name"] == "MOCK_GATEWAY"

    # In production environment, sandbox-payment simulation endpoint returns 404
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    res_prod = client.post(f"{BASE_DONATIONS}/{order['donation_id']}/sandbox-payment")
    assert res_prod.status_code == 404


def test_signed_in_donor_privacy_and_guest_donation_isolation(client, campaign, make):
    """Donations created by an authenticated citizen are strictly isolated from other users."""
    donor_a = make.citizen()
    donor_b = make.citizen()

    # Donor A creates a donation
    order_a = _create_donation(client, campaign, headers=donor_a["headers"], guest_email=None).json()
    don_id = order_a["donation_id"]

    pay_res = client.post(f"{BASE_DONATIONS}/{don_id}/sandbox-payment", headers=donor_a["headers"])
    assert pay_res.status_code == 200
    pay_data = pay_res.json()

    # Donor B tries to inspect or verify Donor A's donation -> 404 (not found / forbidden leakage guard)
    res_b_verify = client.post(f"{BASE_DONATIONS}/{don_id}/verify", json=pay_data, headers=donor_b["headers"])
    assert res_b_verify.status_code == 404

    res_b_sandbox = client.post(f"{BASE_DONATIONS}/{don_id}/sandbox-payment", headers=donor_b["headers"])
    assert res_b_sandbox.status_code == 404

    # Donor A verifies their own donation -> succeeds
    res_a_verify = client.post(f"{BASE_DONATIONS}/{don_id}/verify", json=pay_data, headers=donor_a["headers"])
    assert res_a_verify.status_code == 200


# ── Webhook Defect Notes & XFAIL Tests (Owner: Shlok) ─────────────────────


def _status(sql, donation_id):
    return sql.execute(
        "SELECT status, receipt_no, gateway_payment_id FROM donations WHERE donation_id = %s", (donation_id,)
    ).fetchone()


def test_payments_webhook_valid_signature_confirms_donation(client, campaign, sql):
    order = _create_donation(client, campaign).json()
    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]

    res = _mock_webhook(client, order["gateway_order_id"], payment_id)
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "CONFIRMED"

    row = _status(sql, order["donation_id"])
    assert row["status"] == "CONFIRMED" and row["receipt_no"] is not None
    assert row["gateway_payment_id"] == payment_id


def test_payments_webhook_tampered_signature_is_rejected(client, campaign, sql):
    order = _create_donation(client, campaign).json()
    res = _mock_webhook(client, order["gateway_order_id"], "pay_mock_tampered1", signature="0" * 64)
    assert res.status_code == 400 and res.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert _status(sql, order["donation_id"])["status"] == "PENDING"


def test_payments_webhook_replay_is_idempotent(client, campaign, sql):
    order = _create_donation(client, campaign).json()
    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]
    event_id = f"evt_{uuid.uuid4().hex[:12]}"

    first = _mock_webhook(client, order["gateway_order_id"], payment_id, event_id=event_id)
    receipt = _status(sql, order["donation_id"])["receipt_no"]
    replay = _mock_webhook(client, order["gateway_order_id"], payment_id, event_id=event_id)

    assert first.json()["outcome"] == "CONFIRMED"
    assert replay.status_code == 200 and replay.json()["outcome"] == "DUPLICATE_EVENT"
    assert _status(sql, order["donation_id"])["receipt_no"] == receipt
    stored = sql.execute(
        "SELECT COUNT(*) AS n FROM payment_webhook_events WHERE event_id = %s", (event_id,)
    ).fetchone()["n"]
    assert stored == 1

    # A different event for the same payment does not confirm twice either.
    again = _mock_webhook(client, order["gateway_order_id"], payment_id)
    assert again.json()["outcome"] == "ALREADY_CONFIRMED"
    assert _status(sql, order["donation_id"])["receipt_no"] == receipt


@pytest.mark.parametrize("amount,currency", [(100, "INR"), (250001, "INR"), (250000, "USD")])
def test_payments_webhook_wrong_amount_or_currency_does_not_confirm(client, campaign, sql, amount, currency):
    order = _create_donation(client, campaign).json()
    res = _mock_webhook(client, order["gateway_order_id"], "pay_mock_" + uuid.uuid4().hex[:8],
                        amount=amount, currency=currency)
    assert res.status_code == 200 and res.json()["outcome"] == "AMOUNT_MISMATCH"
    row = _status(sql, order["donation_id"])
    assert row["status"] == "PENDING" and row["receipt_no"] is None


def test_webhook_before_client_callback_race_condition(client, campaign, sql):
    """Webhook confirms first; the browser callback then returns the same receipt, no second one."""
    order = _create_donation(client, campaign).json()
    don_id, order_id = order["donation_id"], order["gateway_order_id"]
    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]

    assert _mock_webhook(client, order_id, payment_id).json()["outcome"] == "CONFIRMED"
    receipt = _status(sql, don_id)["receipt_no"]

    res_callback = client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": payment_id, "signature": _sign_mock(order_id, payment_id)},
    )
    assert res_callback.status_code == 200, res_callback.text
    assert res_callback.json()["status"] == "CONFIRMED"
    assert res_callback.json()["receipt_no"] == receipt


def test_payment_failed_webhook_marks_pending_donation_failed(client, campaign, sql):
    order = _create_donation(client, campaign).json()
    res = _mock_webhook(client, order["gateway_order_id"], "pay_mock_failed01", event="payment.failed")
    assert res.json()["outcome"] == "FAILED"
    assert _status(sql, order["donation_id"])["status"] == "FAILED"


def test_webhook_for_another_gateway_is_not_found(client):
    res = client.post("/api/v1/payments/webhook/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "x"})
    assert res.status_code == 404


def test_callback_signature_is_bound_to_the_amount(client, campaign, sql):
    """A signature produced for a different amount cannot confirm this donation."""
    order = _create_donation(client, campaign).json()
    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]
    res = client.post(
        f"{BASE_DONATIONS}/{order['donation_id']}/verify",
        json={"gateway_payment_id": payment_id, "signature": _sign_mock(order["gateway_order_id"], payment_id, "1.00")},
    )
    assert res.status_code == 400 and res.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert _status(sql, order["donation_id"])["status"] == "PENDING"


def test_me_donations_shows_caller_donations_and_receipts(client, campaign, make):
    citizen, other = make.citizen(), make.citizen()
    order = _create_donation(client, campaign, headers=citizen["headers"], guest_email=None).json()
    don_id, order_id = order["donation_id"], order["gateway_order_id"]

    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]
    client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": payment_id, "signature": _sign_mock(order_id, payment_id)},
        headers=citizen["headers"],
    )

    res = client.get("/api/v1/me/donations", headers=citizen["headers"])
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["donation_id"] == don_id
    assert item["status"] == "CONFIRMED" and item["receipt_no"].startswith("REC-")
    assert item["is_sandbox"] is True and item["campaign_title"]

    assert client.get("/api/v1/me/donations", headers=other["headers"]).json()["total"] == 0
    assert client.get("/api/v1/me/donations").status_code == 401


# ── Audit Hash Chain Integrity ───────────────────────────────────────────


def test_donations_audit_hash_chain_integrity(client, campaign, sql):
    """Donation creation, failed verification, and confirmation preserve audit SHA-256 hash-chain integrity."""
    from app import audit

    # 1. Create donation
    order = _create_donation(client, campaign).json()
    don_id = order["donation_id"]
    order_id = order["gateway_order_id"]

    # 2. Tampered signature attempt (audited failure)
    client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": "pay_mock_fake", "signature": "0" * 64},
    )

    # 3. Successful verification (audited success)
    payment_id = "pay_mock_" + uuid.uuid4().hex[:12]
    sig = _sign_mock(order_id, payment_id)
    client.post(
        f"{BASE_DONATIONS}/{don_id}/verify",
        json={"gateway_payment_id": payment_id, "signature": sig},
    )

    # Verify cryptographic hash-chain integrity across all written entries
    is_valid, count, message = audit.verify_audit_chain(sql)
    assert is_valid is True, f"Audit hash chain compromised: {message}"
    assert count > 0
