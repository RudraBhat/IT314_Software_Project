"""Resource inventory, availability and reservations (DM-FR-08); reading the agency directory (DM-FR-20).

Changing the directory is a supervisor action and lives in agencies.py."""

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

from app import audit, db
from app.auth import DMUser
from app.common import Filters, Page, page_body
from app.errors import ApiError, conflict, not_found
from app.services.resources import derive_status, release, reserve

router = APIRouter()

ResourceType = Literal["TEAM", "VEHICLE", "SUPPLY", "SUPPORT"]
ResourceStatus = Literal["AVAILABLE", "RESERVED", "ASSIGNED", "UNAVAILABLE", "MAINTENANCE"]

_RESOURCE_SELECT = """
SELECT r.resource_id, r.name, r.type, r.status, r.capability, r.quantity_total,
       r.quantity_available, r.version, r.updated_at, r.agency_id, a.name AS agency_name,
       ST_Y(r.current_geom::geometry) AS latitude, ST_X(r.current_geom::geometry) AS longitude,
       (SELECT COUNT(*) FROM resource_assignments x
         WHERE x.resource_id = r.resource_id AND x.released_at IS NULL) AS active_assignments
FROM resources r LEFT JOIN agencies a ON a.agency_id = r.agency_id
"""


@router.get("/resources")
def list_resources(
    *,
    page: Page,
    type: ResourceType | None = None,
    status: ResourceStatus | None = None,
    agency_id: uuid.UUID | None = None,
    available_only: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
    principal: DMUser,
):
    f = Filters()
    if type:
        f.add("r.type = %(type)s::resource_type", type=type)
    if status:
        f.add("r.status = %(status)s::resource_status", status=status)
    if agency_id:
        f.add("r.agency_id = %(agency)s", agency=agency_id)
    if available_only:
        f.add("r.status = 'AVAILABLE' AND r.quantity_available > 0")
    if q:
        f.add("r.name ILIKE %(q)s", q=f"%{q.strip()}%")
    where = f.where()
    with db.read_only() as conn:
        total = conn.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM resources r {}").format(where), f.params
        ).fetchone()["n"]
        items = conn.execute(
            sql.SQL("{} {} ORDER BY r.type, r.name LIMIT %(limit)s OFFSET %(offset)s").format(
                sql.SQL(_RESOURCE_SELECT), where
            ),
            {**f.params, "limit": page.limit, "offset": page.offset},
        ).fetchall()
        summary = conn.execute(
            "SELECT type::text AS type, status::text AS status, COUNT(*) AS n FROM resources GROUP BY 1, 2"
        ).fetchall()
    return {**page_body(items, total, page), "summary": summary}


class Location(BaseModel):
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def _pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class ResourceCreate(Location):
    name: str = Field(min_length=2, max_length=150)
    type: ResourceType
    agency_id: uuid.UUID | None = None
    capability: dict[str, Any] = Field(default_factory=dict)
    quantity_total: Decimal = Field(Decimal(1), gt=0, max_digits=12, decimal_places=2)


def _point(lat: float | None, lon: float | None):
    return (lon, lat) if lat is not None else (None, None)


@router.post("/resources", status_code=201)
def create_resource(body: ResourceCreate, principal: DMUser):
    lon, lat = _point(body.latitude, body.longitude)
    with db.transaction() as conn:
        if body.agency_id and conn.execute(
            "SELECT 1 FROM agencies WHERE agency_id = %s AND is_active", (body.agency_id,)
        ).fetchone() is None:
            raise ApiError(422, "UNKNOWN_AGENCY", "The agency does not exist or is inactive")
        row = conn.execute(
            """
            INSERT INTO resources (agency_id, type, name, capability, quantity_total, quantity_available,
                                   current_geom)
            VALUES (%s, %s, %s, %s, %s, %s,
                    CASE WHEN %s::float8 IS NULL THEN NULL
                         ELSE ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography END)
            RETURNING resource_id
            """,
            (
                body.agency_id,
                body.type,
                body.name.strip(),
                Jsonb(body.capability),
                body.quantity_total,
                body.quantity_total,
                lon,
                lon,
                lat,
            ),
        ).fetchone()
        audit.record(
            conn,
            actor=principal,
            action="RESOURCE_CREATED",
            entity_type="resource",
            entity_id=row["resource_id"],
            after=body.model_dump(mode="json"),
            ip=principal.ip,
        )
        created = conn.execute(
            sql.SQL("{} WHERE r.resource_id = %s").format(sql.SQL(_RESOURCE_SELECT)), (row["resource_id"],)
        ).fetchone()
    return created


class ResourceUpdate(Location):
    version: int = Field(ge=1)
    name: str | None = Field(None, min_length=2, max_length=150)
    capability: dict[str, Any] | None = None
    quantity_total: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=2)
    # Operators set availability; RESERVED/ASSIGNED follow from assignments.
    status: Literal["AVAILABLE", "UNAVAILABLE", "MAINTENANCE"] | None = None
    reason: str | None = Field(None, max_length=1000)


