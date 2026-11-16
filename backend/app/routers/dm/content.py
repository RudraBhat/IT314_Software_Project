"""Verified public updates (DM-FR-11) and versioned safety content (DM-FR-17).

Safety content states map onto the schema as: Draft = DRAFT without approval,
Approved = DRAFT with approved_at, Published = PUBLISHED, Superseded = ARCHIVED.
"""

import uuid
from typing import Literal

from fastapi import APIRouter
from psycopg import sql
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import DMUser, Publisher
from app.common import Filters, Page, Scenario, page_body, scenario_db
from app.errors import ApiError, conflict, not_found

router = APIRouter()

# ------------------------------------------------------------- public updates

_UPDATE_SELECT = """
SELECT p.update_id, p.incident_id, i.incident_ref, lower(p.scenario::text) AS scenario,
       p.title, p.body, p.area_label, p.status, p.created_at, p.updated_at, p.published_at,
       a.full_name AS author_name, pb.full_name AS published_by_name
FROM public_updates p
LEFT JOIN incidents i ON i.incident_id = p.incident_id
LEFT JOIN users a ON a.user_id = p.created_by
LEFT JOIN users pb ON pb.user_id = p.published_by
"""

ContentStatus = Literal["DRAFT", "PUBLISHED", "ARCHIVED"]


@router.get("/public-updates")
def list_public_updates(
    *,
    page: Page,
    status: ContentStatus | None = None,
    scenario: Scenario | None = None,
    incident_id: uuid.UUID | None = None,
    principal: DMUser,
):
    f = Filters()
    if status:
        f.add("p.status = %(status)s::content_status", status=status)
    if scenario:
        f.add("p.scenario = %(scenario)s::scenario_type", scenario=scenario_db(scenario))
    if incident_id:
        f.add("p.incident_id = %(incident)s", incident=incident_id)
    where = f.where()
    with db.read_only() as conn:
        total = conn.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM public_updates p {}").format(where), f.params
        ).fetchone()["n"]
        items = conn.execute(
            sql.SQL("{} {} ORDER BY p.updated_at DESC LIMIT %(limit)s OFFSET %(offset)s").format(
                sql.SQL(_UPDATE_SELECT), where
            ),
            {**f.params, "limit": page.limit, "offset": page.offset},
        ).fetchall()
    return page_body(items, total, page)


class UpdateDraft(BaseModel):
    scenario: Scenario
    title: str = Field(min_length=5, max_length=200)
    body: str = Field(min_length=10, max_length=8000)
    area_label: str | None = Field(None, max_length=200)
    incident_id: uuid.UUID | None = None


def _fetch_update(conn, update_id) -> dict:
    row = conn.execute(
        sql.SQL("{} WHERE p.update_id = %s").format(sql.SQL(_UPDATE_SELECT)), (update_id,)
    ).fetchone()
    if row is None:
        raise not_found("Public update")
    return row


def _check_incident(conn, incident_id, scenario: str) -> None:
    incident = conn.execute(
        "SELECT scenario FROM incidents WHERE incident_id = %s", (incident_id,)
    ).fetchone()
    if incident is None:
        raise ApiError(422, "VALIDATION_FAILED", "The linked incident does not exist")
    if incident["scenario"] != scenario:
        raise ApiError(422, "SCENARIO_MISMATCH", "The update's scenario must match the linked incident")


@router.post("/public-updates", status_code=201)
def draft_public_update(body: UpdateDraft, principal: DMUser):
    scenario = scenario_db(body.scenario)
    with db.transaction() as conn:
        if body.incident_id:
            _check_incident(conn, body.incident_id, scenario)
        row = conn.execute(
            """
            INSERT INTO public_updates (incident_id, scenario, title, body, area_label, status, created_by)
            VALUES (%s, %s, %s, %s, %s, 'DRAFT', %s) RETURNING update_id
            """,
            (body.incident_id, scenario, body.title.strip(), body.body.strip(), body.area_label, principal.user_id),
        ).fetchone()
        audit.record(
            conn,
            actor=principal,
            action="PUBLIC_UPDATE_DRAFTED",
            entity_type="public_update",
            entity_id=row["update_id"],
            rationale=body.title,
            ip=principal.ip,
        )
        return _fetch_update(conn, row["update_id"])


class UpdateEdit(BaseModel):
    title: str | None = Field(None, min_length=5, max_length=200)
    body: str | None = Field(None, min_length=10, max_length=8000)
    area_label: str | None = Field(None, max_length=200)


@router.patch("/public-updates/{update_id}")
def edit_public_update(update_id: uuid.UUID, body: UpdateEdit, principal: DMUser):
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM public_updates WHERE update_id = %s FOR UPDATE", (update_id,)).fetchone()
        if row is None:
            raise not_found("Public update")
        if row["status"] != "DRAFT":
            raise conflict("NOT_A_DRAFT", "Only drafts can be edited; published updates are kept as issued")
        conn.execute(
            """
            UPDATE public_updates SET title = COALESCE(%s, title), body = COALESCE(%s, body),
                   area_label = COALESCE(%s, area_label)
            WHERE update_id = %s
            """,
            (body.title, body.body, body.area_label, update_id),
        )
        audit.record(conn, actor=principal, action="PUBLIC_UPDATE_EDITED", entity_type="public_update",
                     entity_id=update_id, ip=principal.ip)
        return _fetch_update(conn, update_id)


