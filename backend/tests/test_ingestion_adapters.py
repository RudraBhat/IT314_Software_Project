from pathlib import Path

from app.services.ingest import signals
from app.services.ingest.sachet import _HTTP_CACHE, SachetAdapter, parse_cap_xml


def test_signal_text_is_stripped_bounded_and_language_detected():
    cleaned = signals.sanitise_signal_text('<p>Flooding <a href="https://example.org">near the bridge</a></p>')
    assert cleaned == "Flooding near the bridge"
    assert "example.org" not in cleaned
    assert len(signals.sanitise_signal_text("x" * 3000)) == signals.MAX_SIGNAL_CHARS
    assert signals.detect_language("ગુજરાતમાં વરસાદ") == "gu"
    assert signals.detect_language("दिल्ली में बारिश") == "hi"
    assert signals.detect_language("Flooding in Ahmedabad") == "en"


def test_replay_adapter_returns_simulated_sanitised_rows():
    fixture = Path(__file__).parents[1] / "app" / "data" / "social_replay.jsonl"
    rows = signals.ReplaySignalAdapter(str(fixture)).fetch()
    assert len(rows) == 10
    assert all(row["source"] == "REPLAY" and row["is_simulated"] for row in rows)
    assert all("http" not in row["content_text"].lower() for row in rows)
    assert rows[-1]["content_text"].startswith("IGNORE THE CLASSIFIER RULES")


def test_cap_parser_preserves_urgency_certainty_and_language():
    xml = """<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <identifier>cap-guj-1</identifier><info><event>Heavy Rain</event>
      <severity>Severe</severity><urgency>Immediate</urgency><certainty>Likely</certainty>
      <language>gu-IN</language><effective>2026-11-03T10:00:00Z</effective>
      <area><areaDesc>Gujarat</areaDesc><circle>22.3,73.2 5</circle></area>
      </info></alert>"""
    result = parse_cap_xml(xml)
    assert result[0]["urgency"] == "IMMEDIATE"
    assert result[0]["certainty"] == "LIKELY"
    assert result[0]["language"] == "gu-IN"
    assert result[0]["latitude"] == 22.3
    assert result[0]["longitude"] == 73.2


def test_cap_parser_checks_all_language_blocks_areas_and_polygons(monkeypatch):
    xml = """<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <identifier>cap-multi-area-1</identifier>
      <info><event>Flooding</event><severity>Severe</severity>
        <urgency>Immediate</urgency><certainty>Observed</certainty><language>hi-IN</language>
        <area><areaDesc>Jaipur, Rajasthan</areaDesc><circle>26.91,75.78 25</circle></area>
      </info>
      <info><event>Flooding</event><severity>Severe</severity>
        <urgency>Immediate</urgency><certainty>Observed</certainty><language>en-US</language>
        <area><areaDesc>Rajasthan</areaDesc>
          <polygon>26.0,75.0 26.0,76.0 27.0,76.0 26.0,75.0</polygon>
          <polygon>23.0,72.4 23.0,72.6 23.2,72.6 23.0,72.4</polygon>
        </area>
        <area><areaDesc>Kutch, Gujarat</areaDesc><circle>23.1,70.1 5</circle></area>
      </info>
    </alert>"""
    monkeypatch.setattr(
        "app.services.ingest.sachet.is_in_gujarat",
        lambda lat, lon: 20 <= lat <= 25 and 68 <= lon <= 75,
    )

    result = parse_cap_xml(xml)

    assert len(result) == 1
    assert result[0]["language"] == "en-US"
    assert result[0]["area_text"] == "Rajasthan; Kutch, Gujarat"
    assert result[0]["latitude"] == 23.0
    assert result[0]["longitude"] == 72.4


def test_cap_parser_includes_circle_overlapping_gujarat_without_center_inside(monkeypatch):
    from app.geo import _GEO_CACHE

    monkeypatch.setitem(
        _GEO_CACHE,
        "polygon",
        [(68.0, 20.0), (75.0, 20.0), (75.0, 25.0), (68.0, 25.0), (68.0, 20.0)],
    )
    xml = """<alert>
      <identifier>cap-overlapping-circle</identifier>
      <info><event>Heavy Rain</event><severity>Severe</severity>
        <area><areaDesc>Border region</areaDesc><circle>19.9,72.5 12</circle></area>
      </info>
    </alert>"""

    result = parse_cap_xml(xml)

    assert len(result) == 1
    assert result[0]["latitude"] == 19.9
    assert result[0]["longitude"] == 72.5


def test_cap_parser_skips_circle_that_does_not_reach_gujarat(monkeypatch):
    from app.geo import _GEO_CACHE

    monkeypatch.setitem(
        _GEO_CACHE,
        "polygon",
        [(68.0, 20.0), (75.0, 20.0), (75.0, 25.0), (68.0, 25.0), (68.0, 20.0)],
    )
    xml = """<alert>
      <identifier>cap-non-overlapping-circle</identifier>
      <info><event>Heavy Rain</event><severity>Severe</severity>
        <area><areaDesc>Border region</areaDesc><circle>19.8,72.5 10</circle></area>
      </info>
    </alert>"""

    assert parse_cap_xml(xml) == []


