from contextlib import contextmanager
from types import SimpleNamespace

from app.services import ingestion


class FakeConnection:
    def __init__(self, existing=None):
        self.existing = existing
        self.selects = 0
        self.inserts = []

    def execute(self, query, params):
        if query.lstrip().startswith("SELECT"):
            self.selects += 1
            return SimpleNamespace(fetchone=lambda: self.existing)
        self.inserts.append((query, params))
        return None


def _settings():
    return SimpleNamespace(ai_triage_url="http://triage", ai_triage_token=None)


def _signal(text="Flooding is rising near the bridge"):
    return {
        "source": "REPLAY",
        "source_uid": "replay-1",
        "content_text": text,
        "language": "en",
        "is_simulated": True,
        "raw_payload": {"synthetic": True},
    }


def _patch_transaction(monkeypatch, connection):
    @contextmanager
    def transaction():
        yield connection

    monkeypatch.setattr(ingestion.db, "transaction", transaction)


def test_reuses_saved_prelabel_for_unchanged_signal(monkeypatch):
    signal = _signal()
    connection = FakeConnection(
        {
            "content_text": signal["content_text"],
            "ai_label": "URBAN_FLOODING",
            "ai_confidence": 0.82,
        }
    )
    _patch_transaction(monkeypatch, connection)

    def unexpected_prelabel(*args, **kwargs):
        raise AssertionError("unchanged, already labelled signal should use its saved prelabel")

    monkeypatch.setattr(ingestion, "_prelabel", unexpected_prelabel)

    assert ingestion._store_signals([signal], _settings()) == 1
    assert connection.selects == 1
    assert connection.inserts[0][1][11:13] == ("URBAN_FLOODING", 0.82)


def test_duplicate_items_in_one_poll_call_triage_once(monkeypatch):
    signal = _signal()
    connection = FakeConnection()
    _patch_transaction(monkeypatch, connection)
    prelabel_calls = []

    def prelabel(text, settings):
        prelabel_calls.append(text)
        return "URBAN_FLOODING", 0.82

    monkeypatch.setattr(ingestion, "_prelabel", prelabel)

    assert ingestion._store_signals([signal, signal.copy()], _settings()) == 2
    assert prelabel_calls == [signal["content_text"]]
    assert connection.selects == 1
    assert len(connection.inserts) == 2


def test_changed_signal_retries_triage_and_clears_stale_label_on_conflict(monkeypatch):
    signal = _signal("Chemical fire reported at the storage yard")
    connection = FakeConnection(
        {
            "content_text": "Old flooding report",
            "ai_label": "URBAN_FLOODING",
            "ai_confidence": 0.82,
        }
    )
    _patch_transaction(monkeypatch, connection)
    prelabel_calls = []

    def failed_prelabel(text, settings):
        prelabel_calls.append(text)
        return None, None

    monkeypatch.setattr(ingestion, "_prelabel", failed_prelabel)

    assert ingestion._store_signals([signal], _settings()) == 1
    query, params = connection.inserts[0]
    assert prelabel_calls == [signal["content_text"]]
    assert params[11:13] == (None, None)
    assert "source_signals.content_text IS DISTINCT FROM EXCLUDED.content_text" in query
