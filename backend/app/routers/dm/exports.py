"""CSV exports of the incident and dispatch queues, for shift handover and reporting.

Each export uses the same filters as the screen it comes from, is capped at EXPORT_LIMIT rows, and is
recorded in the audit log with its filters and row count. The incident export leaves out everything that
identifies a reporter (name, phone, email) and the free-text description, so citizen personal data never
leaves the system in a spreadsheet. These routes are declared before /incidents/{id} and /dispatches/{id}
so that "export" is never mistaken for an id.
"""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from psycopg import sql

from app import audit, db
from app.auth import DMUser
from app.common import IncidentStatus, Priority, Scenario
from app.ratelimit import rate_limit
from app.routers.dm.dispatches import DispatchStatus, dispatch_filters
from app.routers.dm.incidents import _LIST_COLUMNS, incident_filters
from app.services.csv_export import EXPORT_LIMIT, csv_response
from app.services.dispatch import DISPATCH_SELECT, get_dispatch_timeout

router = APIRouter()

_INCIDENT_HEADER = [
    "Reference", "Scenario", "Status", "Priority", "Reported urgency", "People affected", "Address", "Landmark",
    "Latitude", "Longitude", "Submitted", "Updated", "Closed", "Evidence files", "Active dispatches",
]

_DISPATCH_HEADER = [
    "Dispatch", "Incident", "Scenario", "Status", "Priority", "Agency", "Requested by", "Requested",
    "Acknowledged", "Overdue", "Escalated",
]


@router.get("/incidents/export", dependencies=[rate_limit("dm-export", 10, 3600)])
def export_incidents(
    *,
    principal: DMUser,
    scenario: Scenario | None = None,
    status: Annotated[list[IncidentStatus] | None, Query()] = None,
    priority: Annotated[list[Priority | Literal["UNASSIGNED"]] | None, Query()] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    near_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    near_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[float, Query(gt=0, le=500)] = 10,
):
    """The incident queue (same filters as the screen) as a CSV download, newest first, at most 5000 rows.

    No reporter name, phone or email and no free-text description. Every export is audited.
    """
    f = incident_filters(
        scenario=scenario, status=status, priority=priority, from_=from_, to=to, q=q,
        near_lat=near_lat, near_lon=near_lon, radius_km=radius_km,
    )
    with db.transaction() as conn:
        rows = conn.execute(
            sql.SQL("SELECT {} FROM incidents i {} ORDER BY i.submitted_at DESC LIMIT %(limit)s").format(
                sql.SQL(_LIST_COLUMNS), f.where()
            ),
            {**f.params, "limit": EXPORT_LIMIT + 1},
        ).fetchall()
        truncated = len(rows) > EXPORT_LIMIT
        rows = rows[:EXPORT_LIMIT]
        audit.record(
            conn,
            actor=principal,
            action="INCIDENTS_EXPORTED",
            entity_type="incident",
            rationale=f"Exported {len(rows)} incidents",
            after={
                "rows": len(rows),
                "truncated": truncated,
                "filters": {
                    "scenario": scenario,
                    "status": [str(s) for s in status or []] or None,
                    "priority": [str(p) for p in priority or []] or None,
                    "from": str(from_) if from_ else None,
                    "to": str(to) if to else None,
                    "q": (q or "").strip() or None,
                    "near": [near_lat, near_lon, radius_km] if near_lat is not None and near_lon is not None else None,
                },
            },
            ip=principal.ip,
        )
    return csv_response(
        _INCIDENT_HEADER,
        (
            (
                r["incident_ref"], r["scenario"], r["status"], r["verified_priority"], r["reported_urgency"],
                r["people_affected"], r["address_text"], r["landmark"], r["latitude"], r["longitude"],
                r["submitted_at"], r["updated_at"], r["closed_at"], r["evidence_count"], r["active_dispatches"],
            )
            for r in rows
        ),
        "incidents",
        truncated=truncated,
    )


@router.get("/dispatches/export", dependencies=[rate_limit("dm-export", 10, 3600)])
def export_dispatches(
    *,
    principal: DMUser,
    status: Annotated[list[DispatchStatus] | None, Query()] = None,
    overdue: bool = False,
    active: bool = False,
    incident_id: uuid.UUID | None = None,
):
    """The dispatch queue (same filters as the screen) as a CSV download, at most 5000 rows. Every export is audited."""
    f = dispatch_filters(status=status, overdue=overdue, active=active, incident_id=incident_id)
    with db.transaction() as conn:
        rows = conn.execute(
            sql.SQL("{} {} ORDER BY d.created_at DESC LIMIT %(limit)s").format(sql.SQL(DISPATCH_SELECT), f.where()),
            {**f.params, "timeout": get_dispatch_timeout(), "limit": EXPORT_LIMIT + 1},
        ).fetchall()
        truncated = len(rows) > EXPORT_LIMIT
        rows = rows[:EXPORT_LIMIT]
        audit.record(
            conn,
            actor=principal,
            action="DISPATCHES_EXPORTED",
            entity_type="dispatch_order",
            rationale=f"Exported {len(rows)} dispatches",
            after={
                "rows": len(rows),
                "truncated": truncated,
                "filters": {
                    "status": [str(s) for s in status or []] or None,
                    "overdue": overdue,
                    "active": active,
                    "incident_id": str(incident_id) if incident_id else None,
                },
            },
            ip=principal.ip,
        )
    return csv_response(
        _DISPATCH_HEADER,
        (
            (
                r["dispatch_ref"], r["incident_ref"], r["scenario"], r["status"], r["priority"], r["agency_name"],
                r["created_by_name"], r["created_at"], r["acknowledged_at"], r["overdue"], r["escalated"],
            )
            for r in rows
        ),
        "dispatches",
        truncated=truncated,
    )
