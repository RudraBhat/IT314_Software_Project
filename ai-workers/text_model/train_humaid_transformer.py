"""Fine-tune a Twitter-pretrained encoder on event-held-out HumAID labels.

HumAID text is for humanitarian-computing research and must remain local. This
script writes only aggregate metrics and model files; it never writes tweets or
tweet IDs into the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import accuracy_score, classification_report, f1_score
from torch.nn import functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup


DATASET_ID = "QCRI/HumAID-events"
DATASET_REVISION = "2e7ea23332006f075068b90d401b178d847b447a"
BASE_MODEL_ID = "vinai/bertweet-base"
BASE_MODEL_REVISION = "b349c1243407b0dcffeabb2337497477286e27ab"
MODEL_NAME = "resq-english-humanitarian-bertweet-v1"
HANDLE_PATTERN = re.compile(r"(?<!\w)@[A-Za-z0-9_]+")
URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)\S+")

SET1_EVENTS = (
    "canada_wildfires_2016",
    "cyclone_idai_2019",
    "ecuador_earthquake_2016",
    "greece_wildfires_2018",
    "hurricane_harvey_2017",
    "hurricane_irma_2017",
    "hurricane_maria_2017",
    "hurricane_matthew_2016",
    "italy_earthquake_aug_2016",
    "kaikoura_earthquake_2016",
    "maryland_floods_2018",
    "puebla_mexico_earthquake_2017",
    "srilanka_floods_2017",
)
# No event in either group contributes examples to model fitting.
VALIDATION_EVENTS = ("ecuador_earthquake_2016", "hurricane_matthew_2016")
TEST_EVENTS = ("cyclone_idai_2019", "greece_wildfires_2018", "srilanka_floods_2017")

LABELS = (
    "caution_and_advice",
    "displaced_people_and_evacuations",
    "infrastructure_and_utility_damage",
    "injured_or_dead_people",
    "missing_or_found_people",
    "not_humanitarian",
    "other_relevant_information",
    "requests_or_urgent_needs",
    "rescue_volunteering_or_donation_effort",
    "sympathy_and_support",
)
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
ID_TO_LABEL = {index: label for label, index in LABEL_TO_ID.items()}

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = MODULE_DIR / "data" / "external" / "humaid_events"
DEFAULT_OUTPUT_DIR = MODULE_DIR / "artifacts" / "humaid_bertweet"
DEFAULT_REPORT = MODULE_DIR / "reports" / "humaid_transformer_evaluation.json"


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _split_for_event(event: str) -> str:
    if event in TEST_EVENTS:
        return "test"
    if event in VALIDATION_EVENTS:
        return "validation"
    return "train"


def preprocess_tweet(text: str) -> str:
    """Apply the BERTweet model card's handle and URL placeholders."""
    text = URL_PATTERN.sub("http", text)
    return HANDLE_PATTERN.sub("@user", text)


