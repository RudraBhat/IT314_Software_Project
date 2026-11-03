"""Razorpay adapter: signature maths only, no network (it is not wired into the donation flow yet)."""

import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from app.config import get_settings
from app.payments import RazorpayGateway


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "key-secret-for-tests")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "webhook-secret-for-tests")
    get_settings.cache_clear()
    yield RazorpayGateway()
    get_settings.cache_clear()


def _sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def test_valid_signature_verifies_and_test_key_is_sandbox(gateway):
    sig = _sign("key-secret-for-tests", "order_1|pay_1")
    result = gateway.verify_payment("order_1", "pay_1", sig, Decimal(100), "INR")
    assert result.verified and gateway.is_sandbox


def test_tampered_signature_is_rejected(gateway):
    result = gateway.verify_payment("order_1", "pay_1", "0" * 64, Decimal(100), "INR")
    assert not result.verified and result.error_message


def test_order_creation_is_not_available_yet(gateway):
    with pytest.raises(NotImplementedError):
        gateway.create_order(Decimal(100), "INR", "ref")


def test_webhook_signature_is_checked(gateway):
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_1", "order_id": "order_1"}}}})
    event = gateway.parse_webhook(body, _sign("webhook-secret-for-tests", body))
    assert (event.order_id, event.payment_id) == ("order_1", "pay_1")
    with pytest.raises(ValueError):
        gateway.parse_webhook(body, "bad-signature")
