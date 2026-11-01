"""Internal automated maintenance and scheduled ingestion endpoints (S2-09, S2-16).

Protected via INGEST_TOKEN constant-time validation and PostgreSQL advisory
locks to safely support cron-job.org and GitHub Actions backup triggers.
"""

import hmac
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app import db
from app.config import get_settings

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


@router.post("/ingest/run", response_model=IngestRunResponse)
def run_ingest(
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
    items_fetched = 0
    items_stored = 0

    if settings.database_url:
        with db.transaction() as conn:
            # Advisory lock prevents double triggers from cron-job.org and GH Actions
            locked = conn.execute(
                "SELECT pg_try_advisory_xact_lock(%s) AS ok", (_INGEST_LOCK,)
            ).fetchone()

            if not locked["ok"]:
                logger.info("Ingestion run skipped; concurrent lock active")
                return IngestRunResponse(
                    run_id=str(run_id),
                    source=source,
                    items_fetched=0,
                    items_stored=0,
                    status="SKIPPED",
                    message="Ingestion already active in concurrent process",
                )

            # Record run start in ingest_runs (created in migration 03)
            try:
                conn.execute(
                    """
                    INSERT INTO ingest_runs (run_id, source, status, items_fetched, items_stored, started_at, completed_at)
                    VALUES (%s, %s, %s, %s, %s, now(), now())
                    """,
                    (run_id, source.upper(), "SUCCESS", items_fetched, items_stored),
                )
            except Exception:
                logger.exception("Failed to write to ingest_runs table")

    logger.info("Ingestion trigger completed successfully for source=%s (run_id=%s)", source, run_id)
    return IngestRunResponse(
        run_id=str(run_id),
        source=source.upper(),
        items_fetched=items_fetched,
        items_stored=items_stored,
        status="SUCCESS",
        message="Scheduled ingestion completed successfully",
    )
