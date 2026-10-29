"""Payments package providing payment gateway abstractions and factory."""

import os

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
    """Return configured payment gateway instance based on PAYMENT_GATEWAY environment variable.

    Defaults to MOCK_GATEWAY for sandbox / local development.
    """
    settings = get_settings()
    gw_type = getattr(settings, "payment_gateway", None)
    if gw_type:
        gateway_name = str(gw_type).strip().upper()
    else:
        gateway_name = os.getenv("PAYMENT_GATEWAY", "MOCK").strip().upper()

    if gateway_name in ("RAZORPAY", "RAZORPAY_GATEWAY"):
        return RazorpayGateway()

    return MockGateway()
