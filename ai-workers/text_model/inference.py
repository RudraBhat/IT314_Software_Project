"""Inference helpers for the trained, advisory English text model."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS


DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "artifacts"
RELATED_LABELS = {"0": "NOT_RELATED", "1": "RELATED", "2": "UNCERTAIN"}
ENGLISH_DETECTION_MIN_PROBABILITY = 0.80
DetectorFactory.seed = 0


class ModelCompatibilityError(RuntimeError):
    """Raised when a serialized scikit-learn model is loaded by another version."""


@lru_cache(maxsize=2)
def load_bundle(model_dir: str = str(DEFAULT_MODEL_DIR)) -> dict[str, Any]:
    """Load a local model artifact once per process."""
    path = Path(model_dir) / "model.joblib"
    if not path.is_file():
        raise FileNotFoundError(f"No text model artifact found at {path}")
    bundle = joblib.load(path)
    trained_version = bundle.get("scikit_learn_version")
    if trained_version != sklearn.__version__:
        raise ModelCompatibilityError(
            f"Model requires scikit-learn {trained_version}; runtime has {sklearn.__version__}"
        )
    return bundle


def _evidence_terms(bundle: dict, vector_row, coefficients: np.ndarray, limit: int = 4) -> list[str]:
    contributions = vector_row.multiply(coefficients).tocoo()
    names = bundle["feature_names"]
    ranked: list[tuple[float, str]] = []
    for index, value in zip(contributions.col, contributions.data, strict=True):
        feature = str(names[index])
        if value > 0 and feature.startswith("word__"):
            term = feature.removeprefix("word__")
            if len(term) > 2 and term not in ENGLISH_STOP_WORDS:
                ranked.append((float(value), term))
    ranked.sort(reverse=True)
    result: list[str] = []
    for _, term in ranked:
        if term not in result:
            result.append(term)
        if len(result) == limit:
            break
    return result


def _class_coefficients(classifier, predicted_class) -> np.ndarray:
    classes = list(classifier.classes_)
    class_index = classes.index(predicted_class)
    if classifier.coef_.shape[0] == 1:
        return classifier.coef_[0] if class_index == 1 else -classifier.coef_[0]
    return classifier.coef_[class_index]


def predict_text(text: str, model_dir: str = str(DEFAULT_MODEL_DIR)) -> dict[str, Any]:
    """Return supported model predictions and mark untrained outputs explicitly."""
    bundle = load_bundle(model_dir)
    try:
        detected_language = detect_langs(text)[0]
        language = {
            "label": detected_language.lang,
            "confidence": round(float(detected_language.prob), 4),
        }
    except LangDetectException:
        language = {"label": "UNKNOWN", "confidence": 0.0}
    if language["label"] != "en" or language["confidence"] < ENGLISH_DETECTION_MIN_PROBABILITY:
        status = "LANGUAGE_UNCERTAIN" if language["label"] in {"en", "UNKNOWN"} else "UNSUPPORTED_LANGUAGE"
        return {
            "status": status,
            "model": bundle["model_name"],
            "language": language,
            "human_review_required": True,
            "analysis": None,
            "reason": "The text model only processes text confidently detected as English.",
        }

    vector = bundle["vectorizer"].transform([text])

    related_model = bundle["related_model"]
    related_probabilities = related_model.predict_proba(vector)[0]
    related_index = int(related_probabilities.argmax())
    related_class = str(related_model.classes_[related_index])
    related_confidence = float(related_probabilities[related_index])
    related_label = RELATED_LABELS[related_class]
    needs_human_review = (
        related_label == "UNCERTAIN"
        or related_confidence < float(bundle["relevance_review_threshold"])
    )
    related_coefficients = _class_coefficients(related_model, related_model.classes_[related_index])

    information_types: dict[str, dict[str, Any]] = {}
    for category, classifier in bundle["binary_models"].items():
        probability = float(classifier.predict_proba(vector)[0, 1])
        threshold = float(bundle["thresholds"][category])
        candidate = probability >= threshold
        information_types[category] = {
            "candidate_for_review": candidate,
            "probability": round(probability, 4),
            "threshold": round(threshold, 4),
            "evidence_terms": (
                _evidence_terms(bundle, vector, classifier.coef_[0]) if candidate else []
            ),
        }

    def _boolean_output(name: str) -> dict[str, Any]:
        item = information_types.get(name)
        if item is None:
            return {"status": "NOT_TRAINED", "candidate_for_review": None, "probability": None}
        return {
            "status": "CANDIDATE_FOR_REVIEW" if item["candidate_for_review"] else "LOW_SIGNAL",
            "candidate_for_review": item["candidate_for_review"],
            "probability": item["probability"],
            "threshold": item["threshold"],
            "evidence_terms": item["evidence_terms"],
        }

    return {
        "status": "EXPERIMENTAL_ADVISORY",
        "language": language,
        "human_review_required": True,
        "model": bundle["model_name"],
        "disaster_relevance": {
            "label": "REVIEW" if needs_human_review else related_label,
            "candidate_label": related_label,
            "confidence": round(related_confidence, 4),
            "probabilities": {
                RELATED_LABELS[str(label)]: round(float(probability), 4)
                for label, probability in zip(
                    related_model.classes_, related_probabilities, strict=True
                )
            },
            "needs_human_review": needs_human_review,
            "review_threshold": round(float(bundle["relevance_review_threshold"]), 4),
            "evidence_terms": _evidence_terms(bundle, vector, related_coefficients),
        },
        "intent": {
            "request_for_help": _boolean_output("request"),
            "offer_of_help": _boolean_output("offer"),
        },
        "direct_report": _boolean_output("direct_report"),
        "information_types": information_types,
        "operational_scenario": {"status": "NOT_TRAINED", "value": None},
        "urgency": {"status": "NOT_TRAINED", "value": None},
        "location_mentions": {"status": "NOT_TRAINED", "value": None},
        "event_time_mentioned": {"status": "NOT_TRAINED", "value": None},
        "evidence_note": (
            "Evidence terms are the strongest positive word-feature contributions; they are not a causal explanation."
        ),
    }
