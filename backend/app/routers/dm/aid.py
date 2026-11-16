"""Donation and aid oversight (DM-FR-12), aid allocation (DM-FR-13), needs (DM-FR-19) and campaigns (DM-FR-16).

Payment states are read-only here: only the payment gateway callback may
confirm a donation. Aid becomes Delivered only with a recorded receipt.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from psycopg import sql
from pydantic import BaseModel, Field, model_validator

from app import audit, db
from app.auth import DMUser
from app.common import Filters, Page, Rationale, Scenario, page_body, scenario_db
from app.errors import ApiError, conflict, not_found
from app.payments import get_gateway, is_sandbox_gateway
from app.services.donation_endings import FAILURE_REASONS, expire_stale_donations, ttl_minutes

router = APIRouter()

Qty = Field(gt=0, max_digits=12, decimal_places=2)

# ------------------------------------------------------------------- oversight


@router.get("/oversight/donations")
def donation_oversight(principal: DMUser):
    with db.read_only() as conn:
        # Unpaid orders past their time limit are counted as failed, not as money still to come.
        expire_stale_donations(conn)
        campaigns = conn.execute(
            """
            SELECT s.campaign_id, s.title, c.status, lower(c.scenario::text) AS scenario, c.currency,
                   c.target_amount, s.confirmed_amount, s.pending_amount, s.failed_amount,
                   (SELECT COUNT(*) FROM donations d WHERE d.campaign_id = s.campaign_id AND d.status = 'CONFIRMED') AS confirmed_count,
                   (SELECT COUNT(*) FROM donations d WHERE d.campaign_id = s.campaign_id AND d.status = 'PENDING') AS pending_count,
                   (SELECT COUNT(*) FROM donations d WHERE d.campaign_id = s.campaign_id AND d.status = 'FAILED') AS failed_count
            FROM v_donation_summary s JOIN donation_campaigns c USING (campaign_id)
            ORDER BY c.status, s.title
            """
        ).fetchall()
        oldest_pending = conn.execute(
            "SELECT MIN(created_at) AS t FROM donations WHERE status = 'PENDING'"
        ).fetchone()["t"]
        failed_rows = conn.execute(
            """
            SELECT COALESCE(failure_reason, 'UNKNOWN') AS reason,
                   COUNT(*) AS count,
                   COALESCE(SUM(amount), 0) AS amount
            FROM donations
            WHERE status = 'FAILED'
            GROUP BY 1
            """
        ).fetchall()
        failed_by_reason = {
            reason: {"count": 0, "amount": Decimal(0)}
            for reason in (*FAILURE_REASONS, "UNKNOWN")
        }
        for r in failed_rows:
            failed_by_reason[r["reason"]] = {
                "count": int(r["count"]),
                "amount": r["amount"],
            }
    totals = {
        key: sum((c[key] for c in campaigns), Decimal(0))
        for key in ("confirmed_amount", "pending_amount", "failed_amount")
    }
    return {
        "campaigns": campaigns,
        "totals": totals,
        "oldest_pending_at": oldest_pending,
        "failed_by_reason": failed_by_reason,
        "pending_timeout_minutes": ttl_minutes(),
        "is_sandbox": is_sandbox_gateway(get_gateway().name),
        "definitions": {
            "confirmed": "Confirmed by the payment gateway callback.",
            "pending": (
                "Awaiting gateway confirmation; not counted as received. "
                f"Unpaid orders become failed after {ttl_minutes()} minutes."
            ),
            "failed": (
                "Cancelled by the donor, declined by the gateway or expired unpaid; no receipt is issued. "
                "A payment the gateway still captures later confirms the donation."
            ),
            "failed_by_reason": (
                "Failed donations broken down by why they did not complete "
                "(abandoned by donor, declined by gateway, expired unpaid, or unclassified)."
            ),
        },
    }


@router.get("/oversight/aid")
def aid_oversight(principal: DMUser):
    with db.read_only() as conn:
        by_type = conn.execute(
            "SELECT aid_type, status, contributions, total_quantity FROM v_aid_summary ORDER BY aid_type, status"
        ).fetchall()
        needs = conn.execute(
            """
            SELECT n.need_id, n.aid_type, n.unit, n.quantity_required, n.quantity_fulfilled, n.is_open,
                   n.delivery_address, i.incident_ref,
                   COALESCE((SELECT SUM(c.quantity) FROM aid_contributions c
                              WHERE c.need_id = n.need_id AND c.status IN ('ALLOCATED','IN_TRANSIT')), 0) AS in_flight
            FROM aid_needs n LEFT JOIN incidents i ON i.incident_id = n.incident_id
            WHERE n.is_open
            ORDER BY n.created_at
            """
        ).fetchall()
    return {"by_type_and_status": by_type, "open_needs": needs}


# ---------------------------------------------------------------- contributions

AidStatus = Literal["REGISTERED", "VERIFIED", "ALLOCATED", "IN_TRANSIT", "DELIVERED", "REJECTED"]

_CONTRIBUTION_SELECT = """
SELECT c.contribution_id, c.aid_type, c.description, c.quantity, c.unit, c.pickup_address,
       c.contact_phone, c.status, c.need_id, c.created_at, c.updated_at,
       u.full_name AS contributor_name, v.full_name AS verified_by_name,
       n.aid_type AS need_aid_type, n.unit AS need_unit, i.incident_ref AS need_incident_ref