@router.post("/public-updates/{update_id}/publish")
def publish_public_update(update_id: uuid.UUID, principal: Publisher):
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM public_updates WHERE update_id = %s FOR UPDATE", (update_id,)).fetchone()
        if row is None:
            raise not_found("Public update")
        if row["status"] != "DRAFT":
            raise conflict("NOT_A_DRAFT", f"This update is already {row['status'].lower()}")
        if row["incident_id"]:
            incident = conn.execute(
                "SELECT verified_at FROM incidents WHERE incident_id = %s", (row["incident_id"],)
            ).fetchone()
            if incident is None or incident["verified_at"] is None:
                raise conflict(
                    "INCIDENT_NOT_VERIFIED",
                    "Updates about an incident can be published only after it is verified",
                )
        conn.execute(
            """
            UPDATE public_updates SET status = 'PUBLISHED', published_by = %s, published_at = now()
            WHERE update_id = %s
            """,
            (principal.user_id, update_id),
        )
        audit.record(conn, actor=principal, action="PUBLIC_UPDATE_PUBLISHED", entity_type="public_update",
                     entity_id=update_id, rationale=row["title"], ip=principal.ip)
        return _fetch_update(conn, update_id)


class ArchiveRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/public-updates/{update_id}/archive")
def archive_public_update(
    update_id: uuid.UUID, body: ArchiveRequest, principal: Publisher
):
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM public_updates WHERE update_id = %s FOR UPDATE", (update_id,)).fetchone()
        if row is None:
            raise not_found("Public update")
        if row["status"] == "ARCHIVED":
            raise conflict("ALREADY_ARCHIVED", "This update is already archived")
        conn.execute("UPDATE public_updates SET status = 'ARCHIVED' WHERE update_id = %s", (update_id,))
        audit.record(conn, actor=principal, action="PUBLIC_UPDATE_ARCHIVED", entity_type="public_update",
                     entity_id=update_id, rationale=body.reason, before={"status": row["status"]}, ip=principal.ip)
        return _fetch_update(conn, update_id)


# -------------------------------------------------------------- safety content

_CONTENT_SELECT = """
SELECT c.content_id, lower(c.scenario::text) AS scenario, c.title, c.body, c.source, c.version,
       c.status,
       CASE WHEN c.status = 'DRAFT' AND c.approved_at IS NOT NULL THEN 'APPROVED'
            WHEN c.status = 'ARCHIVED' THEN 'SUPERSEDED'
            ELSE c.status::text END AS state,
       c.created_at, c.updated_at, c.approved_at, c.published_at,
       au.full_name AS author_name, ap.full_name AS approver_name, pb.full_name AS published_by_name
FROM safety_content c
LEFT JOIN users au ON au.user_id = c.author_id
LEFT JOIN users ap ON ap.user_id = c.approved_by
LEFT JOIN users pb ON pb.user_id = c.published_by
"""


def _fetch_content(conn, content_id) -> dict:
    row = conn.execute(
        sql.SQL("{} WHERE c.content_id = %s").format(sql.SQL(_CONTENT_SELECT)), (content_id,)
    ).fetchone()
    if row is None:
        raise not_found("Safety content")
    return row


def _lock_content(conn, content_id) -> dict:
    row = conn.execute("SELECT * FROM safety_content WHERE content_id = %s FOR UPDATE", (content_id,)).fetchone()
    if row is None:
        raise not_found("Safety content")
    return row


@router.get("/safety-content")
def list_safety_content(
    *,
    scenario: Scenario | None = None,
    state: Literal["DRAFT", "APPROVED", "PUBLISHED", "SUPERSEDED"] | None = None,
    principal: DMUser,
):
    f = Filters()
    if scenario:
        f.add("c.scenario = %(scenario)s::scenario_type", scenario=scenario_db(scenario))
    with db.read_only() as conn:
        items = conn.execute(
            sql.SQL("{} {} ORDER BY c.scenario, c.title, c.version DESC").format(sql.SQL(_CONTENT_SELECT), f.where()),
            f.params,
        ).fetchall()
    if state:
        items = [i for i in items if i["state"] == state]
    return {"items": items}


class ContentDraft(BaseModel):
    scenario: Scenario | None = None
    title: str | None = Field(None, min_length=5, max_length=200)
    body: str = Field(min_length=10, max_length=20000)
    source: str = Field(min_length=3, max_length=500, description="Authority or document the guidance is based on")
    based_on_id: uuid.UUID | None = Field(None, description="Create the next version of this content")


