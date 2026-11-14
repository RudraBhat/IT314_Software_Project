"""The one payment-gateway interface used by the donation flow (docs/api_contracts.md section 7).

Every gateway (the sandbox MockGateway and the live RazorpayGateway) implements the same three
operations. A donation is CONFIRMED only after a gateway has verified a signature over the
payment, and that payment is bound to the donation's order, amount and currency.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Gateway events that confirm or fail a payment; anything else is acknowledged and ignored.
CAPTURE_EVENTS = frozenset({"payment.captured", "order.paid"})
FAILURE_EVENTS = frozenset({"payment.failed"})


class PaymentGatewayError(Exception):
    """The gateway could not be reached or refused the request (mapped to 502)."""


class InvalidWebhook(Exception):
    """The webhook signature is missing or wrong, or the body is not a valid event (mapped to 400)."""


def to_minor_units(amount: Decimal) -> int:
    """INR 2500.00 -> 250000 paise. Gateways exchange integer minor units."""
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_minor_units(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return (Decimal(int(value)) / 100).quantize(Decimal("0.01"))
    except (TypeError, ValueError, ArithmeticError):
        return None


def canonical_amount(amount: Decimal) -> str:
    """The exact text an amount is signed as: two decimal places, no grouping ("2500.00")."""
    return f"{Decimal(amount).quantize(Decimal('0.01')):f}"


def fallback_event_id(raw_body: bytes) -> str:
    """A deterministic id for gateways that send none, so a replayed body is still a duplicate."""
    return "sha256:" + hashlib.sha256(raw_body).hexdigest()


def header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive header lookup that works for plain dicts and Starlette headers."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


@dataclass(frozen=True)
class Order:
    order_id: str
    amount: Decimal
    currency: str
    gateway_name: str
    is_sandbox: bool
    status: str = "CREATED"
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class Verification:
    verified: bool
    order_id: str
    payment_id: str
    error_message: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    event_type: str
    order_id: str | None
    payment_id: str | None
    amount: Decimal | None
    currency: str | None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_capture(self) -> bool:
        return self.event_type in CAPTURE_EVENTS

    @property
    def is_failure(self) -> bool:
        return self.event_type in FAILURE_EVENTS


def parse_payment_entity(event_id: str, data: dict[str, Any]) -> WebhookEvent:
    """Read the Razorpay-shaped body {"event", "payload": {"payment": {"entity": {...}}}}."""
    if not isinstance(data, dict) or not isinstance(data.get("event"), str):
        raise InvalidWebhook("Webhook body has no event type")
    entity = (data.get("payload") or {}).get("payment", {}).get("entity", {}) or {}
    currency = entity.get("currency")
    return WebhookEvent(
        event_id=event_id,
        event_type=data["event"],
        order_id=entity.get("order_id"),
        payment_id=entity.get("id"),
        amount=from_minor_units(entity.get("amount")),
        currency=currency.upper() if isinstance(currency, str) else None,
        payload=data,
    )


class PaymentGateway(ABC):
    """Common interface for every gateway selectable with PAYMENT_GATEWAY."""

    #: Value stored in donations.gateway_name.
    name: str
    #: Path segment of POST /api/v1/payments/webhook/{gateway}.
    slug: str

    @property
    @abstractmethod
    def is_sandbox(self) -> bool:
        """True when no real money can move (shown to the donor as a sandbox label)."""

    def checkout_key(self) -> str | None:
        """Public key the browser needs to open the gateway's hosted checkout (None when there is none).

        Only ever a publishable identifier, never a secret.
        """
        return None

    @abstractmethod
    def create_order(self, amount: Decimal, currency: str, reference: str) -> Order:
        """Create a gateway order for exactly this amount and currency."""

    @abstractmethod
    def verify_payment(
        self, order_id: str, payment_id: str, signature: str, amount: Decimal, currency: str
    ) -> Verification:
        """Verify the browser callback signature for a payment against this order and amount."""

    @abstractmethod
    def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Check the webhook signature over the raw body and parse the event, or raise InvalidWebhook."""
