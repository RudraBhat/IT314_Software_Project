"""Base classes and interfaces for payment gateways."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Order:
    order_id: str
    amount: Decimal
    currency: str
    gateway_name: str
    is_sandbox: bool
    status: str = "PENDING"
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class Verification:
    verified: bool
    order_id: str
    payment_id: str
    error_message: str | None = None
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class WebhookEvent:
    event_type: str
    order_id: str | None
    payment_id: str | None
    status: str
    payload: dict[str, Any]


class PaymentGateway(ABC):
    """Abstract payment gateway interface."""

    name: str
    is_sandbox: bool

    @abstractmethod
    def create_order(self, amount: Decimal, currency: str, reference: str) -> Order:
        """Create an order with the payment gateway."""
        raise NotImplementedError

    @abstractmethod
    def verify_payment(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
        amount: Decimal,
        currency: str,
    ) -> Verification:
        """Verify payment signature and details."""
        raise NotImplementedError

    @abstractmethod
    def parse_webhook(self, raw_body: bytes | str, signature: str) -> WebhookEvent:
        """Verify webhook signature and parse event payload."""
        raise NotImplementedError
