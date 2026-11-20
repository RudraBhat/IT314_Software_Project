
import numpy as np
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("langdetect")

from sklearn.linear_model import LogisticRegression  # noqa: E402

from train import _fit_binary_classifier, _report_binary, summarize_multilabel  # noqa: E402


def imbalanced_data():
    """12 positives among 400 negatives, only weakly separable: the situation of a rare category."""
    rng = np.random.default_rng(7)
    negatives = rng.normal(0.0, 1.0, size=(400, 2))
    positives = rng.normal(0.0, 1.0, size=(12, 2)) + np.array([1.5, 0.0])
    features = np.vstack([negatives, positives])
    labels = np.array([0] * 400 + [1] * 12)
    return features, labels, positives


def test_category_heads_use_balanced_class_weights():
    features, labels, positives = imbalanced_data()
    balanced = _fit_binary_classifier(features, labels)
    plain = LogisticRegression(C=2.0, max_iter=1000, solver="liblinear", random_state=17).fit(features, labels)

    assert balanced.class_weight == "balanced"
    # A rare category is scored higher, so it can actually reach the 0.5 candidate threshold.
    assert balanced.predict_proba(positives)[:, 1].mean() > plain.predict_proba(positives)[:, 1].mean()
    assert (balanced.predict_proba(positives)[:, 1] >= 0.5).sum() > (plain.predict_proba(positives)[:, 1] >= 0.5).sum()


def test_binary_report_counts_match_scores():
    y_true = np.array([1, 1, 1, 0, 0, 0])
    probabilities = np.array([0.9, 0.8, 0.1, 0.7, 0.2, 0.1])
    report = _report_binary(y_true, probabilities, 0.5)
    assert (report["true_positive"], report["false_positive"], report["false_negative"]) == (2, 1, 1)
    assert report["support_positive"] == 3
    assert report["precision"] == pytest.approx(2 / 3, abs=1e-6)
    assert report["recall"] == pytest.approx(2 / 3, abs=1e-6)


def test_multilabel_summary_aggregates_only_categories_with_positives():
    reports = {
        "water": {"f1": 0.6, "support_positive": 40, "true_positive": 30, "false_positive": 10, "false_negative": 10},
        "floods": {"f1": 0.0, "support_positive": 16, "true_positive": 0, "false_positive": 0, "false_negative": 16},
        "hospitals": {"f1": 0.0, "support_positive": 0, "true_positive": 0, "false_positive": 2, "false_negative": 0},
    }
    summary = summarize_multilabel(reports)
    assert summary["categories_trained"] == 3
    assert summary["categories_with_test_positives"] == 2
    assert summary["categories_with_zero_f1"] == ["floods"]
    assert summary["macro_f1"] == pytest.approx(0.3)
    assert summary["micro_precision"] == pytest.approx(30 / 42, abs=1e-5)
    assert summary["micro_recall"] == pytest.approx(30 / 56, abs=1e-5)
    assert summary["micro_f1"] == pytest.approx(60 / 98, abs=1e-5)


def test_multilabel_summary_handles_nothing_to_score():
    summary = summarize_multilabel({})
    assert summary["macro_f1"] is None and summary["micro_f1"] == 0.0 and summary["categories_with_zero_f1"] == []
