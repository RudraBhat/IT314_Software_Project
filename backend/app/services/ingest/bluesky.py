"""Bluesky public post search adapter for recent Gujarat hazard posts.

Uses the unauthenticated AppView search endpoint. Only the post text (sanitised, with links and
@mentions removed), its language, creation time, and an openable public post URL are kept. The
author's handle and display name, and the original AT URI, are not stored. The deduplication
source_uid is a one-way hash of the URI; the public URL uses the DID as requested for verification.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.config import get_settings
from app.services.ingest.base import Adapter, get_capped
from app.services.ingest.signals import (
    detect_language,
    locate_gujarat_text,
    mentions_hazard,
    sanitise_signal_text,
    stable_uid,
)

logger = logging.getLogger("drch.ingest.bluesky")

DEFAULT_SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
ALLOWED_HOSTS = {"api.bsky.app", "public.api.bsky.app"}
LOOKBACK = timedelta(hours=24)
RESULTS_PER_QUERY = 50
MAX_RESPONSE_BYTES = 3_000_000
USER_AGENT = "ResQ-DRCH-ingest/1.0"
MENTION_RE = re.compile(r"(?<!\w)@[\w.-]+")

# Broad place-name searches; hazard words are matched locally. Narrow searches such as
# "gujarat flood" return almost nothing within a 24-hour window.
QUERIES = (
    "gujarat", "ahmedabad", "surat", "vadodara", "rajkot", "kutch", "bharuch",
)


def _created_at(raw: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw))  # Python 3.11+ accepts a trailing "Z"
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _public_post_url(uri: str) -> str | None:
    """Build a public link using the DID, without persisting the author's handle."""
    if not uri.startswith("at://"):
        return None
    parts = uri[5:].split("/")
    if len(parts) != 3 or not parts[0].startswith("did:") or parts[1] != "app.bsky.feed.post":
        return None
    did, rkey = parts[0], parts[2]
    if not did or not rkey:
        return None
    return f"https://bsky.app/profile/{quote(did, safe=':')}/post/{quote(rkey, safe='')}"


def parse_search_response(
    body: Any,
    now: datetime | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Turn a searchPosts response into signal rows (recent hazard posts about Gujarat only)."""
    now = now or datetime.now(UTC)
    cutoff = max(since or (now - LOOKBACK), now - LOOKBACK)
    posts = body.get("posts", []) if isinstance(body, dict) else []
    rows: list[dict[str, Any]] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        record = post.get("record") or {}
        uri = str(post.get("uri") or "")
        if not uri or not isinstance(record, dict):
            continue
        created = _created_at(record.get("createdAt"))
        if created is None or created < cutoff or created > now:
            continue
        text = sanitise_signal_text(MENTION_RE.sub(" ", str(record.get("text") or "")))
        if not text or not mentions_hazard(text):
            continue
        language = detect_language(text)
        if language != "en":
            continue
        location = locate_gujarat_text(text)
        if location is None:
            continue
        langs = record.get("langs") if isinstance(record.get("langs"), list) else []
        rows.append({
            "source": "BLUESKY",
            "source_uid": stable_uid("bluesky", uri),
            "content_text": text,
            "language": language,
            "location_text": location["location_text"],
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "source_created_at": created,
            "location_precision": "DISTRICT_CENTROID" if location["district"] else "NONE",
            "is_simulated": False,
            "raw_payload": {
                "kind": "social_post",
                "created_at": created.isoformat(),
                "source_url": _public_post_url(uri),
                "declared_langs": [str(lang)[:10] for lang in langs[:3]],
                "location_precision": "district_centroid" if location["district"] else "none",
            },
        })
    return rows


class BlueskySearchAdapter(Adapter):
    """Search recent public Bluesky posts for Gujarat hazard keywords."""

    name = "BLUESKY"
    kind = "signal"

    def __init__(self, search_url: str | None = None) -> None:
        self.search_url = (search_url or get_settings().bluesky_search_url or DEFAULT_SEARCH_URL).strip()
        self.since: datetime | None = None
        self.partial_failure = False

    def set_since(self, value: datetime | None) -> None:
        """Set an incremental search watermark; the adapter always retains a 24-hour cap."""
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        self.since = value

    def fetch(self) -> list[dict[str, Any]]:
        self.partial_failure = False
        parsed = urlsplit(self.search_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError("BLUESKY_SEARCH_URL must be an https Bluesky AppView URL")
        now = datetime.now(UTC)
        cutoff = max(self.since or (now - LOOKBACK), now - LOOKBACK)
        since = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows: dict[str, dict[str, Any]] = {}
        failures = 0
        with httpx.Client(timeout=15.0, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            for query in QUERIES:
                try:
                    body, _, _ = get_capped(client, self.search_url, params={
                        "q": query, "sort": "latest", "since": since, "limit": RESULTS_PER_QUERY,
                    }, limit=MAX_RESPONSE_BYTES)
                    for row in parse_search_response(json.loads(body), now=now, since=cutoff):
                        rows.setdefault(row["source_uid"], row)
                except (httpx.HTTPError, ValueError) as exc:
                    failures += 1
                    logger.warning("Bluesky search query failed (%s)", type(exc).__name__)
        if failures == len(QUERIES):
            raise RuntimeError("Every Bluesky search query failed")
        self.partial_failure = failures > 0
        return list(rows.values())