FROM aid_contributions c
JOIN users u ON u.user_id = c.contributor_id
LEFT JOIN users v ON v.user_id = c.verified_by
LEFT JOIN aid_needs n ON n.need_id = c.need_id
LEFT JOIN incidents i ON i.incident_id = n.incident_id
"""


@router.get("/aid-contributions")
def list_contributions(
    *,
    page: Page,
    status: Annotated[list[AidStatus] | None, Query()] = None,
    aid_type: Annotated[str | None, Query(max_length=80)] = None,
    principal: DMUser,
):
    f = Filters()
    if status:
        f.add("c.status = ANY(%(status)s::aid_status[])", status=status)
    if aid_type:
        f.add("upper(c.aid_type) = upper(%(aid_type)s)", aid_type=aid_type)
    where = f.where()
    with db.read_only() as conn:
        total = conn.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM aid_contributions c {}").format(where), f.params
        ).fetchone()["n"]
        items = conn.execute(
            sql.SQL("{} {} ORDER BY c.created_at DESC LIMIT %(limit)s OFFSET %(offset)s").format(
                sql.SQL(_CONTRIBUTION_SELECT), where
            ),
            {**f.params, "limit": page.limit, "offset": page.offset},
        ).fetchall()
    return page_body(items, total, page)


def _fetch_contribution(conn, contribution_id) -> dict:
    row = conn.execute(
        sql.SQL("{} WHERE c.contribution_id = %s").format(sql.SQL(_CONTRIBUTION_SELECT)), (contribution_id,)
    ).fetchone()
    if row is None:
        raise not_found("Aid contribution")
    return row


class AidVerification(BaseModel):
    decision: Literal["VERIFIED", "REJECTED"]
    reason: str = Rationale


@router.post("/aid-contributions/{contribution_id}/verification")
def verify_contribution(
    contribution_id: uuid.UUID, body: AidVerification, principal: DMUser
):
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM aid_contributions WHERE contribution_id = %s FOR UPDATE", (contribution_id,)
        ).fetchone()
        if row is None:
            raise not_found("Aid contribution")
        if row["status"] != "REGISTERED":
            raise conflict("INVALID_TRANSITION", f"This contribution is already {row['status'].lower()}")
        conn.execute(
            "UPDATE aid_contributions SET status = %s, verified_by = %s WHERE contribution_id = %s",
            (body.decision, principal.user_id, contribution_id),
        )
        audit.record(conn, actor=principal, action=f"AID_{body.decision}", entity_type="aid_contribution",
                     entity_id=contribution_id, rationale=body.reason,
                     before={"status": row["status"]}, after={"status": body.decision}, ip=principal.ip)
        return _fetch_contribution(conn, contribution_id)


# ------------------------------------------------------------------------ needs

_NEED_SELECT = """
SELECT n.need_id, n.incident_id, i.incident_ref, n.aid_type, n.unit, n.quantity_required,
       n.quantity_fulfilled, n.delivery_address, n.is_open, n.created_at, n.updated_at,
       COALESCE((SELECT SUM(c.quantity) FROM aid_contributions c
                  WHERE c.need_id = n.need_id AND c.status IN ('ALLOCATED','IN_TRANSIT')), 0) AS in_flight
