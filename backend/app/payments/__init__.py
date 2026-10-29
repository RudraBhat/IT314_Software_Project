"""Payments package providing payment gateway abstractions and factory."""

from app.config import get_settings
from app.payments.base import Order, PaymentGateway, Verification, WebhookEvent
from app.payments.mock import MockGateway
from app.payments.razorpay_gateway import RazorpayGateway

__all__ = [
    "MockGateway",
    "Order",
    "PaymentGateway",
    "RazorpayGateway",
    "Verification",
    "WebhookEvent",
    "get_gateway",
]


def get_gateway() -> PaymentGateway:
    """Return configured payment gateway instance based on application settings.

    Defaults to MOCK_GATEWAY for sandbox / local development.
    """
    settings = get_settings()
    gateway_name = settings.payment_gateway.strip().upper()

    if gateway_name in ("RAZORPAY", "RAZORPAY_GATEWAY"):
        return RazorpayGateway()

    return MockGateway()
