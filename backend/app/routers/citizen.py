"""Citizen incident reporting and tracking (NU-FR-03..07).

Contract: docs/api_contracts.md sections 2.3 and 2.4.
Every query is scoped to the authenticated citizen (reporter_id); another
citizen's incident is reported as 404 so its existence is never revealed.
"""

import hashlib
import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from psycopg import sql
from pydantic import BaseModel, Field, field_validator, model_validator

from app import audit, db, security
from app.auth import Citizen
from app.common import Page, Priority, Scenario, next_incident_ref, notify, page_body, scenario_db
from app.errors import ApiError, conflict, not_found
from app.geo import district_for, is_in_gujarat
from app.ratelimit import rate_limit
from app.routers.auth import _PHONE_RE
from app.routers.auth import _check_password_policy as check_password_policy
from app.uploads import read_capped_body, safe_filename, sniff_image_type

router = APIRouter(prefix="/api/v1", tags=["citizen"])

_MAX_DETAILS_BYTES = 4096


class IncidentCreate(BaseModel):
    scenario: Scenario
    description: str = Field(min_length=10, max_length=2000)
    reported_urgency: Priority | None = None
    people_affected: int | None = Field(default=None, ge=0, le=1_000_000)
    location_source: Literal["GPS", "MAP_PIN", "MANUAL"] = "GPS"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    address_text: str | None = Field(default=None, max_length=300)
    landmark: str | None = Field(default=None, max_length=200)
    details: dict = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def _small_details(cls, value: dict) -> dict:
        if len(json.dumps(value, default=str)) > _MAX_DETAILS_BYTES:
            raise ValueError("details is too large")
        return value


