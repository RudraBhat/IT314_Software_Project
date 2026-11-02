"""Tests for donation campaigns and donation order endpoints.

Module-level env setup MUST precede all app imports so that lru_cache
picks up the secret on first call.
"""

import os

os.environ.setdefault("MOCK_GATEWAY_SECRET", "test-only-payment-signing-secret")

# Clear settings cache so our env var is picked up even if conftest seeded it first.
from app.config import get_settings

get_settings.cache_clear()

import uuid

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CAMPAIGN_1 = "c0000000-0000-0000-0000-000000000001"  # seeded ACTIVE campaign


def _idem() -> str:
    """Return a fresh UUID string to use as an Idempotency-Key."""
    return str(uuid.uuid4())


def _make_campaign(sql, status: str = "ACTIVE", scenario: str = "URBAN_FLOODING") -> str:
    """Insert a test donation campaign and return its campaign_id string."""
    row = sql.execute(
        "INSERT INTO donation_campaigns (title, purpose, scenario, target_amount, currency, status) "
        "VALUES (%s, %s, %s, %s, 'INR', %s) RETURNING campaign_id",
        (f"Test Campaign {uuid.uuid4().hex[:8]}", "Test purpose text", scenario, 10000, status),
    ).fetchone()
    return str(row["campaign_id"])


def _post_donation(client, campaign_id: str, idem_key: str, **overrides):
    """POST /api/v1/donations with sensible defaults; overrides applied last."""
    body = {
        "campaign_id": campaign_id,
        "amount": "500.00",
        "currency": "INR",
        "guest_email": "donor@example.com",
        "is_anonymous": False,
    }
    body.update(overrides)
    return client.post(
        "/api/v1/donations",
        json=body,
        headers={"Idempotency-Key": idem_key},
    )


# ===========================================================================
# GET /api/v1/public/campaigns
# ===========================================================================


@pytest.mark.db
def test_public_campaigns_requires_no_auth(client):
    """Endpoint must return 200 with no Authorization header."""
    res = client.get("/api/v1/public/campaigns")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


@pytest.mark.db
def test_public_campaigns_only_active(client, sql):
    """DRAFT and PAUSED campaigns must not appear in the response."""
    draft_id = _make_campaign(sql, status="DRAFT")
    paused_id = _make_campaign(sql, status="PAUSED")

    res = client.get("/api/v1/public/campaigns")
    assert res.status_code == 200
    ids = [str(c["campaign_id"]) for c in res.json()]

    assert draft_id not in ids, "DRAFT campaign leaked into public response"
    assert paused_id not in ids, "PAUSED campaign leaked into public response"


@pytest.mark.db
def test_public_campaigns_scenario_lowercase(client, sql):
    """scenario field must be lowercase in the API response (stored as UPPERCASE in DB)."""
    _make_campaign(sql, scenario="URBAN_FLOODING")

    res = client.get("/api/v1/public/campaigns")
    assert res.status_code == 200
    campaigns = res.json()
    assert len(campaigns) > 0

    for c in campaigns:
        if c["scenario"] is not None:
            assert c["scenario"] == c["scenario"].lower(), (
                f"scenario not lowercase: {c['scenario']!r}"
            )


@pytest.mark.db
def test_public_campaigns_currency_no_padding(client, sql):
    """currency returned must be exactly 'INR', no trailing spaces from CHAR(3) column."""
    res = client.get("/api/v1/public/campaigns")
    assert res.status_code == 200
    campaigns = res.json()
    assert len(campaigns) > 0

    for c in campaigns:
        assert c["currency"] == c["currency"].strip(), (
            f"currency has padding: {c['currency']!r}"
        )
        # At least the seeded campaigns use INR
        assert c["currency"] in {"INR"}, f"Unexpected currency: {c['currency']!r}"


# ===========================================================================
# POST /api/v1/donations
# ===========================================================================


@pytest.mark.db
def test_donation_creates_pending_order(client, sql):
    """Successful donation must return 201 with PENDING status and a mock order id."""
    cid = _make_campaign(sql)
    res = _post_donation(client, cid, _idem())

    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "PENDING"
    assert data["is_sandbox"] is True
    assert data["gateway_order_id"].startswith("order_mock_sandbox_"), (
        f"Unexpected order id format: {data['gateway_order_id']!r}"
    )
    assert uuid.UUID(data["donation_id"])  # valid UUID, no exception


