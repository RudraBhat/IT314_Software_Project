"""Razorpay gateway (PAYMENT_GATEWAY=razorpay).

- Orders are created server-side through the Orders API for the exact amount (in paise) and
  currency of the donation, so a checkout payment is bound to that amount by Razorpay itself.
- The checkout callback signature is HMAC-SHA256 with RAZORPAY_KEY_SECRET over
  "<order_id>|<payment_id>" (Razorpay's documented scheme).
- Webhooks are HMAC-SHA256 with RAZORPAY_WEBHOOK_SECRET over the raw body, sent in
  X-Razorpay-Signature; the event id comes from X-Razorpay-Event-Id. The webhook amount and
  currency are checked against the donation by the caller before anything is confirmed.

Keys starting with rzp_live are live mode; any other key is Razorpay test mode (sandbox).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from decimal import Decimal

import httpx

from app.config import ConfigError, get_settings
from app.payments.base import (
    InvalidWebhook,
    Order,
    PaymentGateway,
    PaymentGatewayError,
    Verification,
    WebhookEvent,
    fallback_event_id,
    header,
    parse_payment_entity,
    to_minor_units,
)

ORDERS_URL = "https://api.razorpay.com/v1/orders"
SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "X-Razorpay-Event-Id"
_TIMEOUT_SECONDS = 10.0


class RazorpayGateway(PaymentGateway):
    name = "RAZORPAY"
    slug = "razorpay"

    @staticmethod
    def _credentials() -> tuple[str, str]:
        settings = get_settings()
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise ConfigError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required for PAYMENT_GATEWAY=razorpay")
        return settings.razorpay_key_id, settings.razorpay_key_secret

    @property
    def is_sandbox(self) -> bool:
        key_id = get_settings().razorpay_key_id or ""
        return not key_id.startswith("rzp_live")

    def checkout_key(self) -> str | None:
        # The key id is public by design: Razorpay Checkout needs it in the browser.
        return get_settings().razorpay_key_id or None

    def create_order(self, amount: Decimal, currency: str, reference: str) -> Order:
        key_id, key_secret = self._credentials()
        try:
            response = httpx.post(
                ORDERS_URL,
                auth=(key_id, key_secret),
                json={"amount": to_minor_units(amount), "currency": currency, "receipt": reference[:40]},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise PaymentGatewayError("Razorpay could not be reached") from exc
        if response.status_code >= 400:
            raise PaymentGatewayError(f"Razorpay refused the order (HTTP {response.status_code})")
        data = response.json()
        if data.get("amount") != to_minor_units(amount) or str(data.get("currency", "")).upper() != currency:
            raise PaymentGatewayError("Razorpay returned an order for a different amount or currency")
        return Order(
            order_id=data["id"],
            amount=amount,
            currency=currency,
            gateway_name=self.name,
            is_sandbox=self.is_sandbox,
            status=str(data.get("status", "created")).upper(),
            raw_response=data,
        )

    def verify_payment(
        self, order_id: str, payment_id: str, signature: str, amount: Decimal, currency: str
    ) -> Verification:
        # amount and currency are fixed by the server-created order (see module docstring).
        _, key_secret = self._credentials()
        expected = hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(expected, signature or "")
        return Verification(
            verified=valid,
            order_id=order_id,
            payment_id=payment_id,
            error_message=None if valid else "Razorpay signature verification failed",
        )

    def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        secret = get_settings().razorpay_webhook_secret
        if not secret:
            raise ConfigError("RAZORPAY_WEBHOOK_SECRET is required for PAYMENT_GATEWAY=razorpay")
        signature = header(headers, SIGNATURE_HEADER)
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise InvalidWebhook("Razorpay webhook signature did not match")
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidWebhook("Webhook body is not valid JSON") from exc
        event_id = header(headers, EVENT_ID_HEADER) or fallback_event_id(raw_body)
        return parse_payment_entity(event_id, data)
