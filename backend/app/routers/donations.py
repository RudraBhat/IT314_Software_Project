"""Donations (docs/api_contracts.md section 6). Owner: Shlok.

Create an order (PENDING), then verify the gateway signature to CONFIRM and issue a receipt.
The sandbox endpoint exists only for the mock gateway outside production so the UI and tests
can complete a payment without a real provider.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import MaybeUser
from app.config import get_settings
from app.errors import ApiError, conflict, not_found
from app.ratelimit import rate_limit
from app.services.payments import get_gateway

router = APIRouter(prefix="/api/v1/donations", tags=["donations"])


class DonationCreate(BaseModel):
    campaign_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", pattern="^INR$")
    guest_name: str | None = Field(default=None, max_length=150)
    guest_email: str | None = Field(default=None, max_length=254)
    is_anonymous: bool = False


class DonationVerify(BaseModel):
    gateway_payment_id: str = Field(min_length=5, max_length=100)
    signature: str = Field(min_length=10, max_length=200)


def _order_body(row: dict) -> dict:
    return {
        "donation_id": row["donation_id"],
        "gateway_name": row["gateway_name"],
        "gateway_order_id": row["gateway_order_id"],
        "amount": row["amount"],
        "currency": row["currency"].strip(),
        "status": row["status"],
        "is_sandbox": True,
    }


def _load_for_caller(conn, donation_id: uuid.UUID, user) -> dict:
    row = conn.execute("SELECT * FROM donations WHERE donation_id = %s FOR UPDATE", (donation_id,)).fetchone()
    # A donation tied to an account is visible only to that account; guest donations to whoever holds the id.
    if row is None or (row["donor_id"] is not None and (user is None or row["donor_id"] != user.user_id)):
        raise not_found("Donation")
    return row


@router.post("", status_code=201, dependencies=[rate_limit("donation", 30, 3600)])
def create_donation(
    body: DonationCreate,
    user: MaybeUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
):
    if not idempotency_key:
        raise ApiError(422, "IDEMPOTENCY_KEY_REQUIRED", "The Idempotency-Key header is required")
    if user is None and not (body.guest_email or body.is_anonymous):
        raise ApiError(422, "VALIDATION_FAILED", "Guests must provide guest_email, or donate anonymously")
    gateway = get_gateway()
    with db.transaction() as conn:
        existing = conn.execute("SELECT * FROM donations WHERE idempotency_key = %s", (idempotency_key,)).fetchone()
        if existing:
            same = (
                existing["campaign_id"] == body.campaign_id
                and existing["amount"] == body.amount
                and existing["donor_id"] == (user.user_id if user else None)
            )
            if not same:
                raise conflict("IDEMPOTENCY_CONFLICT", "Idempotency-Key was already used for a different donation")
            return JSONResponse(status_code=200, content=jsonable_encoder(_order_body(existing)))
        campaign = conn.execute(
            "SELECT status FROM donation_campaigns WHERE campaign_id = %s", (body.campaign_id,)
        ).fetchone()
        if campaign is None:
            raise not_found("Campaign")
        if campaign["status"] != "ACTIVE":
            raise conflict("CAMPAIGN_NOT_ACTIVE", "This campaign is not accepting donations")
        donation_id = uuid.uuid4()
        order_id = gateway.create_order(str(donation_id), str(body.amount), body.currency)
        row = conn.execute(
            """
            INSERT INTO donations (donation_id, campaign_id, donor_id, amount, currency, is_anonymous,
                                   guest_name, guest_email, gateway_name, gateway_order_id, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
            """,
            (
                donation_id, body.campaign_id, user.user_id if user else None, body.amount, body.currency,
                body.is_anonymous, None if user else body.guest_name, None if user else body.guest_email,
                gateway.name, order_id, idempotency_key,
            ),
        ).fetchone()
        audit.record(
            conn, actor=user, action="DONATION_CREATED", entity_type="donation", entity_id=donation_id,
            after={"amount": str(body.amount), "campaign_id": str(body.campaign_id), "gateway": gateway.name},
            ip=user.ip if user else None,
        )
        return _order_body(row)


@router.post("/{donation_id}/sandbox-payment")
def sandbox_payment(donation_id: uuid.UUID, user: MaybeUser):
    """Sandbox only: act as the gateway and return a payment id plus a valid signature."""
    settings = get_settings()
    if settings.payment_gateway != "mock" or settings.app_env == "production":
        raise not_found("Endpoint")
    gateway = get_gateway()
    with db.transaction() as conn:
        row = _load_for_caller(conn, donation_id, user)
        if row["status"] != "PENDING":
            raise conflict("DONATION_NOT_PENDING", f"Donation is {row['status']}")
    payment_id = gateway.new_payment_id()
    return {"gateway_payment_id": payment_id, "signature": gateway.sign(row["gateway_order_id"], payment_id)}


@router.post("/{donation_id}/verify")
def verify_donation(donation_id: uuid.UUID, body: DonationVerify, user: MaybeUser):
    gateway = get_gateway()
    with db.transaction() as conn:
        row = _load_for_caller(conn, donation_id, user)
        if row["status"] == "CONFIRMED":
            if row["gateway_payment_id"] != body.gateway_payment_id:
                raise conflict("ALREADY_CONFIRMED", "This donation was confirmed with a different payment")
            return _confirmed_body(row)
        if row["status"] != "PENDING":
            raise conflict("DONATION_NOT_PENDING", f"Donation is {row['status']}")
        if not gateway.verify(row["gateway_order_id"], body.gateway_payment_id, body.signature):
            audit.record(
                conn, actor=user, action="DONATION_SIGNATURE_REJECTED", entity_type="donation",
                entity_id=donation_id, result="FAILURE", rationale="Gateway signature did not match",
                ip=user.ip if user else None,
            )
            # commit the audit row, then fail the request
            error = ApiError(400, "INVALID_SIGNATURE", "The payment signature is not valid")
        else:
            error = None
            row = conn.execute(
                """
                UPDATE donations
                SET status = 'CONFIRMED', gateway_payment_id = %s, gateway_txn_ref = %s,
                    confirmed_at = now(), verified_at = now(),
                    receipt_no = 'REC-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('receipt_seq')::text, 6, '0'),
                    receipt_issued_at = now()
                WHERE donation_id = %s RETURNING *
                """,
                (body.gateway_payment_id, body.gateway_payment_id, donation_id),
            ).fetchone()
            audit.record(
                conn, actor=user, action="DONATION_CONFIRMED", entity_type="donation", entity_id=donation_id,
                after={"receipt_no": row["receipt_no"]}, ip=user.ip if user else None,
            )
    if error:
        raise error
    return _confirmed_body(row)


def _confirmed_body(row: dict) -> dict:
    return {
        "donation_id": row["donation_id"],
        "status": row["status"],
        "receipt_no": row["receipt_no"],
        "receipt_issued_at": row["receipt_issued_at"],
    }
