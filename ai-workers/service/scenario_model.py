"""Optional trained scenario classifier for /triage (S2-06). Owner: Neeti.

/triage always computes the rules result (``rules.py``). When ``TRIAGE_MODEL_DIR`` points at a trained scenario
model whose labels cover the three supported scenarios, the model's scenario and confidence replace the rules'
scenario and confidence. Priority and its factors still come from the written priority rules
(docs/ai/triage-rules.md). Without an artifact, or with one that fails a check, /triage stays on the rules and
says so in ``GET /health``.

The backend still applies its own guardrails: a confidence below ``AI_LOW_CONFIDENCE_THRESHOLD`` becomes
``LOW_CONFIDENCE`` and ``OTHER`` is flagged out of scope. Nothing here can change an incident.

Artifact contract (written by the S2-05 training script, never committed to git):

    <TRIAGE_MODEL_DIR>/scenario_model.joblib   dict with "pipeline" (a scikit-learn estimator over raw text with
                                              predict_proba and classes_), "model_name", "scikit_learn_version"
    <TRIAGE_MODEL_DIR>/metadata.json           {"artifact": {"sha256": "<SHA-256 of scenario_model.joblib>"}, ...}

``metadata.json`` is required: joblib unpickles, which can run code, so an artifact is loaded only when its
SHA-256 matches. Class labels are the dataset labels of docs/ai/text-label-guideline.md.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

ARTIFACT_NAME = "scenario_model.joblib"
LABEL_TO_SCENARIO = {
    "cyclone": "CYCLONE",
    "flood": "URBAN_FLOODING",
    "fire": "INDUSTRIAL_FIRE",
    # Not supported scenarios: the backend shows them as out of scope for manual triage.
    "earthquake": "OTHER",
    "other_disaster": "OTHER",
    "not_disaster": "OTHER",
}
REQUIRED_LABELS = frozenset({"cyclone", "flood", "fire"})


class ScenarioModel(Protocol):
    name: str

    def predict(self, text: str) -> tuple[str, float]:
        """Return the dataset label and its probability for one text."""
        ...


class SklearnScenarioModel:
    """Wraps a trained scikit-learn text pipeline (for example TF-IDF character n-grams + logistic regression)."""

    def __init__(self, bundle: dict[str, Any]):
        self.pipeline = bundle["pipeline"]
        self.name = str(bundle.get("model_name") or "drch-triage-text-model")[:100]
        labels = {str(label).lower() for label in self.pipeline.classes_}
        missing = REQUIRED_LABELS - labels
        if missing:
            raise ValueError(f"model labels do not cover {sorted(missing)}")
        unknown = labels - set(LABEL_TO_SCENARIO)
        if unknown:
            raise ValueError(f"model has labels outside the dataset schema: {sorted(unknown)}")

    def predict(self, text: str) -> tuple[str, float]:
        probabilities = self.pipeline.predict_proba([text])[0]
        index = int(probabilities.argmax())
        return str(self.pipeline.classes_[index]).lower(), float(probabilities[index])


@lru_cache(maxsize=2)
def load_model(model_dir: str) -> SklearnScenarioModel | None:
    """Load and check the artifact once per process; return None (rules stay in use) on any problem."""
    path = Path(model_dir) / ARTIFACT_NAME
    if not path.is_file():
        logger.info("No scenario model at %s; /triage uses the rules", path)
        return None
    if not (path.parent / "metadata.json").is_file():
        logger.warning("Scenario model has no metadata.json with its SHA-256; not loaded")
        return None
    try:
        import joblib
        import sklearn

        from service.text_analysis import ModelIntegrityError, _verify_artifact_hash

        _verify_artifact_hash(path)
        # Unpickled only after the SHA-256 check above.
        bundle = joblib.load(path)  # nosec B301
        if bundle.get("scikit_learn_version") != sklearn.__version__:
            logger.warning("Scenario model needs scikit-learn %s; runtime has %s; not loaded",
                           bundle.get("scikit_learn_version"), sklearn.__version__)
            return None
        return SklearnScenarioModel(bundle)
    except (ModelIntegrityError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("Scenario model not loaded: %s", exc)
        return None


def configured_model() -> SklearnScenarioModel | None:
    model_dir = os.getenv("TRIAGE_MODEL_DIR")
    return load_model(model_dir) if model_dir else None


def engine_name(model: ScenarioModel | None) -> str:
    return f"model:{model.name}" if model else "rules"


def apply_model(result: dict, payload: dict, model: ScenarioModel | None) -> dict:
    """Replace the rules' scenario and confidence with the model's; keep the rules' priority and its factors."""
    description = (payload.get("description") or "").strip()
    if model is None or not description:
        return result
    try:
        label, probability = model.predict(description)
    except (ValueError, TypeError, AttributeError, IndexError, RuntimeError) as exc:
        logger.warning("Scenario model prediction failed (%s); using the rules result", type(exc).__name__)
        return result

    scenario = LABEL_TO_SCENARIO.get(label, "OTHER")
    confidence = round(min(max(probability, 0.0), 1.0), 3)
    reported = (payload.get("reported_scenario") or "").strip().upper().replace(" ", "_")
    notes = []
    if reported in {"CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING"} and reported != scenario:
        notes.append(f"The text model reads this as {scenario.lower()} rather than the reported {reported.lower()}.")
    if scenario == "OTHER":
        notes.append(f"The text model labelled it {label}, which is not one of the three supported scenarios.")

    factors = [f for f in result.get("factors", []) if f.get("name") != "scenario_keywords"]
    factors.insert(0, {"name": "text_model", "detail": f"{label} ({confidence:.2f})", "weight": confidence})
    return {
        **result,
        "model": model.name,
        "scenario": scenario,
        "confidence": confidence,
        "uncertainty": " ".join(notes) or None,
        "factors": factors,
    }
