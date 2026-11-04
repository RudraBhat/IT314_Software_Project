"""Tests for external disaster alert ingestion adapters and internal runners (R-05, D-12)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import config, db
from app.cli import load_fallback_alerts


@pytest.fixture
def sample_xml_path() -> Path:
    p = Path(__file__).parent / "fixtures" / "sachet_sample.xml"
    assert p.is_file(), f"Fixture missing: {p}"
    return p


@pytest.mark.db
def test_sachet_ingest_stored_and_skipped(client, sample_xml_path, monkeypatch, sql):
    """Test SACHET ingestion stores Gujarat alert, skips Rajasthan alert, and makes it visible."""
    test_token = "secret_ingest_token_48_chars_long_for_sachet_tests"

    orig_settings = config.get_settings()
    mock_settings = MagicMock(wraps=orig_settings)
    mock_settings.ingest_token = test_token
    mock_settings.sachet_feed_url = sample_xml_path.as_uri()
    mock_settings.database_url = orig_settings.database_url
    monkeypatch.setattr("app.routers.internal.get_settings", lambda: mock_settings)
    monkeypatch.setattr("app.services.ingest.sachet.get_settings", lambda: mock_settings)

    # Trigger ingestion
    resp = client.post(
        "/api/v1/internal/ingest/run?source=SACHET",
        headers={"Authorization": f"Bearer {test_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["source"] == "SACHET"
    assert data["items_fetched"] == 1  # 1 Gujarat alert passed filter
    assert data["items_stored"] == 1

    # Verify public alerts endpoint returns the alert
    pub_resp = client.get("/api/v1/public/alerts")
    assert pub_resp.status_code == 200
    alerts = pub_resp.json()
    guj_alerts = [a for a in alerts if a["source"] == "SACHET" and a["area_text"] and "Gujarat" in a["area_text"]]
    assert len(guj_alerts) >= 1
    assert guj_alerts[0]["event_type"] == "CYCLONE"
    assert guj_alerts[0]["severity"] == "CRITICAL"

    # Verify out-of-state alert was not stored
    raj_alerts = [a for a in alerts if a["source"] == "SACHET" and a["area_text"] and "Rajasthan" in a["area_text"]]
    assert len(raj_alerts) == 0


@pytest.mark.db
def test_sachet_ingest_idempotency(client, sample_xml_path, monkeypatch, sql):
    """Replaying ingestion does not duplicate alerts (ON CONFLICT DO UPDATE)."""
    test_token = "secret_ingest_token_48_chars_long_for_sachet_tests"

    orig_settings = config.get_settings()
    mock_settings = MagicMock(wraps=orig_settings)
    mock_settings.ingest_token = test_token
    mock_settings.sachet_feed_url = sample_xml_path.as_uri()
    mock_settings.database_url = orig_settings.database_url
    monkeypatch.setattr("app.routers.internal.get_settings", lambda: mock_settings)
    monkeypatch.setattr("app.services.ingest.sachet.get_settings", lambda: mock_settings)

    # Run 1
    resp1 = client.post(
        "/api/v1/internal/ingest/run?source=SACHET",
        headers={"X-Ingest-Token": test_token},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "SUCCESS"

    # Run 2
    resp2 = client.post(
        "/api/v1/internal/ingest/run?source=SACHET",
        headers={"X-Ingest-Token": test_token},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "SUCCESS"

    with db.transaction() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM external_alerts WHERE source = 'SACHET' AND source_uid = 'SACHET-GUJ-CYC-2026-001'"
        ).fetchone()["n"]
    assert count == 1


def test_sachet_ingest_malformed_xml(client, tmp_path, monkeypatch):
    """Malformed XML results in FAILED run status without storing alerts."""
    test_token = "secret_ingest_token_48_chars_long_for_sachet_tests"
    bad_xml_file = tmp_path / "bad.xml"
    bad_xml_file.write_text("<alerts><open_tag>no_closing</alerts>", encoding="utf-8")

    orig_settings = config.get_settings()
    mock_settings = MagicMock(wraps=orig_settings)
    mock_settings.ingest_token = test_token
    mock_settings.sachet_feed_url = bad_xml_file.as_uri()
    mock_settings.database_url = orig_settings.database_url
    monkeypatch.setattr("app.routers.internal.get_settings", lambda: mock_settings)
    monkeypatch.setattr("app.services.ingest.sachet.get_settings", lambda: mock_settings)

    resp = client.post(
        "/api/v1/internal/ingest/run?source=SACHET",
        headers={"X-Ingest-Token": test_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "FAILED"
    assert data["items_stored"] == 0

    with db.transaction() as conn:
        run = conn.execute(
            "SELECT status, error_message FROM ingest_runs WHERE run_id = %s",
            (data["run_id"],),
        ).fetchone()
    assert run["status"] == "FAILED"
    assert run["error_message"] is not None


@pytest.mark.db
def test_cli_load_fallback_alerts(monkeypatch, sql):
    """CLI load-fallback-alerts inserts 3 fallback alerts and refuses in production."""
    orig_settings = config.get_settings()

    # Refuses when APP_ENV != development
    mock_prod = MagicMock(wraps=orig_settings)
    mock_prod.app_env = "production"
    monkeypatch.setattr("app.config.get_settings", lambda: mock_prod)
    with pytest.raises(SystemExit) as exc_info:
        load_fallback_alerts(argparse_dummy())
    assert "only allowed when APP_ENV=development" in str(exc_info.value)

    # Allowed in development
    mock_dev = MagicMock(wraps=orig_settings)
    mock_dev.app_env = "development"
    monkeypatch.setattr("app.config.get_settings", lambda: mock_dev)

    load_fallback_alerts(argparse_dummy())

    with db.transaction() as conn:
        fallbacks = conn.execute(
            "SELECT source_uid, is_fallback, event_type FROM external_alerts WHERE source_uid LIKE 'FALLBACK-%'"
        ).fetchall()
    assert len(fallbacks) == 3
    for f in fallbacks:
        assert f["is_fallback"] is True


@pytest.mark.db
def test_public_alerts_hides_unofficial_sources(client, sql):
    sql.execute(
        """INSERT INTO external_alerts (source, source_uid, event_type, severity, area_text, expires_at)
           VALUES ('UNKNOWN_SOCIAL', 'test-unofficial-alert', 'OTHER', 'LOW', 'Test only', now() + interval '1 day')
           ON CONFLICT (source, source_uid) DO NOTHING"""
    )
    sources = {row["source"] for row in client.get("/api/v1/public/alerts").json()}
    assert "UNKNOWN_SOCIAL" not in sources


def argparse_dummy():
    class Dummy:
        pass
    return Dummy()
