"""S2-06: /triage uses a trained scenario model when one is configured, and the rules otherwise.

The tiny pipeline below is a test fixture built from a handful of inline sentences; it is not a dataset and
says nothing about model quality. It only proves the loading, checking and wiring.
"""

import hashlib
import json

import joblib
import pytest
import sklearn
from fastapi.testclient import TestClient
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from rules import MODEL_NAME, triage
from service import scenario_model
from triage_service import app

FIXTURE = [
    ("cyclone winds uprooted trees on the coast", "cyclone"),
    ("storm surge and strong wind hit the coast", "cyclone"),
    ("cyclone warning, very strong winds", "cyclone"),
    ("flood water entered homes near the river", "flood"),
    ("roads waterlogged and the drain overflowing", "flood"),
    ("flooding in the colony, water rising", "flood"),
    ("fire and explosion at the chemical plant", "fire"),
    ("gas leak and blaze at the factory", "fire"),
    ("smoke from the burning plant tank", "fire"),
    ("nice weather for cricket today", "not_disaster"),
    ("new phone launch sale this weekend", "not_disaster"),
    ("memes about the rain are funny", "not_disaster"),
]


class StubModel:
    name = "stub-scenario-model"

    def __init__(self, label="flood", probability=0.83, error=None):
        self.label, self.probability, self.error = label, probability, error

    def predict(self, text):
        if self.error:
            raise self.error
        return self.label, self.probability


def write_artifact(directory, labels=None, sha=None, version=None):
    rows = [(t, lab) for t, lab in FIXTURE if labels is None or lab in labels]
    pipeline = make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)), LogisticRegression(max_iter=500))
    pipeline.fit([t for t, _ in rows], [lab for _, lab in rows])
    path = directory / scenario_model.ARTIFACT_NAME
    joblib.dump({"pipeline": pipeline, "model_name": "test-scenario-tfidf",
                 "scikit_learn_version": version or sklearn.__version__}, path)
    digest = sha or hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "metadata.json").write_text(json.dumps({"artifact": {"sha256": digest}}), encoding="utf-8")
    return directory


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.delenv("TRIAGE_MODEL_DIR", raising=False)
    scenario_model.load_model.cache_clear()
    yield
    scenario_model.load_model.cache_clear()


PAYLOAD = {"description": "Water entered 20 homes, people trapped on rooftops", "reported_scenario": "CYCLONE",
           "reported_urgency": "HIGH", "people_affected": 20, "details": {}}


def test_model_replaces_scenario_and_confidence_but_priority_stays_with_the_rules():
    rules_result = triage(PAYLOAD)
    out = scenario_model.apply_model(rules_result, PAYLOAD, StubModel("flood", 0.834))
    assert out["model"] == "stub-scenario-model"
    assert out["scenario"] == "URBAN_FLOODING" and out["confidence"] == 0.834
    assert out["priority"] == rules_result["priority"]
    assert out["factors"][0] == {"name": "text_model", "detail": "flood (0.83)", "weight": 0.834}
    assert "scenario_keywords" not in {f["name"] for f in out["factors"]}
    assert {"stranded_trapped", "people_affected"} <= {f["name"] for f in out["factors"]}
    assert "rather than the reported cyclone" in out["uncertainty"]


@pytest.mark.parametrize("label", ["earthquake", "other_disaster", "not_disaster"])
def test_unsupported_labels_become_other_for_manual_triage(label):
    out = scenario_model.apply_model(triage(PAYLOAD), PAYLOAD, StubModel(label, 0.9))
    assert out["scenario"] == "OTHER" and label in out["uncertainty"]


def test_prediction_error_or_empty_text_keeps_the_rules_result():
    rules_result = triage(PAYLOAD)
    assert scenario_model.apply_model(rules_result, PAYLOAD, StubModel(error=ValueError("bad"))) == rules_result
    empty = {**PAYLOAD, "description": "  "}
    assert scenario_model.apply_model(triage(empty), empty, StubModel()) == triage(empty)
    assert scenario_model.apply_model(rules_result, PAYLOAD, None) == rules_result


def test_without_a_model_triage_and_health_use_the_rules():
    client = TestClient(app)
    assert client.get("/health").json()["triage_engine"] == "rules"
    assert client.post("/triage", json=PAYLOAD).json()["model"] == MODEL_NAME


def test_a_checked_artifact_is_loaded_and_used_by_the_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_MODEL_DIR", str(write_artifact(tmp_path)))
    client = TestClient(app)
    assert client.get("/health").json()["triage_engine"] == "model:test-scenario-tfidf"
    body = client.post("/triage", json={**PAYLOAD, "description": "fire and explosion at the chemical plant"}).json()
    assert body["model"] == "test-scenario-tfidf"
    assert body["scenario"] in {"CYCLONE", "URBAN_FLOODING", "INDUSTRIAL_FIRE", "OTHER"}
    assert 0 <= body["confidence"] <= 1 and body["priority"] in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def test_wrong_checksum_missing_metadata_old_version_or_missing_labels_fall_back_to_rules(tmp_path):
    def artifact(name, **kwargs):
        (tmp_path / name).mkdir()
        return write_artifact(tmp_path / name, **kwargs)

    assert scenario_model.load_model(str(artifact("hash", sha="0" * 64))) is None

    no_meta = artifact("meta")
    (no_meta / "metadata.json").unlink()
    assert scenario_model.load_model(str(no_meta)) is None

    assert scenario_model.load_model(str(artifact("old", version="0.0.1"))) is None
    assert scenario_model.load_model(str(artifact("part", labels={"flood", "fire", "not_disaster"}))) is None

    assert scenario_model.load_model(str(tmp_path / "missing")) is None
