"""Sanitised, explicitly simulated social-signal replay adapter."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.ingest.base import Adapter

logger = logging.getLogger("drch.ingest.signals")
MAX_SIGNAL_CHARS = 2_000
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SPACE_RE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def sanitise_signal_text(value: str) -> str:
    """Strip markup, links and controls, then bound text before triage or storage."""
    parser = _TextExtractor()
    parser.feed(value or "")
    parser.close()
    text = " ".join(parser.parts)
    text = URL_RE.sub(" ", text)
    text = CONTROL_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()[:MAX_SIGNAL_CHARS]


def detect_language(value: str) -> str:
    """Small dependency-free script detector for the supported Indian languages."""
    counts = {"gu": 0, "hi": 0}
    for char in value:
        code = ord(char)
        if 0x0A80 <= code <= 0x0AFF:
            counts["gu"] += 1
        elif 0x0900 <= code <= 0x097F:
            counts["hi"] += 1
    if counts["gu"] or counts["hi"]:
        return max(counts, key=counts.get)
    return "en" if any(ch.isalpha() for ch in value) else "und"


class ReplaySignalAdapter(Adapter):
    """Read team-authored replay items; never fetches or stores live user posts."""

    name = "REPLAY"
    kind = "signal"

    def __init__(self, replay_file: str | None = None) -> None:
        configured = (replay_file or get_settings().social_replay_file).strip()
        self.path = Path(configured) if configured else Path(__file__).resolve().parents[3] / "app" / "data" / "social_replay.jsonl"

    def fetch(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            logger.warning("Signal replay dataset not found: %s", self.path)
            return []
        items: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as stream:
            for row_num, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid replay JSON on line {row_num}") from exc
                text = sanitise_signal_text(str(row.get("text", "")))
                if not text:
                    continue
                uid = str(row.get("id") or hashlib.sha256(text.encode()).hexdigest()[:32])
                lat, lon = row.get("latitude"), row.get("longitude")
                items.append({
                    "source": self.name,
                    "source_uid": uid,
                    "content_text": text,
                    "language": detect_language(text),
                    "location_text": str(row.get("location") or "")[:200] or None,
                    "latitude": float(lat) if lat is not None else None,
                    "longitude": float(lon) if lon is not None else None,
                    "is_simulated": True,
                    "raw_payload": {"dataset": "social_replay", "synthetic": True},
                })
        return items
