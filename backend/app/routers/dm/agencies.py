"""Agency directory maintenance (DM-FR-20): supervisors keep the contacts that dispatch messages go to.

Any dispatch staff member can read the directory (GET /agency-contacts). Only a supervisor can add, edit or
deactivate an agency. Agencies hold no accounts and are never deleted: deactivating one stops new dispatches
and resources being linked to it but keeps the history, and is refused while dispatches to it are still
active. Every change is audited with a reason.
"""

import uuid
from typing import Literal

from fastapi import APIRouter
from psycopg import sql
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field, model_validator

from app import audit, db
from app.auth import Supervisor
from app.errors import conflict, not_found
from app.ratelimit import rate_limit
from app.services.incidents import ACTIVE_DISPATCH

router = APIRouter(prefix="/agencies", tags=["agencies"])

AgencyType = Literal["FIRE", "POLICE", "NDRF", "MEDICAL", "MUNICIPAL", "NGO"]

_COLUMNS = sql.SQL("agency_id, name, agency_type, contact_email, contact_phone, is_active, created_at, updated_at")


class AgencyBody(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    agency_type: AgencyType
    contact_email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
    contact_phone: str | None = Field(default=None, max_length=20, pattern=r"^[0-9+()\-\s]{3,20}$")
    is_active: bool = True
    reason: str = Field(min_length=5, max_length=500, description="Recorded in the audit log")

    @model_validator(mode="after")
    def _reachable(self):
        if not ((self.contact_email or "").strip() or (self.contact_phone or "").strip()):
            raise ValueError("Give an email address or a phone number so the agency can be reached")
        return self


def _clean(body: AgencyBody) -> dict:
    return {
        "name": body.name.strip(),
        "agency_type": body.agency_type,
        "contact_email": (body.contact_email or "").strip() or None,
        "contact_phone": (body.contact_phone or "").strip() or None,
        "is_active": body.is_active,
    }


def _public(row: dict) -> dict:
    return {**row, "agency_id": str(row["agency_id"])}


def _duplicate_name(conn, name: str, *, excluding: uuid.UUID | None = None) -> bool:
    row = conn.execute(
        "SELECT 1 FROM agencies WHERE lower(name) = lower(%s) AND (%s::uuid IS NULL OR agency_id <> %s::uuid)",
        (name, excluding, excluding),
    ).fetchone()
    return row is not None


_DUPLICATE = ("DUPLICATE_NAME", "An agency with this name already exists")


@router.post("", status_code=201, dependencies=[rate_limit("agency-change", 30, 3600)])
def create_agency(body: AgencyBody, principal: Supervisor):
    values = _clean(body)
    try:
        with db.transaction() as conn:
            if _duplicate_name(conn, values["name"]):
                raise conflict(*_DUPLICATE)
            row = conn.execute(
                sql.SQL("""
                INSERT INTO agencies (name, agency_type, contact_email, contact_phone, is_active)
                VALUES (%(name)s, %(agency_type)s, %(contact_email)s, %(contact_phone)s, %(is_active)s)
                RETURNING {cols}
                """).format(cols=_COLUMNS),
                values,
            ).fetchone()
            audit.record(
                conn, actor=principal, action="AGENCY_CREATED", entity_type="agency", entity_id=row["agency_id"],
                rationale=body.reason.strip(), after=values, ip=principal.ip,
            )
    except UniqueViolation:  # two supervisors adding the same name at the same moment
        raise conflict(*_DUPLICATE) from None
    return _public(row)


@router.put("/{agency_id}", dependencies=[rate_limit("agency-change", 30, 3600)])
def update_agency(agency_id: uuid.UUID, body: AgencyBody, principal: Supervisor):
    """Replace an agency's details (the whole record, so the audit before and after are unambiguous)."""
    values = _clean(body)
    try:
        with db.transaction() as conn:
            before = conn.execute(
                sql.SQL("SELECT {cols} FROM agencies WHERE agency_id = %s FOR UPDATE").format(cols=_COLUMNS), (agency_id,)
            ).fetchone()
            if before is None:
                raise not_found("Agency")
            if all(before[k] == v for k, v in values.items()):
                raise conflict("NO_CHANGE", "These are already this agency's details.")
            if _duplicate_name(conn, values["name"], excluding=agency_id):
                raise conflict(*_DUPLICATE)
            if before["is_active"] and not values["is_active"]:
                active = conn.execute(
                    "SELECT COUNT(*) AS n FROM dispatch_orders WHERE receiving_agency_id = %s AND status = ANY(%s::dispatch_status[])",
                    (agency_id, list(ACTIVE_DISPATCH)),
                ).fetchone()["n"]
                if active:
                    raise conflict(
                        "AGENCY_IN_USE",
                        f"{active} dispatch{'es are' if active != 1 else ' is'} still active for this agency. Complete, reject or fail them before deactivating it.",
                        {"active_dispatches": active},
                    )
            row = conn.execute(
                sql.SQL("""
                UPDATE agencies SET name = %(name)s, agency_type = %(agency_type)s, contact_email = %(contact_email)s,
                       contact_phone = %(contact_phone)s, is_active = %(is_active)s, updated_at = now()
                WHERE agency_id = %(id)s RETURNING {cols}
                """).format(cols=_COLUMNS),
                {**values, "id": agency_id},
            ).fetchone()
            if before["is_active"] and not values["is_active"]:
                action = "AGENCY_DEACTIVATED"
            elif not before["is_active"] and values["is_active"]:
                action = "AGENCY_REACTIVATED"
            else:
                action = "AGENCY_UPDATED"
            audit.record(
                conn, actor=principal, action=action, entity_type="agency", entity_id=agency_id,
                rationale=body.reason.strip(), before={k: before[k] for k in values}, after=values, ip=principal.ip,
            )
    except UniqueViolation:
        raise conflict(*_DUPLICATE) from None
    return _public(row)
