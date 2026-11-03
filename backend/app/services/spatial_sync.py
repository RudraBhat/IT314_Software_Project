"""Automated Monthly Spatial Boundary Synchronization Service.

Provides commercial-grade GIS dataset synchronization:
1. Scheduled monthly (30-day) background execution without developer intervention.
2. HTTP ETag & Last-Modified conditional validation to eliminate unnecessary bandwidth & DB writes.
3. Idempotent PostGIS Upsert of administrative district polygons & centroids.
4. Live OpenStreetMap / official GIS dataset integration without hardcoded coordinate files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app import db
from app.config import get_settings

logger = logging.getLogger("drch.spatial_sync")

@dataclass(frozen=True)
class BoundarySource:
    key: str
    name: str
    level: str
    state_name: str
    url: str
    check_interval_hours: int = 720  # Monthly sync (30 days = 720 hours)


def get_registered_sources() -> list[BoundarySource]:
    """Return all configured administrative boundary sources."""
    settings = get_settings()
    if not settings.geojson_gujarat_districts_url:
        return []
    return [
        BoundarySource(
            key="gujarat_districts",
            name="Gujarat Administrative Districts",
            level="DISTRICT",
            state_name="Gujarat",
            url=settings.geojson_gujarat_districts_url,
            check_interval_hours=settings.boundary_sync_interval_hours,
        )
    ]


def _check_upstream_headers(
    url: str, etag: str | None, last_modified: str | None, timeout_seconds: int = 10
) -> tuple[bool, str | None, str | None, bytes | None]:
    """Check upstream HTTP server using ETag and Last-Modified headers.
    
    Returns:
        (is_modified, new_etag, new_last_modified, response_body_bytes)
        - If 304 Not Modified: returns (False, etag, last_modified, None)
        - If 200 OK: returns (True, new_etag, new_last_modified, content)
    """
    headers = {
        "User-Agent": "DRCH-EmergencyGIS-SpatialSync/1.0",
        "Accept": "application/geo+json, application/json, text/plain",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    try:
        resp = httpx.get(url, headers=headers, timeout=timeout_seconds)
        if resp.status_code == 304:
            logger.info("Upstream GIS resource %s unchanged (HTTP 304).", url)
            return False, etag, last_modified, None
        resp.raise_for_status()
        return True, resp.headers.get("ETag"), resp.headers.get("Last-Modified"), resp.content
    except httpx.HTTPError as exc:
        logger.warning("Upstream GIS request failed for %s: %s", url, exc)
        raise


def is_source_due_for_check(
    source: BoundarySource, conn: Any = None
) -> tuple[bool, dict[str, Any] | None]:
    """Check if a boundary source is due for an upstream update check."""
    query = """
        SELECT source_key, etag, last_modified, last_checked_at, last_synced_at, feature_count, status
        FROM boundary_sync_state
        WHERE source_key = %s;
    """
    row = None
    if conn is not None:
        row = conn.execute(query, (source.key,)).fetchone()
    else:
        with db.transaction() as db_conn:
            row = db_conn.execute(query, (source.key,)).fetchone()

    if not row or row["last_synced_at"] is None:
        return True, row

    last_checked = row["last_checked_at"]
    if last_checked is None:
        return True, row

    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=UTC)

    hours_since_check = (datetime.now(UTC) - last_checked).total_seconds() / 3600.0
    is_due = hours_since_check >= source.check_interval_hours
    return is_due, row


def sync_boundary_source(
    source: BoundarySource, force: bool = False, conn: Any = None
) -> dict[str, Any]:
    """Synchronize an administrative boundary source into PostGIS idempotently.
    
    1. Checks upstream ETag / Last-Modified headers.
    2. If 304 Not Modified and not force: skips download, touches last_checked_at.
    3. If modified or initial run: parses GeoJSON features and upserts into PostGIS.
    """
    logger.info("Initiating spatial sync check for [%s]...", source.name)

    # 1. Inspect current DB sync state
    is_due, state_row = is_source_due_for_check(source, conn=conn)
    if not is_due and not force:
        logger.info(
            "Boundary source [%s] checked recently; skipping (monthly interval: %s hrs).",
            source.name,
            source.check_interval_hours,
        )
        return {"status": "skipped", "reason": "not_due", "source": source.key}

    curr_etag = state_row["etag"] if state_row else None
    curr_last_mod = state_row["last_modified"] if state_row else None

    # 2. Check remote upstream
    is_modified = True
    new_etag = curr_etag
    new_last_mod = curr_last_mod
    geojson_bytes = None

    if source.url:
        try:
            is_modified, new_etag, new_last_mod, geojson_bytes = _check_upstream_headers(
                source.url, curr_etag if not force else None, curr_last_mod if not force else None
            )
        except (httpx.HTTPError, TimeoutError, OSError) as exc:
            logger.warning("Remote boundary fetch failed (%s). Retaining existing boundaries.", exc)
            return {"status": "skipped", "reason": f"remote_unavailable_{exc}", "source": source.key}

    # 3. If upstream is 304 Not Modified, update check timestamp and exit cleanly
    if not is_modified and not force:
        update_check_sql = """
            UPDATE boundary_sync_state
            SET last_checked_at = now(), status = 'SKIPPED_NOT_MODIFIED'
            WHERE source_key = %s;
        """
        if conn is not None:
            conn.execute(update_check_sql, (source.key,))
        else:
            with db.transaction() as db_conn:
                db_conn.execute(update_check_sql, (source.key,))
        logger.info("Boundary source [%s] is up to date (ETag: %s).", source.name, curr_etag)
        return {
            "status": "skipped",
            "reason": "304_not_modified",
            "source": source.key,
            "etag": curr_etag,
        }

    # 4. Parse GeoJSON payload
    geojson_data = None
    if geojson_bytes:
        try:
            geojson_data = json.loads(geojson_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error("Failed to parse remote GeoJSON for %s: %s", source.key, exc)


    if not geojson_data:
        return {"status": "failed", "reason": "invalid_or_empty_geojson", "source": source.key}

    features = geojson_data.get("features", [])
    if not features:
        logger.warning("GeoJSON for %s contains 0 features.", source.key)
        return {"status": "empty", "source": source.key, "count": 0}

    upsert_sql = """
        INSERT INTO administrative_boundaries (
            level, state_name, district_name, boundary_geom, centroid_geom, metadata, updated_at
        )
        VALUES (
            %(level)s,
            %(state_name)s,
            %(district_name)s,
            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)),
            ST_Centroid(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)),
            %(metadata)s,
            now()
        )
        ON CONFLICT (level, state_name, district_name) DO UPDATE SET
            boundary_geom = EXCLUDED.boundary_geom,
            centroid_geom = EXCLUDED.centroid_geom,
            metadata = EXCLUDED.metadata,
            updated_at = now();
    """

    state_upsert_sql = """
        INSERT INTO boundary_sync_state (
            source_key, source_url, etag, last_modified, last_checked_at, last_synced_at, feature_count, status, metadata
        )
        VALUES (
            %(key)s, %(url)s, %(etag)s, %(last_modified)s, now(), now(), %(count)s, 'SYNCED', %(metadata)s
        )
        ON CONFLICT (source_key) DO UPDATE SET
            source_url = EXCLUDED.source_url,
            etag = EXCLUDED.etag,
            last_modified = EXCLUDED.last_modified,
            last_checked_at = now(),
            last_synced_at = now(),
            feature_count = EXCLUDED.feature_count,
            status = 'SYNCED',
            metadata = EXCLUDED.metadata;
    """

    synced_count = 0

    def _execute_sync(active_conn: Any):
        nonlocal synced_count
        for feat in features:
            props = feat.get("properties", {}) or {}
            district_name = (
                props.get("district")
                or props.get("DISTRICT")
                or props.get("dtname")
                or props.get("name")
                or props.get("NAME")
            )
            if not district_name or not feat.get("geometry"):
                continue

            district_name = str(district_name).strip().title()
            geom_str = json.dumps(feat["geometry"])
            metadata = json.dumps({
                "properties": props,
                "synced_at": datetime.now(UTC).isoformat(),
                "source": source.key,
            })

            active_conn.execute(
                upsert_sql,
                {
                    "level": source.level,
                    "state_name": source.state_name,
                    "district_name": district_name,
                    "geom": geom_str,
                    "metadata": metadata,
                },
            )
            synced_count += 1

        active_conn.execute(
            state_upsert_sql,
            {
                "key": source.key,
                "url": source.url,
                "etag": new_etag,
                "last_modified": new_last_mod,
                "count": synced_count,
                "metadata": json.dumps({"source_name": source.name}),
            },
        )

    if conn is not None:
        _execute_sync(conn)
    else:
        with db.transaction() as db_conn:
            _execute_sync(db_conn)

    logger.info(
        "Successfully synchronized [%s]: %d district boundaries upserted.",
        source.name,
        synced_count,
    )
    return {
        "status": "synced",
        "source": source.key,
        "count": synced_count,
        "etag": new_etag,
        "last_modified": new_last_mod,
    }


def check_and_sync_all_sources(force: bool = False, conn: Any = None) -> list[dict[str, Any]]:
    """Scan and synchronize all registered spatial boundary sources on a monthly cycle."""
    results = []
    sources = get_registered_sources()
    for source in sources:
        try:
            res = sync_boundary_source(source, force=force, conn=conn)
            results.append(res)
        except Exception as exc:
            logger.exception("Error synchronizing boundary source %s", source.key)
            results.append({"status": "error", "source": source.key, "error": str(exc)})
    return results


def get_sync_status(conn: Any = None) -> list[dict[str, Any]]:
    """Fetch status summary of all boundary synchronization sources."""
    query = """
        SELECT source_key, source_url, etag, last_modified, last_checked_at, last_synced_at, feature_count, status
        FROM boundary_sync_state
        ORDER BY source_key;
    """
    if conn is not None:
        rows = conn.execute(query).fetchall()
    else:
        with db.transaction() as db_conn:
            rows = db_conn.execute(query).fetchall()

    return [dict(r) for r in rows]
