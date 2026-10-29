"""Public donation campaigns and donation order processing."""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import Principal, load_principal
from app.errors import ApiError, conflict, not_found
from app.payments import get_gateway
from app.security import ACCESS, decode_token

router = APIRouter(prefix="/api/v1", tags=["donations"])

_bearer = HTTPBearer(auto_error=False)


def _optional_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal | None:
    """Extract authenticated Principal if a valid bearer token is present.

    Invalid or missing tokens are treated as unauthenticated guest requests (no 401).
    """
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    claims = decode_token(creds.credentials, ACCESS)
    if claims is None:
        return None
    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, KeyError):
        return None
    ip = request.client.host if request.client else None
    return load_principal(user_id, int(claims.get("tv", 1)), claims.get("mfa") is True, ip)


OptionalUser = Annotated[Principal | None, Depends(_optional_principal)]


class PublicCampaignResponse(BaseModel):
    campaign_id: uuid.UUID
    title: str
    purpose: str
    scenario: str | None
    target_amount: Decimal | None
    currency: str
    status: str


class DonationCreateRequest(BaseModel):
    campaign_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", max_length=3)
    guest_name: str | None = Field(default=None, max_length=150)
    guest_email: str | None = Field(default=None, max_length=254)
    is_anonymous: bool = False


class DonationResponse(BaseModel):
    donation_id: uuid.UUID
    gateway_name: str
    gateway_order_id: str
    amount: Decimal
    currency: str
    status: str
    is_sandbox: bool


@router.get("/public/campaigns", response_model=list[PublicCampaignResponse])
def list_public_campaigns():
    """Retrieve all active disaster relief donation campaigns (Contract Section 1.2)."""
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT campaign_id, title, purpose, lower(scenario::text) AS scenario,
                   target_amount, rtrim(currency) AS currency, status
            FROM donation_campaigns
            WHERE status = 'ACTIVE'
            ORDER BY created_at DESC
            """
        ).fetchall()
    return rows


@router.post("/donations", status_code=201, response_model=DonationResponse)
def create_donation_order(
    body: DonationCreateRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)],
    principal: OptionalUser,
):
    """Initiate a monetary donation order against an active campaign (Contract Section 6.1)."""
    clean_idempotency = idempotency_key.strip()
    req_currency = body.currency.strip().upper()

    if req_currency != "INR":
        raise ApiError(422, "UNSUPPORTED_CURRENCY", "Only INR currency is currently supported")

    gateway = get_gateway()
    ip = request.client.host if request.client else None

    with db.transaction() as conn:
        # 1. Idempotency replay check
        existing = conn.execute(
            """
            SELECT donation_id, gateway_name, gateway_order_id, amount,
                   rtrim(currency) AS currency, status
            FROM donations
            WHERE idempotency_key = %s
            """,
            (clean_idempotency,),
        ).fetchone()
        if existing:
            return {
                "donation_id": existing["donation_id"],
                "gateway_name": existing["gateway_name"] or gateway.name,
                "gateway_order_id": existing["gateway_order_id"],
                "amount": existing["amount"],
                "currency": existing["currency"],
                "status": existing["status"],
                "is_sandbox": gateway.is_sandbox,
            }

        # 2. Campaign validation
        campaign = conn.execute(
            """
            SELECT campaign_id, status, rtrim(currency) AS currency
            FROM donation_campaigns
            WHERE campaign_id = %s
            """,
            (body.campaign_id,),
        ).fetchone()
        if campaign is None:
            raise not_found("Campaign")

        if campaign["status"] != "ACTIVE":
            raise conflict(
                "CAMPAIGN_NOT_ACTIVE",
                f"Campaign is not active (current status: {campaign['status']})",
                {"campaign_id": str(body.campaign_id), "status": campaign["status"]},
            )

        if campaign["currency"] != req_currency:
            raise ApiError(
                422,
                "CURRENCY_MISMATCH",
                f"Campaign currency is {campaign['currency']}, got {req_currency}",
            )

        # 3. Donor identity & schema constraints
        donor_id = principal.user_id if principal else None

        if donor_id is not None:
            # CHECK (donor_id IS NULL OR (guest_name IS NULL AND guest_email IS NULL))
            guest_name = None
            guest_email = None
        else:
            # CHECK (donor_id IS NOT NULL OR is_anonymous = TRUE OR guest_email IS NOT NULL)
            clean_email = body.guest_email.strip().lower() if body.guest_email else None
            clean_name = body.guest_name.strip() if body.guest_name else None

            if not body.is_anonymous and not clean_email:
                raise ApiError(
                    422,
                    "GUEST_EMAIL_REQUIRED",
                    "Guest donors must provide an email address unless donating anonymously",
                )

            # If anonymous, guest_name must be NULL
            guest_name = None if body.is_anonymous else clean_name
            guest_email = clean_email

        # 4. Generate order with payment gateway
        order = gateway.create_order(
            amount=body.amount,
            currency=req_currency,
            reference=f"camp_{body.campaign_id}",
        )

        # 5. Insert donation (status PENDING; receipt_no and receipt_issued_at remain NULL)
        row = conn.execute(
            """
            INSERT INTO donations (
                campaign_id, donor_id, amount, currency, status,
                is_anonymous, guest_name, guest_email,
                gateway_name, gateway_order_id, idempotency_key
            )
            VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s, %s, %s, %s)
            RETURNING donation_id, gateway_name, gateway_order_id, amount,
                      rtrim(currency) AS currency, status
            """,
            (
                body.campaign_id,
                donor_id,
                body.amount,
                req_currency,
                body.is_anonymous,
                guest_name,
                guest_email,
                gateway.name,
                order.order_id,
                clean_idempotency,
            ),
        ).fetchone()

        # 6. Audit trail record within the same transaction
        audit.record(
            conn,
            actor=principal,
            action="DONATION_ORDER_CREATED",
            entity_type="donation",
            entity_id=row["donation_id"],
            after={
                "campaign_id": str(body.campaign_id),
                "amount": str(body.amount),
                "currency": req_currency,
                "gateway_order_id": order.order_id,
                "is_anonymous": body.is_anonymous,
                "donor_id": str(donor_id) if donor_id else None,
            },
            ip=ip,
        )

        return {
            "donation_id": row["donation_id"],
            "gateway_name": row["gateway_name"],
            "gateway_order_id": row["gateway_order_id"],
            "amount": row["amount"],
            "currency": row["currency"],
            "status": row["status"],
            "is_sandbox": gateway.is_sandbox,
        }
