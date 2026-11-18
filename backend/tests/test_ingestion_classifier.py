import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.services import ingestion


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def _settings(**overrides):
    values = {
        "disaster_classifier_url": "https://classifier.example/predict",
        "ai_low_confidence_threshold": 0.6,
        "ai_triage_url": "https://triage.example/triage",
        "database_url": "postgresql://localhost/drch_test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_classifier_sends_scrubbed_text_and_returns_supported_scenario(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({
            "prediction": "Cyclone",
            "confidence": 0.91,
            "probabilities": {"Cyclone": 0.91, "Flood": 0.09},
        })

    monkeypatch.setattr(ingestion.httpx, "post", post)

    label, confidence, details = ingestion._classify_with_indicbert(
        "Cyclone rescue: call person@example.com", _settings(),
    )

    assert calls[0][0] == "https://classifier.example/predict"
    assert calls[0][1]["json"] == {"text": "Cyclone rescue: call [email removed]"}
    assert label == "CYCLONE"
    assert confidence == 0.91
    assert details["classification"] == {
        "prediction": "Cyclone",
        "is_disaster": True,
        "confidence": 0.91,
        "probabilities": {"Cyclone": 0.91, "Flood": 0.09},
    }


@pytest.mark.parametrize(
    ("prediction", "expected_disaster"),
    [("Fire", True), ("Earthquake", True), ("Non-Disaster", False)],
)
def test_classifier_keeps_raw_out_of_scope_and_non_disaster_labels(
    monkeypatch, prediction, expected_disaster,
):
    monkeypatch.setattr(
        ingestion.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"prediction": prediction, "confidence": 0.9}),
    )

    label, _, details = ingestion._classify_with_indicbert("A report", _settings())

    assert label is None
    assert details["classification"]["prediction"] == prediction
    assert details["classification"]["is_disaster"] is expected_disaster


def test_low_confidence_classifier_result_does_not_suggest_scenario(monkeypatch):
    monkeypatch.setattr(
        ingestion.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"prediction": "Flood", "confidence": 0.4}),
    )

    label, confidence, details = ingestion._classify_with_indicbert("Flood report", _settings())

    assert label is None
    assert confidence == 0.4
    assert details["classification"]["is_disaster"] is True
    assert "below the review threshold" in details["uncertainty"]


def test_unrecognized_classifier_label_is_left_for_review(monkeypatch):
    monkeypatch.setattr(
        ingestion.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"prediction": "Landslide", "confidence": 0.99}),
    )

    assert ingestion._classify_with_indicbert("Landslide report", _settings()) == (None, None, None)


def test_ingestion_persists_classifier_result_without_calling_legacy_triage(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.updates = []

        def execute(self, query, params):
            if query.lstrip().startswith("SELECT"):
                return SimpleNamespace(fetchall=lambda: [{
                    "signal_id": "signal-1",
                    "content_text": "Cyclone reported near the coast",
                }])
            self.updates.append((query, params))
            return SimpleNamespace(rowcount=1)

    connection = FakeConnection()

    @contextmanager
    def transaction():
        yield connection

    monkeypatch.setattr(ingestion.db, "transaction", transaction)
    monkeypatch.setattr(
        ingestion,
        "_classify_with_indicbert",
        lambda text, settings: (
            "CYCLONE",
            0.91,
            {"classification": {"prediction": "Cyclone", "is_disaster": True}},
        ),
    )

    def unexpected_prelabel(*args, **kwargs):
        raise AssertionError("the configured disaster classifier should be used")

    monkeypatch.setattr(ingestion, "_prelabel", unexpected_prelabel)

    assert ingestion._triage_unprocessed_social_signals(["BLUESKY"], _settings()) == 1
    params = connection.updates[0][1]
    assert params[0:2] == ("CYCLONE", 0.91)
    assert json.loads(params[2]) == {
        "classification": {"prediction": "Cyclone", "is_disaster": True}
    }
