"""Donations and payments (docs/api_contracts.md section 7). Owner: Shlok.

Flow: create an order (PENDING) -> the gateway confirms the payment through the browser callback
(POST /donations/{id}/verify) and/or the server-to-server webhook
(POST /payments/webhook/{gateway}). Whichever arrives first CONFIRMS the donation and issues the
receipt; the other is an idempotent no-op. Nothing becomes CONFIRMED without a verified signature
bound to the donation's order, amount and currency.

The sandbox endpoint exists only for the mock gateway outside production so the UI and tests can
complete a payment without a real provider.
"""

import logging
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import audit, db
from app.auth import Citizen, MaybeUser
from app.common import Page, page_body
from app.config import get_settings
from app.errors import ApiError, conflict, not_found
from app.payments import (
    InvalidWebhook,
    MockGateway,
    PaymentGateway,
    PaymentGatewayError,
    WebhookEvent,
    get_gateway,
    is_sandbox_gateway,
)
from app.ratelimit import rate_limit

logger = logging.getLogger("drch.donations")

router = APIRouter(prefix="/api/v1", tags=["donations"])


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
    gateway = get_gateway()
    return {
        # Public key the browser needs to open the gateway checkout; null for the sandbox gateway.
        "checkout_key": gateway.checkout_key() if gateway.name == row["gateway_name"] else None,
        "donation_id": row["donation_id"],
        "gateway_name": row["gateway_name"],
        "gateway_order_id": row["gateway_order_id"],
        "amount": row["amount"],
        "currency": row["currency"].strip(),
        "status": row["status"],
        "is_sandbox": is_sandbox_gateway(row["gateway_name"]),
    }


def _confirmed_body(row: dict) -> dict:
    return {
        "donation_id": row["donation_id"],
        "status": row["status"],
        "receipt_no": row["receipt_no"],
        "receipt_issued_at": row["receipt_issued_at"],
    }


def _load_for_caller(conn, donation_id: uuid.UUID, user) -> dict:
    row = conn.execute("SELECT * FROM donations WHERE donation_id = %s FOR UPDATE", (donation_id,)).fetchone()
    # A donation tied to an account is visible only to that account; guest donations to whoever holds the id.
    if row is None or (row["donor_id"] is not None and (user is None or row["donor_id"] != user.user_id)):
        raise not_found("Donation")
    return row


def _require_same_gateway(row: dict, gateway: PaymentGateway) -> None:
    if row["gateway_name"] != gateway.name:
        raise conflict(
            "GATEWAY_MISMATCH",
            f"This donation was created with {row['gateway_name']}, not the active gateway {gateway.name}",
        )


def _confirm(conn, row: dict, payment_id: str, *, actor, via: str, ip: str | None) -> dict:
    """PENDING -> CONFIRMED with a receipt number, in the caller's transaction (row is locked)."""
    confirmed = conn.execute(
        """
        UPDATE donations
        SET status = 'CONFIRMED', gateway_payment_id = %s, gateway_txn_ref = %s,
            confirmed_at = now(), verified_at = now(),
            receipt_no = 'REC-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('receipt_seq')::text, 6, '0'),
            receipt_issued_at = now()
        WHERE donation_id = %s AND status = 'PENDING'
        RETURNING *
        """,
        (payment_id, payment_id, row["donation_id"]),
    ).fetchone()
    audit.record(
        conn, actor=actor, action="DONATION_CONFIRMED", entity_type="donation", entity_id=row["donation_id"],
        rationale=f"Payment {payment_id} verified via {via}", after={"receipt_no": confirmed["receipt_no"]}, ip=ip,
    )
    return confirmed


# ── Orders and browser callback ─────────────────────────────────────────


