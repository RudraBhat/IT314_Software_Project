"""Baseline text classifiers and evaluation harness (S1-12).

One command prints the baseline table on the validation split:
    python eval/baselines.py data/text_dataset.csv --split val

Baselines: the keyword rules from rules.py and TF-IDF + logistic regression (v0).
Reports macro-F1, per-class precision and recall, the confusion matrix, per-language macro-F1 and latency.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402

from data.validate_dataset import LABELS, assign_split, is_synthetic, load  # noqa: E402
from rules import triage  # noqa: E402

# The rules only know the three supported scenarios; anything else is reported as other_disaster.
RULES_TO_LABEL = {"CYCLONE": "cyclone", "URBAN_FLOODING": "flood", "INDUSTRIAL_FIRE": "fire", "OTHER": "other_disaster"}


def rules_predict(texts: list[str]) -> list[str]:
    return [RULES_TO_LABEL[triage({"description": t})["scenario"]] for t in texts]


def make_tfidf_lr():
    return make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )


def split_rows(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for r in rows:
        out[assign_split(r["event_id"], is_synthetic(r))].append(r)
    return out


def metrics(y_true: list[str], y_pred: list[str], langs: list[str], elapsed: float) -> dict:
    labels = list(LABELS)
    p, r, _, support = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    per_lang = {}
    for lang in sorted(set(langs)):
        idx = [i for i, g in enumerate(langs) if g == lang]
        per_lang[lang] = round(f1_score([y_true[i] for i in idx], [y_pred[i] for i in idx], labels=labels, average="macro", zero_division=0), 3)
    return {
        "macro_f1": round(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0), 3),
        "per_class": {l: {"precision": round(a, 3), "recall": round(b, 3), "support": int(s)} for l, a, b, s in zip(LABELS, p, r, support)},
        "confusion": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "per_language_macro_f1": per_lang,
        "ms_per_text": round(1000 * elapsed / max(len(y_true), 1), 3),
    }


def evaluate(rows: list[dict], split: str = "val") -> dict[str, dict]:
    parts = split_rows([r for r in rows if r["label"] in LABELS])
    train, target = parts["train"], parts[split]
    if not train or not target:
        raise SystemExit(f"need rows in train and {split}; got {len(train)} and {len(target)}")
    texts = [r["text"] for r in target]
    y_true, langs = [r["label"] for r in target], [r["lang"] for r in target]

    t0 = time.perf_counter()
    rules_pred = rules_predict(texts)
    rules_time = time.perf_counter() - t0

    model = make_tfidf_lr().fit([r["text"] for r in train], [r["label"] for r in train])
    t0 = time.perf_counter()
    lr_pred = list(model.predict(texts))
    lr_time = time.perf_counter() - t0
    return {"rules": metrics(y_true, rules_pred, langs, rules_time), "tfidf_lr_v0": metrics(y_true, lr_pred, langs, lr_time)}


def print_table(results: dict[str, dict], split: str) -> None:
    print(f"Baselines on the {split} split")
    print(f"{'model':<14}{'macro-F1':>10}{'ms/text':>10}")
    for name, m in results.items():
        print(f"{name:<14}{m['macro_f1']:>10}{m['ms_per_text']:>10}")
    for name, m in results.items():
        print(f"\n{name}: per-class")
        for label, c in m["per_class"].items():
            print(f"  {label:<15} P={c['precision']:<6} R={c['recall']:<6} n={c['support']}")
        print(f"  per-language macro-F1: {m['per_language_macro_f1']}")
        print("  confusion matrix (rows=true, cols=pred, order=" + ",".join(LABELS) + ")")
        for row in m["confusion"]:
            print("   ", row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--split", choices=("val", "test"), default="val")
    args = parser.parse_args()
    print_table(evaluate(load(args.csv_path), args.split), args.split)


if __name__ == "__main__":
    main()
