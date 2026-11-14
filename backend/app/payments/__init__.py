"""Payment gateways behind one interface, selected with PAYMENT_GATEWAY (mock | razorpay).

An unsupported PAYMENT_GATEWAY, or razorpay without its keys, is a startup error
(payment_config_problems is checked in main.lifespan) instead of a 500 on the first donation.
"""

from app.config import ConfigError, Settings, get_settings
from app.payments.base import (
    InvalidWebhook,
    Order,
    PaymentGateway,
    PaymentGatewayError,
    Verification,
    WebhookEvent,
)
from app.payments.mock_gateway import MockGateway
from app.payments.razorpay_gateway import RazorpayGateway

GATEWAYS: dict[str, type[PaymentGateway]] = {
    MockGateway.slug: MockGateway,
    RazorpayGateway.slug: RazorpayGateway,
}
_BY_STORED_NAME = {cls.name: cls for cls in GATEWAYS.values()}


def payment_config_problems(settings: Settings) -> list[str]:
    """Configuration errors that must stop startup in every environment."""
    name = settings.payment_gateway
    if name not in GATEWAYS:
        return [f"PAYMENT_GATEWAY={name!r} is not supported; use one of: {', '.join(sorted(GATEWAYS))}"]
    if name == RazorpayGateway.slug:
        missing = [
            env
            for env, value in (
                ("RAZORPAY_KEY_ID", settings.razorpay_key_id),
                ("RAZORPAY_KEY_SECRET", settings.razorpay_key_secret),
                ("RAZORPAY_WEBHOOK_SECRET", settings.razorpay_webhook_secret),
            )
            if not value
        ]
        if missing:
            return [f"PAYMENT_GATEWAY=razorpay requires {', '.join(missing)}"]
    return []


def get_gateway() -> PaymentGateway:
    """The configured gateway. Startup already rejected bad configuration; this is the backstop."""
    settings = get_settings()
    problems = payment_config_problems(settings)
    if problems:
        raise ConfigError("; ".join(problems))
    return GATEWAYS[settings.payment_gateway]()


def is_sandbox_gateway(stored_name: str | None) -> bool:
    """Sandbox label for a stored donation: unknown or mock gateways are always sandbox."""
    cls = _BY_STORED_NAME.get(stored_name or "")
    return True if cls is None else cls().is_sandbox


__all__ = [
    "GATEWAYS",
    "InvalidWebhook",
    "MockGateway",
    "Order",
    "PaymentGateway",
    "PaymentGatewayError",
    "RazorpayGateway",
    "Verification",
    "WebhookEvent",
    "get_gateway",
    "is_sandbox_gateway",
    "payment_config_problems",
]