class InformationReply(BaseModel):
    """Answer to a DM information request: text, a corrected location, or both (S2-13)."""

    message: str | None = Field(default=None, min_length=3, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address_text: str | None = Field(default=None, max_length=300)

    @field_validator("message")
    @classmethod
    def _message_has_content(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) < 3:
            raise ValueError("message must contain at least 3 non-whitespace characters")
        return value

    @model_validator(mode="after")
    def _needs_content(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        if not (self.message and self.message.strip()) and self.latitude is None:
            raise ValueError("Provide a message or a corrected location")
        return self


# Readable timeline labels so clients never show raw status codes (S2-13).
STATUS_LABELS = {
    "SUBMITTED": "Report submitted",
    "NEEDS_INFORMATION": "More information requested",
    "VERIFIED": "Verified by the response team",
    "REJECTED": "Report not accepted",
    "DISPATCHED": "Help is on the way",
    "IN_PROGRESS": "Response in progress",
    "RESOLVED": "Incident resolved",
    "CLOSED": "Report closed",
}


def _readable(item: dict) -> dict:
    """Add a human-readable label to the incident status and every timeline entry."""
    item["status_label"] = STATUS_LABELS.get(item["status"], item["status"].replace("_", " ").capitalize())
    for entry in item.get("timeline") or []:
        code = entry.get("status", "")
        entry["label"] = STATUS_LABELS.get(code, code.replace("_", " ").capitalize())
    return item


def _created_body(row: dict) -> dict:
    return {
        "incident_id": row["incident_id"],
        "incident_ref": row["incident_ref"],
        "status": row["status"],
        "district": row["district"],
        "created_at": row["submitted_at"],
    }


@router.post("/incidents", status_code=201, dependencies=[rate_limit("report", 30, 3600)])
def create_incident(
    body: IncidentCreate,
    principal: Citizen,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
):
    # Required (docs/api_contracts.md s.2.3): without a key, every client retry of the same
    # emergency would create another report. Same rule and error code as POST /donations.
    if not idempotency_key or not idempotency_key.strip():
        raise ApiError(422, "IDEMPOTENCY_KEY_REQUIRED", "The Idempotency-Key header is required")
    idempotency_key = idempotency_key.strip()
    if not is_in_gujarat(body.latitude, body.longitude):
        raise ApiError(422, "OUTSIDE_GUJARAT", "The reported location is outside Gujarat")
    district = district_for(body.latitude, body.longitude)
    with db.transaction() as conn:
        existing = conn.execute(
            """
            SELECT incident_id, incident_ref, status, district, submitted_at
            FROM incidents WHERE reporter_id = %s AND idempotency_key = %s
            """,
            (principal.user_id, idempotency_key),
        ).fetchone()
        if existing:
            return JSONResponse(status_code=200, content=jsonable_encoder(_created_body(existing)))
        ref = next_incident_ref(conn)
        row = conn.execute(
            """
            INSERT INTO incidents
                (incident_ref, reporter_id, scenario, description, reported_urgency, people_affected,
                 location_source, latitude, longitude, accuracy_m, address_text, landmark, details,
                 idempotency_key, district, source)
            VALUES (%s, %s, %s::scenario_type, %s, %s::priority_level, %s,
                    %s::location_source, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'CITIZEN')
            ON CONFLICT (reporter_id, idempotency_key) DO NOTHING
            RETURNING incident_id, incident_ref, status, district, submitted_at
            """,
            (
                ref,
                principal.user_id,
                scenario_db(body.scenario),
                body.description.strip(),
                body.reported_urgency,
                body.people_affected,
                body.location_source,
                body.latitude,
                body.longitude,
                body.accuracy_m,
                body.address_text.strip() if body.address_text else None,
                body.landmark.strip() if body.landmark else None,
                json.dumps(body.details),
                idempotency_key,
                district,
            ),
        ).fetchone()
        if row is None:  # lost a race with a concurrent request using the same key
            row = conn.execute(
                """
                SELECT incident_id, incident_ref, status, district, submitted_at
                FROM incidents WHERE reporter_id = %s AND idempotency_key = %s
                """,
                (principal.user_id, idempotency_key),
            ).fetchone()
            return JSONResponse(status_code=200, content=jsonable_encoder(_created_body(row)))
        conn.execute(
            """
            INSERT INTO incident_status_history (incident_id, from_status, to_status, changed_by, reason)
            VALUES (%s, NULL, 'SUBMITTED', %s, 'Report submitted')
            """,
            (row["incident_id"], principal.user_id),
        )
        audit.record(
            conn,
            actor=principal,
            action="INCIDENT_SUBMITTED",
            entity_type="incident",
            entity_id=row["incident_id"],
            rationale=f"{row['incident_ref']} submitted by citizen",
            ip=principal.ip,
        )
        notify(
            conn,
            user_id=principal.user_id,
            event_code="INCIDENT_RECEIVED",
            title=f"Report received ({row['incident_ref']})",
            body="Your report was received and is waiting for verification by the response team.",
            related_id=row["incident_id"],
        )
        return _created_body(row)


_MY_COLUMNS = """
    i.incident_id, i.incident_ref, lower(i.scenario::text) AS scenario, i.status, i.district,
    i.description, i.address_text, i.landmark, i.people_affected, i.submitted_at, i.updated_at,
    i.latitude::float AS latitude, i.longitude::float AS longitude,
    COALESCE((
        SELECT jsonb_agg(
                   jsonb_build_object(
                       'status', h.to_status,
                       'timestamp', h.changed_at,
                       -- Staff questions/rejections, and the reporter's own replies; never internal notes.
                       'message', CASE WHEN h.to_status IN ('NEEDS_INFORMATION', 'REJECTED')
                                         OR h.changed_by = i.reporter_id THEN h.reason END
                   ) ORDER BY h.changed_at, h.history_id)
        FROM incident_status_history h
        WHERE h.incident_id = i.incident_id AND h.from_status IS DISTINCT FROM h.to_status
    ), '[]'::jsonb) AS timeline,
    EXISTS (SELECT 1 FROM incident_status_history w WHERE w.incident_id = i.incident_id
            AND w.reason LIKE 'Reporter asked to withdraw%%') AS withdrawal_requested
"""


@router.get("/me/incidents")
def my_incidents(principal: Citizen, page: Page):
    with db.transaction() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM incidents WHERE reporter_id = %s", (principal.user_id,)
        ).fetchone()["n"]
        items = conn.execute(
            sql.SQL(
                "SELECT {} FROM incidents i WHERE i.reporter_id = %s "
                "ORDER BY i.submitted_at DESC LIMIT %s OFFSET %s"
            ).format(sql.SQL(_MY_COLUMNS)),
            (principal.user_id, page.limit, page.offset),
        ).fetchall()
    return page_body([_readable(i) for i in items], total, page)


def _own_incident(conn, incident_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    row = conn.execute(
        sql.SQL("SELECT {} FROM incidents i WHERE i.incident_id = %s AND i.reporter_id = %s").format(
            sql.SQL(_MY_COLUMNS)
        ),
        (incident_id, user_id),
    ).fetchone()
    if row is None:
        raise not_found("Incident")
    return row


@router.get("/me/incidents/{incident_id}")
def my_incident(incident_id: uuid.UUID, principal: Citizen):
    with db.transaction() as conn:
        return _readable(_own_incident(conn, incident_id, principal.user_id))


@router.post(
    "/me/incidents/{incident_id}/information-response",
    status_code=201,
    dependencies=[rate_limit("information-response", 20, 3600)],
)
@router.post(
    "/me/incidents/{incident_id}/information",  # earlier path, kept for existing clients
    status_code=201,
    dependencies=[rate_limit("information-response", 20, 3600)],
)
def reply_to_information_request(incident_id: uuid.UUID, body: InformationReply, principal: Citizen):
    """The reporter answers a DM information request (own incident, NEEDS_INFORMATION only).

    Stores the text and/or a corrected Gujarat location, returns the incident to SUBMITTED for
    the dispatcher to review again, and writes status history plus an audit entry.
    """
    if body.latitude is not None and not is_in_gujarat(body.latitude, body.longitude):
        raise ApiError(422, "OUTSIDE_GUJARAT", "The corrected location is outside Gujarat")
    with db.transaction() as conn:
        _own_incident(conn, incident_id, principal.user_id)
        row = conn.execute(
            "SELECT status FROM incidents WHERE incident_id = %s FOR UPDATE", (incident_id,)
        ).fetchone()
        if row["status"] != "NEEDS_INFORMATION":
            raise ApiError(409, "NOT_AWAITING_INFORMATION", "No information has been requested for this report")
        reason_parts = []
        if body.message and body.message.strip():
            reason_parts.append("Reporter reply: " + body.message.strip())
        if body.latitude is not None:
            district = district_for(body.latitude, body.longitude)
            conn.execute(
                """
                UPDATE incidents
                SET latitude = %s, longitude = %s,
                    geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    district = COALESCE(%s, district),
                    address_text = COALESCE(%s, address_text),
                    location_source = 'MANUAL'
                WHERE incident_id = %s
                """,
                (
                    body.latitude, body.longitude, body.longitude, body.latitude,
                    district, body.address_text.strip() if body.address_text else None, incident_id,
                ),
            )
            reason_parts.append("Reporter corrected the location")
        conn.execute(
            """
            UPDATE incidents SET status = 'SUBMITTED', version = version + 1, updated_at = now()
            WHERE incident_id = %s
            """,
            (incident_id,),
        )
        conn.execute(
            """
            INSERT INTO incident_status_history (incident_id, from_status, to_status, changed_by, reason)
            VALUES (%s, 'NEEDS_INFORMATION', 'SUBMITTED', %s, %s)
            """,
            (incident_id, principal.user_id, "; ".join(reason_parts)),
        )
        audit.record(
            conn,
            actor=principal,
            action="INFORMATION_PROVIDED",
            entity_type="incident",
            entity_id=incident_id,
            rationale="Reporter replied to an information request",
            before={"status": "NEEDS_INFORMATION"},
            after={"status": "SUBMITTED"},
            ip=principal.ip,
        )
    return {"incident_id": incident_id, "status": "SUBMITTED", "status_label": STATUS_LABELS["SUBMITTED"]}


# --------------------------------------------------------------------------- photo attachments (NU-FR-05)

_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_MAX_ATTACHMENTS = 5
_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
# Moderation state shown to the reporter; REJECTED files are treated as removed and never listed.
_ATTACHMENT_STATUS = {
    "PENDING": "Awaiting review",
    "CLEAN": "Approved",
    "QUARANTINED": "Held for review",
    "FAILED": "Held for review",
}


def _attachment_body(row: dict) -> dict:
    return {
        "evidence_id": row["evidence_id"],
        "file_name": row["file_name"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "status": _ATTACHMENT_STATUS.get(row["scan_state"], "Removed"),
        "uploaded_at": row["uploaded_at"],
    }


def _own_incident_status(conn, incident_id: uuid.UUID, user_id: uuid.UUID) -> str:
    row = conn.execute(
        "SELECT status FROM incidents WHERE incident_id = %s AND reporter_id = %s", (incident_id, user_id)
    ).fetchone()
    if row is None:
        raise not_found("Incident")
    return row["status"]


def _ensure_own_open_incident(incident_id: uuid.UUID, user_id: uuid.UUID) -> None:
    with db.transaction() as conn:
        if _own_incident_status(conn, incident_id, user_id) in ("CLOSED", "REJECTED"):
            raise conflict("INCIDENT_CLOSED", "Photos can no longer be added to this report")


def _store_attachment(principal, incident_id: uuid.UUID, filename: str, mime: str, content: bytes):
    digest = hashlib.sha256(content).hexdigest()
    with db.transaction() as conn:
        _own_incident_status(conn, incident_id, principal.user_id)
        status = conn.execute(
            "SELECT status FROM incidents WHERE incident_id = %s FOR UPDATE", (incident_id,)
        ).fetchone()["status"]
        if status in ("CLOSED", "REJECTED"):
            raise conflict("INCIDENT_CLOSED", "Photos can no longer be added to this report")
        same = conn.execute(
            "SELECT evidence_id, file_name, mime_type, size_bytes, scan_state, uploaded_at FROM evidence_files "
            "WHERE incident_id = %s AND sha256 = %s AND scan_state <> 'REJECTED'",
            (incident_id, digest),
        ).fetchone()
        if same:
            return _attachment_body(same), False
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM evidence_files WHERE incident_id = %s AND scan_state <> 'REJECTED'",
            (incident_id,),
        ).fetchone()["n"]
        if count >= _MAX_ATTACHMENTS:
            raise conflict("TOO_MANY_ATTACHMENTS", f"A report can have at most {_MAX_ATTACHMENTS} photos")
        evidence_id = uuid.uuid4()
        row = conn.execute(
            """
            INSERT INTO evidence_files
                (evidence_id, incident_id, uploaded_by, file_name, mime_type, size_bytes, storage_key, sha256)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING evidence_id, file_name, mime_type, size_bytes, scan_state, uploaded_at
            """,
            (evidence_id, incident_id, principal.user_id, filename, mime, len(content), f"db:{evidence_id}", digest),
        ).fetchone()
        conn.execute("INSERT INTO evidence_blobs (evidence_id, content) VALUES (%s, %s)", (evidence_id, content))
        audit.record(
            conn,
            actor=principal,
            action="EVIDENCE_UPLOADED",
            entity_type="evidence",
            entity_id=evidence_id,
            rationale="Reporter attached a photo",
            after={"incident_id": str(incident_id), "mime_type": mime, "size_bytes": len(content)},
            ip=principal.ip,
        )
        return _attachment_body(row), True


@router.post(
    "/me/incidents/{incident_id}/attachments",
    status_code=201,
    dependencies=[rate_limit("attachment", 30, 3600)],
)
async def upload_attachment(incident_id: uuid.UUID, request: Request, principal: Citizen):
    """Attach a JPEG, PNG or WebP photo (up to 5 MB, 5 per report) to your own open report.

    The photo is sent as the raw request body with its image content type and an optional
    X-Filename header. The type is checked from the file's bytes, not the declared header. The photo
    starts as Awaiting review for the moderation queue; the same photo sent twice returns the first.
    """
    declared = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if declared not in _ATTACHMENT_TYPES:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Send a JPEG, PNG or WebP photo as the request body.")
    await run_in_threadpool(_ensure_own_open_incident, incident_id, principal.user_id)
    content = await read_capped_body(request, _MAX_ATTACHMENT_BYTES)
    mime = sniff_image_type(content)
    if mime is None:
        raise ApiError(415, "INVALID_IMAGE", "The file is not a JPEG, PNG or WebP image.")
    filename = safe_filename(request.headers.get("x-filename"))
    body, created = await run_in_threadpool(_store_attachment, principal, incident_id, filename, mime, content)
    return JSONResponse(status_code=201 if created else 200, content=jsonable_encoder(body))


@router.get("/me/incidents/{incident_id}/attachments")
def list_attachments(incident_id: uuid.UUID, principal: Citizen):
    with db.transaction() as conn:
        _own_incident_status(conn, incident_id, principal.user_id)
        rows = conn.execute(
            "SELECT evidence_id, file_name, mime_type, size_bytes, scan_state, uploaded_at FROM evidence_files "
            "WHERE incident_id = %s AND scan_state <> 'REJECTED' ORDER BY uploaded_at",
            (incident_id,),
        ).fetchall()
    return {"items": [_attachment_body(r) for r in rows], "max_attachments": _MAX_ATTACHMENTS}


@router.get("/me/incidents/{incident_id}/attachments/{evidence_id}")
def download_attachment(incident_id: uuid.UUID, evidence_id: uuid.UUID, principal: Citizen):
    """Return your own photo. Another citizen's photo, or a removed one, is a 404."""
    with db.transaction() as conn:
        _own_incident_status(conn, incident_id, principal.user_id)
        row = conn.execute(
            """
            SELECT e.mime_type, b.content
            FROM evidence_files e JOIN evidence_blobs b ON b.evidence_id = e.evidence_id
            WHERE e.evidence_id = %s AND e.incident_id = %s AND e.scan_state <> 'REJECTED'
            """,
            (evidence_id, incident_id),
        ).fetchone()
    if row is None:
        raise not_found("Attachment")
    return Response(
        content=bytes(row["content"]),
        media_type=row["mime_type"],
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete("/me/incidents/{incident_id}/attachments/{evidence_id}")
def remove_attachment(incident_id: uuid.UUID, evidence_id: uuid.UUID, principal: Citizen):
    """Remove your own photo: the file is deleted and the record is kept as removed for the audit trail."""
    with db.transaction() as conn:
        _own_incident_status(conn, incident_id, principal.user_id)
        row = conn.execute(
            "SELECT scan_state FROM evidence_files WHERE evidence_id = %s AND incident_id = %s FOR UPDATE",
            (evidence_id, incident_id),
        ).fetchone()
        if row is None or row["scan_state"] == "REJECTED":
            raise not_found("Attachment")
        conn.execute("DELETE FROM evidence_blobs WHERE evidence_id = %s", (evidence_id,))
        conn.execute("UPDATE evidence_files SET scan_state = 'REJECTED' WHERE evidence_id = %s", (evidence_id,))
        audit.record(
            conn,
            actor=principal,
            action="EVIDENCE_REMOVED",
            entity_type="evidence",
            entity_id=evidence_id,
            rationale="Removed by the reporter",
            before={"moderation_state": row["scan_state"]},
            ip=principal.ip,
        )
    return {"evidence_id": evidence_id, "status": "Removed"}


# --------------------------------------------------------------------------- withdrawal request

_WITHDRAWABLE = ("SUBMITTED", "NEEDS_INFORMATION", "VERIFIED")


class WithdrawalRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.post(
    "/me/incidents/{incident_id}/withdrawal-request",
    status_code=201,
    dependencies=[rate_limit("withdrawal", 10, 3600)],
)
def request_withdrawal(incident_id: uuid.UUID, body: WithdrawalRequest, principal: Citizen):
    """Ask the dispatchers to withdraw your report (for example a false alarm or a duplicate).

    This only records the request. The status does not change: a dispatcher decides whether to
    reject or close the report, because closing is always a human decision. Allowed before dispatch.
    """
    reason = "Reporter asked to withdraw this report" + (f": {body.reason.strip()}" if body.reason and body.reason.strip() else "")
    with db.transaction() as conn:
        _own_incident_status(conn, incident_id, principal.user_id)
        status = conn.execute(
            "SELECT status FROM incidents WHERE incident_id = %s FOR UPDATE", (incident_id,)
        ).fetchone()["status"]
        if status not in _WITHDRAWABLE:
            raise conflict("NOT_WITHDRAWABLE", "Help has already been sent or the report is closed, so it cannot be withdrawn here")
        if conn.execute(
            "SELECT 1 FROM incident_status_history WHERE incident_id = %s AND reason LIKE 'Reporter asked to withdraw%%'",
            (incident_id,),
        ).fetchone():
            raise conflict("ALREADY_REQUESTED", "You have already asked to withdraw this report")
        conn.execute(
            """
            INSERT INTO incident_status_history (incident_id, from_status, to_status, changed_by, reason)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (incident_id, status, status, principal.user_id, reason),
        )
        conn.execute("UPDATE incidents SET version = version + 1, updated_at = now() WHERE incident_id = %s", (incident_id,))
        audit.record(
            conn, actor=principal, action="WITHDRAWAL_REQUESTED", entity_type="incident", entity_id=incident_id,
            rationale=reason, ip=principal.ip,
        )
    return {"incident_id": incident_id, "status": status, "withdrawal_requested": True}


# --------------------------------------------------------------------------- account (profile, password)

_LANGUAGES = ("en", "hi", "gu")


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    preferred_language: Literal["en", "hi", "gu"] | None = None
    email_alerts: bool | None = None
    sms_alerts: bool | None = None

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Name must not be blank")
        return value

    @field_validator("phone")
    @classmethod
    def _valid_phone(cls, value: str | None) -> str | None:
        if value is not None and value.strip() and not _PHONE_RE.fullmatch(value.strip()):
            raise ValueError("Enter a valid phone number with the country code, for example +91 followed by 10 digits")
        return value


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


_NO_PASSWORD_MESSAGE = (
    "Your account uses Google sign-in and has no password yet. Set one with Forgot password on the sign-in page "
    "(the link goes to your Google email), then try again."
)


def _require_password_set(row: dict | None) -> None:
    """A Google-only account has no password to confirm with: point it to the reset link instead of 'wrong password'."""
    if row is not None and row["password_hash"] is None:
        raise conflict("NO_PASSWORD_SET", _NO_PASSWORD_MESSAGE)


def _profile_body(row: dict) -> dict:
    prefs = row["alert_preferences"] or {}
    return {
        "user_id": row["user_id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "preferred_language": row["preferred_language"] or "en",
        # In-app notifications are the source of truth and cannot be turned off.
        "alerts": {"in_app": True, "email": bool(prefs.get("email", True)), "sms": bool(prefs.get("sms", False))},
        "created_at": row["created_at"],
        # False for an account created with Google sign-in that never set a password.
        "has_password": bool(row.get("has_password", True)),
    }


@router.get("/me/profile")
def my_profile(principal: Citizen):
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT user_id, email, full_name, phone, preferred_language, alert_preferences, created_at, "
            "(SELECT a.password_hash IS NOT NULL FROM user_auth a WHERE a.user_id = users.user_id) AS has_password "
            "FROM users WHERE user_id = %s",
            (principal.user_id,),
        ).fetchone()
    if row is None:
        raise not_found("Account")
    return _profile_body(row)


@router.patch("/me/profile", dependencies=[rate_limit("profile", 30, 3600)])
def update_my_profile(body: ProfileUpdate, principal: Citizen):
    """Change your own name, phone, language or alert preferences. The email address is your sign-in identity and is not editable here."""
    with db.transaction() as conn:
        before = conn.execute(
            "SELECT user_id, email, full_name, phone, preferred_language, alert_preferences, created_at "
            "FROM users WHERE user_id = %s FOR UPDATE",
            (principal.user_id,),
        ).fetchone()
        if before is None:
            raise not_found("Account")
        prefs = dict(before["alert_preferences"] or {})
        if body.email_alerts is not None:
            prefs["email"] = body.email_alerts
        if body.sms_alerts is not None:
            prefs["sms"] = body.sms_alerts
        prefs["in_app"] = True
        phone = before["phone"] if body.phone is None else (body.phone.strip() or None)
        after = conn.execute(
            """
            UPDATE users SET full_name = %s, phone = %s, preferred_language = %s, alert_preferences = %s::jsonb
            WHERE user_id = %s
            RETURNING user_id, email, full_name, phone, preferred_language, alert_preferences, created_at,
                      (SELECT a.password_hash IS NOT NULL FROM user_auth a WHERE a.user_id = users.user_id) AS has_password
            """,
            (
                body.full_name.strip() if body.full_name else before["full_name"],
                phone,
                body.preferred_language or before["preferred_language"] or "en",
                json.dumps(prefs),
                principal.user_id,
            ),
        ).fetchone()
        audit.record(
            conn,
            actor=principal,
            action="PROFILE_UPDATED",
            entity_type="user",
            entity_id=principal.user_id,
            rationale="Citizen updated their profile",
            before={"preferred_language": before["preferred_language"], "alerts": _profile_body(before)["alerts"]},
            after={"preferred_language": after["preferred_language"], "alerts": _profile_body(after)["alerts"]},
            ip=principal.ip,
        )
    return _profile_body(after)


@router.post("/me/password", dependencies=[rate_limit("password-change", 10, 900)])
def change_my_password(body: PasswordChange, principal: Citizen):
    """Change your password. Every signed-in session, including this one, is ended so you sign in again."""
    check_password_policy(body.new_password)
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT password_hash FROM user_auth WHERE user_id = %s FOR UPDATE", (principal.user_id,)
        ).fetchone()
        _require_password_set(row)
        wrong_current = row is None or not security.verify_password(row["password_hash"], body.current_password)
    if wrong_current:
        # Audited in its own transaction: raising inside the one above would roll the audit row back.
        audit.record_standalone(
            actor=principal, action="PASSWORD_CHANGE_FAILED", entity_type="user", entity_id=principal.user_id,
            result="FAILURE", rationale="Wrong current password", ip=principal.ip,
        )
        raise ApiError(400, "INVALID_CURRENT_PASSWORD", "Your current password is not correct")
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT password_hash FROM user_auth WHERE user_id = %s FOR UPDATE", (principal.user_id,)
        ).fetchone()
        if security.verify_password(row["password_hash"], body.new_password):
            raise ApiError(422, "PASSWORD_UNCHANGED", "Choose a password different from your current one")
        conn.execute(
            """
            UPDATE user_auth
            SET password_hash = %s, token_version = token_version + 1, password_changed_at = now(),
                failed_login_count = 0, locked_until = NULL
            WHERE user_id = %s
            """,
            (security.hash_password(body.new_password), principal.user_id),
        )
        audit.record(
            conn, actor=principal, action="PASSWORD_CHANGED", entity_type="user",
            entity_id=principal.user_id, rationale="Citizen changed their password", ip=principal.ip,
        )
    return {"changed": True, "sign_in_required": True}


class AccountDeletion(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@router.post("/me/account/deletion", dependencies=[rate_limit("account-deletion", 5, 3600)])
def delete_my_account(body: AccountDeletion, principal: Citizen):
    """Delete your account: personal details are erased and every session ends.

    Reports you filed stay on record for the response audit trail but no longer link to a name,
    email or phone number, and your photos are deleted. Refused while a report of yours is still open,
    so an emergency is never left without a contact.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT password_hash FROM user_auth WHERE user_id = %s FOR UPDATE", (principal.user_id,)
        ).fetchone()
        _require_password_set(row)
        wrong = row is None or not security.verify_password(row["password_hash"], body.password)
    if wrong:
        audit.record_standalone(
            actor=principal, action="ACCOUNT_DELETION_FAILED", entity_type="user", entity_id=principal.user_id,
            result="FAILURE", rationale="Wrong password", ip=principal.ip,
        )
        raise ApiError(400, "INVALID_CURRENT_PASSWORD", "Your password is not correct")
    with db.transaction() as conn:
        open_reports = conn.execute(
            "SELECT COUNT(*) AS n FROM incidents WHERE reporter_id = %s AND status NOT IN ('RESOLVED', 'CLOSED', 'REJECTED')",
            (principal.user_id,),
        ).fetchone()["n"]
        if open_reports:
            raise conflict("OPEN_REPORTS", f"You still have {open_reports} open report(s). Wait until they are resolved or ask to withdraw them first.")
        conn.execute(
            "DELETE FROM evidence_blobs WHERE evidence_id IN (SELECT evidence_id FROM evidence_files WHERE uploaded_by = %s)",
            (principal.user_id,),
        )
        conn.execute("UPDATE evidence_files SET scan_state = 'REJECTED' WHERE uploaded_by = %s", (principal.user_id,))
        conn.execute("DELETE FROM notifications WHERE user_id = %s", (principal.user_id,))
        conn.execute(
            """
            UPDATE users SET email = %s, full_name = 'Deleted user', phone = NULL, address_line = NULL, city = NULL,
                state = NULL, postal_code = NULL, preferred_language = 'en', status = 'DISABLED'
            WHERE user_id = %s
            """,
            (f"deleted-{principal.user_id}@deleted.invalid", principal.user_id),
        )
        conn.execute(
            "UPDATE user_auth SET password_hash = %s, token_version = token_version + 1, mfa_enabled = FALSE, mfa_secret = NULL "
            "WHERE user_id = %s",
            (security.hash_password(uuid.uuid4().hex + "Aa1!"), principal.user_id),
        )
        audit.record(
            conn, actor=principal, action="ACCOUNT_DELETED", entity_type="user", entity_id=principal.user_id,
            rationale="Citizen deleted their account; personal details erased", ip=principal.ip,
        )
    return {"deleted": True, "sign_in_required": True}


@router.post("/me/notifications/read-all", status_code=200)
def mark_all_notifications_read(principal: Citizen):
    with db.transaction() as conn:
        updated = conn.execute(
            """
            UPDATE notifications SET read_at = now(), status = 'READ'
            WHERE user_id = %s AND channel = 'IN_APP' AND read_at IS NULL
            """,
            (principal.user_id,),
        ).rowcount
    return {"marked_read": updated}


@router.get("/me/notifications")
def my_notifications(principal: Citizen, page: Page):
    with db.transaction() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND channel = 'IN_APP'",
            (principal.user_id,),
        ).fetchone()["n"]
        items = conn.execute(
            """
            SELECT notification_id, event_code, title, body, related_id, created_at, read_at
            FROM notifications WHERE user_id = %s AND channel = 'IN_APP'
            ORDER BY created_at DESC LIMIT %s OFFSET %s
            """,
            (principal.user_id, page.limit, page.offset),
        ).fetchall()
    return page_body(items, total, page)


@router.post("/me/notifications/{notification_id}/read", status_code=200)
def mark_notification_read(notification_id: uuid.UUID, principal: Citizen):
    with db.transaction() as conn:
        row = conn.execute(
            """
            UPDATE notifications SET read_at = COALESCE(read_at, now()), status = 'READ'
            WHERE notification_id = %s AND user_id = %s RETURNING notification_id, read_at
            """,
            (notification_id, principal.user_id),
        ).fetchone()
        if row is None:
            raise not_found("Notification")
    return row