FROM aid_needs n LEFT JOIN incidents i ON i.incident_id = n.incident_id
"""


@router.get("/needs")
def list_needs(
    *,
    open_only: bool = True,
    incident_id: uuid.UUID | None = None,
    principal: DMUser,
):
    f = Filters()
    if open_only:
        f.add("n.is_open")
    if incident_id:
        f.add("n.incident_id = %(incident)s", incident=incident_id)
    with db.read_only() as conn:
        items = conn.execute(
            sql.SQL("{} {} ORDER BY n.is_open DESC, n.created_at DESC LIMIT 200").format(
                sql.SQL(_NEED_SELECT), f.where()
            ),
            f.params,
        ).fetchall()
    return {"items": items}


class NeedCreate(BaseModel):
    aid_type: str = Field(min_length=2, max_length=80)
    unit: str = Field(min_length=1, max_length=30)
    quantity_required: Decimal = Qty
    incident_id: uuid.UUID | None = None
    delivery_address: str | None = Field(None, max_length=500)


def _norm(value: str) -> str:
    return value.strip().upper().replace(" ", "_")


@router.post("/needs", status_code=201)
def create_need(body: NeedCreate, principal: DMUser):
    with db.transaction() as conn:
        if body.incident_id and conn.execute(
            "SELECT 1 FROM incidents WHERE incident_id = %s AND status <> 'CLOSED'", (body.incident_id,)
        ).fetchone() is None:
            raise ApiError(422, "VALIDATION_FAILED", "The incident does not exist or is closed")
        duplicate = conn.execute(
            """
            SELECT need_id FROM aid_needs
            WHERE is_open AND aid_type = %s AND unit = %s AND incident_id IS NOT DISTINCT FROM %s
            """,
            (_norm(body.aid_type), _norm(body.unit), body.incident_id),
        ).fetchone()
        if duplicate:
            raise conflict("DUPLICATE_NEED", "An open need of this type already exists; update its quantity instead",
                           {"need_id": str(duplicate["need_id"])})
        row = conn.execute(
            """
            INSERT INTO aid_needs (incident_id, aid_type, quantity_required, unit, delivery_address)
            VALUES (%s, %s, %s, %s, %s) RETURNING need_id
            """,
            (body.incident_id, _norm(body.aid_type), body.quantity_required, _norm(body.unit), body.delivery_address),
        ).fetchone()
        audit.record(conn, actor=principal, action="NEED_CREATED", entity_type="aid_need",
                     entity_id=row["need_id"], after=body.model_dump(mode="json"), ip=principal.ip)
        return conn.execute(sql.SQL("{} WHERE n.need_id = %s").format(sql.SQL(_NEED_SELECT)),
                            (row["need_id"],)).fetchone()


class NeedUpdate(BaseModel):
    quantity_required: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=2)
    is_open: bool | None = None
    delivery_address: str | None = Field(None, max_length=500)
    reason: str = Rationale


@router.patch("/needs/{need_id}")
def update_need(need_id: uuid.UUID, body: NeedUpdate, principal: DMUser):
    with db.transaction() as conn:
        need = conn.execute("SELECT * FROM aid_needs WHERE need_id = %s FOR UPDATE", (need_id,)).fetchone()
        if need is None:
            raise not_found("Need")
        in_flight = conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS q FROM aid_contributions
            WHERE need_id = %s AND status IN ('ALLOCATED','IN_TRANSIT')
            """,
            (need_id,),
        ).fetchone()["q"]
        if body.quantity_required is not None and body.quantity_required < need["quantity_fulfilled"] + in_flight:
            raise conflict("OVER_ALLOCATED", "The requirement cannot drop below what is delivered or in flight")
        if body.is_open is False and in_flight > 0:
            raise conflict("OPEN_ALLOCATIONS", "Finish or fail the in-flight allocations before closing this need")
        conn.execute(
            """
            UPDATE aid_needs SET quantity_required = COALESCE(%s, quantity_required),
                   is_open = COALESCE(%s, is_open), delivery_address = COALESCE(%s, delivery_address)
            WHERE need_id = %s
            """,
            (body.quantity_required, body.is_open, body.delivery_address, need_id),
        )
        audit.record(conn, actor=principal, action="NEED_UPDATED", entity_type="aid_need", entity_id=need_id,
                     rationale=body.reason, after=body.model_dump(mode="json", exclude_none=True), ip=principal.ip)
        return conn.execute(sql.SQL("{} WHERE n.need_id = %s").format(sql.SQL(_NEED_SELECT)), (need_id,)).fetchone()


