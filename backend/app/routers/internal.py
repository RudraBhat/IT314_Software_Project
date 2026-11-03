"""Internal automated maintenance and scheduled ingestion endpoints (S2-09, S2-16).

Protected via INGEST_TOKEN constant-time validation and PostgreSQL advisory
locks to safely support cron-job.org and GitHub Actions backup triggers.
"""

from __future__ import annotations

import hmac
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import db
from app.config import get_settings
from app.services.ingest.sachet import SachetAdapter

logger = logging.getLogger("drch.ingest")

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])

# Arbitrary constant advisory lock for ingestion scheduler
_INGEST_LOCK = 314_0020


class IngestRunResponse(BaseModel):
    run_id: str
    source: str
    items_fetched: int
    items_stored: int
    status: str
    message: str | None = None


def _sync_run_ingest(source: str, run_id: uuid.UUID) -> IngestRunResponse:
    settings = get_settings()
    src = source.upper()

    # Check if adapter is requested
    if src not in ("ALL", "SACHET"):
        return IngestRunResponse(
            run_id=str(run_id),
            source=src,
            items_fetched=0,
            items_stored=0,
            status="NOT_IMPLEMENTED",
            message=f"No ingestion adapters are installed yet for source '{source}'.",
        )

    # Check if SACHET feed URL is configured
    if not settings.sachet_feed_url:
        logger.warning("Ingestion trigger ran but no adapters are enabled (source=%s, run_id=%s)", src, run_id)
        return IngestRunResponse(
            run_id=str(run_id),
            source=src,
            items_fetched=0,
            items_stored=0,
            status="NOT_IMPLEMENTED",
            message="No ingestion adapters are installed yet; nothing was fetched.",
        )

    adapter = SachetAdapter(feed_url=settings.sachet_feed_url)

    if not settings.database_url:
        try:
            items = adapter.fetch()
            return IngestRunResponse(
                run_id=str(run_id),
                source=src,
                items_fetched=len(items),
                items_stored=len(items),
                status="SUCCESS",
            )
        except Exception as exc:
            logger.exception("Ingestion failed in DB-free mode")
            return IngestRunResponse(
                run_id=str(run_id),
                source=src,
                items_fetched=0,
                items_stored=0,
                status="FAILED",
                message=str(exc),
            )

    with db.transaction() as conn:
        locked = conn.execute(
            "SELECT pg_try_advisory_xact_lock(%s) AS ok", (_INGEST_LOCK,)
        ).fetchone()

        if not locked["ok"]:
            logger.info("Ingestion run skipped; concurrent lock active")
            return IngestRunResponse(
                run_id=str(run_id),
                source=src,
                items_fetched=0,
                items_stored=0,
                status="SKIPPED",
                message="Ingestion already active in concurrent process",
            )

        # 1. Record run start as RUNNING
        conn.execute(
            """
            INSERT INTO ingest_runs (run_id, source, status, items_fetched, items_stored, started_at)
            VALUES (%s, %s, 'RUNNING', 0, 0, now())
            """,
            (run_id, src),
        )

    # 2. Fetch items
    try:
        items = adapter.fetch()
    except Exception as exc:
        logger.exception("Ingestion failed during fetch for source %s", src)
        with db.transaction() as conn:
            conn.execute(
                """
                UPDATE ingest_runs
                SET status = 'FAILED', error_message = %s, finished_at = now()
                WHERE run_id = %s
                """,
                (str(exc), run_id),
            )
        return IngestRunResponse(
            run_id=str(run_id),
            source=src,
            items_fetched=0,
            items_stored=0,
            status="FAILED",
            message=str(exc),
        )

    # 3. Store items
    items_fetched = len(items)
    items_stored = 0
    with db.transaction() as conn:
        for it in items:
            conn.execute(
                """
                INSERT INTO external_alerts (
                    source, source_uid, event_type, severity, area_text,
                    latitude, longitude, geom, is_fallback, effective_at, expires_at, raw_payload
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    CASE WHEN %s IS NOT NULL AND %s IS NOT NULL
                         THEN ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                         ELSE NULL END,
                    FALSE, %s, %s, %s::jsonb
                )
                ON CONFLICT (source, source_uid) DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    severity = EXCLUDED.severity,
                    area_text = EXCLUDED.area_text,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    geom = EXCLUDED.geom,
                    effective_at = EXCLUDED.effective_at,
                    expires_at = EXCLUDED.expires_at,
                    raw_payload = EXCLUDED.raw_payload
                """,
                (
                    it["source"],
                    it["source_uid"],
                    it["event_type"],
                    it["severity"],
                    it["area_text"],
                    it["latitude"],
                    it["longitude"],
                    it["latitude"],
                    it["longitude"],
                    it["longitude"],
                    it["latitude"],
                    it["effective_at"],
                    it["expires_at"],
                    json.dumps(it["raw_payload"]),
                ),
            )
            items_stored += 1

        conn.execute(
            """
            UPDATE ingest_runs
            SET status = 'SUCCESS', items_fetched = %s, items_stored = %s, finished_at = now()
            WHERE run_id = %s
            """,
            (items_fetched, items_stored, run_id),
        )

    return IngestRunResponse(
        run_id=str(run_id),
        source=src,
        items_fetched=items_fetched,
        items_stored=items_stored,
        status="SUCCESS",
    )


@router.post("/ingest/run", response_model=IngestRunResponse)
async def run_ingest(
    source: Annotated[str, Query(description="Ingestion source name")] = "ALL",
    x_ingest_token: Annotated[str | None, Header(alias="X-Ingest-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
):
    """Trigger scheduled background ingestion of official disaster feeds.

    Accepts X-Ingest-Token or Authorization: Bearer <token>.
    Guarded by constant-time verification against INGEST_TOKEN and
    PostgreSQL advisory locking to prevent concurrent runs.
    """
    settings = get_settings()
    expected_token = settings.ingest_token

    # Extract provided token
    provided_token = None
    if x_ingest_token:
        provided_token = x_ingest_token.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization[7:].strip()

    if not expected_token or not provided_token or not hmac.compare_digest(provided_token, expected_token):
        logger.warning("Rejected unauthenticated or invalid ingestion trigger attempt")
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: invalid or missing ingestion token",
        )

    run_id = uuid.uuid4()
    return await run_in_threadpool(_sync_run_ingest, source, run_id)
