"""Donations with the sandbox gateway (contract s.6)."""

import uuid

import pytest

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _gateway_secret(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_GATEWAY_SECRET", "unit-test-gateway-secret-0123456789")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def campaign(sql):
    return sql.execute(
        "INSERT INTO donation_campaigns (title, purpose, scenario, status) "
        "VALUES (%s, 'Relief', 'URBAN_FLOODING', 'ACTIVE') RETURNING *",
        (f"Campaign {uuid.uuid4().hex[:8]}",),
    ).fetchone()


def _create(client, campaign, key=None, headers=None, **extra):
    body = {"campaign_id": str(campaign["campaign_id"]), "amount": 2500.00, "guest_email": "suresh@example.in", **extra}
    return client.post("/api/v1/donations", json=body, headers={"Idempotency-Key": key or str(uuid.uuid4()), **(headers or {})})


def test_full_payment_flow_issues_receipt(client, campaign):
    r = _create(client, campaign)
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["status"] == "PENDING" and order["is_sandbox"] and order["gateway_order_id"].startswith("order_mock_")
    pay = client.post(f"/api/v1/donations/{order['donation_id']}/sandbox-payment").json()
    done = client.post(f"/api/v1/donations/{order['donation_id']}/verify", json=pay)
    assert done.status_code == 200 and done.json()["status"] == "CONFIRMED"
    assert done.json()["receipt_no"].startswith("REC-")
    again = client.post(f"/api/v1/donations/{order['donation_id']}/verify", json=pay)
    assert again.status_code == 200 and again.json()["receipt_no"] == done.json()["receipt_no"]


def test_bad_signature_never_confirms(client, campaign, sql):
    order = _create(client, campaign).json()
    r = client.post(f"/api/v1/donations/{order['donation_id']}/verify",
                    json={"gateway_payment_id": "pay_mock_123456", "signature": "0" * 64})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_SIGNATURE"
    row = sql.execute("SELECT status, receipt_no FROM donations WHERE donation_id=%s", (order["donation_id"],)).fetchone()
    assert row["status"] == "PENDING" and row["receipt_no"] is None


def test_idempotency_and_validation(client, campaign):
    key = str(uuid.uuid4())
    a, b = _create(client, campaign, key=key), _create(client, campaign, key=key)
    assert a.status_code == 201 and b.status_code == 200 and a.json()["donation_id"] == b.json()["donation_id"]
    assert _create(client, campaign, key=key, amount=1).status_code == 409
    assert client.post("/api/v1/donations", json={"campaign_id": str(campaign["campaign_id"]), "amount": 5,
                                                 "guest_email": "a@b.in"}).status_code == 422
    assert _create(client, campaign, amount=-5).status_code == 422
    r = client.post("/api/v1/donations", json={"campaign_id": str(campaign["campaign_id"]), "amount": 5},
                    headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 422  # guest without email and not anonymous


def test_closed_campaign_rejects_donations(client, campaign, sql):
    sql.execute("UPDATE donation_campaigns SET status='CLOSED' WHERE campaign_id=%s", (campaign["campaign_id"],))
    r = _create(client, campaign)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAMPAIGN_NOT_ACTIVE"


def test_donation_of_a_signed_in_donor_is_private(client, campaign, make):
    owner, other = make.citizen(), make.citizen()
    order = _create(client, campaign, headers=owner["headers"], guest_email=None).json()
    pay = client.post(f"/api/v1/donations/{order['donation_id']}/sandbox-payment", headers=owner["headers"]).json()
    assert client.post(f"/api/v1/donations/{order['donation_id']}/verify", json=pay, headers=other["headers"]).status_code == 404
    assert client.post(f"/api/v1/donations/{order['donation_id']}/verify", json=pay, headers=owner["headers"]).status_code == 200


def test_sandbox_endpoint_hidden_in_production(client, campaign, monkeypatch):
    from app.config import get_settings

    order = _create(client, campaign).json()
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    assert client.post(f"/api/v1/donations/{order['donation_id']}/sandbox-payment").status_code == 404
