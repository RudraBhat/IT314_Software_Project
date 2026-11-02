"""SACHET (CAP - Common Alerting Protocol) Ingestion Adapter (R-05, D-12).

Parses CAP 1.1 / 1.2 XML feeds provided by NDMA SACHET.
Filters strictly for Gujarat geofenced alerts and maps events and severities
to the standard DRCH scenario taxonomy.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import defusedxml.ElementTree as ET
import httpx

from app.config import get_settings
from app.geo import is_in_gujarat
from app.services.ingest.base import Adapter

logger = logging.getLogger("drch.ingest.sachet")


def _find_child(node: ET.Element, local_name: str) -> ET.Element | None:
    for child in node:
        tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag_name.lower() == local_name.lower():
            return child
    return None


def _find_child_text(node: ET.Element, local_name: str) -> str:
    child = _find_child(node, local_name)
    return child.text.strip() if (child is not None and child.text) else ""


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        clean = value.strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return None


def map_cap_event(event_text: str) -> str:
    """Map CAP event text to DRCH scenario taxonomy."""
    ev = event_text.lower()
    if any(k in ev for k in ("cyclone", "storm", "hurricane", "typhoon")):
        return "CYCLONE"
    if any(k in ev for k in ("flood", "inundation", "heavy rain", "waterlogging", "rain")):
        return "URBAN_FLOODING"
    if any(k in ev for k in ("fire", "chemical", "blast", "explosion", "toxic", "gas leak")):
        return "INDUSTRIAL_FIRE"
    return "OTHER"


def map_cap_severity(severity_text: str) -> str:
    """Map CAP severity to DRCH severity levels."""
    sev = severity_text.lower()
    if sev in ("extreme", "critical"):
        return "CRITICAL"
    if sev in ("severe", "high"):
        return "HIGH"
    if sev in ("moderate", "medium"):
        return "MEDIUM"
    if sev in ("minor", "low"):
        return "LOW"
    return "MEDIUM"


def parse_cap_coordinates(circle_text: str, polygon_text: str) -> tuple[float | None, float | None]:
    """Extract centroid (latitude, longitude) from circle or polygon elements."""
    if circle_text:
        parts = [p.strip() for p in circle_text.split(",") if p.strip()]
        if len(parts) >= 2:
            try:
                return round(float(parts[0]), 6), round(float(parts[1]), 6)
            except ValueError:
                pass

    if polygon_text:
        points = [p.strip().split(",") for p in polygon_text.split() if "," in p]
        lats: list[float] = []
        lons: list[float] = []
        for pair in points:
            if len(pair) >= 2:
                try:
                    lats.append(float(pair[0].strip()))
                    lons.append(float(pair[1].strip()))
                except ValueError:
                    continue
        if lats and lons:
            return round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6)

    return None, None


def parse_cap_xml(xml_content: str, source_name: str = "SACHET") -> list[dict[str, Any]]:
    """Parse CAP XML string and return list of Gujarat-relevant alert dictionaries."""
    root = ET.fromstring(xml_content)

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag.lower() == "alert":
        alert_nodes = [root]
    else:
        alert_nodes = [
            elem for elem in root.iter()
            if (elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag).lower() == "alert"
        ]

    alerts: list[dict[str, Any]] = []

    for alert in alert_nodes:
        source_uid = _find_child_text(alert, "identifier")
        if not source_uid:
            continue

        info = _find_child(alert, "info")
        if info is None:
            continue

        event_text = _find_child_text(info, "event")
        severity_text = _find_child_text(info, "severity")
        effective_text = _find_child_text(info, "effective")
        expires_text = _find_child_text(info, "expires")
        headline = _find_child_text(info, "headline")
        description = _find_child_text(info, "description")

        area = _find_child(info, "area")
        area_desc = ""
        circle_text = ""
        polygon_text = ""
        if area is not None:
            area_desc = _find_child_text(area, "areaDesc")
            circle_text = _find_child_text(area, "circle")
            polygon_text = _find_child_text(area, "polygon")

        lat, lon = parse_cap_coordinates(circle_text, polygon_text)

        # Geofence check: areaDesc mentions Gujarat OR centroid passes is_in_gujarat
        in_gujarat = False
        if "gujarat" in area_desc.lower():
            in_gujarat = True
        elif lat is not None and lon is not None:
            in_gujarat = is_in_gujarat(lat, lon)

        if not in_gujarat:
            logger.debug("Skipping out-of-state alert: %s (%s)", source_uid, area_desc)
            continue

        alerts.append({
            "source": source_name,
            "source_uid": source_uid,
            "event_type": map_cap_event(event_text),
            "severity": map_cap_severity(severity_text),
            "area_text": area_desc or headline or "Gujarat",
            "latitude": lat,
            "longitude": lon,
            "effective_at": _parse_iso_datetime(effective_text),
            "expires_at": _parse_iso_datetime(expires_text),
            "raw_payload": {
                "identifier": source_uid,
                "event": event_text,
                "severity": severity_text,
                "headline": headline,
                "description": description,
                "area_desc": area_desc,
            },
        })

    return alerts


class SachetAdapter(Adapter):
    """NDMA SACHET CAP Feed Adapter."""

    name = "SACHET"

    def __init__(self, feed_url: str | None = None) -> None:
        self.feed_url = feed_url

    def fetch(self) -> list[dict[str, Any]]:
        url = (self.feed_url or get_settings().sachet_feed_url).strip()
        if not url:
            logger.info("SACHET adapter disabled: feed URL is empty")
            return []

        parsed = urlparse(url)
        if parsed.scheme == "file":
            raw_path = parsed.path
            if parsed.netloc:
                raw_path = f"//{parsed.netloc}{raw_path}"
            path_str = url2pathname(unquote(raw_path))
            file_path = Path(path_str)
            if not file_path.is_file():
                # On Windows, url2pathname('/C:/...') might retain leading slash or backslash
                stripped = Path(unquote(parsed.path).lstrip("\\/"))
                if stripped.is_file():
                    file_path = stripped
            if not file_path.is_file():
                raise FileNotFoundError(f"Fixture feed file not found: {url} (resolved to {file_path})")
            xml_text = file_path.read_text(encoding="utf-8")
        elif not parsed.scheme:
            file_path = Path(url)
            if not file_path.is_file():
                raise FileNotFoundError(f"Fixture feed file not found: {url}")
            xml_text = file_path.read_text(encoding="utf-8")
        else:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                xml_text = resp.text

        return parse_cap_xml(xml_text, source_name=self.name)
