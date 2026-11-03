"""Runs registered alert and signal adapters and keeps an audit of each run."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from app import db
from app.config import get_settings
from app.services.ingest.base import Adapter
from app.services.ingest.sachet import SachetAdapter
from app.services.ingest.signals import ReplaySignalAdapter
from app.services.ingest.usgs import UsgsAdapter

logger = logging.getLogger("drch.ingest")
ALLOWED_TRIAGE_LABELS = {"CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING", "OTHER"}


@dataclass
class IngestRunResult:
    run_id: str
    source: str
    items_fetched: int
    items_stored: int
    status: str
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def registered_adapters(settings=None) -> list[Adapter]:
    settings = settings or get_settings()
    return [
        SachetAdapter(settings.sachet_feed_url),
        UsgsAdapter(settings.usgs_feed_url),
        ReplaySignalAdapter(settings.social_replay_file),
    ]


def _prelabel(text: str, settings=None) -> tuple[str | None, float | None]:
    """Call the advisory triage service without sending identities or location data."""
    settings = settings or get_settings()
    url = settings.ai_triage_url
    if not url:
        return None, None
    try:
        headers = {"Authorization": f"Bearer {settings.ai_triage_token}"} if settings.ai_triage_token else {}
        response = httpx.post(
            url,
            json={"description": text, "reported_scenario": None, "details": {}},
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()
        raw = response.json()
        label = str(raw.get("scenario", "")).strip().upper().replace(" ", "_")
        confidence = float(raw.get("confidence"))
        if label not in ALLOWED_TRIAGE_LABELS or not 0 <= confidence <= 1:
            logger.warning("Triage returned a label outside the allowed set; discarded")
            return None, None
        return label, confidence
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Signal pre-label unavailable (%s); storing without a label", _safe_error_message(exc))
        return None, None


def _safe_error_message(exc: Exception) -> str:
    """Keep feed URLs, response bodies and source text out of run history."""
    if isinstance(exc, httpx.HTTPStatusError):
        host = urlsplit(str(exc.request.url)).hostname or "configured feed"
        return f"HTTP {exc.response.status_code} from {host}"
    if isinstance(exc, httpx.TimeoutException):
        return "Source request timed out"
    if isinstance(exc, httpx.RequestError):
        host = urlsplit(str(exc.request.url)).hostname if exc.request else None
        return f"Source request failed ({host or 'configured feed'})"
    if isinstance(exc, FileNotFoundError):
        return "Replay fixture file was not found"
    return f"Ingestion failed ({type(exc).__name__})"


def _store_alerts(items: list[dict[str, Any]]) -> int:
    stored = 0
    with db.transaction() as conn:
        for item in items:
            conn.execute(
                """
                INSERT INTO external_alerts (
                    source, source_uid, event_type, severity, urgency, certainty, language,
                    area_text, latitude, longitude, geom, is_fallback,
                    effective_at, expires_at, raw_payload
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s IS NOT NULL AND %s IS NOT NULL
                         THEN ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography ELSE NULL END,
                    %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (source, source_uid) DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    severity = EXCLUDED.severity,
                    urgency = EXCLUDED.urgency,
                    certainty = EXCLUDED.certainty,
                    language = EXCLUDED.language,
                    area_text = EXCLUDED.area_text,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    geom = EXCLUDED.geom,
                    is_fallback = EXCLUDED.is_fallback,
                    effective_at = EXCLUDED.effective_at,
                    expires_at = EXCLUDED.expires_at,
                    raw_payload = EXCLUDED.raw_payload
                """,
                (
                    item["source"], item["source_uid"], item["event_type"], item["severity"],
                    item.get("urgency"), item.get("certainty"), item.get("language"),
                    item.get("area_text"), item.get("latitude"), item.get("longitude"),
                    item.get("latitude"), item.get("longitude"), item.get("longitude"), item.get("latitude"),
                    bool(item.get("is_fallback", False)), item.get("effective_at"), item.get("expires_at"),
                    json.dumps(item.get("raw_payload") or {}),
                ),
            )
            stored += 1
    return stored


def _store_signals(items: list[dict[str, Any]], settings=None) -> int:
    stored = 0
    for item in items:
        label, confidence = _prelabel(item["content_text"], settings)
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO source_signals (
                    source, source_uid, content_text, language, location_text, latitude, longitude,
                    geom, ai_label, ai_confidence, is_simulated, raw_payload
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s IS NOT NULL AND %s IS NOT NULL
                         THEN ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography ELSE NULL END,
                    %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (source, source_uid) DO UPDATE SET
                    content_text = EXCLUDED.content_text,
                    language = EXCLUDED.language,
                    location_text = EXCLUDED.location_text,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    geom = EXCLUDED.geom,
                    ai_label = COALESCE(EXCLUDED.ai_label, source_signals.ai_label),
                    ai_confidence = COALESCE(EXCLUDED.ai_confidence, source_signals.ai_confidence),
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = now()
                """,
                (
                    item["source"], item["source_uid"], item["content_text"], item.get("language"),
                    item.get("location_text"), item.get("latitude"), item.get("longitude"),
                    item.get("latitude"), item.get("longitude"), item.get("longitude"), item.get("latitude"),
                    label, confidence, bool(item.get("is_simulated", False)),
                    json.dumps(item.get("raw_payload") or {}),
                ),
            )
        stored += 1
    return stored


