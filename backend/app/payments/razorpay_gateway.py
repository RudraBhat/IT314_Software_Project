"""Razorpay payment gateway stub and signature verification."""

import hashlib
import hmac
import json
import os
from decimal import Decimal

from app.config import get_settings
from app.payments.base import Order, PaymentGateway, Verification, WebhookEvent


def _get_razorpay_credentials() -> tuple[str | None, str | None]:
    """Read credentials from app settings or environment variables."""
    settings = get_settings()
    key_id = getattr(settings, "razorpay_key_id", None)
    key_secret = getattr(settings, "razorpay_key_secret", None)
    if key_id and key_secret:
        return str(key_id), str(key_secret)
    return os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")


class RazorpayGateway(PaymentGateway):
    """Razorpay payment gateway implementation."""

    name: str = "RAZORPAY"

    @property
    def is_sandbox(self) -> bool:
        key_id, _ = _get_razorpay_credentials()
        return not bool(key_id and key_id.startswith("rzp_live"))

    def create_order(self, amount: Decimal, currency: str, reference: str) -> Order:
        """Create Razorpay order (stubbed in Sprint 1 to prevent external network calls)."""
        raise NotImplementedError("Razorpay live order creation is not supported in Sprint 1; use MOCK_GATEWAY")

    def verify_payment(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
        amount: Decimal,
        currency: str,
    ) -> Verification:
        """Verify Razorpay payment signature: HMAC-SHA256 of '<order_id>|<payment_id>'."""
        _, key_secret = _get_razorpay_credentials()
        if not key_secret:
            return Verification(
                verified=False,
                order_id=order_id,
                payment_id=payment_id,
                error_message="RAZORPAY_KEY_SECRET is not configured",
            )

        message = f"{order_id}|{payment_id}".encode()
        expected = hmac.new(key_secret.encode(), message, hashlib.sha256).hexdigest()
        is_valid = hmac.compare_digest(expected, signature)
        return Verification(
            verified=is_valid,
            order_id=order_id,
            payment_id=payment_id,
            error_message=None if is_valid else "Razorpay signature verification failed",
            raw_payload={
                "order_id": order_id,
                "payment_id": payment_id,
                "signature": signature,
                "amount": str(amount),
                "currency": currency,
            },
        )

    def parse_webhook(self, raw_body: bytes | str, signature: str) -> WebhookEvent:
        """Verify and parse Razorpay webhook payload."""
        webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
        if not webhook_secret:
            _, webhook_secret = _get_razorpay_credentials()
        if not webhook_secret:
            raise ValueError("RAZORPAY_WEBHOOK_SECRET is not configured")

        body_bytes = raw_body.encode() if isinstance(raw_body, str) else raw_body
        expected = hmac.new(webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid Razorpay webhook signature")

        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid webhook JSON payload: {e}") from e

        event_type = data.get("event", "payment.captured")
        payment_entity = data.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = payment_entity.get("order_id")
        payment_id = payment_entity.get("id")
        status = payment_entity.get("status", "captured")

        return WebhookEvent(
            event_type=event_type,
            order_id=order_id,
            payment_id=payment_id,
            status=status,
            payload=data,
        )
