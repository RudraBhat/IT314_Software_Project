"""Dispatcher ingestion controls and per-source health summary."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app import db
from app.auth import DMUser
from app.config import get_settings
from app.errors import ApiError
from app.services.ingestion import run_ingestion

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _require_operator(user: DMUser) -> None:
    if not (user.has("DISPATCH") or user.has("SUPERVISOR")):
        raise ApiError(403, "PERMISSION_REQUIRED", "The dispatch or supervisor permission is required")


@router.get("/health")
def ingestion_health(user: DMUser) -> dict[str, Any]:
    _require_operator(user)
    if not get_settings().database_url:
        return {"sources": [], "history_available": False}
    with db.transaction() as conn:
        rows = conn.execute(
            """
            WITH last_run AS (
                SELECT DISTINCT ON (source) source, status, items_fetched, items_stored,
                       started_at, finished_at, error_message
                FROM ingest_runs ORDER BY source, started_at DESC
            ), rollup AS (
                SELECT source,
                       COUNT(*) FILTER (WHERE started_at >= now() - interval '24 hours') AS runs_24h,
                       COUNT(*) FILTER (WHERE started_at >= now() - interval '24 hours' AND status = 'SUCCESS') AS successes_24h,
                       COUNT(*) FILTER (WHERE started_at >= now() - interval '24 hours' AND status = 'FAILED') AS failures_24h
                FROM ingest_runs GROUP BY source
            ), last_error AS (
                SELECT DISTINCT ON (source) source, error_message, started_at
                FROM ingest_runs WHERE status = 'FAILED' ORDER BY source, started_at DESC
            )
            SELECT l.source, l.status, l.items_fetched, l.items_stored, l.started_at, l.finished_at,
                   r.runs_24h, r.successes_24h, r.failures_24h, e.error_message AS last_error,
                   e.started_at AS last_error_at
            FROM last_run l
            LEFT JOIN rollup r USING (source)
            LEFT JOIN last_error e USING (source)
            ORDER BY l.source
            """
        ).fetchall()
    return {"sources": rows, "history_available": True}


@router.post("/poll")
async def poll_now(user: DMUser) -> list[dict[str, Any]]:
    _require_operator(user)
    return await run_in_threadpool(run_ingestion, "ALL")
