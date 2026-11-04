import os

import pytest

pytest.importorskip("sklearn")

from data.validate_dataset import LABELS, assign_split, leakage, load, validate  # noqa: E402
from eval.baselines import evaluate, rules_predict  # noqa: E402


def row(text, label="flood", event="e1", synthetic="false", lang="en"):
    return {"text": text, "label": label, "lang": lang, "source": "team-written", "synthetic": synthetic, "event_id": event}


def test_valid_rows_pass_and_bad_rows_fail():
    assert validate([row("water in homes")]) == []
    errors = validate([row("a", label="tsunami"), row("a", lang="fr"), row("b", event="")])
    assert any("label" in e for e in errors) and any("lang" in e for e in errors) and any("event_id" in e for e in errors)
    assert any("duplicate" in e for e in errors)


def test_synthetic_rows_never_land_in_test():
    assert all(assign_split(f"e{i}", synthetic=True) == "train" for i in range(200))


def test_same_event_never_crosses_splits():
    rows = [row(f"text {i}", event=f"e{i % 17}") for i in range(100)]
    assert leakage(rows) == []


def test_assign_split_is_deterministic():
    assert assign_split("event-42", False) == assign_split("event-42", False)


def test_rules_baseline_maps_to_labels():
    assert rules_predict(["flood water level rising, drain overflow", "factory fire and gas leak", "just my opinion"]) == ["flood", "fire", "other_disaster"]


def test_baseline_table_runs_on_a_small_dataset():
    samples = {
        "flood": "water flood rooftop stranded river overflow",
        "fire": "factory fire blaze explosion smoke",
        "cyclone": "cyclone storm wind surge coastal",
        "not_disaster": "my opinion on the budget and cricket",
    }
    rows = [row(f"{t} report {i}", label=l, event=f"ev-{l}-{i}") for l, t in samples.items() for i in range(40)]
    results = evaluate(rows, "val")
    assert set(results) == {"rules", "tfidf_lr_v0"}
    assert 0.0 <= results["tfidf_lr_v0"]["macro_f1"] <= 1.0
    assert set(results["rules"]["per_class"]) == set(LABELS)


def test_template_loads_and_validates():
    rows = load(os.path.join(os.path.dirname(__file__), "..", "data", "text_dataset_template.csv"))
    assert validate(rows) == []