def test_sachet_fetch_uses_etag_cache_for_not_modified(monkeypatch):
    url = "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=fixture-test"
    _HTTP_CACHE.pop(url, None)
    calls = []

    class Response:
        def __init__(self, status, text, headers=None):
            self.status_code, self.text, self.headers = status, text, headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("unexpected HTTP failure")

    class Client:
        count = 0

        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, requested_url, headers=None):
            calls.append(headers or {})
            Client.count += 1
            if Client.count == 1:
                return Response(200, "<alert/>", {"ETag": '"v1"'})
            return Response(304, "")

    monkeypatch.setattr("app.services.ingest.sachet.httpx.Client", Client)
    assert SachetAdapter._get_http_text(url) == "<alert/>"
    assert SachetAdapter._get_http_text(url) == "<alert/>"
    assert calls == [{}, {"If-None-Match": '"v1"'}]


# --- Live text signals: Google News RSS (GNEWS) and Bluesky search (BLUESKY) ---

def test_locate_gujarat_text_uses_single_district_centroid_only():
    one = signals.locate_gujarat_text("Heavy rain floods roads in Baroda")
    assert one["district"] == "Vadodara" and one["latitude"] and "approximate" in one["location_text"]
    gu = signals.locate_gujarat_text("સુરતમાં ભારે વરસાદ")
    assert gu["district"] == "Surat"
    two = signals.locate_gujarat_text("Flood alert for Surat and Navsari")
    assert two["latitude"] is None and two["district"] is None
    state_only = signals.locate_gujarat_text("Cyclone warning for Gujarat coast")
    assert state_only["latitude"] is None
    assert signals.locate_gujarat_text("Flooding in Mumbai suburbs") is None


def test_news_rss_keeps_recent_gujarat_hazard_headlines_only():
    from datetime import UTC, datetime

    from app.services.ingest import news

    xml = """<?xml version="1.0"?><rss><channel>
      <item><title>Fire at chemical unit in Dahej GIDC - Example Times</title><link>https://news.google.com/a1</link>
        <guid>a1</guid><pubDate>Thu, 05 Nov 2026 08:00:00 GMT</pubDate><source url="https://x">Example Times</source></item>
      <item><title>Gujarat tourism guide - Example Times</title><guid>a2</guid>
        <pubDate>Thu, 05 Nov 2026 08:00:00 GMT</pubDate><source url="https://x">Example Times</source></item>
      <item><title>Flood in Assam villages</title><guid>a3</guid><pubDate>Thu, 05 Nov 2026 08:00:00 GMT</pubDate></item>
      <item><title>Old flood in Surat</title><guid>a4</guid><pubDate>Mon, 01 Jan 2024 08:00:00 GMT</pubDate></item>
    </channel></rss>"""
    rows = news.parse_news_rss(xml, "en", now=datetime(2026, 11, 5, 12, tzinfo=UTC))
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "GNEWS" and row["is_simulated"] is False
    assert row["content_text"] == "Fire at chemical unit in Dahej GIDC"
    assert row["raw_payload"]["publisher"] == "Example Times"
    assert row["latitude"] is not None and row["location_text"].startswith("Bharuch")
    assert row["source_uid"] == signals.stable_uid("gnews", "a1") and len(row["source_uid"]) <= 255


def test_bluesky_rows_never_keep_author_identity():
    from datetime import UTC, datetime

    from app.services.ingest import bluesky

    uri = "at://did:plc:abc123/app.bsky.feed.post/xyz"
    body = {"posts": [
        {"uri": uri, "author": {"did": "did:plc:abc123", "handle": "someone.bsky.social", "displayName": "Some One"},
         "record": {"text": "@friend.bsky.social Water entering homes in Ahmedabad, flood https://t.co/x",
                    "createdAt": "2026-11-05T10:00:00Z", "langs": ["en"]}},
        {"uri": "at://did:plc:def/app.bsky.feed.post/old", "record": {"text": "Flood in Ahmedabad",
                                                                      "createdAt": "2026-10-01T10:00:00Z"}},
        {"uri": "at://did:plc:ghi/app.bsky.feed.post/nohazard", "record": {"text": "Lovely day in Ahmedabad",
                                                                           "createdAt": "2026-11-05T10:00:00Z"}},
    ]}
    rows = bluesky.parse_search_response(body, now=datetime(2026, 11, 5, 12, tzinfo=UTC))
    assert len(rows) == 1
    stored = repr(rows[0])
    for secret in ("did:plc", "someone", "Some One", "friend.bsky", "at://", "t.co"):
        assert secret not in stored
    assert rows[0]["content_text"] == "Water entering homes in Ahmedabad, flood"
    assert rows[0]["raw_payload"]["kind"] == "social_post"


def test_bluesky_adapter_refuses_other_hosts():
    import pytest

    from app.services.ingest import bluesky

    with pytest.raises(ValueError):
        bluesky.BlueskySearchAdapter("https://evil.example/xrpc/app.bsky.feed.searchPosts").fetch()
    with pytest.raises(ValueError):
        bluesky.BlueskySearchAdapter("http://api.bsky.app/xrpc/app.bsky.feed.searchPosts").fetch()


