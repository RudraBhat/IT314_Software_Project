"""Internal notes on an incident: a shared, append-only log for the dispatch team (DM-FR-02).

Notes are for Disaster Management staff only and are never shown to the reporter. They cannot be edited or
deleted, so the log can be trusted at handover; a correction is a new note.
"""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import DMUser
from app.errors import ApiError, not_found
from app.ratelimit import rate_limit

router = APIRouter()


class NoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=1000, description="What the next shift should know")


@router.get("/incidents/{incident_id}/notes")
def list_notes(incident_id: uuid.UUID, principal: DMUser):
    """The incident's internal notes, newest first."""
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM incidents WHERE incident_id = %s", (incident_id,)).fetchone() is None:
            raise not_found("Incident")
        rows = conn.execute(
            """
            SELECT n.note_id, n.body, n.created_at, u.full_name AS author_name, n.author_id = %(me)s AS mine
            FROM incident_notes n JOIN users u ON u.user_id = n.author_id
            WHERE n.incident_id = %(incident)s
            ORDER BY n.created_at DESC, n.note_id DESC
            """,
            {"me": principal.user_id, "incident": incident_id},
        ).fetchall()
    return {"items": rows}


@router.post("/incidents/{incident_id}/notes", status_code=201, dependencies=[rate_limit("incident-note", 60, 3600)])
def add_note(incident_id: uuid.UUID, body: NoteRequest, principal: DMUser):
    """Add a note. Allowed on any incident, including a closed one (a late outcome is worth recording)."""
    text = body.body.strip()
    if not text:
        raise ApiError(422, "VALIDATION_FAILED", "Write the note before saving it")
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM incidents WHERE incident_id = %s", (incident_id,)).fetchone() is None:
            raise not_found("Incident")
        note_id = conn.execute(
            "INSERT INTO incident_notes (incident_id, author_id, body) VALUES (%s, %s, %s) RETURNING note_id",
            (incident_id, principal.user_id, text),
        ).fetchone()["note_id"]
        audit.record(
            conn,
            actor=principal,
            action="INCIDENT_NOTE_ADDED",
            entity_type="incident",
            entity_id=incident_id,
            rationale="Internal note added",
            after={"note_id": str(note_id)},
            ip=principal.ip,
        )
        note = conn.execute(
            """
            SELECT n.note_id, n.body, n.created_at, u.full_name AS author_name, n.author_id = %(me)s AS mine
            FROM incident_notes n JOIN users u ON u.user_id = n.author_id
            WHERE n.note_id = %(note)s
            """,
            {"me": principal.user_id, "note": note_id},
        ).fetchone()
    return note
