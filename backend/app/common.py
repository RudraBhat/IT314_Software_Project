"""Shared types and helpers for the Disaster Management API."""

from typing import Annotated, Any, Literal

from fastapi import Depends, Query
from psycopg import sql
from pydantic import BaseModel, Field

# The API uses the lower-case scenario values defined in SRS s.15.1; the
# database enum is upper-case. Anything else fails validation (EH-25).
Scenario = Literal["cyclone", "industrial_fire", "urban_flooding"]
Priority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
IncidentStatus = Literal[
    "SUBMITTED", "NEEDS_INFORMATION", "VERIFIED", "DISPATCHED", "RESOLVED", "CLOSED", "REJECTED"
]

# Shorter text limits than the database allows keep payloads reasonable.
Rationale = Field(min_length=3, max_length=2000)


def scenario_db(value: str | None) -> str | None:
    return value.upper() if value else None


def scenario_api(value: str | None) -> str | None:
    return value.lower() if value else None


class Version(BaseModel):
    """Optimistic concurrency: the version the client last read (DM-NFR-11)."""

    version: int = Field(ge=1)


class PageParams:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ):
        self.page = page
        self.limit = limit
        self.offset = (page - 1) * limit


Page = Annotated[PageParams, Depends()]


def page_body(items: list[Any], total: int, params: PageParams) -> dict:
    return {
        "items": items,
        "page": params.page,
        "limit": params.limit,
        "total": total,
        "pages": (total + params.limit - 1) // params.limit if total else 0,
    }


class Filters:
    """Builds a parameterised WHERE clause from trusted SQL fragments and untrusted values."""

    def __init__(self) -> None:
        self._parts: list[sql.Composable] = []
        self.params: dict[str, Any] = {}

    def add(self, fragment: str, **params: Any) -> None:
        self._parts.append(sql.SQL(fragment))
        self.params.update(params)

    def where(self) -> sql.Composable:
        if not self._parts:
            return sql.SQL("")
        return sql.SQL("WHERE ") + sql.SQL(" AND ").join(self._parts)


def notify(conn, *, user_id, event_code: str, title: str, body: str, related_id=None) -> None:
    """Queue an in-app notification. In-app status is the source of truth (NU-FR-07)."""
    conn.execute(
        """
        INSERT INTO notifications (user_id, event_code, channel, title, body, related_id, status)
        VALUES (%s, %s, 'IN_APP', %s, %s, %s, 'QUEUED')
        """,
        (user_id, event_code, title[:200], body, related_id),
    )


def next_incident_ref(conn) -> str:
    """INC-YYYY-NNNNNN from incident_ref_seq, skipping any reference that already exists
    (e.g. rows inserted by hand or by seed files)."""
    for _ in range(20):
        ref = conn.execute(
            "SELECT 'INC-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('incident_ref_seq')::text, 6, '0') AS ref"
        ).fetchone()["ref"]
        if conn.execute("SELECT 1 FROM incidents WHERE incident_ref = %s", (ref,)).fetchone() is None:
            return ref
    raise RuntimeError("could not allocate an incident reference")
