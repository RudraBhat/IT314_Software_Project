"""Build a TF-IDF reference score on the same event split as BERTweet."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion

from text_model.train_humaid_transformer import (
    DEFAULT_DATA_DIR,
    LABELS,
    LABEL_TO_ID,
    TEST_EVENTS,
    _choose_review_threshold,
    _metrics,
    load_event_splits,
)


def build_vectorizer() -> FeatureUnion:
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


def main() -> None:
    splits, split_counts = load_event_splits(DEFAULT_DATA_DIR)
    vectorizer = build_vectorizer()
    x_train = vectorizer.fit_transform([row["text"] for row in splits["train"]])
    x_validation = vectorizer.transform([row["text"] for row in splits["validation"]])
    x_test = vectorizer.transform([row["text"] for row in splits["test"]])
    y_train = np.asarray([LABEL_TO_ID[row["label"]] for row in splits["train"]])
    y_validation = np.asarray([LABEL_TO_ID[row["label"]] for row in splits["validation"]])

    candidates = []
    for c_value in (0.5, 2.0, 8.0):
        for class_weight in (None, "balanced"):
            classifier = LogisticRegression(
                C=c_value,
                class_weight=class_weight,
                max_iter=1000,
                solver="lbfgs",
                random_state=17,
            )
            classifier.fit(x_train, y_train)
            validation_probabilities = classifier.predict_proba(x_validation)
            validation_metrics = _metrics(splits["validation"], validation_probabilities)
            candidates.append(
                {
                    "C": c_value,
                    "class_weight": class_weight,
                    "validation_macro_f1": validation_metrics["macro_f1"],
                    "validation_accuracy": validation_metrics["accuracy"],
                    "classifier": classifier,
                }
            )

    best = max(
        candidates,
        key=lambda row: (row["validation_macro_f1"], row["validation_accuracy"]),
    )
    classifier = best["classifier"]
    validation_probabilities = classifier.predict_proba(x_validation)
    test_probabilities = classifier.predict_proba(x_test)
    test_metrics = _metrics(splits["test"], test_probabilities)
    test_metrics["by_event"] = {}
    for event in TEST_EVENTS:
        indices = [index for index, row in enumerate(splits["test"]) if row["event"] == event]
        if indices:
            test_metrics["by_event"][event] = _metrics(
                [splits["test"][index] for index in indices],
                test_probabilities[indices],
            )

    review_gate = _choose_review_threshold(
        splits["validation"], validation_probabilities, min_accuracy=0.90, min_coverage=0.20
    )
    if review_gate is not None:
        y_test = np.asarray([LABEL_TO_ID[row["label"]] for row in splits["test"]])
        accepted = test_probabilities.max(axis=1) >= review_gate["threshold"]
        test_metrics["validation_selected_review_gate"] = {
            **review_gate,
            "test_coverage": round(float(accepted.mean()), 6),
            "test_accepted_accuracy": round(
                float((y_test[accepted] == test_probabilities[accepted].argmax(axis=1)).mean()), 6
            ),
        }

    report = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset": split_counts,
        "model": "tfidf-word-char-logistic-reference",
        "selection": {
            "criterion": "validation macro-F1, then validation accuracy",
            "candidate_count": len(candidates),
            "best_C": best["C"],
            "best_class_weight": best["class_weight"],
            "validation_macro_f1": best["validation_macro_f1"],
            "validation_accuracy": best["validation_accuracy"],
        },
        "event_held_out_test": test_metrics,
        "comparison_note": "Use this reference for the BERTweet result with the same revision, event split, and labels. Neither is an operational DRCH validation.",
    }
    report_path = Path(__file__).resolve().parent / "reports" / "humaid_tfidf_evaluation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "rows": test_metrics["rows"],
                "macro_f1": test_metrics["macro_f1"],
                "weighted_f1": test_metrics["weighted_f1"],
                "accuracy": test_metrics["accuracy"],
                "validation_selected_review_gate": test_metrics.get("validation_selected_review_gate"),
                "report": str(report_path),
                "labels": len(LABELS),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
