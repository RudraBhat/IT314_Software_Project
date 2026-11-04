"""Validate the text dataset CSV. Run: python data/validate_dataset.py data/text_dataset.csv

Checks the schema, duplicate texts, synthetic rows in test and event_id leakage across splits.
Exit code 1 if anything is wrong, so it can run in CI.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter, defaultdict

LABELS = ("cyclone", "flood", "fire", "earthquake", "other_disaster", "not_disaster")
LANGS = ("en", "hi", "gu")
COLUMNS = ("text", "label", "lang", "source", "synthetic", "event_id")


def assign_split(event_id: str, synthetic: bool, test_pct: int = 20, val_pct: int = 10) -> str:
    """Deterministic split by event_id so an event or template stays together. Synthetic rows are train only."""
    if synthetic:
        return "train"
    bucket = int(hashlib.sha256(event_id.encode()).hexdigest(), 16) % 100
    return "test" if bucket < test_pct else "val" if bucket < test_pct + val_pct else "train"


def is_synthetic(row: dict) -> bool:
    return (row["synthetic"] or "").strip().lower() == "true"


def load(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"missing columns: {', '.join(missing)}")
        return list(reader)


def validate(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, int] = {}
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        text = (r["text"] or "").strip()
        if not text:
            errors.append(f"row {i}: empty text")
        if r["label"] not in LABELS:
            errors.append(f"row {i}: label {r['label']!r} not in {LABELS}")
        if r["lang"] not in LANGS:
            errors.append(f"row {i}: lang {r['lang']!r} not in {LANGS}")
        if not (r["source"] or "").strip():
            errors.append(f"row {i}: source is empty")
        if (r["synthetic"] or "").strip().lower() not in ("true", "false"):
            errors.append(f"row {i}: synthetic must be true or false")
        if not (r["event_id"] or "").strip():
            errors.append(f"row {i}: event_id is empty")
        key = " ".join(text.lower().split())
        if key in seen:
            errors.append(f"row {i}: duplicate of row {seen[key]}")
        seen.setdefault(key, i)
    return errors


def leakage(rows: list[dict]) -> list[str]:
    """An event_id must not appear in more than one split, and test must be human-written."""
    errors: list[str] = []
    splits: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        split = assign_split(r["event_id"], is_synthetic(r))
        if split == "test" and is_synthetic(r):
            errors.append(f"synthetic row in test: {r['text'][:40]!r}")
        splits[r["event_id"]].add(split)
    errors += [f"event_id {e!r} appears in {sorted(s)}" for e, s in splits.items() if len(s) > 1]
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    rows = load(parser.parse_args().csv_path)
    errors = validate(rows) + leakage(rows)
    splits = [assign_split(r["event_id"], is_synthetic(r)) for r in rows]
    test_per_class = Counter(r["label"] for r, s in zip(rows, splits) if s == "test")
    print(f"{len(rows)} rows; split sizes {dict(Counter(splits))}; test per class {dict(test_per_class)}")
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