@router.post("/safety-content", status_code=201)
def draft_safety_content(body: ContentDraft, principal: DMUser):
    with db.transaction() as conn:
        if body.based_on_id:
            base = conn.execute(
                "SELECT scenario, title FROM safety_content WHERE content_id = %s", (body.based_on_id,)
            ).fetchone()
            if base is None:
                raise not_found("Safety content")
            scenario, title = base["scenario"], base["title"]
        else:
            if not (body.scenario and body.title):
                raise ApiError(422, "VALIDATION_FAILED", "scenario and title are required for new content")
            scenario, title = scenario_db(body.scenario), body.title.strip()
        # Serialise version numbering for this (scenario, title).
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"safety:{scenario}:{title}",))
        if conn.execute(
            """
            SELECT 1 FROM safety_content
            WHERE scenario = %s AND title = %s AND status = 'DRAFT'
            """,
            (scenario, title),
        ).fetchone():
            raise conflict("DRAFT_EXISTS", "A draft of this content already exists; edit or publish it first")
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM safety_content WHERE scenario = %s AND title = %s",
            (scenario, title),
        ).fetchone()["v"]
        row = conn.execute(
            """
            INSERT INTO safety_content (scenario, title, body, source, status, version, author_id)
            VALUES (%s, %s, %s, %s, 'DRAFT', %s, %s) RETURNING content_id
            """,
            (scenario, title, body.body.strip(), body.source.strip(), version, principal.user_id),
        ).fetchone()
        audit.record(conn, actor=principal, action="SAFETY_CONTENT_DRAFTED", entity_type="safety_content",
                     entity_id=row["content_id"], rationale=f"{title} v{version}", ip=principal.ip)
        return _fetch_content(conn, row["content_id"])


class ContentEdit(BaseModel):
    body: str | None = Field(None, min_length=10, max_length=20000)
    source: str | None = Field(None, min_length=3, max_length=500)


@router.patch("/safety-content/{content_id}")
def edit_safety_content(content_id: uuid.UUID, body: ContentEdit, principal: DMUser):
    with db.transaction() as conn:
        row = _lock_content(conn, content_id)
        if row["status"] != "DRAFT" or row["approved_at"] is not None:
            raise conflict("NOT_EDITABLE", "Only unapproved drafts can be edited; create a new version instead")
        conn.execute(
            "UPDATE safety_content SET body = COALESCE(%s, body), source = COALESCE(%s, source) WHERE content_id = %s",
            (body.body, body.source, content_id),
        )
        audit.record(conn, actor=principal, action="SAFETY_CONTENT_EDITED", entity_type="safety_content",
                     entity_id=content_id, ip=principal.ip)
        return _fetch_content(conn, content_id)


@router.get("/safety-content/{content_id}/versions")
def safety_content_versions(content_id: uuid.UUID, principal: DMUser):
    with db.read_only() as conn:
        base = conn.execute(
            "SELECT scenario, title FROM safety_content WHERE content_id = %s", (content_id,)
        ).fetchone()
        if base is None:
            raise not_found("Safety content")
        items = conn.execute(
            sql.SQL("{} WHERE c.scenario = %s AND c.title = %s ORDER BY c.version DESC").format(
                sql.SQL(_CONTENT_SELECT)
            ),
            (base["scenario"], base["title"]),
        ).fetchall()
    return {"items": items}


@router.post("/safety-content/{content_id}/approval")
def approve_safety_content(content_id: uuid.UUID, principal: Publisher):
    with db.transaction() as conn:
        row = _lock_content(conn, content_id)
        if row["status"] != "DRAFT":
            raise conflict("NOT_A_DRAFT", "Only drafts can be approved")
        if row["approved_at"] is not None:
            raise conflict("ALREADY_APPROVED", "This version is already approved")
        conn.execute(
            "UPDATE safety_content SET approved_by = %s, approved_at = now() WHERE content_id = %s",
            (principal.user_id, content_id),
        )
        audit.record(conn, actor=principal, action="SAFETY_CONTENT_APPROVED", entity_type="safety_content",
                     entity_id=content_id, rationale=f"{row['title']} v{row['version']}", ip=principal.ip)
        return _fetch_content(conn, content_id)


@router.post("/safety-content/{content_id}/publish")
def publish_safety_content(content_id: uuid.UUID, principal: Publisher):
    with db.transaction() as conn:
        row = _lock_content(conn, content_id)
        if row["status"] != "DRAFT":
            raise conflict("NOT_A_DRAFT", f"This version is already {row['status'].lower()}")
        if row["approved_at"] is None:
            raise conflict("NOT_APPROVED", "A publisher must approve this version before it is published")
        superseded = conn.execute(
            """
            UPDATE safety_content SET status = 'ARCHIVED'
            WHERE scenario = %s AND title = %s AND status = 'PUBLISHED' AND content_id <> %s
            RETURNING content_id
            """,
            (row["scenario"], row["title"], content_id),
        ).fetchall()
        conn.execute(
            """
            UPDATE safety_content SET status = 'PUBLISHED', published_at = now(), published_by = %s
            WHERE content_id = %s
            """,
            (principal.user_id, content_id),
        )
        audit.record(
            conn,
            actor=principal,
            action="SAFETY_CONTENT_PUBLISHED",
            entity_type="safety_content",
            entity_id=content_id,
            rationale=f"{row['title']} v{row['version']}",
            after={"superseded": [str(s["content_id"]) for s in superseded]},
            ip=principal.ip,
        )
        return _fetch_content(conn, content_id)