@pytest.mark.db
def test_donation_idempotency_replay(client, sql):
    """Replaying the same Idempotency-Key must return the same donation_id and insert only 1 row."""
    cid = _make_campaign(sql)
    key = _idem()

    res1 = _post_donation(client, cid, key)
    res2 = _post_donation(client, cid, key)

    assert res1.status_code == 201
    assert res2.status_code == 201
    assert res1.json()["donation_id"] == res2.json()["donation_id"], (
        "Idempotency replay returned different donation_id"
    )

    count = sql.execute(
        "SELECT COUNT(*) AS n FROM donations WHERE idempotency_key = %s", (key,)
    ).fetchone()["n"]
    assert count == 1, f"Expected 1 row in DB, found {count}"


@pytest.mark.db
def test_donation_missing_idempotency_key(client, sql):
    """Request without Idempotency-Key header must be rejected with 422."""
    cid = _make_campaign(sql)
    res = client.post(
        "/api/v1/donations",
        json={
            "campaign_id": cid,
            "amount": "100.00",
            "currency": "INR",
            "guest_email": "x@example.com",
            "is_anonymous": False,
        },
        # Intentionally no Idempotency-Key header
    )
    assert res.status_code == 422


@pytest.mark.db
def test_donation_invalid_amount(client, sql):
    """Negative or zero amount must be rejected with 422."""
    cid = _make_campaign(sql)
    res = _post_donation(client, cid, _idem(), amount="-1")
    assert res.status_code == 422


@pytest.mark.db
def test_donation_nonexistent_campaign(client):
    """Donation against a non-existent campaign must return 404."""
    fake_id = str(uuid.uuid4())
    res = _post_donation(client, fake_id, _idem())
    assert res.status_code == 404


@pytest.mark.db
def test_donation_inactive_campaign(client, sql):
    """Donation against a non-ACTIVE campaign must return 409 with CAMPAIGN_NOT_ACTIVE code."""
    cid = _make_campaign(sql, status="DRAFT")
    res = _post_donation(client, cid, _idem())

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "CAMPAIGN_NOT_ACTIVE"


@pytest.mark.db
def test_donation_logged_in_citizen(client, sql, make):
    """Authenticated citizen donation must persist donor_id and clear guest fields in DB."""
    citizen = make.citizen()
    cid = _make_campaign(sql)

    res = client.post(
        "/api/v1/donations",
        json={
            "campaign_id": cid,
            "amount": "250.00",
            "currency": "INR",
            "is_anonymous": False,
        },
        headers={**citizen["headers"], "Idempotency-Key": _idem()},
    )

    assert res.status_code == 201
    donation_id = res.json()["donation_id"]

    row = sql.execute(
        "SELECT donor_id, guest_name, guest_email FROM donations WHERE donation_id = %s",
        (donation_id,),
    ).fetchone()

    assert str(row["donor_id"]) == str(citizen["user_id"]), "donor_id not set for logged-in citizen"
    assert row["guest_name"] is None, "guest_name should be NULL for logged-in citizen"
    assert row["guest_email"] is None, "guest_email should be NULL for logged-in citizen"


@pytest.mark.db
def test_donation_logged_in_citizen_ignores_guest_fields(client, sql, make):
    """Guest fields sent by an authenticated citizen must be ignored (DB stores NULL)."""
    citizen = make.citizen()
    cid = _make_campaign(sql)

    res = client.post(
        "/api/v1/donations",
        json={
            "campaign_id": cid,
            "amount": "100.00",
            "currency": "INR",
            "guest_name": "Should Be Ignored",
            "guest_email": "should-be-ignored@example.com",
            "is_anonymous": False,
        },
        headers={**citizen["headers"], "Idempotency-Key": _idem()},
    )

    assert res.status_code == 201

    row = sql.execute(
        "SELECT guest_name, guest_email FROM donations WHERE donation_id = %s",
        (res.json()["donation_id"],),
    ).fetchone()

    assert row["guest_name"] is None, "guest_name must be NULL for logged-in user even if sent"
    assert row["guest_email"] is None, "guest_email must be NULL for logged-in user even if sent"


