"""Payment gateways (issue #102): one interface, boot-time validation, Razorpay signature maths.

No network: the Razorpay Orders API call is replaced with a fake httpx response.
"""

import hashlib
import hmac
import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest

from app.config import ConfigError, get_settings
from app.payments import (
    InvalidWebhook,
    MockGateway,
    PaymentGateway,
    PaymentGatewayError,
    RazorpayGateway,
    get_gateway,
    is_sandbox_gateway,
    payment_config_problems,
)
from app.payments.base import to_minor_units


@pytest.fixture
def razorpay_env(monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY", "razorpay")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "key-secret-for-tests")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "webhook-secret-for-tests")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def gateway(razorpay_env):
    return RazorpayGateway()


def _sign(secret: str, message: str | bytes) -> str:
    data = message.encode() if isinstance(message, str) else message
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


# ── configuration ───────────────────────────────────────────────────────


def test_unsupported_gateway_is_a_startup_problem():
    settings = replace(get_settings(), payment_gateway="stripe")
    problems = payment_config_problems(settings)
    assert problems and "not supported" in problems[0]


def test_razorpay_without_keys_is_a_startup_problem():
    settings = replace(
        get_settings(), payment_gateway="razorpay",
        razorpay_key_id=None, razorpay_key_secret=None, razorpay_webhook_secret=None,
    )
    assert "RAZORPAY_KEY_ID" in payment_config_problems(settings)[0]


def test_app_refuses_to_start_with_an_unsupported_gateway(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app

    monkeypatch.setenv("PAYMENT_GATEWAY", "paypal")
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigError, match="PAYMENT_GATEWAY"), TestClient(app):
            pass
    finally:
        get_settings.cache_clear()


def test_get_gateway_returns_the_configured_implementation(razorpay_env):
    gateway = get_gateway()
    assert isinstance(gateway, RazorpayGateway) and isinstance(gateway, PaymentGateway)


def test_sandbox_label_follows_the_gateway(razorpay_env, monkeypatch):
    assert is_sandbox_gateway("MOCK_GATEWAY") is True
    assert is_sandbox_gateway("RAZORPAY") is True  # rzp_test_ key
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_abc")
    get_settings.cache_clear()
    assert is_sandbox_gateway("RAZORPAY") is False


def test_minor_units():
    assert to_minor_units(Decimal("2500.00")) == 250000
    assert to_minor_units(Decimal("0.01")) == 1


# ── mock gateway ────────────────────────────────────────────────────────


def test_mock_signature_binds_amount_and_currency(monkeypatch):
    monkeypatch.setenv("MOCK_GATEWAY_SECRET", "mock-secret-for-tests")
    get_settings.cache_clear()
    try:
        gw = MockGateway()
        sig = gw.sign("order_1", "pay_1", Decimal("100.00"), "INR")
        assert gw.verify_payment("order_1", "pay_1", sig, Decimal("100.00"), "INR").verified
        assert not gw.verify_payment("order_1", "pay_1", sig, Decimal("100.01"), "INR").verified
        assert not gw.verify_payment("order_1", "pay_1", sig, Decimal("100.00"), "USD").verified
        assert not gw.verify_payment("order_2", "pay_1", sig, Decimal("100.00"), "INR").verified
    finally:
        get_settings.cache_clear()


# ── razorpay ────────────────────────────────────────────────────────────


def test_valid_signature_verifies_and_test_key_is_sandbox(gateway):
    sig = _sign("key-secret-for-tests", "order_1|pay_1")
    result = gateway.verify_payment("order_1", "pay_1", sig, Decimal(100), "INR")
    assert result.verified and gateway.is_sandbox


def test_checkout_key_is_the_public_key_id_only(gateway):
    key = gateway.checkout_key()
    assert key == "rzp_test_abc"
    assert "key-secret-for-tests" not in key and "webhook-secret-for-tests" not in key


def test_mock_gateway_has_no_checkout_key(monkeypatch):
    monkeypatch.setenv("MOCK_GATEWAY_SECRET", "mock-secret-for-tests")
    get_settings.cache_clear()
    try:
        assert MockGateway().checkout_key() is None
    finally:
        get_settings.cache_clear()


def test_tampered_signature_is_rejected(gateway):
    result = gateway.verify_payment("order_1", "pay_1", "0" * 64, Decimal(100), "INR")
    assert not result.verified and result.error_message


def test_create_order_sends_paise_and_returns_the_order(gateway, monkeypatch):
    calls = {}

    def fake_post(url, *, auth, json, timeout):
        calls.update(url=url, auth=auth, json=json)
        return httpx.Response(200, json={"id": "order_RZP1", "amount": json["amount"], "currency": "INR", "status": "created"})

    monkeypatch.setattr(httpx, "post", fake_post)
    order = gateway.create_order(Decimal("2500.00"), "INR", "donation-ref")
    assert order.order_id == "order_RZP1" and order.gateway_name == "RAZORPAY"
    assert calls["json"] == {"amount": 250000, "currency": "INR", "receipt": "donation-ref"}
    assert calls["auth"] == ("rzp_test_abc", "key-secret-for-tests")


def test_create_order_failure_is_a_gateway_error(gateway, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(401, json={"error": {}}))
    with pytest.raises(PaymentGatewayError):
        gateway.create_order(Decimal("10.00"), "INR", "ref")


def test_create_order_with_a_different_amount_is_refused(gateway, monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: httpx.Response(200, json={"id": "order_X", "amount": 1, "currency": "INR"})
    )
    with pytest.raises(PaymentGatewayError):
        gateway.create_order(Decimal("10.00"), "INR", "ref")


def test_webhook_signature_amount_and_event_id_are_parsed(gateway):
    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_1", "order_id": "order_1", "amount": 250000, "currency": "INR"}}},
    }).encode()
    headers = {"x-razorpay-signature": _sign("webhook-secret-for-tests", body), "X-Razorpay-Event-Id": "evt_1"}
    event = gateway.parse_webhook(body, headers)
    assert (event.event_id, event.order_id, event.payment_id) == ("evt_1", "order_1", "pay_1")
    assert event.amount == Decimal("2500.00") and event.currency == "INR" and event.is_capture

    with pytest.raises(InvalidWebhook):
        gateway.parse_webhook(body, {"X-Razorpay-Signature": "bad-signature"})


def test_webhook_without_event_id_uses_a_stable_body_hash(gateway):
    body = json.dumps({"event": "payment.captured", "payload": {}}).encode()
    headers = {"X-Razorpay-Signature": _sign("webhook-secret-for-tests", body)}
    assert gateway.parse_webhook(body, headers).event_id == gateway.parse_webhook(body, headers).event_id
