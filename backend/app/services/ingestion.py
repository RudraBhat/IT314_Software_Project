"""Runs registered alert and signal adapters and keeps an audit of each run."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from app import db
from app.config import get_settings
from app.services.ai_provider import scrub_pii
from app.services.ingest.base import Adapter
from app.services.ingest.bluesky import BlueskySearchAdapter
from app.services.ingest.news import GoogleNewsAdapter
from app.services.ingest.sachet import SachetAdapter
from app.services.ingest.signals import ReplaySignalAdapter

logger = logging.getLogger("drch.ingest")
ALLOWED_TRIAGE_LABELS = {"CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING", "OTHER"}
CLASSIFIER_LABELS = {
    "fire": "Fire",
    "earthquake": "Earthquake",
    "cyclone": "Cyclone",
    "flood": "Flood",
    "non_disaster": "Non-Disaster",
}
CLASSIFIER_SCENARIOS = {
    "cyclone": "CYCLONE",
    "flood": "URBAN_FLOODING",
    # Generic fire does not establish the project's narrower industrial-fire scenario.
    "fire": None,
    "earthquake": None,
    "non_disaster": None,
}
SOCIAL_SIGNAL_SOURCES = {"BLUESKY", "GNEWS"}
MAX_SOCIAL_TRIAGE_PER_RUN = 50
# Shared by the in-process worker, the protected manual endpoint, and the scheduled
# GitHub Actions trigger. A session lock spans network fetches and writes, unlike a
# transaction lock that would be released between the adapter's short DB transactions.
_INGESTION_LOCK = 314_0041
SOCIAL_POLL_OVERLAP = timedelta(minutes=5)


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
        ReplaySignalAdapter(settings.social_replay_file),
        GoogleNewsAdapter(),
        BlueskySearchAdapter(settings.bluesky_search_url),
    ]


def _disabled_reason(adapter: Adapter, settings) -> str | None:
    if adapter.name == "SACHET" and not settings.sachet_feed_url:
        return "SACHET feed URL is not configured."
    if adapter.name == "GNEWS" and not settings.news_rss_enabled:
        return "GNEWS is disabled (set NEWS_RSS_ENABLED=true)."
    if adapter.name == "BLUESKY" and not settings.bluesky_search_enabled:
        return "BLUESKY is disabled (set BLUESKY_SEARCH_ENABLED=true)."
    if adapter.name == "REPLAY" and not settings.social_replay_enabled:
        return "REPLAY is disabled (simulated fixture; set SOCIAL_REPLAY_ENABLED=true)."
    return None


def enabled_adapters(settings=None) -> list[Adapter]:
    """Registered adapters that are switched on (not skipped by configuration)."""
    settings = settings or get_settings()
    return [adapter for adapter in registered_adapters(settings) if _disabled_reason(adapter, settings) is None]


def _prelabel(text: str, settings=None) -> tuple[str | None, float | None, dict[str, Any] | None]:
    """Call the advisory triage service without sending identities or location data."""
    settings = settings or get_settings()
    url = settings.ai_triage_url
    if not url:
        return None, None, None
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
            return None, None, None
        priority = str(raw.get("priority", "")).strip().upper()
        if priority not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            priority = None
        uncertainty = raw.get("uncertainty")
        details: dict[str, Any] = {
            "model": str(raw.get("model", ""))[:100] or None,
            "priority": priority,
            "uncertainty": str(uncertainty)[:1000] if uncertainty else None,
            "factors": [],
        }
        raw_factors = raw.get("factors") if isinstance(raw.get("factors"), list) else []
        for factor in raw_factors[:20]:
            if not isinstance(factor, dict):
                continue
            clean_factor = {
                "name": str(factor.get("name", ""))[:100],
                "detail": str(factor.get("detail", ""))[:300],
            }
            try:
                weight = float(factor.get("weight"))
            except (TypeError, ValueError):
                weight = None
            if weight is not None and 0 <= weight <= 1:
                clean_factor["weight"] = weight
            details["factors"].append(clean_factor)
        return label, confidence, details
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Signal pre-label unavailable (%s); storing without a label", _safe_error_message(exc))
        return None, None, None


def _classify_with_indicbert(
    text: str, settings=None,
) -> tuple[str | None, float | None, dict[str, Any] | None]:
    """Call the configured multilingual text classifier and keep its raw class for review."""
    settings = settings or get_settings()
    url = getattr(settings, "disaster_classifier_url", None)
    if not url:
        return None, None, None
    try:
        response = httpx.post(
            url,
            json={"text": scrub_pii(text)},
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise TypeError("classifier response was not an object")

        raw_prediction = str(raw.get("prediction", "")).strip()
        prediction_key = raw_prediction.casefold().replace("-", "_").replace(" ", "_")
        prediction = CLASSIFIER_LABELS.get(prediction_key)
        confidence_value = raw.get("confidence")
        if prediction is None or isinstance(confidence_value, bool):
            raise ValueError("classifier response had an unknown label or invalid confidence")
        confidence = float(confidence_value)
        if not 0 <= confidence <= 1:
            raise ValueError("classifier confidence was outside [0, 1]")

        probabilities: dict[str, float] = {}
        raw_probabilities = raw.get("probabilities")
        if raw_probabilities is not None:
            if not isinstance(raw_probabilities, dict) or len(raw_probabilities) > len(CLASSIFIER_LABELS):
                raise ValueError("classifier probabilities were malformed")
            for key, value in raw_probabilities.items():
                normalized_key = str(key).strip().casefold().replace("-", "_").replace(" ", "_")
                canonical = CLASSIFIER_LABELS.get(normalized_key)
                if canonical is None or isinstance(value, bool):
                    raise ValueError("classifier probabilities had an unknown class or value")
                score = float(value)
                if not 0 <= score <= 1:
                    raise ValueError("classifier probability was outside [0, 1]")
                probabilities[canonical] = round(score, 6)

        scenario = CLASSIFIER_SCENARIOS[prediction_key]
        threshold = getattr(settings, "ai_low_confidence_threshold", 0.6)
        low_confidence = confidence < threshold
        suggested_scenario = scenario if scenario and not low_confidence else None
        uncertainty = None
        if low_confidence:
            uncertainty = "Classifier confidence is below the review threshold; choose a scenario manually."
        elif prediction_key == "fire":
            uncertainty = "The model's generic Fire class does not confirm an industrial fire; review before choosing a scenario."
        elif prediction_key == "earthquake":
            uncertainty = "Earthquake is outside the platform's supported scenarios; dispatcher review is required."
        elif prediction_key == "non_disaster":
            uncertainty = "The model predicted Non-Disaster. Keep pending for human review; it was not dismissed automatically."

        details: dict[str, Any] = {
            "model": "indicbert-disaster-api",
            "priority": None,
            "uncertainty": uncertainty,
            "factors": [{"name": "disaster_classifier", "detail": prediction, "weight": round(confidence, 6)}],
            "classification": {
                "prediction": prediction,
                "is_disaster": prediction_key != "non_disaster",
                "confidence": round(confidence, 6),
                "probabilities": probabilities,
            },
        }
        return suggested_scenario, round(confidence, 6), details
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Multilingual signal classifier unavailable (%s); signal remains for human review",
                       _safe_error_message(exc))
        return None, None, None


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


def _set_incremental_watermark(adapter: Adapter, settings) -> None:
    """Search Bluesky from the previous successful poll, with a small retry overlap."""
    if adapter.name != "BLUESKY" or not settings.database_url:
        return
    setter = getattr(adapter, "set_since", None)
    if not callable(setter):
        return
    with db.transaction() as conn:
        previous = conn.execute(
            """
            SELECT started_at FROM ingest_runs
            WHERE source = %s AND status = 'SUCCESS'
            ORDER BY started_at DESC LIMIT 1
            """,
            (adapter.name,),
        ).fetchone()
    setter(previous["started_at"] - SOCIAL_POLL_OVERLAP if previous else None)


def _triage_unprocessed_social_signals(sources: list[str], settings) -> int:
    """Classify a bounded queue of newly stored social signals, at most once per text version."""
    classifier_url = getattr(settings, "disaster_classifier_url", None)
    if not sources or not settings.database_url or not (classifier_url or settings.ai_triage_url):
        return 0
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT signal_id, content_text FROM source_signals
            WHERE source = ANY(%s) AND status = 'PENDING'
              AND ai_triage_attempted_at IS NULL AND ai_label IS NULL
            ORDER BY COALESCE(source_created_at, created_at), created_at
            LIMIT %s
            """,
            (sources, MAX_SOCIAL_TRIAGE_PER_RUN),
        ).fetchall()

    processed = 0
    for row in rows:
        if classifier_url:
            label, confidence, details = _classify_with_indicbert(row["content_text"], settings)
        else:
            label, confidence, details = _prelabel(row["content_text"], settings)
        with db.transaction() as conn:
            updated = conn.execute(
                """
                UPDATE source_signals
                SET ai_label = %s, ai_confidence = %s, ai_details = %s::jsonb,
                    ai_triage_attempted_at = now(), updated_at = now()
                WHERE signal_id = %s AND content_text = %s
                  AND status = 'PENDING' AND ai_triage_attempted_at IS NULL AND ai_label IS NULL
                """,
                (
                    label,
                    confidence,
                    json.dumps(details) if details is not None else None,
                    row["signal_id"],
                    row["content_text"],
                ),
            )
            if updated.rowcount > 0:
                processed += 1
    return processed