@router.patch("/resources/{resource_id}")
def update_resource(resource_id: uuid.UUID, body: ResourceUpdate, principal: DMUser):
    with db.transaction() as conn:
        res = conn.execute("SELECT * FROM resources WHERE resource_id = %s FOR UPDATE", (resource_id,)).fetchone()
        if res is None:
            raise not_found("Resource")
        if res["version"] != body.version:
            raise conflict(
                "VERSION_CONFLICT",
                "This resource was changed by someone else. Reload and try again.",
                {"current_version": res["version"]},
            )
        total = res["quantity_total"] or Decimal(0)
        available = res["quantity_available"] or Decimal(0)
        in_use = total - available
        if body.quantity_total is not None:
            if body.quantity_total < in_use:
                raise conflict(
                    "RESOURCE_IN_USE",
                    f"{in_use} units are assigned; the total cannot drop below that",
                )
            available = body.quantity_total - in_use
            total = body.quantity_total
        status = res["status"]
        if body.status is not None:
            if body.status in ("UNAVAILABLE", "MAINTENANCE") and in_use > 0:
                raise conflict(
                    "RESOURCE_IN_USE",
                    "Release the active assignments before marking this resource unavailable",
                )
            status = body.status
        if status == "AVAILABLE" or status in ("ASSIGNED", "RESERVED"):
            status = derive_status("AVAILABLE", available)

        lon, lat = _point(body.latitude, body.longitude)
        conn.execute(
            """
            UPDATE resources SET
                name = COALESCE(%s, name),
                capability = COALESCE(%s, capability),
                quantity_total = %s,
                quantity_available = %s,
                status = %s,
                current_geom = CASE WHEN %s::float8 IS NULL THEN current_geom
                                    ELSE ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography END,
                version = version + 1
            WHERE resource_id = %s
            """,
            (
                body.name.strip() if body.name else None,
                Jsonb(body.capability) if body.capability is not None else None,
                total,
                available,
                status,
                lon,
                lon,
                lat,
                resource_id,
            ),
        )
        audit.record(
            conn,
            actor=principal,
            action="RESOURCE_UPDATED",
            entity_type="resource",
            entity_id=resource_id,
            rationale=body.reason,
            before={"status": res["status"], "quantity_total": res["quantity_total"],
                    "quantity_available": res["quantity_available"]},
            after={"status": status, "quantity_total": total, "quantity_available": available},
            ip=principal.ip,
        )
        updated = conn.execute(
            sql.SQL("{} WHERE r.resource_id = %s").format(sql.SQL(_RESOURCE_SELECT)), (resource_id,)
        ).fetchone()
    return updated


@router.get("/resources/{resource_id}/assignments")
def resource_assignments(resource_id: uuid.UUID, principal: DMUser):
    with db.read_only() as conn:
        if conn.execute("SELECT 1 FROM resources WHERE resource_id = %s", (resource_id,)).fetchone() is None:
            raise not_found("Resource")
        items = conn.execute(
            """
            SELECT x.assignment_id, x.quantity, x.assigned_at, x.released_at, d.dispatch_id,
                   d.dispatch_ref, d.status AS dispatch_status, i.incident_ref, u.full_name AS assigned_by_name
            FROM resource_assignments x
            JOIN dispatch_orders d ON d.dispatch_id = x.dispatch_id
            JOIN incidents i ON i.incident_id = d.incident_id
            JOIN users u ON u.user_id = x.assigned_by
            WHERE x.resource_id = %s ORDER BY x.assigned_at DESC
            """,
            (resource_id,),
        ).fetchall()
    return {"items": items}


class ReservationRequest(BaseModel):
    dispatch_id: uuid.UUID
    quantity: Decimal = Field(Decimal(1), gt=0, max_digits=12, decimal_places=2)


@router.post("/resources/{resource_id}/reservations", status_code=201)
def create_reservation(
    resource_id: uuid.UUID, body: ReservationRequest, principal: DMUser
):
    with db.transaction() as conn:
        dispatch = conn.execute(
            "SELECT * FROM dispatch_orders WHERE dispatch_id = %s FOR UPDATE", (body.dispatch_id,)
        ).fetchone()
        if dispatch is None:
            raise not_found("Dispatch")
        assignment = reserve(conn, principal, resource_id=resource_id, dispatch=dispatch, quantity=body.quantity)
    return assignment


@router.delete("/resources/{resource_id}/reservations/{assignment_id}", status_code=200)
def release_reservation(
    resource_id: uuid.UUID,
    assignment_id: uuid.UUID,
    principal: DMUser,
):
    with db.transaction() as conn:
        assignment = conn.execute(
            "SELECT * FROM resource_assignments WHERE assignment_id = %s AND resource_id = %s FOR UPDATE",
            (assignment_id, resource_id),
        ).fetchone()
        if assignment is None:
            raise not_found("Reservation")
        if assignment["released_at"] is not None:
            raise conflict("ALREADY_RELEASED", "This reservation was already released")
        release(conn, principal, assignment, "Released by staff")
    return {"assignment_id": assignment_id, "released": True}


@router.get("/agency-contacts")
def agency_contacts(principal: DMUser):
    """External agencies are message recipients only; they hold no accounts (SRS s.2)."""
    with db.read_only() as conn:
        items = conn.execute(
            """
            SELECT agency_id, name, agency_type, contact_email, contact_phone, is_active, updated_at
            FROM agencies ORDER BY is_active DESC, name
            """
        ).fetchall()
    return {"items": items}
