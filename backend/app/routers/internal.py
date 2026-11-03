"""Token-protected cron endpoint for scheduled ingestion."""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.services.ingestion import run_ingestion

logger = logging.getLogger("drch.ingest")
router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


class IngestRunResponse(BaseModel):
    run_id: str
    source: str
    items_fetched: int
    items_stored: int
    status: str
    message: str | None = None


@router.post("/ingest/run", response_model=IngestRunResponse | list[IngestRunResponse])
async def run_ingest(
    source: Annotated[str, Query(description="Ingestion source name or ALL")] = "ALL",
    x_ingest_token: Annotated[str | None, Header(alias="X-Ingest-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
):
    """Run all feeds or a named source; accepts X-Ingest-Token or a bearer token."""
    expected_token = get_settings().ingest_token
    provided_token = x_ingest_token.strip() if x_ingest_token else None
    if not provided_token and authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization[7:].strip()
    if not expected_token or not provided_token or not hmac.compare_digest(provided_token, expected_token):
        logger.warning("Rejected unauthenticated or invalid ingestion trigger attempt")
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing ingestion token")

    results = await run_in_threadpool(run_ingestion, source, get_settings())
    if source.strip().upper() != "ALL" and results:
        return results[0]
    return results