def _run_adapter(adapter: Adapter, settings=None) -> IngestRunResult:
    run_id = uuid.uuid4()
    has_db = bool((settings or get_settings()).database_url)
    if has_db:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO ingest_runs (run_id, source, status, started_at) VALUES (%s, %s, 'RUNNING', now())",
                (run_id, adapter.name),
            )
    configured = (settings or get_settings())
    disabled = (adapter.name == "SACHET" and not configured.sachet_feed_url) or (
        adapter.name == "USGS" and not configured.usgs_feed_url
    )
    if disabled:
        message = f"{adapter.name} feed URL is not configured."
        if has_db:
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE ingest_runs SET status = 'SKIPPED', error_message = %s, finished_at = now() WHERE run_id = %s",
                    (message, run_id),
                )
        return IngestRunResult(str(run_id), adapter.name, 0, 0, "SKIPPED", message)
    try:
        items = adapter.fetch()
        if has_db:
            stored = _store_signals(items, settings) if adapter.kind == "signal" else _store_alerts(items)
        else:
            stored = 0
        result = IngestRunResult(str(run_id), adapter.name, len(items), stored,
                                 "SUCCESS" if has_db else "PREVIEW")
        if has_db:
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE ingest_runs SET status = 'SUCCESS', items_fetched = %s, items_stored = %s, finished_at = now() WHERE run_id = %s",
                    (result.items_fetched, result.items_stored, run_id),
                )
        return result
    except Exception as exc:  # one feed failure must not stop other sources
        safe_message = _safe_error_message(exc)
        logger.error("Ingestion failed for source %s: %s", adapter.name, safe_message)
        if has_db:
            try:
                with db.transaction() as conn:
                    conn.execute(
                        "UPDATE ingest_runs SET status = 'FAILED', error_message = %s, finished_at = now() WHERE run_id = %s",
                        (safe_message, run_id),
                    )
            except Exception:
                logger.exception("Could not record failed run for source %s", adapter.name)
        return IngestRunResult(str(run_id), adapter.name, 0, 0, "FAILED", safe_message)


def run_ingestion(source: str = "ALL", settings=None) -> list[dict[str, Any]]:
    source = source.strip().upper()
    settings = settings or get_settings()
    adapters = registered_adapters(settings)
    if source != "ALL":
        adapters = [adapter for adapter in adapters if adapter.name == source]
        if not adapters:
            return [IngestRunResult(str(uuid.uuid4()), source, 0, 0, "NOT_CONFIGURED",
                                    f"No adapter is configured for '{source}'.").as_dict()]
    return [_run_adapter(adapter, settings).as_dict() for adapter in adapters]
