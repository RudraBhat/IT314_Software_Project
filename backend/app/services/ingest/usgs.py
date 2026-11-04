"""USGS earthquake catalog adapter restricted to the Gujarat bounding box."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.geo import is_in_gujarat
from app.services.ingest.base import Adapter

logger = logging.getLogger("drch.ingest.usgs")


def _severity(magnitude: float) -> str:
    if magnitude >= 6.0:
        return "CRITICAL"
    if magnitude >= 5.0:
        return "HIGH"
    if magnitude >= 4.0:
        return "MEDIUM"
    return "LOW"


class UsgsAdapter(Adapter):
    """Fetch public USGS GeoJSON events and retain Gujarat events only."""

    name = "USGS"

    def __init__(self, feed_url: str | None = None) -> None:
        self.feed_url = feed_url

    def fetch(self) -> list[dict[str, Any]]:
        url = (self.feed_url or get_settings().usgs_feed_url).strip()
        if not url:
            logger.info("USGS adapter disabled: USGS_FEED_URL is empty")
            return []
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.get(url, headers={"Accept": "application/geo+json, application/json"})
        response.raise_for_status()
        body = response.json()
        features = body.get("features", []) if isinstance(body, dict) else []
        alerts: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            if len(coordinates) < 2:
                continue
            try:
                longitude, latitude = float(coordinates[0]), float(coordinates[1])
                magnitude = float(properties.get("mag"))
            except (TypeError, ValueError):
                continue
            if not is_in_gujarat(latitude, longitude):
                continue
            event_uid = str(feature.get("id") or properties.get("code") or "").strip()
            if not event_uid:
                continue
            try:
                effective_at = datetime.fromtimestamp(float(properties["time"]) / 1000, UTC)
            except (KeyError, TypeError, ValueError, OSError):
                effective_at = None
            alerts.append({
                "source": self.name,
                "source_uid": event_uid,
                "event_type": "EARTHQUAKE",
                "severity": _severity(magnitude),
                "area_text": str(properties.get("place") or "Gujarat")[:500],
                "latitude": latitude,
                "longitude": longitude,
                "effective_at": effective_at,
                "expires_at": effective_at + timedelta(days=7) if effective_at else now + timedelta(days=1),
                "raw_payload": {
                    "magnitude": magnitude,
                    "place": str(properties.get("place") or "")[:500],
                    "url": str(properties.get("url") or "")[:1000],
                    "status": str(properties.get("status") or "")[:40],
                    "updated": properties.get("updated"),
                },
            })
        return alerts