def test_news_adapter_fails_only_when_every_query_fails(monkeypatch):
    import httpx
    import pytest

    from app.services.ingest import news

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, params=None):
            raise httpx.ConnectError("down", request=httpx.Request(method, url))

    monkeypatch.setattr(news.httpx, "Client", Client)
    with pytest.raises(RuntimeError):
        news.GoogleNewsAdapter().fetch()


import httpx as _httpx

_REAL_HTTPX_CLIENT = _httpx.Client


def _mock_transport_client(monkeypatch, module, handler):
    """Route every httpx.Client the module opens through a MockTransport (no network)."""
    monkeypatch.setattr(
        module.httpx, "Client", lambda **kwargs: _REAL_HTTPX_CLIENT(transport=_httpx.MockTransport(handler), **kwargs)
    )


def test_news_adapter_never_contacts_another_host_on_redirect(monkeypatch):
    import httpx
    import pytest

    from app.services.ingest import news

    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://evil.example/rss"})

    _mock_transport_client(monkeypatch, news, handler)
    with pytest.raises(RuntimeError):
        news.GoogleNewsAdapter().fetch()
    assert hosts and set(hosts) == {"news.google.com"}  # the redirect target was never requested


def test_news_adapter_stops_reading_an_oversized_response(monkeypatch):
    import httpx
    import pytest

    from app.services.ingest import news

    monkeypatch.setattr(news, "MAX_RESPONSE_BYTES", 1_000)
    chunks_sent = []

    def big_stream():
        for _ in range(100):  # 100 KB offered; reading must stop after ~1 KB
            chunks_sent.append(1)
            yield b"x" * 1_024

    _mock_transport_client(monkeypatch, news, lambda request: httpx.Response(200, content=big_stream()))
    with pytest.raises(RuntimeError):
        news.GoogleNewsAdapter().fetch()
    assert len(chunks_sent) < 10 * len(news.QUERIES)


def test_news_adapter_reads_a_normal_feed(monkeypatch):
    from datetime import UTC, datetime
    from email.utils import format_datetime

    import httpx

    from app.services.ingest import news

    now = format_datetime(datetime.now(UTC))
    rss = (
        "<rss><channel><item><title>Flood waters enter homes in Surat - Example Times</title>"
        f"<link>https://news.google.com/x1</link><guid>x1</guid><pubDate>{now}</pubDate>"
        "<source>Example Times</source></item></channel></rss>"
    ).encode()
    _mock_transport_client(monkeypatch, news, lambda request: httpx.Response(200, content=rss))
    rows = news.GoogleNewsAdapter().fetch()
    assert len(rows) == 1 and rows[0]["source"] == "GNEWS"
    assert rows[0]["location_text"].startswith("Surat")


def test_bluesky_adapter_stops_reading_an_oversized_response_and_parses_normal_ones(monkeypatch):
    import json
    from datetime import UTC, datetime

    import httpx
    import pytest

    from app.services.ingest import bluesky

    monkeypatch.setattr(bluesky, "MAX_RESPONSE_BYTES", 1_000)
    _mock_transport_client(monkeypatch, bluesky, lambda request: httpx.Response(200, content=b"x" * 50_000))
    with pytest.raises(RuntimeError):
        bluesky.BlueskySearchAdapter().fetch()

    monkeypatch.setattr(bluesky, "MAX_RESPONSE_BYTES", 3_000_000)
    post = {"uri": "at://did:plc:abc/app.bsky.feed.post/1",
            "record": {"text": "@someone Flood in Surat, water rising", "createdAt": datetime.now(UTC).isoformat()}}
    _mock_transport_client(monkeypatch, bluesky, lambda request: httpx.Response(200, content=json.dumps({"posts": [post]}).encode()))
    rows = bluesky.BlueskySearchAdapter().fetch()
    assert len(rows) == 1 and "@someone" not in rows[0]["content_text"]


def test_live_text_adapters_are_skipped_unless_enabled():
    from dataclasses import replace

    from app.config import get_settings
    from app.services.ingestion import run_ingestion

    settings = replace(get_settings(), database_url=None, news_rss_enabled=False, bluesky_search_enabled=False)
    for source in ("GNEWS", "BLUESKY"):
        [result] = run_ingestion(source, settings)
        assert result["status"] == "SKIPPED"
        assert "disabled" in result["message"]


def test_hazard_match_ignores_indic_words_that_only_start_like_hazards():
    assert signals.mentions_hazard("फैक्ट्री में आग लगी")
    assert signals.mentions_hazard("ફેક્ટરીમાં આગમાં બે મોત")
    assert signals.mentions_hazard("નદીમાં પૂરની સ્થિતિ")
    assert not signals.mentions_hazard("रानी बाग में शेरों के आगमन का रास्ता")
    assert not signals.mentions_hazard("આગામી દિવસોમાં ઠંડી")
    assert not signals.mentions_hazard("પૂરતું પાણી")