@pytest.mark.db
def test_donation_guest_no_email_not_anonymous(client, sql):
    """Guest donation without email and is_anonymous=False must return 422 GUEST_EMAIL_REQUIRED."""
    cid = _make_campaign(sql)
    res = _post_donation(
        client,
        cid,
        _idem(),
        guest_email=None,
        is_anonymous=False,
    )

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "GUEST_EMAIL_REQUIRED"


@pytest.mark.db
def test_donation_anonymous_no_email(client, sql):
    """Anonymous donation without email must succeed; guest_name must be NULL in DB."""
    cid = _make_campaign(sql)
    res = _post_donation(
        client,
        cid,
        _idem(),
        guest_email=None,
        guest_name="Ghost Donor",
        is_anonymous=True,
    )

    assert res.status_code == 201

    row = sql.execute(
        "SELECT guest_name, guest_email FROM donations WHERE donation_id = %s",
        (res.json()["donation_id"],),
    ).fetchone()

    assert row["guest_name"] is None, "guest_name must be NULL for anonymous donation"


@pytest.mark.db
def test_donation_garbage_bearer_token(client, sql):
    """Invalid bearer token must be treated as guest (not 401) and the donation must succeed."""
    cid = _make_campaign(sql)
    res = client.post(
        "/api/v1/donations",
        json={
            "campaign_id": cid,
            "amount": "75.00",
            "currency": "INR",
            "guest_email": "guest@example.com",
            "is_anonymous": False,
        },
        headers={
            "Authorization": "Bearer this.is.garbage",
            "Idempotency-Key": _idem(),
        },
    )

    assert res.status_code == 201, (
        f"Expected 201 for garbage bearer token (guest fallback), got {res.status_code}: {res.text}"
    )

    row = sql.execute(
        "SELECT donor_id FROM donations WHERE donation_id = %s",
        (res.json()["donation_id"],),
    ).fetchone()
    assert row["donor_id"] is None, "donor_id should be NULL for garbage token (guest)"


@pytest.mark.db
def test_donation_audit_row_created(client, sql):
    """A DONATION_ORDER_CREATED audit log entry must exist within the same transaction."""
    cid = _make_campaign(sql)
    res = _post_donation(client, cid, _idem())

    assert res.status_code == 201
    donation_id = res.json()["donation_id"]

    row = sql.execute(
        "SELECT action, entity_type FROM audit_logs "
        "WHERE action = 'DONATION_ORDER_CREATED' AND entity_id = %s",
        (donation_id,),
    ).fetchone()

    assert row is not None, f"No audit log found for donation_id={donation_id}"
    assert row["action"] == "DONATION_ORDER_CREATED"
    assert row["entity_type"] == "donation"


# ===========================================================================
# MockGateway unit tests  (no DB — no pytestmark.db)
# ===========================================================================


def test_mock_gateway_valid_signature():
    """compute_signature + verify_payment round-trip must return verified=True."""
    from app.payments.mock import MockGateway

    gw = MockGateway()
    order_id = "order_mock_sandbox_abc123"
    payment_id = "pay_test_xyz789"

    sig = gw.compute_signature(order_id, payment_id)
    result = gw.verify_payment(
        order_id=order_id,
        payment_id=payment_id,
        signature=sig,
        amount=100,
        currency="INR",
    )

    assert result.verified is True, "Valid signature must verify successfully"


def test_mock_gateway_tampered_signature():
    """A tampered signature must return verified=False without raising."""
    from app.payments.mock import MockGateway

    gw = MockGateway()
    order_id = "order_mock_sandbox_abc123"
    payment_id = "pay_test_xyz789"

    result = gw.verify_payment(
        order_id=order_id,
        payment_id=payment_id,
        signature="deadbeef" * 8,  # wrong but same length as SHA256 hex
        amount=100,
        currency="INR",
    )

    assert result.verified is False, "Tampered signature must not verify"


def test_mock_gateway_none_signature():
    """Passing signature=None must not raise and must return verified=False."""
    from app.payments.mock import MockGateway

    gw = MockGateway()

    result = gw.verify_payment(
        order_id="order_mock_sandbox_x",
        payment_id="pay_none",
        signature=None,
        amount=50,
        currency="INR",
    )

    assert result.verified is False, "None signature must not crash and must not verify"
