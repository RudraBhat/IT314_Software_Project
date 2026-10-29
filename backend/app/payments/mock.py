"""Mock payment gateway implementation for sandbox/development environments."""

import hashlib
import hmac
import json
import uuid
from decimal import Decimal

from app.config import get_settings
from app.payments.base import Order, PaymentGateway, Verification, WebhookEvent


def _get_mock_secret() -> str:
    """Read mock signing secret from app settings. Never hardcoded."""
    settings = get_settings()
    secret = getattr(settings, "payment_signing_secret", None) or settings.jwt_secret
    return secret or "mock_sandbox_fallback_key"


class MockGateway(PaymentGateway):
    """Deterministic mock gateway for local testing and CI."""

    name: str = "MOCK_GATEWAY"
    is_sandbox: bool = True

    def create_order(self, amount: Decimal, currency: str, reference: str) -> Order:
        """Create mock order with contract ID format: order_mock_sandbox_xxxx."""
        suffix = uuid.uuid4().hex[:6]
        order_id = f"order_mock_sandbox_{suffix}"
        return Order(
            order_id=order_id,
            amount=Decimal(str(amount)),
            currency=currency.upper(),
            gateway_name=self.name,
            is_sandbox=self.is_sandbox,
            status="PENDING",
            raw_response={"reference": reference, "mode": "sandbox"},
        )

    def compute_signature(self, order_id: str, payment_id: str) -> str:
        """Compute expected HMAC-SHA256 signature for verification."""
        secret = _get_mock_secret().encode()
        payload = f"{order_id}|{payment_id}".encode()
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def compute_webhook_signature(self, raw_body: bytes | str) -> str:
        """Compute expected HMAC-SHA256 signature for webhook payload."""
        body_bytes = raw_body.encode() if isinstance(raw_body, str) else raw_body
        secret = _get_mock_secret().encode()
        return hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

    def verify_payment(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
        amount: Decimal,
        currency: str,
    ) -> Verification:
        """Verify payment using constant-time HMAC-SHA256 comparison."""
        expected = self.compute_signature(order_id, payment_id)
        is_valid = hmac.compare_digest(expected, signature)
        return Verification(
            verified=is_valid,
            order_id=order_id,
            payment_id=payment_id,
            error_message=None if is_valid else "Signature verification failed",
            raw_payload={
                "order_id": order_id,
                "payment_id": payment_id,
                "signature": signature,
                "amount": str(amount),
                "currency": currency,
            },
        )

    def parse_webhook(self, raw_body: bytes | str, signature: str) -> WebhookEvent:
        """Verify raw body HMAC-SHA256 signature and normalize webhook event."""
        body_bytes = raw_body.encode() if isinstance(raw_body, str) else raw_body
        expected = self.compute_webhook_signature(body_bytes)
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid webhook signature")

        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid webhook JSON payload: {e}") from e

        event_type = data.get("event", "payment.captured")
        payload_entity = data.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = data.get("order_id") or payload_entity.get("order_id")
        payment_id = data.get("payment_id") or payload_entity.get("id")
        status = data.get("status") or payload_entity.get("status", "captured")

        return WebhookEvent(
            event_type=event_type,
            order_id=order_id,
            payment_id=payment_id,
            status=status,
            payload=data,
        )
