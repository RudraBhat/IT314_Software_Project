"""Relief shelters and medical posts that citizens see on their dashboard (maintained by dispatchers).

Anyone with the dispatch or supervisor permission may add and update them. A shelter is never deleted:
closing it hides it from the public list but keeps the history. Every change is audited.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from psycopg import sql
from pydantic import BaseModel, Field, model_validator

from app import audit, db
from app.auth import DMUser
from app.errors import ApiError, not_found

router = APIRouter(prefix="/shelters", tags=["shelters"])

ShelterType = Literal["SHELTER", "RELIEF_CAMP", "MEDICAL_POST"]
ShelterStatus = Literal["OPERATIONAL", "FULL", "CLOSED"]

_COLUMNS = sql.SQL("""
    shelter_id, name, type, address_text, district, latitude, longitude, total_capacity,
    current_occupancy, contact_number, status, notes, is_simulated, created_at, updated_at
""")


def _require_manager(principal: DMUser) -> None:
    if not (principal.has("DISPATCH") or principal.has("SUPERVISOR")):
        raise ApiError(403, "PERMISSION_REQUIRED", "The dispatch or supervisor permission is required")


class ShelterBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    type: ShelterType = "SHELTER"
    address_text: str = Field(min_length=3, max_length=300)
    district: str | None = Field(default=None, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    total_capacity: int | None = Field(default=None, ge=0, le=1_000_000)
    current_occupancy: int | None = Field(default=None, ge=0, le=1_000_000)
    contact_number: str | None = Field(default=None, max_length=30, pattern=r"^[0-9+()\-\s]{5,30}$")
    status: ShelterStatus = "OPERATIONAL"
    notes: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=5, max_length=500, description="Recorded in the audit log")

    @model_validator(mode="after")
    def _occupancy_fits(self):
        if self.total_capacity is not None and self.current_occupancy is not None and self.current_occupancy > self.total_capacity:
            raise ValueError("current_occupancy cannot exceed total_capacity")
        return self


def _clean(body: ShelterBody) -> dict:
    return {
        "name": body.name.strip(),
        "type": body.type,
        "address_text": body.address_text.strip(),
        "district": (body.district or "").strip() or None,
        "latitude": body.latitude,
        "longitude": body.longitude,
        "total_capacity": body.total_capacity,
        "current_occupancy": body.current_occupancy,
        "contact_number": (body.contact_number or "").strip() or None,
        "status": body.status,
        "notes": (body.notes or "").strip() or None,
    }


def _public(row: dict) -> dict:
    return {**row, "shelter_id": str(row["shelter_id"])}


@router.get("")
def list_shelters(
    principal: DMUser,
    include_closed: Annotated[bool, Query()] = True,
):
    """All shelters (closed ones included unless asked otherwise), most recently updated first."""
    _require_manager(principal)
    with db.transaction() as conn:
        rows = conn.execute(
            sql.SQL("SELECT {cols} FROM shelters WHERE (%s OR status <> 'CLOSED') ORDER BY updated_at DESC, name LIMIT 500").format(
                cols=_COLUMNS
            ),
            (include_closed,),
        ).fetchall()
    return {"items": [_public(r) for r in rows]}


@router.post("", status_code=201)
def create_shelter(body: ShelterBody, principal: DMUser):
    _require_manager(principal)
    values = _clean(body)
    with db.transaction() as conn:
        row = conn.execute(
            sql.SQL("""
            INSERT INTO shelters (name, type, address_text, district, latitude, longitude, total_capacity,
                                  current_occupancy, contact_number, status, notes, created_by, updated_by)
            VALUES (%(name)s, %(type)s, %(address_text)s, %(district)s, %(latitude)s, %(longitude)s, %(total_capacity)s,
                    %(current_occupancy)s, %(contact_number)s, %(status)s, %(notes)s, %(user)s, %(user)s)
            RETURNING {cols}
            """).format(cols=_COLUMNS),
            {**values, "user": principal.user_id},
        ).fetchone()
        audit.record(
            conn, actor=principal, action="SHELTER_CREATED", entity_type="shelter", entity_id=row["shelter_id"],
            rationale=body.reason.strip(), after=values, ip=principal.ip,
        )
    return _public(row)


@router.put("/{shelter_id}")
def update_shelter(shelter_id: uuid.UUID, body: ShelterBody, principal: DMUser):
    """Replace a shelter's details (the whole record, so the audit before and after are unambiguous)."""
    _require_manager(principal)
    values = _clean(body)
    with db.transaction() as conn:
        before = conn.execute(
            sql.SQL("SELECT {cols} FROM shelters WHERE shelter_id = %s FOR UPDATE").format(cols=_COLUMNS), (shelter_id,)
        ).fetchone()
        if before is None:
            raise not_found("Shelter")
        row = conn.execute(
            sql.SQL("""
            UPDATE shelters SET name = %(name)s, type = %(type)s, address_text = %(address_text)s, district = %(district)s,
                   latitude = %(latitude)s, longitude = %(longitude)s, total_capacity = %(total_capacity)s,
                   current_occupancy = %(current_occupancy)s, contact_number = %(contact_number)s, status = %(status)s,
                   notes = %(notes)s, updated_by = %(user)s, updated_at = now()
            WHERE shelter_id = %(id)s RETURNING {cols}
            """).format(cols=_COLUMNS),
            {**values, "user": principal.user_id, "id": shelter_id},
        ).fetchone()
        audit.record(
            conn, actor=principal, action="SHELTER_UPDATED", entity_type="shelter", entity_id=shelter_id,
            rationale=body.reason.strip(),
            before={k: before[k] for k in values},
            after=values,
            ip=principal.ip,
        )
    return _public(row)