@router.post("/donations", status_code=201, dependencies=[rate_limit("donation", 30, 3600)])
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
        try:
            order = gateway.create_order(body.amount, body.currency, str(donation_id))
        except PaymentGatewayError as exc:
            logger.warning("Order creation failed: %s", exc)
            raise ApiError(502, "GATEWAY_UNAVAILABLE", "The payment gateway is unavailable. Try again shortly.") from exc
        row = conn.execute(
            """
            INSERT INTO donations (donation_id, campaign_id, donor_id, amount, currency, is_anonymous,
                                   guest_name, guest_email, gateway_name, gateway_order_id, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
            """,
            (
                donation_id, body.campaign_id, user.user_id if user else None, body.amount, body.currency,
                body.is_anonymous, None if user else body.guest_name, None if user else body.guest_email,
                gateway.name, order.order_id, idempotency_key,
            ),
        ).fetchone()
        audit.record(
            conn, actor=user, action="DONATION_CREATED", entity_type="donation", entity_id=donation_id,
            after={"amount": str(body.amount), "campaign_id": str(body.campaign_id), "gateway": gateway.name},
            ip=user.ip if user else None,
        )
        return _order_body(row)


@router.post("/donations/{donation_id}/sandbox-payment")
def sandbox_payment(donation_id: uuid.UUID, user: MaybeUser):
    """Sandbox only: act as the gateway and return a payment id plus a valid signature."""
    settings = get_settings()
    if settings.payment_gateway != MockGateway.slug or settings.app_env == "production":
        raise not_found("Endpoint")
    gateway = MockGateway()
    with db.transaction() as conn:
        row = _load_for_caller(conn, donation_id, user)
        if row["status"] != "PENDING":
            raise conflict("DONATION_NOT_PENDING", f"Donation is {row['status']}")
    payment_id = gateway.new_payment_id()
    signature = gateway.sign(row["gateway_order_id"], payment_id, row["amount"], row["currency"].strip())
    return {"gateway_payment_id": payment_id, "signature": signature}


@router.post("/donations/{donation_id}/verify")
def verify_donation(donation_id: uuid.UUID, body: DonationVerify, user: MaybeUser):
    gateway = get_gateway()
    ip = user.ip if user else None
    error: ApiError | None = None
    with db.transaction() as conn:
        row = _load_for_caller(conn, donation_id, user)
        _require_same_gateway(row, gateway)
        result = gateway.verify_payment(
            row["gateway_order_id"], body.gateway_payment_id, body.signature, row["amount"], row["currency"].strip()
        )
        if not result.verified:
            audit.record(
                conn, actor=user, action="DONATION_SIGNATURE_REJECTED", entity_type="donation",
                entity_id=donation_id, result="FAILURE", rationale=result.error_message, ip=ip,
            )
            # commit the audit row, then fail the request
            error = ApiError(400, "INVALID_SIGNATURE", "The payment signature is not valid")
        elif row["status"] == "CONFIRMED":
            # The webhook (or an earlier callback) got here first: same payment -> same receipt.
            if row["gateway_payment_id"] != body.gateway_payment_id:
                error = conflict("ALREADY_CONFIRMED", "This donation was confirmed with a different payment")
        elif row["status"] != "PENDING":
            error = conflict("DONATION_NOT_PENDING", f"Donation is {row['status']}")
        else:
            row = _confirm(conn, row, body.gateway_payment_id, actor=user, via="callback", ip=ip)
    if error:
        raise error
    return _confirmed_body(row)


# ── Server-to-server webhook ────────────────────────────────────────────


def _claim_event(conn, gateway: PaymentGateway, event: WebhookEvent) -> bool:
    """Store the event id first; False when it was already processed (replay).

    The primary key makes a concurrent second delivery wait for the first one's transaction and
    then see the conflict, so an event is applied at most once.
    """
    inserted = conn.execute(
        """
        INSERT INTO payment_webhook_events (gateway_name, event_id, event_type, outcome)
        VALUES (%s, %s, %s, 'RECEIVED')
        ON CONFLICT (gateway_name, event_id) DO NOTHING
        RETURNING event_id
        """,
        (gateway.name, event.event_id, event.event_type),
    ).fetchone()
    return inserted is not None


