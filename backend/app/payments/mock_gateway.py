"""Sandbox gateway (PAYMENT_GATEWAY=mock): no money moves, every response is labelled sandbox.

The callback signature is HMAC-SHA256 with MOCK_GATEWAY_SECRET over
"<order_id>|<payment_id>|<amount>|<currency>", so a signature issued for one amount or currency
cannot confirm a donation of another. Webhooks are signed over the raw body and sent with the
X-Mock-Signature header; the body has the same shape as a Razorpay payment event.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from decimal import Decimal

from app.config import get_settings
from app.payments.base import (
    InvalidWebhook,
    Order,
    PaymentGateway,
    Verification,
    WebhookEvent,
    canonical_amount,
    fallback_event_id,
    header,
    parse_payment_entity,
)

SIGNATURE_HEADER = "X-Mock-Signature"
EVENT_ID_HEADER = "X-Mock-Event-Id"


class MockGateway(PaymentGateway):
    name = "MOCK_GATEWAY"
    slug = "mock"

    @property
    def is_sandbox(self) -> bool:
        return True

    @staticmethod
    def _secret() -> bytes:
        return get_settings().require("mock_gateway_secret").encode()

    def _hmac(self, message: bytes) -> str:
        return hmac.new(self._secret(), message, hashlib.sha256).hexdigest()

    # ── orders and callbacks ────────────────────────────────────────────

    def create_order(self, amount: Decimal, currency: str, reference: str) -> Order:
        return Order(
            order_id="order_mock_" + secrets.token_hex(8),
            amount=amount,
            currency=currency,
            gateway_name=self.name,
            is_sandbox=True,
        )

    def sign(self, order_id: str, payment_id: str, amount: Decimal, currency: str) -> str:
        message = f"{order_id}|{payment_id}|{canonical_amount(amount)}|{currency.upper()}"
        return self._hmac(message.encode())

    def verify_payment(
        self, order_id: str, payment_id: str, signature: str, amount: Decimal, currency: str
    ) -> Verification:
        valid = hmac.compare_digest(self.sign(order_id, payment_id, amount, currency), signature or "")
        return Verification(
            verified=valid,
            order_id=order_id,
            payment_id=payment_id,
            error_message=None if valid else "Mock gateway signature did not match",
        )

    def new_payment_id(self) -> str:
        return "pay_mock_" + secrets.token_hex(6)

    # ── webhooks ────────────────────────────────────────────────────────

    def sign_webhook(self, raw_body: bytes) -> str:
        return self._hmac(raw_body)

    def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        signature = header(headers, SIGNATURE_HEADER)
        if not signature or not hmac.compare_digest(self.sign_webhook(raw_body), signature):
            raise InvalidWebhook("Mock webhook signature did not match")
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidWebhook("Webhook body is not valid JSON") from exc
        event_id = header(headers, EVENT_ID_HEADER) or str(data.get("id") or "") or fallback_event_id(raw_body)
        return parse_payment_entity(event_id, data)
