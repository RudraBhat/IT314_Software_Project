"""Payment gateway interface and the sandbox MockGateway (docs/api_contracts.md section 6). Owner: Shlok.

Only a verified gateway callback may move a donation to CONFIRMED. The mock gateway signs
"<order_id>|<payment_id>" with HMAC-SHA256 using MOCK_GATEWAY_SECRET. A real gateway
(Razorpay/Stripe) implements the same three methods; select it with PAYMENT_GATEWAY.
"""

import hashlib
import hmac
import secrets
from typing import Protocol

from app.config import get_settings


class PaymentGateway(Protocol):
    name: str
    is_sandbox: bool

    def create_order(self, donation_id: str, amount: str, currency: str) -> str: ...

    def verify(self, order_id: str, payment_id: str, signature: str) -> bool: ...


class MockGateway:
    name = "MOCK_GATEWAY"
    is_sandbox = True

    @staticmethod
    def _secret() -> bytes:
        return get_settings().require("mock_gateway_secret").encode()

    def create_order(self, donation_id: str, amount: str, currency: str) -> str:
        return "order_mock_" + secrets.token_hex(8)

    def sign(self, order_id: str, payment_id: str) -> str:
        return hmac.new(self._secret(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()

    def verify(self, order_id: str, payment_id: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(order_id, payment_id), signature or "")

    def new_payment_id(self) -> str:
        return "pay_mock_" + secrets.token_hex(6)


def get_gateway() -> MockGateway:
    name = get_settings().payment_gateway
    if name != "mock":
        raise NotImplementedError(f"Payment gateway '{name}' is not implemented; use PAYMENT_GATEWAY=mock")
    return MockGateway()