def _apply_event(conn, gateway: PaymentGateway, event: WebhookEvent) -> tuple[str, dict | None]:
    """Decide what a verified event does. Returns (outcome, donation row or None)."""
    if not (event.is_capture or event.is_failure):
        return "IGNORED_EVENT_TYPE", None
    row = None
    if event.order_id:
        row = conn.execute(
            "SELECT * FROM donations WHERE gateway_order_id = %s AND gateway_name = %s FOR UPDATE",
            (event.order_id, gateway.name),
        ).fetchone()
    if row is None:
        return "UNKNOWN_ORDER", None

    if event.is_failure:
        if row["status"] == "PENDING":
            conn.execute("UPDATE donations SET status = 'FAILED' WHERE donation_id = %s", (row["donation_id"],))
            audit.record(
                conn, actor=None, action="DONATION_FAILED", entity_type="donation", entity_id=row["donation_id"],
                result="FAILURE", rationale=f"Gateway reported {event.event_type}",
            )
            return "FAILED", row
        return "IGNORED_NOT_PENDING", row

    # Capture: the amount and currency must be exactly what the donor pledged.
    expected_currency = row["currency"].strip()
    if event.amount != row["amount"] or (event.currency or "") != expected_currency:
        audit.record(
            conn, actor=None, action="DONATION_WEBHOOK_REJECTED", entity_type="donation",
            entity_id=row["donation_id"], result="FAILURE",
            rationale=(
                f"Webhook amount {event.amount} {event.currency} does not match "
                f"donation amount {row['amount']} {expected_currency}"
            ),
        )
        return "AMOUNT_MISMATCH", row
    if row["status"] == "CONFIRMED":
        same = row["gateway_payment_id"] == event.payment_id
        return ("ALREADY_CONFIRMED" if same else "PAYMENT_CONFLICT"), row
    if row["status"] != "PENDING" or not event.payment_id:
        return "IGNORED_NOT_PENDING", row
    return "CONFIRMED", _confirm(conn, row, event.payment_id, actor=None, via="webhook", ip=None)


@router.post("/payments/webhook/{gateway_slug}")
async def payment_webhook(gateway_slug: str, request: Request):
    """Gateway -> server notification. Signature checked over the raw body; idempotent on event id.

    Verified events always answer 200 (even when nothing changes) so the gateway stops retrying;
    a bad signature answers 400 and changes nothing.
    """
    gateway = get_gateway()
    if gateway_slug != gateway.slug:
        raise not_found("Endpoint")
    raw_body = await request.body()
    try:
        event = gateway.parse_webhook(raw_body, request.headers)
    except InvalidWebhook as exc:
        audit.record_standalone(
            actor=None, action="PAYMENT_WEBHOOK_REJECTED", entity_type="payment_webhook",
            result="FAILURE", rationale=str(exc), ip=request.client.host if request.client else None,
        )
        raise ApiError(400, "INVALID_SIGNATURE", "The webhook signature is not valid") from exc

    def handle() -> dict:
        with db.transaction() as conn:
            if not _claim_event(conn, gateway, event):
                return {"event_id": event.event_id, "outcome": "DUPLICATE_EVENT", "donation_id": None}
            outcome, row = _apply_event(conn, gateway, event)
            donation_id = row["donation_id"] if row else None
            conn.execute(
                "UPDATE payment_webhook_events SET outcome = %s, donation_id = %s "
                "WHERE gateway_name = %s AND event_id = %s",
                (outcome, donation_id, gateway.name, event.event_id),
            )
            return {"event_id": event.event_id, "outcome": outcome, "donation_id": donation_id}

    result = await run_in_threadpool(handle)
    return jsonable_encoder({"received": True, **result})


# ── Donor history and receipts ──────────────────────────────────────────


@router.get("/me/donations")
def my_donations(principal: Citizen, page: Page):
    """The citizen's own donations, newest first, with receipt numbers once confirmed.

    Guest donations have no account and are not listed; their receipt is returned by /verify.
    """
    with db.transaction() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM donations WHERE donor_id = %s", (principal.user_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            """
            SELECT d.donation_id, d.campaign_id, c.title AS campaign_title, d.amount, d.currency, d.status,
                   d.is_anonymous, d.gateway_name, d.receipt_no, d.receipt_issued_at, d.created_at,
                   d.confirmed_at
            FROM donations d
            JOIN donation_campaigns c ON c.campaign_id = d.campaign_id
            WHERE d.donor_id = %s
            ORDER BY d.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (principal.user_id, page.limit, page.offset),
        ).fetchall()
    items = [
        {
            **{key: value for key, value in row.items() if key != "gateway_name"},
            "currency": row["currency"].strip(),
            "is_sandbox": is_sandbox_gateway(row["gateway_name"]),
        }
        for row in rows
    ]
    return page_body(items, total, page)
