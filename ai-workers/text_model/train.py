"""Train and evaluate the English crisis-message classifier."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import platform
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score, precision_score, recall_score
from sklearn.pipeline import FeatureUnion
from sklearn.model_selection import train_test_split
from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from .download_data import DEFAULT_DESTINATION, FILES
from .download_india_data import CSV_NAME, DATASET_ID, DATASET_VERSION


MODEL_NAME = "resq-english-crisis-text-v1"
RELATED_LABELS = {"0": "NOT_RELATED", "1": "RELATED", "2": "UNCERTAIN"}
MULTILABELS = (
    "request",
    "offer",
    "direct_report",
    "aid_related",
    "medical_help",
    "medical_products",
    "search_and_rescue",
    "security",
    "water",
    "food",
    "shelter",
    "missing_people",
    "death",
    "infrastructure_related",
    "transport",
    "buildings",
    "electricity",
    "hospitals",
    "weather_related",
    "floods",
    "storm",
    "fire",
    "earthquake",
    "cold",
    "other_weather",
)
MIN_POSITIVE = 25
MIN_NEGATIVE = 25
MIN_VALIDATION_POSITIVE = 20
MIN_VALIDATION_NEGATIVE = 20
ENGLISH_DETECTION_MIN_PROBABILITY = 0.80
DetectorFactory.seed = 0

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "artifacts"
DEFAULT_REPORT = Path(__file__).resolve().parent / "reports" / "evaluation.json"


def _read_source_rows(data_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for filename in FILES:
        with (data_dir / filename).open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def _assign_split(row: dict[str, str]) -> str | None:
    event = (row.get("event") or "news").strip().lower()
    source_split = (row.get("split") or "").strip().lower()
    if event == "usa_sandy":
        return "test"
    if event == "pakistan_floods":
        return "validation"
    if source_split == "train":
        return "train"
    return None


def build_event_splits(data_dir: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    """Hold out complete events and drop exact text duplicates across all splits."""
    candidates: list[tuple[str, dict[str, str]]] = []
    for row in _read_source_rows(data_dir):
        split = _assign_split(row)
        text = re.sub(r"\s+", " ", (row.get("message") or "")).strip()
        if split and text and row.get("related") in RELATED_LABELS:
            row["message"] = text
            row["_source"] = "appen"
            candidates.append((split, row))

    india_path = data_dir / CSV_NAME
    india_split_counts = {name: 0 for name in ("train", "validation", "test")}
    india_language_counts = Counter()
    if india_path.is_file():
        india_rows: list[dict[str, str]] = []
        seen_india_text: set[str] = set()
        with india_path.open(encoding="utf-8-sig", newline="") as handle:
            for source_row in csv.DictReader(handle):
                message = re.sub(r"\s+", " ", (source_row.get("Tweet_text") or "")).strip()
                target = (source_row.get("Target") or "").strip()
                if not message or target not in {"0", "1"}:
                    continue
                try:
                    language = detect_langs(message)[0]
                except LangDetectException:
                    india_language_counts["unknown_excluded"] += 1
                    continue
                if language.lang != "en" or language.prob < ENGLISH_DETECTION_MIN_PROBABILITY:
                    india_language_counts["non_english_or_uncertain_excluded"] += 1
                    continue
                india_language_counts["english_kept"] += 1
                key = message.casefold()
                if key in seen_india_text:
                    continue
                seen_india_text.add(key)
                india_rows.append({"message": message, "related": target, "_source": "india"})

        india_labels = [row["related"] for row in india_rows]
        india_train, india_other = train_test_split(
            india_rows,
            test_size=0.30,
            random_state=42,
            stratify=india_labels,
        )
        india_other_labels = [row["related"] for row in india_other]
        india_validation, india_test = train_test_split(
            india_other,
            test_size=0.50,
            random_state=43,
            stratify=india_other_labels,
        )
        for split, rows in (
            ("train", india_train),
            ("validation", india_validation),
            ("test", india_test),
        ):
            india_split_counts[split] = len(rows)
            candidates.extend((split, row) for row in rows)

    priority = {"train": 0, "validation": 1, "test": 2}
    by_text: dict[str, tuple[str, dict[str, str]]] = {}
    duplicate_rows = 0
    for split, row in candidates:
        key = row["message"].casefold()
        current = by_text.get(key)
        if current is None:
            by_text[key] = (split, row)
        else:
            duplicate_rows += 1
            if priority[split] > priority[current[0]]:
                by_text[key] = (split, row)

    splits = {name: [] for name in ("train", "validation", "test")}
    for split, row in by_text.values():
        splits[split].append(row)

    counts = {
        "candidate_rows": len(candidates),
        "exact_duplicate_rows_removed": duplicate_rows,
        **{f"{name}_rows": len(rows) for name, rows in splits.items()},
        "source_rows_by_split": {
            split: dict(Counter(row["_source"] for row in rows))
            for split, rows in splits.items()
        },
        "india_source_rows_before_global_dedup": india_split_counts,
        "india_language_filter": dict(india_language_counts),
    }
    return splits, counts


def build_vectorizer() -> FeatureUnion:
    """Combine word context with character n-grams for noisy, short messages."""
    return FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=2,
                    max_features=150_000,
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=2,
                    max_features=150_000,
                    sublinear_tf=True,
                ),
            ),
        ],
        transformer_weights={"word": 1.0, "char": 0.7},
    )


def _positive_threshold(y_true: np.ndarray, probabilities: np.ndarray) -> tuple[float, str]:
    positives = int(y_true.sum())
    negatives = int(len(y_true) - positives)
    if positives < MIN_VALIDATION_POSITIVE or negatives < MIN_VALIDATION_NEGATIVE:
        return 0.5, "default_0.5_insufficient_validation_examples"

    candidates = np.unique(np.concatenate(([0.05, 0.5, 0.95], probabilities)))
    best = (0.0, 0.5)
    for threshold in candidates:
        score = f1_score(y_true, probabilities >= threshold, zero_division=0)
        if score > best[0] or (score == best[0] and threshold > best[1]):
            best = (float(score), float(threshold))
    return best[1], "validation_event_max_f1"


def _report_binary(y_true: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict:
    predictions = probabilities >= threshold
    return {
        "threshold": round(float(threshold), 6),
        "precision": round(float(precision_score(y_true, predictions, zero_division=0)), 6),
        "recall": round(float(recall_score(y_true, predictions, zero_division=0)), 6),
        "f1": round(float(f1_score(y_true, predictions, zero_division=0)), 6),
        "support_positive": int(y_true.sum()),
    }


def _choose_relevance_review_threshold(
    true_labels: np.ndarray,
    probabilities: np.ndarray,
    classes: np.ndarray,
    *,
    minimum_accuracy: float = 0.90,
    minimum_coverage: float = 0.50,
) -> float:
    """Choose the widest-coverage confidence threshold meeting validation targets."""
    predicted = classes[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)
    candidates = np.unique(np.concatenate(([0.5, 0.8, 0.9, 0.95], confidence)))
    for threshold in candidates:
        accepted = (confidence >= threshold) & (predicted != "2")
        coverage = float(accepted.mean())
        if coverage < minimum_coverage:
            continue
        accuracy = float(np.mean(predicted[accepted] == true_labels[accepted]))
        if accuracy >= minimum_accuracy:
            return float(threshold)
    return 0.95


def _abstention_metrics(
    rows: list[dict[str, str]],
    probabilities: np.ndarray,
    classes: np.ndarray,
    threshold: float,
) -> dict:
    true_labels = np.asarray([row["related"] for row in rows])
    predicted = classes[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)
    accepted = (confidence >= threshold) & (predicted != "2")
    accepted_count = int(accepted.sum())
    return {
        "rows": len(rows),
        "review_threshold": round(float(threshold), 6),
        "accepted_rows": accepted_count,
        "coverage": round(float(accepted.mean()), 6),
        "accepted_accuracy": (
            round(float(np.mean(predicted[accepted] == true_labels[accepted])), 6)
            if accepted_count
            else None
        ),
    }


def _fit_binary_classifier(features, labels: np.ndarray) -> LogisticRegression:
    model = LogisticRegression(C=2.0, max_iter=1000, solver="liblinear", random_state=17)
    return model.fit(features, labels)


def _relevance_metrics(
    rows: list[dict[str, str]],
    predictions: np.ndarray,
    probabilities: np.ndarray,
    classes: np.ndarray,
) -> dict:
    true_labels = np.asarray([row["related"] for row in rows])
    present_labels = np.unique(true_labels)
    report = classification_report(
        true_labels,
        predictions,
        labels=["0", "1", "2"],
        target_names=[RELATED_LABELS[str(label)] for label in ("0", "1", "2")],
        output_dict=True,
        zero_division=0,
    )
    determinate = true_labels != "2"
    binary_true = true_labels[determinate] == "1"
    binary_predictions = predictions[determinate] == "1"
    targets = np.column_stack([true_labels == label for label in classes]).astype(float)
    return {
        "rows": len(rows),
        "accuracy": round(float(accuracy_score(true_labels, predictions)), 6),
        "macro_f1": round(float(f1_score(true_labels, predictions, labels=present_labels, average="macro", zero_division=0)), 6),
        "multiclass_brier_score": round(float(np.square(probabilities - targets).sum(axis=1).mean()), 6),
        "classification_report": report,
        "determinate_binary": {
            "rows": int(determinate.sum()),
            "precision": round(float(precision_score(binary_true, binary_predictions, zero_division=0)), 6),
            "recall": round(float(recall_score(binary_true, binary_predictions, zero_division=0)), 6),
            "f1": round(float(f1_score(binary_true, binary_predictions, zero_division=0)), 6),
        },
    }


def train(data_dir: Path, output_dir: Path, report_path: Path) -> dict:
    splits, split_counts = build_event_splits(data_dir)
    india_path = data_dir / CSV_NAME
    if not india_path.is_file():
        raise FileNotFoundError(
            f"Missing {india_path}; download the pinned India relevance corpus first."
        )
    if not splits["train"] or not splits["validation"] or not splits["test"]:
        raise ValueError(f"Event split is empty: {split_counts}")

    texts = {name: [row["message"] for row in rows] for name, rows in splits.items()}
    vectorizer = build_vectorizer()
    x_train = vectorizer.fit_transform(texts["train"])
    x_validation = vectorizer.transform(texts["validation"])
    x_test = vectorizer.transform(texts["test"])
    y_related = {
        name: np.asarray([row["related"] for row in rows])
        for name, rows in splits.items()
    }
    related_model = LogisticRegression(C=2.0, max_iter=1000, solver="lbfgs", random_state=17)
    related_model.fit(x_train, y_related["train"])
    related_validation_probabilities = related_model.predict_proba(x_validation)
    related_test_probabilities = related_model.predict_proba(x_test)
    related_test_labels = related_model.classes_[related_test_probabilities.argmax(axis=1)]
    appen_validation_indices = [
        i for i, row in enumerate(splits["validation"]) if row["_source"] == "appen"
    ]
    relevance_review_threshold = _choose_relevance_review_threshold(
        y_related["validation"][appen_validation_indices],
        related_validation_probabilities[appen_validation_indices],
        related_model.classes_,
    )
    validation_abstention_by_source = {}
    for source in ("appen", "india"):
        selected = [i for i, row in enumerate(splits["validation"]) if row["_source"] == source]
        if selected:
            validation_abstention_by_source[source] = _abstention_metrics(
                [splits["validation"][i] for i in selected],
                related_validation_probabilities[selected],
                related_model.classes_,
                relevance_review_threshold,
            )
    relevance_by_source = {}
    for source in ("appen", "india"):
        selected = [i for i, row in enumerate(splits["test"]) if row["_source"] == source]
        if selected:
            relevance_by_source[source] = _relevance_metrics(
                [splits["test"][i] for i in selected],
                related_test_labels[selected],
                related_test_probabilities[selected],
                related_model.classes_,
            )

    binary_models: dict[str, LogisticRegression] = {}
    thresholds: dict[str, float] = {}
    threshold_methods: dict[str, str] = {}
    multilabel_reports: dict[str, dict] = {}
    skipped_labels: dict[str, str] = {}
    label_counts: dict[str, dict[str, int]] = {}

    category_rows = {
        split: [row for row in rows if row["_source"] == "appen"]
        for split, rows in splits.items()
    }
    category_features = {
        split: vectorizer.transform([row["message"] for row in rows])
        for split, rows in category_rows.items()
    }
    for label in MULTILABELS:
        train_y = np.asarray([int(row.get(label, "0") or 0) for row in category_rows["train"]])
        validation_y = np.asarray([int(row.get(label, "0") or 0) for row in category_rows["validation"]])
        test_y = np.asarray([int(row.get(label, "0") or 0) for row in category_rows["test"]])
        positives, negatives = int(train_y.sum()), int(len(train_y) - train_y.sum())
        label_counts[label] = {"train_positive": positives, "validation_positive": int(validation_y.sum()), "test_positive": int(test_y.sum())}
        if positives < MIN_POSITIVE or negatives < MIN_NEGATIVE:
            skipped_labels[label] = "insufficient_train_class_examples"
            continue

        classifier = _fit_binary_classifier(category_features["train"], train_y)
        validation_probabilities = classifier.predict_proba(category_features["validation"])[:, 1]
        tuned_threshold, method = _positive_threshold(validation_y, validation_probabilities)
        threshold = max(0.5, tuned_threshold)
        if threshold != tuned_threshold:
            method += "_with_0.5_minimum"
        test_probabilities = classifier.predict_proba(category_features["test"])[:, 1]
        binary_models[label] = classifier
        thresholds[label] = threshold
        threshold_methods[label] = method
        multilabel_reports[label] = _report_binary(test_y, test_probabilities, threshold)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    feature_names = vectorizer.get_feature_names_out()
    bundle = {
        "model_name": MODEL_NAME,
        "scikit_learn_version": sklearn.__version__,
        "vectorizer": vectorizer,
        "feature_names": feature_names,
        "related_model": related_model,
        "binary_models": binary_models,
        "thresholds": thresholds,
        "multilabel_categories": tuple(binary_models),
        "relevance_review_threshold": relevance_review_threshold,
    }
    model_path = output_dir / "model.joblib"
    joblib.dump(bundle, model_path, compress=3)
    model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    dataset_hashes = {
        filename: hashlib.sha256((data_dir / filename).read_bytes()).hexdigest()
        for filename in FILES
    }

    report = {
        "model": MODEL_NAME,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "relevance_sources": [
                {
                    "name": "Disaster Response Messages (Robert Munro)",
                    "commit": "1657e1c4e11acbfa56241d2b5cd627adbd989ca2",
                    "license": "CC BY 4.0",
                    "sha256": dataset_hashes,
                },
                {
                    "name": "Hierarchical Disaster Tweet Classification Corpus (India + Nepal)",
                    "doi": f"10.17632/{DATASET_ID}.{DATASET_VERSION}",
                    "license": "CC BY 4.0",
                    "sha256": hashlib.sha256(india_path.read_bytes()).hexdigest() if india_path.is_file() else None,
                    "usage": "supplemental India relevance labels only",
                },
            ],
            "split_strategy": "event-held-out Appen: train Haiti/news, validate Pakistan, test Sandy; confidently English India tweets: stratified 70/15/15 random split, deduplicated by text",
            **split_counts,
        },
        "training": {
            "vectorizer": "word TF-IDF uni/bi-grams + character 3-5 grams",
            "classifier": "scikit-learn logistic regression",
            "runtime_versions": {
                "python": platform.python_version(),
                "scikit_learn": sklearn.__version__,
                "numpy": np.__version__,
                "joblib": joblib.__version__,
                "langdetect": "1.0.9",
            },
            "feature_count": int(x_train.shape[1]),
            "related_label_counts": dict(Counter(y_related["train"])),
            "multilabel_categories": list(binary_models),
            "skipped_categories": skipped_labels,
            "category_counts": label_counts,
        },
        "evaluation": {
            "disaster_relevance": {
                "validation_abstention": {
                    "threshold_selected_on": "Pakistan event holdout only",
                    "target_accepted_accuracy": 0.90,
                    "minimum_coverage": 0.50,
                    "by_source": validation_abstention_by_source,
                },
                "event_held_out_sandy": relevance_by_source.get("appen"),
                "india_random_holdout": relevance_by_source.get("india"),
                "interpretation": "Keep these dataset-specific results separate; the India split is random and the Sandy split is event-held-out.",
            },
            "multilabel_categories": multilabel_reports,
            "threshold_selection": threshold_methods,
        },
        "artifact": {"path": str(model_path), "sha256": model_sha256, "committed_to_git": False},
        "limitations": [
            "The source is mostly 2010-2012 disaster SMS, message-board posts, and news; it is not a representative sample of current social media.",
            "The India tweet source does not specify a language; high-confidence English-only language detection excludes non-English and uncertain short texts, which may leave language-related selection bias.",
            "The India tweet README does not document annotation procedures, and its public X text requires a separate rights and platform-terms review before product use.",
            "Its labels do not distinguish cyclone from other storms, urban flooding from other floods, or industrial fire from other fires.",
            "It has no general urgency, incident-coordinate, location-mention, or event-time labels.",
            "Event-held-out scores measure transfer to one older event and do not establish readiness for Gujarat operations.",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metadata = {key: value for key, value in report.items() if key != "evaluation"}
    metadata["relevance_classes"] = {
        str(label): RELATED_LABELS[str(label)] for label in related_model.classes_
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Model written: {model_path}")
    print(f"Evaluation report written: {report_path}")
    print(f"Split rows: {split_counts}")
    sandy = report["evaluation"]["disaster_relevance"]["event_held_out_sandy"]
    india = report["evaluation"]["disaster_relevance"]["india_random_holdout"]
    print(f"Sandy event-held-out relevance macro-F1: {sandy['macro_f1']:.3f}")
    print(f"India random-holdout relevance macro-F1: {india['macro_f1']:.3f}")
    print(f"Relevance review threshold: {relevance_review_threshold:.3f}")
    print(f"Trainable multilabel categories: {len(binary_models)}; skipped: {len(skipped_labels)}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    train(args.data_dir, args.output_dir, args.report)


if __name__ == "__main__":
    main()