def load_event_splits(data_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load set 1 and deduplicate by tweet ID/text, preserving held-out events."""
    candidates: list[tuple[str, dict[str, Any]]] = []
    for event in SET1_EVENTS:
        event_dir = data_dir / event
        for split_path in sorted(event_dir.glob("*.json")):
            if split_path.stem not in {"train", "dev", "test"}:
                continue
            with split_path.open(encoding="utf-8") as handle:
                source_rows = json.load(handle)
            for source_row in source_rows:
                text = re.sub(
                    r"\s+",
                    " ",
                    preprocess_tweet(str(source_row.get("tweet_text") or "")),
                ).strip()
                label = str(source_row.get("class_label") or "").strip()
                if not text or label not in LABEL_TO_ID:
                    continue
                candidates.append(
                    (
                        _split_for_event(event),
                        {
                            "event": event,
                            "text": text,
                            "label": label,
                            "tweet_id": str(source_row.get("tweet_id") or ""),
                        },
                    )
                )

    priority = {"train": 0, "validation": 1, "test": 2}
    candidates.sort(
        key=lambda item: (
            -priority[item[0]],
            item[1]["event"],
            item[1]["tweet_id"],
            item[1]["text"].casefold(),
        )
    )
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    rows_by_split = {name: [] for name in ("train", "validation", "test")}
    duplicate_count = 0
    conflicting_duplicate_count = 0
    seen_labels_by_text: dict[str, str] = {}
    for split, row in candidates:
        text_key = row["text"].casefold()
        tweet_id = row["tweet_id"]
        if (tweet_id and tweet_id in seen_ids) or text_key in seen_text:
            duplicate_count += 1
            prior_label = seen_labels_by_text.get(text_key)
            if prior_label is not None and prior_label != row["label"]:
                conflicting_duplicate_count += 1
            continue
        if tweet_id:
            seen_ids.add(tweet_id)
        seen_text.add(text_key)
        seen_labels_by_text[text_key] = row["label"]
        rows_by_split[split].append(row)

    for split, rows in rows_by_split.items():
        if not rows:
            raise ValueError(f"HumAID {split} split is empty; check the local set 1 files.")

    counts = {
        "dataset": DATASET_ID,
        "dataset_revision": DATASET_REVISION,
        "set1_events": list(SET1_EVENTS),
        "validation_events": list(VALIDATION_EVENTS),
        "test_events": list(TEST_EVENTS),
        "rows_by_split": {name: len(rows) for name, rows in rows_by_split.items()},
        "event_rows": {
            split: dict(Counter(row["event"] for row in rows))
            for split, rows in rows_by_split.items()
        },
        "duplicate_rows_removed": duplicate_count,
        "duplicate_label_conflicts_removed": conflicting_duplicate_count,
        "labels": {
            split: dict(Counter(row["label"] for row in rows))
            for split, rows in rows_by_split.items()
        },
    }
    return rows_by_split, counts


def _device_from_arg(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _encode_batch(tokenizer, rows: list[dict[str, Any]], device: torch.device, max_length: int):
    encoded = tokenizer(
        [row["text"] for row in rows],
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    return {key: value.to(device) for key, value in encoded.items()}


@torch.inference_mode()
def predict_probabilities(model, tokenizer, rows, device, *, batch_size: int, max_length: int):
    model.eval()
    batches: list[np.ndarray] = []
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        encoded = _encode_batch(tokenizer, batch, device, max_length)
        logits = model(**encoded).logits
        batches.append(torch.softmax(logits, dim=-1).float().cpu().numpy())
    return np.concatenate(batches, axis=0)


def _metrics(rows, probabilities) -> dict[str, Any]:
    y_true = np.asarray([LABEL_TO_ID[row["label"]] for row in rows])
    y_pred = probabilities.argmax(axis=1)
    return {
        "rows": len(rows),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 6),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=list(range(len(LABELS))), average="macro", zero_division=0)), 6),
        "weighted_f1": round(float(f1_score(y_true, y_pred, labels=list(range(len(LABELS))), average="weighted", zero_division=0)), 6),
        "classification_report": classification_report(
            y_true,
            y_pred,
            labels=list(range(len(LABELS))),
            target_names=list(LABELS),
            output_dict=True,
            zero_division=0,
        ),
    }


def _choose_review_threshold(rows, probabilities, *, min_accuracy: float, min_coverage: float) -> dict[str, float] | None:
    y_true = np.asarray([LABEL_TO_ID[row["label"]] for row in rows])
    y_pred = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    best = None
    for threshold in np.unique(confidence):
        accepted = confidence >= threshold
        coverage = float(accepted.mean())
        if coverage < min_coverage:
            continue
        accepted_accuracy = float(accuracy_score(y_true[accepted], y_pred[accepted]))
        if accepted_accuracy >= min_accuracy and (best is None or coverage > best["coverage"]):
            best = {
                "threshold": round(float(threshold), 6),
                "coverage": round(coverage, 6),
                "accepted_accuracy": round(accepted_accuracy, 6),
            }
    return best


def train(
    data_dir: Path,
    output_dir: Path,
    report_path: Path,
    *,
    epochs: int = 2,
    batch_size: int = 16,
    max_length: int = 128,
    learning_rate: float = 2e-5,
    device_name: str = "auto",
    seed: int = 17,
) -> dict[str, Any]:
    seed_everything(seed)
    device = _device_from_arg(device_name)
    if device.type == "cpu":
        torch.set_num_threads(min(6, max(1, os.cpu_count() or 4)))

    splits, split_counts = load_event_splits(data_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL_ID,
        revision=BASE_MODEL_REVISION,
        normalization=True,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL_ID,
        revision=BASE_MODEL_REVISION,
        num_labels=len(LABELS),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    ).to(device)

    train_rows = splits["train"]
    train_labels = np.asarray([LABEL_TO_ID[row["label"]] for row in train_rows])
    label_counts = np.bincount(train_labels, minlength=len(LABELS))
    if np.any(label_counts == 0):
        raise ValueError("At least one HumAID label is absent from the training event groups.")
    class_weights = (label_counts.max() / label_counts.astype(float)) ** 0.35
    class_weights = class_weights / class_weights.mean()
    class_weights_tensor = torch.tensor(class_weights, dtype=torch.float32, device=device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    total_steps = epochs * ((len(train_rows) + batch_size - 1) // batch_size)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=max(1, int(total_steps * 0.06)),
        num_training_steps=total_steps,
    )

    best_val_macro_f1 = -1.0
    best_epoch = 0
    epoch_rows: list[dict[str, Any]] = []
    started = time.monotonic()
    for epoch in range(1, epochs + 1):
        model.train()
        order = np.random.permutation(len(train_rows))
        cumulative_loss = 0.0
        steps = 0
        for start in range(0, len(order), batch_size):
            batch = [train_rows[int(index)] for index in order[start : start + batch_size]]
            encoded = _encode_batch(tokenizer, batch, device, max_length)
            labels = torch.tensor(
                [LABEL_TO_ID[row["label"]] for row in batch],
                dtype=torch.long,
                device=device,
            )
            optimizer.zero_grad(set_to_none=True)
            logits = model(**encoded).logits
            loss = F.cross_entropy(logits, labels, weight=class_weights_tensor)
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss while fine-tuning BERTweet.")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            cumulative_loss += float(loss.detach().cpu())
            steps += 1
            if steps % 200 == 0:
                elapsed = round(time.monotonic() - started, 1)
                print(
                    f"epoch={epoch}/{epochs} step={steps} loss={cumulative_loss / steps:.4f} elapsed_s={elapsed}",
                    flush=True,
                )

        val_probabilities = predict_probabilities(
            model,
            tokenizer,
            splits["validation"],
            device,
            batch_size=batch_size,
            max_length=max_length,
        )
        val_metrics = _metrics(splits["validation"], val_probabilities)
        epoch_record = {
            "epoch": epoch,
            "training_loss": round(cumulative_loss / max(steps, 1), 6),
            "validation_macro_f1": val_metrics["macro_f1"],
            "validation_accuracy": val_metrics["accuracy"],
        }
        epoch_rows.append(epoch_record)
        print(f"validation_epoch={json.dumps(epoch_record, sort_keys=True)}", flush=True)
        if val_metrics["macro_f1"] > best_val_macro_f1:
            best_val_macro_f1 = val_metrics["macro_f1"]
            best_epoch = epoch
            output_dir.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(output_dir, safe_serialization=True)
            tokenizer.save_pretrained(output_dir)

    del model
    model = AutoModelForSequenceClassification.from_pretrained(output_dir).to(device)
    validation_probabilities = predict_probabilities(
        model,
        tokenizer,
        splits["validation"],
        device,
        batch_size=batch_size,
        max_length=max_length,
    )
    review_gate = _choose_review_threshold(
        splits["validation"],
        validation_probabilities,
        min_accuracy=0.90,
        min_coverage=0.20,
    )
    test_probabilities = predict_probabilities(
        model,
        tokenizer,
        splits["test"],
        device,
        batch_size=batch_size,
        max_length=max_length,
    )
    test_metrics = _metrics(splits["test"], test_probabilities)
    y_pred = test_probabilities.argmax(axis=1)
    by_event = {}
    for event in TEST_EVENTS:
        indices = [index for index, row in enumerate(splits["test"]) if row["event"] == event]
        if indices:
            by_event[event] = _metrics(
                [splits["test"][index] for index in indices],
                test_probabilities[indices],
            )
    test_metrics["by_event"] = by_event
    if review_gate is not None:
        confidence = test_probabilities.max(axis=1)
        accepted = confidence >= review_gate["threshold"]
        y_true = np.asarray([LABEL_TO_ID[row["label"]] for row in splits["test"]])
        test_metrics["validation_selected_review_gate"] = {
            **review_gate,
            "test_coverage": round(float(accepted.mean()), 6),
            "test_accepted_accuracy": round(float(accuracy_score(y_true[accepted], y_pred[accepted])), 6),
        }
    else:
        test_metrics["validation_selected_review_gate"] = None

    weight_files = sorted(output_dir.glob("*.safetensors"))
    artifact_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in weight_files
    }
    report = {
        "model": MODEL_NAME,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "base_model": {"id": BASE_MODEL_ID, "revision": BASE_MODEL_REVISION, "license": "MIT"},
        "dataset": split_counts,
        "training": {
            "preprocessing": "BERTweet tokenizer normalization; @handles -> @user; URLs -> http",
            "device": str(device),
            "torch_version": torch.__version__,
            "epochs_requested": epochs,
            "best_epoch_by_validation_macro_f1": best_epoch,
            "epoch_metrics": epoch_rows,
            "batch_size": batch_size,
            "max_length": max_length,
            "learning_rate": learning_rate,
            "class_weight_power": 0.35,
            "seed": seed,
        },
        "evaluation": {
            "validation": _metrics(splits["validation"], validation_probabilities),
            "event_held_out_test": test_metrics,
            "review_gate_selection": "widest validation confidence coverage with at least 90% accuracy and at least 20% coverage",
        },
        "artifact": {"path": str(output_dir), "sha256": artifact_hashes, "committed_to_git": False},
        "limits": [
            "HumAID labels humanitarian information type, not the project's exact three operational scenarios or dispatch urgency.",
            "This evaluation tests transfer to three held-out events from the same research corpus; it is not a Gujarat or current-live-feed evaluation.",
            "The source dataset is licensed CC BY-NC-SA 4.0 and its terms restrict use to humanitarian-computing research; do not ship its trained weights without a separate rights review.",
            "Confidence and evidence are model signals, not proof that a report is true or current.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    model_metadata = {
        "model": MODEL_NAME,
        "base_model": BASE_MODEL_ID,
        "base_model_revision": BASE_MODEL_REVISION,
        "dataset": DATASET_ID,
        "dataset_revision": DATASET_REVISION,
        "labels": list(LABELS),
        "max_length": max_length,
        "review_threshold": review_gate["threshold"] if review_gate else 1.01,
        "human_review_required": True,
        "evaluation_report": str(report_path),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(model_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "final_test="
        + json.dumps(
            {
                "rows": test_metrics["rows"],
                "macro_f1": test_metrics["macro_f1"],
                "weighted_f1": test_metrics["weighted_f1"],
                "accuracy": test_metrics["accuracy"],
                "review_gate": test_metrics["validation_selected_review_gate"],
                "report": str(report_path),
                "artifact": str(output_dir),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    train(
        args.data_dir,
        args.output_dir,
        args.report,
        epochs=args.epochs,
        batch_size=args.batch_size,
        max_length=args.max_length,
        learning_rate=args.learning_rate,
        device_name=args.device,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