# ------------------------------------------------------------------ allocations


class AllocationCreate(BaseModel):
    contribution_id: uuid.UUID
    need_id: uuid.UUID


@router.get("/allocations")
def list_allocations(principal: DMUser):
    with db.read_only() as conn:
        items = conn.execute(
            sql.SQL("{} WHERE c.need_id IS NOT NULL AND c.status IN ('ALLOCATED','IN_TRANSIT','DELIVERED') "
                    "ORDER BY c.updated_at DESC LIMIT 200").format(sql.SQL(_CONTRIBUTION_SELECT))
        ).fetchall()
    return {"items": items}


@router.post("/allocations", status_code=201)
def allocate(body: AllocationCreate, principal: DMUser):
    with db.transaction() as conn:
        need = conn.execute("SELECT * FROM aid_needs WHERE need_id = %s FOR UPDATE", (body.need_id,)).fetchone()
        if need is None:
            raise not_found("Need")
        aid = conn.execute(
            "SELECT * FROM aid_contributions WHERE contribution_id = %s FOR UPDATE", (body.contribution_id,)
        ).fetchone()
        if aid is None:
            raise not_found("Aid contribution")
        if aid["status"] != "VERIFIED":
            raise conflict("AID_NOT_VERIFIED", "Only verified, unallocated aid can be allocated")
        if not need["is_open"]:
            raise conflict("NEED_CLOSED", "This need is closed")
        if _norm(aid["aid_type"]) != need["aid_type"] or _norm(aid["unit"]) != need["unit"]:
            raise conflict(
                "INCOMPATIBLE_AID",
                f"The need is for {need['aid_type']} in {need['unit']}; this aid is {aid['aid_type']} in {aid['unit']}",
            )
        in_flight = conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS q FROM aid_contributions
            WHERE need_id = %s AND status IN ('ALLOCATED','IN_TRANSIT')
            """,
            (body.need_id,),
        ).fetchone()["q"]
        remaining = need["quantity_required"] - need["quantity_fulfilled"] - in_flight
        if aid["quantity"] > remaining:
            raise conflict(
                "OVER_ALLOCATION",
                f"Only {remaining} {need['unit']} remain unallocated for this need",
                {"remaining": str(remaining), "offered": str(aid["quantity"])},
            )
        conn.execute(
            "UPDATE aid_contributions SET need_id = %s, status = 'ALLOCATED' WHERE contribution_id = %s",
            (body.need_id, body.contribution_id),
        )
        audit.record(conn, actor=principal, action="AID_ALLOCATED", entity_type="aid_contribution",
                     entity_id=body.contribution_id, after={"need_id": str(body.need_id)}, ip=principal.ip)
        return _fetch_contribution(conn, body.contribution_id)


class DeliveryEvent(BaseModel):
    event: Literal["PICKED_UP", "IN_TRANSIT", "DELIVERED", "FAILED"]
    note: str | None = Field(None, max_length=1000)
    received_by: str | None = Field(None, min_length=2, max_length=150)

    @model_validator(mode="after")
    def _check(self):
        if self.event == "DELIVERED" and not self.received_by:
            raise ValueError("received_by is required: delivery needs a recorded receipt confirmation")
        if self.event == "FAILED" and not (self.note and len(self.note.strip()) >= 3):
            raise ValueError("note is required to explain a failed delivery")
        return self


@router.post("/allocations/{contribution_id}/delivery-events")
def delivery_event(contribution_id: uuid.UUID, body: DeliveryEvent, principal: DMUser):
    with db.transaction() as conn:
        aid = conn.execute(
            "SELECT * FROM aid_contributions WHERE contribution_id = %s FOR UPDATE", (contribution_id,)
        ).fetchone()
        if aid is None or aid["need_id"] is None:
            raise not_found("Allocation")
        status = aid["status"]
        if status not in ("ALLOCATED", "IN_TRANSIT"):
            raise conflict("INVALID_TRANSITION", f"This allocation is {status.lower()}; no further events")
        need_id = aid["need_id"]
        if body.event in ("PICKED_UP", "IN_TRANSIT"):
            new_status = "IN_TRANSIT"
            conn.execute("UPDATE aid_contributions SET status = 'IN_TRANSIT' WHERE contribution_id = %s",
                         (contribution_id,))
        elif body.event == "DELIVERED":
            if status != "IN_TRANSIT":
                raise conflict("INVALID_TRANSITION", "Record pickup or transit before delivery")
            new_status = "DELIVERED"
            conn.execute("UPDATE aid_contributions SET status = 'DELIVERED' WHERE contribution_id = %s",
                         (contribution_id,))
            conn.execute(
                """
                UPDATE aid_needs SET quantity_fulfilled = quantity_fulfilled + %s,
                       is_open = (quantity_fulfilled + %s) < quantity_required
                WHERE need_id = %s
                """,
                (aid["quantity"], aid["quantity"], need_id),
            )
        else:
            # EH-14: keep a non-success state; the aid returns to the pool for reallocation.
            new_status = "VERIFIED"
            conn.execute(
                "UPDATE aid_contributions SET status = 'VERIFIED', need_id = NULL WHERE contribution_id = %s",
                (contribution_id,),
            )
        audit.record(
            conn,
            actor=principal,
            action=f"AID_DELIVERY_{body.event}",
            entity_type="aid_contribution",
            entity_id=contribution_id,
            result="FAILURE" if body.event == "FAILED" else "SUCCESS",
            rationale=body.note or (f"Received by {body.received_by}" if body.received_by else None),
            before={"status": status},
            after={"status": new_status, "need_id": str(need_id), "received_by": body.received_by},
            ip=principal.ip,
        )
        return _fetch_contribution(conn, contribution_id)


# -------------------------------------------------------------------- campaigns

_CAMPAIGN_SELECT = """
SELECT c.campaign_id, c.title, c.purpose, lower(c.scenario::text) AS scenario, c.target_amount,
       c.currency, c.status, c.created_at, c.updated_at,
       s.confirmed_amount, s.pending_amount
