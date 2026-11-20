import hashlib
import json

import joblib
import pytest
import sklearn
from fastapi.testclient import TestClient
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from service import text_analysis as inference
from triage_service import app

client = TestClient(app)

ENGLISH = "The river has flooded the neighbourhood and several families on the first floor need urgent rescue and drinking water"
TEXTS = [
    "flood water rescue families need help urgent",
    "river flooded homes people stranded rescue",
    "cyclone storm wind damage roads blocked",
    "football match score tonight great game",
    "new phone launch discount sale today",
    "movie review actors story music",
]


def _bundle() -> dict:
    vectorizer = TfidfVectorizer().fit(TEXTS)
    matrix = vectorizer.transform(TEXTS)
    related = LogisticRegression(max_iter=200).fit(matrix, ["1", "1", "1", "0", "0", "0"])
    request = LogisticRegression(max_iter=200).fit(matrix, [1, 1, 0, 0, 0, 0])
    return {
        "model_name": "test-text-model",
        "scikit_learn_version": sklearn.__version__,
        "vectorizer": vectorizer,
        "feature_names": ["word__" + name for name in vectorizer.get_feature_names_out()],
        "related_model": related,
        "relevance_review_threshold": 0.55,
        "binary_models": {"request": request},
        "thresholds": {"request": 0.5},
    }


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    joblib.dump(_bundle(), path)
    (tmp_path / "metadata.json").write_text(
        json.dumps({"artifact": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}), encoding="utf-8"
    )
    monkeypatch.setenv("TEXT_MODEL_DIR", str(tmp_path))
    inference.load_bundle.cache_clear()
    yield tmp_path
    inference.load_bundle.cache_clear()


def test_missing_artifact_is_503(tmp_path, monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_DIR", str(tmp_path))
    inference.load_bundle.cache_clear()
    resp = client.post("/analyze-text", json={"description": ENGLISH})
    assert resp.status_code == 503


def test_token_is_enforced(model_dir, monkeypatch):
    monkeypatch.setenv("AI_TRIAGE_TOKEN", "s3cret-token")
    assert client.post("/analyze-text", json={"description": ENGLISH}).status_code == 401
    ok = client.post("/analyze-text", json={"description": ENGLISH}, headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"description": ""},
        {"description": ENGLISH, "latitude": 23.0},
        {"description": ENGLISH, "latitude": 123.0, "longitude": 72.0},
        {"description": ENGLISH, "source_created_at": "2026-11-04T12:30:00"},
    ],
)
def test_request_validation(body):
    assert client.post("/analyze-text", json=body).status_code == 422


def test_analysis_is_advisory_and_marks_untrained_outputs(model_dir):
    body = {"description": ENGLISH, "source": "example-feed", "latitude": 23.02, "longitude": 72.57}
    resp = client.post("/analyze-text", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["human_review_required"] is True
    assert data["status"] == "EXPERIMENTAL_ADVISORY"
    for untrained in ("operational_scenario", "urgency", "location_mentions", "event_time_mentioned"):
        assert data[untrained]["status"] == "NOT_TRAINED"
    assert data["source_metadata"]["provenance"] == "PROVIDED_BY_CALLER"
    assert data["source_metadata"]["coordinates"] == {"latitude": 23.02, "longitude": 72.57}


def test_non_english_text_is_not_classified(model_dir):
    data = client.post("/analyze-text", json={"description": "Die Stadt ist überflutet und die Menschen brauchen dringend Hilfe"}).json()
    assert data["status"] in {"UNSUPPORTED_LANGUAGE", "LANGUAGE_UNCERTAIN"}
    assert data["analysis"] is None and data["human_review_required"] is True


def test_tampered_artifact_is_rejected(model_dir):
    (model_dir / "model.joblib").write_bytes(b"not the model that was trained")
    resp = client.post("/analyze-text", json={"description": ENGLISH})
    assert resp.status_code == 503
    assert "integrity" in resp.json()["detail"]


def test_incompatible_sklearn_version_is_503(tmp_path, monkeypatch):
    bundle = _bundle()
    bundle["scikit_learn_version"] = "0.0.1"
    joblib.dump(bundle, tmp_path / "model.joblib")
    monkeypatch.setenv("TEXT_MODEL_DIR", str(tmp_path))
    inference.load_bundle.cache_clear()
    resp = client.post("/analyze-text", json={"description": ENGLISH})
    assert resp.status_code == 503
    assert "incompatible" in resp.json()["detail"]
    inference.load_bundle.cache_clear()