@contextmanager
def _ingestion_run_lock(settings) -> Iterator[bool]:
    """Prevent multiple schedulers or manual triggers from polling at the same time."""
    if not settings.database_url:
        # DB-free preview mode has no shared state to coordinate.
        yield True
        return

    with db.get_pool().connection(timeout=10.0) as conn:
        locked = False
        try:
            acquired = conn.execute(
                "SELECT pg_try_advisory_lock(%s) AS ok",
                (_INGESTION_LOCK,),
            ).fetchone()
            locked = bool(acquired and acquired.get("ok"))
            conn.commit()
            yield locked
        finally:
            if locked:
                try:
                    released = conn.execute(
                        "SELECT pg_advisory_unlock(%s) AS ok",
                        (_INGESTION_LOCK,),
                    ).fetchone()
                    conn.commit()
                    if not released or not released.get("ok"):
                        logger.error("Ingestion advisory lock was not held during release")
                except Exception:
                    # Discard a connection that might still own the session-level lock.
                    logger.exception("Could not release ingestion advisory lock; closing connection")
                    conn.close()


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
                    CASE WHEN %s::double precision IS NOT NULL AND %s::double precision IS NOT NULL
                         THEN ST_SetSRID(ST_MakePoint(%s::double precision, %s::double precision), 4326)::geography ELSE NULL::geography END,
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
    settings = settings or get_settings()
    stored = 0
    if items and items[0]["source"] in SOCIAL_SIGNAL_SOURCES:
        source = items[0]["source"]
        source_uids = [item["source_uid"] for item in items]
        with db.transaction() as conn:
            deleted_rows = conn.execute(
                "SELECT source_uid FROM deleted_social_signal_ids WHERE source = %s AND source_uid = ANY(%s)",
                (source, source_uids),
            ).fetchall()
        deleted_uids = {row["source_uid"] for row in deleted_rows}
        items = [item for item in items if item["source_uid"] not in deleted_uids]
    prelabels: dict[
        tuple[str, str, str],
        tuple[str | None, float | None, dict[str, Any] | None, datetime | None],
    ] = {}
    for item in items:
        source = item["source"]
        source_uid = item["source_uid"]
        content_text = item["content_text"]
        cache_key = (source, source_uid, content_text)

        if source in SOCIAL_SIGNAL_SOURCES:
            # Live social posts are first stored, then triaged from a bounded queue
            # after all configured sources have been polled.
            label = confidence = triage_details = triage_attempted_at = None
        elif cache_key in prelabels:
            label, confidence, triage_details, triage_attempted_at = prelabels[cache_key]
        else:
            label = confidence = triage_details = triage_attempted_at = None
            if settings.ai_triage_url:
                with db.transaction() as conn:
                    existing = conn.execute(
                        """
                        SELECT content_text, ai_label, ai_confidence, ai_details, ai_triage_attempted_at
                        FROM source_signals
                        WHERE source = %s AND source_uid = %s
                        """,
                        (source, source_uid),
                    ).fetchone()
                if existing and existing["content_text"] == content_text and (
                    existing.get("ai_triage_attempted_at") is not None or existing.get("ai_label") is not None
                ):
                    # A repeated poll must not send unchanged posts through the
                    # classifier again after an attempt. If triage was not configured
                    # on first ingest, a later configured run gets one first attempt.
                    label = str(existing["ai_label"]) if existing["ai_label"] is not None else None
                    confidence = (
                        float(existing["ai_confidence"])
                        if existing["ai_confidence"] is not None
                        else None
                    )
                    triage_details = existing.get("ai_details")
                    triage_attempted_at = existing.get("ai_triage_attempted_at")
                else:
                    result = _prelabel(content_text, settings)
                    label, confidence = result[0], result[1]
                    triage_details = result[2] if len(result) > 2 else None
                    triage_attempted_at = datetime.now(UTC)
            prelabels[cache_key] = (label, confidence, triage_details, triage_attempted_at)

        raw_payload = item.get("raw_payload") or {}
        location_precision = item.get("location_precision") or raw_payload.get("location_precision")
        if location_precision is None:
            location_precision = (
                "EXACT"
                if item.get("latitude") is not None and item.get("longitude") is not None
                else "NONE"
            )
        location_precision = str(location_precision).upper()
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO source_signals (
                    source, source_uid, content_text, language, location_text, latitude, longitude,
                    geom, ai_label, ai_confidence, is_simulated, raw_payload, source_created_at,
                    location_precision, ai_details, ai_triage_attempted_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s::double precision IS NOT NULL AND %s::double precision IS NOT NULL
                         THEN ST_SetSRID(ST_MakePoint(%s::double precision, %s::double precision), 4326)::geography ELSE NULL::geography END,
                    %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s
                )
                ON CONFLICT (source, source_uid) DO UPDATE SET
                    content_text = EXCLUDED.content_text,
                    language = EXCLUDED.language,
                    location_text = EXCLUDED.location_text,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    geom = EXCLUDED.geom,
                    ai_label = CASE
                        WHEN source_signals.content_text IS DISTINCT FROM EXCLUDED.content_text
                        THEN EXCLUDED.ai_label
                        ELSE COALESCE(EXCLUDED.ai_label, source_signals.ai_label)
                    END,
                    ai_confidence = CASE
                        WHEN source_signals.content_text IS DISTINCT FROM EXCLUDED.content_text
                        THEN EXCLUDED.ai_confidence
                        ELSE COALESCE(EXCLUDED.ai_confidence, source_signals.ai_confidence)
                    END,
                    raw_payload = EXCLUDED.raw_payload,
                    source_created_at = COALESCE(EXCLUDED.source_created_at, source_signals.source_created_at),
                    location_precision = EXCLUDED.location_precision,
                    ai_details = CASE
                        WHEN source_signals.content_text IS DISTINCT FROM EXCLUDED.content_text
                        THEN EXCLUDED.ai_details
                        ELSE COALESCE(EXCLUDED.ai_details, source_signals.ai_details)
                    END,
                    ai_triage_attempted_at = CASE
                        WHEN source_signals.content_text IS DISTINCT FROM EXCLUDED.content_text
                        THEN EXCLUDED.ai_triage_attempted_at
                        ELSE COALESCE(EXCLUDED.ai_triage_attempted_at, source_signals.ai_triage_attempted_at)
                    END,
                    updated_at = now()
                """,
                (
                    item["source"], item["source_uid"], item["content_text"], item.get("language"),
                    item.get("location_text"), item.get("latitude"), item.get("longitude"),
                    item.get("latitude"), item.get("longitude"), item.get("longitude"), item.get("latitude"),
                    label, confidence, bool(item.get("is_simulated", False)),
                    json.dumps(raw_payload), item.get("source_created_at"), location_precision,
                    json.dumps(triage_details) if triage_details is not None else None, triage_attempted_at,
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
    message = _disabled_reason(adapter, settings or get_settings())
    if message:
        if has_db:
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE ingest_runs SET status = 'SKIPPED', error_message = %s, finished_at = now() WHERE run_id = %s",
                    (message, run_id),
                )
        return IngestRunResult(str(run_id), adapter.name, 0, 0, "SKIPPED", message)
    try:
        _set_incremental_watermark(adapter, settings or get_settings())
        items = adapter.fetch()
        partial_failure = bool(getattr(adapter, "partial_failure", False))
        message = (
            "Some Bluesky search queries failed; the last successful watermark will be retried."
            if adapter.name == "BLUESKY" and partial_failure
            else None
        )
        if has_db:
            stored = _store_signals(items, settings) if adapter.kind == "signal" else _store_alerts(items)
        else:
            stored = 0
        result = IngestRunResult(str(run_id), adapter.name, len(items), stored,
                                 "PARTIAL" if has_db and partial_failure else "SUCCESS" if has_db else "PREVIEW",
                                 message)
        if has_db:
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE ingest_runs SET status = %s, items_fetched = %s, items_stored = %s, error_message = %s, finished_at = now() WHERE run_id = %s",
                    (result.status, result.items_fetched, result.items_stored, message, run_id),
                )
        return result
    except Exception as exc:  # noqa: BLE001 - isolate one feed failure from other sources
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
    with _ingestion_run_lock(settings) as acquired:
        if not acquired:
            logger.info("Skipping ingestion request for %s; another run is active", source)
            return [IngestRunResult(
                str(uuid.uuid4()), source, 0, 0, "SKIPPED",
                "Another ingestion run is already in progress.",
            ).as_dict()]
        results = [_run_adapter(adapter, settings).as_dict() for adapter in adapters]
        social_sources = []
        if source == "ALL":
            if settings.bluesky_search_enabled:
                social_sources.append("BLUESKY")
            if settings.news_rss_enabled:
                social_sources.append("GNEWS")
        elif source == "BLUESKY" and settings.bluesky_search_enabled:
            social_sources.append("BLUESKY")
        elif source == "GNEWS" and settings.news_rss_enabled:
            social_sources.append("GNEWS")
        try:
            triaged = _triage_unprocessed_social_signals(social_sources, settings)
            if triaged:
                logger.info("Classified %s new social signals (limit %s per run)",
                            triaged, MAX_SOCIAL_TRIAGE_PER_RUN)
        except Exception:
            logger.exception("Social triage queue failed; pending signals remain available for review")
        return results