FROM donation_campaigns c LEFT JOIN v_donation_summary s USING (campaign_id)
"""


@router.get("/campaigns")
def list_campaigns(principal: DMUser):
    with db.read_only() as conn:
        items = conn.execute(
            sql.SQL("{} ORDER BY (c.status = 'CLOSED'), c.created_at DESC").format(sql.SQL(_CAMPAIGN_SELECT))
        ).fetchall()
    return {"items": items}


class CampaignCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    purpose: str = Field(min_length=10, max_length=4000)
    scenario: Scenario
    target_amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    activate: bool = False


def _fetch_campaign(conn, campaign_id) -> dict:
    row = conn.execute(
        sql.SQL("{} WHERE c.campaign_id = %s").format(sql.SQL(_CAMPAIGN_SELECT)), (campaign_id,)
    ).fetchone()
    if row is None:
        raise not_found("Campaign")
    return row


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignCreate, principal: DMUser):
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('campaign-title'))")
        if conn.execute(
            "SELECT 1 FROM donation_campaigns WHERE lower(title) = lower(%s) AND status <> 'CLOSED'",
            (body.title.strip(),),
        ).fetchone():
            raise conflict("DUPLICATE_CAMPAIGN", "An open campaign with this title already exists")
        row = conn.execute(
            """
            INSERT INTO donation_campaigns (title, purpose, scenario, target_amount, status)
            VALUES (%s, %s, %s, %s, %s) RETURNING campaign_id
            """,
            (body.title.strip(), body.purpose.strip(), scenario_db(body.scenario), body.target_amount,
             "ACTIVE" if body.activate else "DRAFT"),
        ).fetchone()
        audit.record(conn, actor=principal, action="CAMPAIGN_CREATED", entity_type="campaign",
                     entity_id=row["campaign_id"], after=body.model_dump(mode="json"), ip=principal.ip)
        return _fetch_campaign(conn, row["campaign_id"])


_CAMPAIGN_MOVES = {"DRAFT": {"ACTIVE"}, "ACTIVE": {"PAUSED"}, "PAUSED": {"ACTIVE"}}


class CampaignUpdate(BaseModel):
    title: str | None = Field(None, min_length=5, max_length=200)
    purpose: str | None = Field(None, min_length=10, max_length=4000)
    scenario: Scenario | None = None
    target_amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    status: Literal["ACTIVE", "PAUSED"] | None = None


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: uuid.UUID, body: CampaignUpdate, principal: DMUser):
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM donation_campaigns WHERE campaign_id = %s FOR UPDATE", (campaign_id,)
        ).fetchone()
        if row is None:
            raise not_found("Campaign")
        if row["status"] == "CLOSED":
            raise conflict("CAMPAIGN_CLOSED", "Closed campaigns cannot be changed")
        if body.scenario and row["status"] != "DRAFT":
            raise conflict("CAMPAIGN_ACTIVE", "The scenario can only be changed while the campaign is a draft")
        if body.status and body.status != row["status"] and body.status not in _CAMPAIGN_MOVES.get(row["status"], set()):
            raise conflict("INVALID_TRANSITION", f"A {row['status'].lower()} campaign cannot become {body.status.lower()}")
        conn.execute(
            """
            UPDATE donation_campaigns SET title = COALESCE(%s, title), purpose = COALESCE(%s, purpose),
                   scenario = COALESCE(%s::scenario_type, scenario),
                   target_amount = COALESCE(%s, target_amount), status = COALESCE(%s::campaign_status, status)
            WHERE campaign_id = %s
            """,
            (body.title, body.purpose, scenario_db(body.scenario), body.target_amount, body.status, campaign_id),
        )
        audit.record(conn, actor=principal, action="CAMPAIGN_UPDATED", entity_type="campaign", entity_id=campaign_id,
                     before={"status": row["status"]}, after=body.model_dump(mode="json", exclude_none=True),
                     ip=principal.ip)
        return _fetch_campaign(conn, campaign_id)


class CampaignClosure(BaseModel):
    reason: str = Rationale


@router.post("/campaigns/{campaign_id}/closure")
def close_campaign(campaign_id: uuid.UUID, body: CampaignClosure, principal: DMUser):
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM donation_campaigns WHERE campaign_id = %s FOR UPDATE", (campaign_id,)
        ).fetchone()
        if row is None:
            raise not_found("Campaign")
        if row["status"] == "CLOSED":
            raise conflict("CAMPAIGN_CLOSED", "This campaign is already closed")
        conn.execute("UPDATE donation_campaigns SET status = 'CLOSED' WHERE campaign_id = %s", (campaign_id,))
        audit.record(conn, actor=principal, action="CAMPAIGN_CLOSED", entity_type="campaign", entity_id=campaign_id,
                     rationale=body.reason, before={"status": row["status"]}, ip=principal.ip)
        return _fetch_campaign(conn, campaign_id)
