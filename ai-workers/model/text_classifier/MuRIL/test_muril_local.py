#!/usr/bin/env python3
"""
Evaluate a locally fine-tuned MuRIL classifier against a labelled CSV.

Default:
    python test_muril_local.py

Expected files in the current folder:
    muril_disaster_classifier_best.zip
    tweets_multilingual.csv

The script:
- safely extracts the model ZIP to a local cache folder;
- loads the fine-tuned AutoModelForSequenceClassification and tokenizer;
- predicts in batches on CPU by default (use --device cuda if available);
- maps Hurricane -> Cyclone for the five-class model taxonomy;
- reports accuracy, macro/weighted F1, precision, recall, classification report,
  confusion matrix, language-wise metrics and unaugmented-only metrics;
- saves detailed row-level predictions and reports under muril_local_test_results/.

The supplied original test CSV has no genuine Fire examples. Fire support will be
zero in the test report; this script does not fabricate Fire test examples.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)
from transformers import AutoModelForSequenceClassification, AutoTokenizer


LABELS = ["Fire", "Earthquake", "Cyclone", "Flood", "Non-Disaster"]
DEFAULT_MODEL_ZIP = "muril_disaster_classifier_best.zip"
DEFAULT_TEST_CSV = "tweets_multilingual.csv"
DEFAULT_OUTPUT_DIR = "muril_local_test_results"
DEFAULT_MAX_LENGTH = 192  # Matches the MuRIL training notebook.
LABEL_NORMALIZATION = {
    "fire": "Fire",
    "earthquake": "Earthquake",
    "cyclone": "Cyclone",
    "hurricane": "Cyclone",
    "flood": "Flood",
    "non-disaster": "Non-Disaster",
    "nondisaster": "Non-Disaster",
    "non_disaster": "Non-Disaster",
}


def normalize_label(value: Any) -> str:
    raw = str(value).strip()
    return LABEL_NORMALIZATION.get(raw.lower(), raw)


def safe_extract_zip(zip_path: Path, extract_dir: Path) -> None:
    """Extract ZIP while rejecting paths that escape the extraction directory."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    root = extract_dir.resolve()

    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = (extract_dir / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Unsafe ZIP path detected: {member.filename}")
        archive.extractall(extract_dir)


def find_model_dir(extract_dir: Path) -> Path:
    """Find the checkpoint directory containing config and model weights."""
    candidates = []
    for config_path in extract_dir.rglob("config.json"):
        folder = config_path.parent
        has_weights = (
            (folder / "model.safetensors").exists()
            or (folder / "pytorch_model.bin").exists()
            or any(folder.glob("model-*.safetensors"))
            or any(folder.glob("pytorch_model-*.bin"))
        )
        if has_weights:
            candidates.append(folder)

    if not candidates:
        raise FileNotFoundError(
            "Could not find a Hugging Face model checkpoint in the ZIP. "
            "Expected config.json plus model.safetensors or pytorch_model.bin."
        )

    # Prefer the folder that also has the training notebook's label_mapping.json.
    candidates.sort(key=lambda p: (not (p / "label_mapping.json").exists(), len(p.parts)))
    return candidates[0]


def get_id2label(model_dir: Path, model_config: Any) -> dict[int, str]:
    """Read and validate label order from checkpoint metadata."""
    mapping_path = model_dir / "label_mapping.json"
    mapping: dict[str, Any] = {}

    if mapping_path.exists():
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)

    raw = mapping.get("id2label") or getattr(model_config, "id2label", {})
    result: dict[int, str] = {}

    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                result[int(key)] = str(value)
            except (TypeError, ValueError):
                continue

    if not result:
        raise ValueError(
            "Could not read id2label from label_mapping.json or model config."
        )

    expected = {i: label for i, label in enumerate(LABELS)}
    if result != expected:
        raise ValueError(
            "Checkpoint label order does not match this evaluation script.\n"
            f"Expected: {expected}\nFound: {result}\n"
            "Do not evaluate until the label mapping is corrected."
        )

    return result


def select_device(device_arg: str) -> torch.device:
    if device_arg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device_arg == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but no CUDA GPU is available.")
    return torch.device(device_arg)


@torch.inference_mode()
def predict_batches(
    texts: list[str],
    tokenizer: Any,
    model: Any,
    device: torch.device,
    batch_size: int,
    max_length: int,
) -> tuple[list[str], list[float], dict[str, list[float]]]:
    model.eval()
    all_predictions: list[str] = []
    all_confidences: list[float] = []
    all_probabilities = {label: [] for label in LABELS}

    for start in range(0, len(texts), batch_size):
        batch_texts = texts[start : start + batch_size]
        encoded = tokenizer(
            batch_texts,
            truncation=True,
            max_length=max_length,
            padding=True,
            return_tensors="pt",
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}

        outputs = model(**encoded)
        probabilities = torch.softmax(outputs.logits.float(), dim=-1)
        confidence, predicted_ids = torch.max(probabilities, dim=-1)

        predicted_ids = predicted_ids.cpu().tolist()
        confidence = confidence.cpu().tolist()
        probabilities = probabilities.cpu().numpy()

        for row_idx, label_id in enumerate(predicted_ids):
            all_predictions.append(LABELS[int(label_id)])
            all_confidences.append(float(confidence[row_idx]))
            for class_idx, label in enumerate(LABELS):
                all_probabilities[label].append(float(probabilities[row_idx, class_idx]))

        done = min(start + len(batch_texts), len(texts))
        print(f"\rPredicted {done}/{len(texts)}", end="", flush=True)

    print()
    return all_predictions, all_confidences, all_probabilities


def calculate_metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    present = [label for label in LABELS if label in set(y_true)]
    return {
        "rows": len(y_true),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        # Fair summary for the original test file: averages labels that have test support.
        "macro_f1_present_classes": float(
            f1_score(y_true, y_pred, labels=present, average="macro", zero_division=0)
        ),
        # Fixed five-class macro F1: absent Fire support counts as zero.
        "macro_f1_all_five_classes": float(
            f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)
        ),
        "weighted_f1": float(
            f1_score(y_true, y_pred, labels=LABELS, average="weighted", zero_division=0)
        ),
        "classes_with_test_support": present,
    }


def report_subset(
    name: str,
    frame: pd.DataFrame,
    report_lines: list[str],
) -> None:
    if frame.empty:
        report_lines.extend([f"\n{name}", "No rows in this subset."])
        return

    y_true = frame["actual_label"].tolist()
    y_pred = frame["predicted_label"].tolist()
    metrics = calculate_metrics(y_true, y_pred)

    report_lines.extend([
        f"\n{name}",
        json.dumps(metrics, indent=2, ensure_ascii=False),
        classification_report(
            y_true,
            y_pred,
            labels=LABELS,
            target_names=LABELS,
            digits=4,
            zero_division=0,
        ),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a local fine-tuned MuRIL ZIP on tweets_multilingual.csv."
    )
    parser.add_argument("--model-zip", default=DEFAULT_MODEL_ZIP)
    parser.add_argument("--test-csv", default=DEFAULT_TEST_CSV)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument("--limit", type=int, default=0, help="Only test first N rows; 0 means all.")
    args = parser.parse_args()

    model_zip = Path(args.model_zip)
    test_csv = Path(args.test_csv)
    output_dir = Path(args.output_dir)

    if not model_zip.is_file():
        print(f"ERROR: model ZIP not found: {model_zip.resolve()}", file=sys.stderr)
        return 2
    if not test_csv.is_file():
        print(f"ERROR: test CSV not found: {test_csv.resolve()}", file=sys.stderr)
        return 2
    if args.batch_size < 1 or args.max_length < 8:
        print("ERROR: batch size must be positive and max length must be at least 8.", file=sys.stderr)
        return 2

    try:
        df = pd.read_csv(test_csv, encoding="utf-8-sig")
    except Exception as exc:
        print(f"ERROR: Could not read test CSV: {exc}", file=sys.stderr)
        return 2

    required = {"text", "label"}
    missing = required - set(df.columns)
    if missing:
        print(f"ERROR: Test CSV missing columns: {sorted(missing)}", file=sys.stderr)
        return 2

    df = df.copy()
    if "language" not in df:
        df["language"] = "unknown"
    if "augmented" not in df:
        df["augmented"] = "unknown"
    if "seed_id" not in df:
        df["seed_id"] = ""

    df["text"] = df["text"].fillna("").astype(str).str.strip()
    df["actual_label_original"] = df["label"].fillna("").astype(str).str.strip()
    df["actual_label"] = df["actual_label_original"].map(normalize_label)
    df["language"] = df["language"].fillna("unknown").astype(str).str.strip()
    df["augmented"] = df["augmented"].fillna("unknown").astype(str).str.strip()
    df = df[df["text"].str.len() > 0].reset_index(drop=True)

    unknown = sorted(set(df["actual_label"]) - set(LABELS))
    if unknown:
        print(f"ERROR: Unknown labels after normalization: {unknown}", file=sys.stderr)
        return 2

    if args.limit > 0:
        df = df.head(args.limit).copy()
    if df.empty:
        print("ERROR: No non-empty test rows.", file=sys.stderr)
        return 2

    # Unzip once into a reusable local folder.
    extract_dir = output_dir / "extracted_model"
    extract_dir.mkdir(parents=True, exist_ok=True)
    marker = extract_dir / ".extracted_ok"
    if not marker.exists():
        print("Extracting model ZIP...")
        safe_extract_zip(model_zip, extract_dir)
        marker.write_text(str(model_zip.resolve()), encoding="utf-8")

    model_dir = find_model_dir(extract_dir)
    print("Model directory:", model_dir)

    print("Loading MuRIL tokenizer...")
    # Loading from a local checkpoint; no Hugging Face Hub download.
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_dir),
        local_files_only=True,
    )  # nosec B615
    print("Loading fine-tuned MuRIL classifier...")
    # Loading from a local checkpoint; no Hugging Face Hub download.
    model = AutoModelForSequenceClassification.from_pretrained(
        str(model_dir),
        local_files_only=True,
    )  # nosec B615

    id2label = get_id2label(model_dir, model.config)
    print("Model class order:", [id2label[i] for i in range(len(LABELS))])

    device = select_device(args.device)
    model.to(device)
    print("Inference device:", device)
    print("Model parameters:", f"{sum(p.numel() for p in model.parameters()):,}")
    print("Maximum sequence length:", args.max_length)
    print("Testing rows:", len(df))
    print("\nTrue label counts after Hurricane -> Cyclone normalization:")
    print(df["actual_label"].value_counts().reindex(LABELS, fill_value=0).to_string())

    predictions, confidences, probabilities = predict_batches(
        texts=df["text"].tolist(),
        tokenizer=tokenizer,
        model=model,
        device=device,
        batch_size=args.batch_size,
        max_length=args.max_length,
    )

    df["predicted_label"] = predictions
    df["confidence"] = confidences
    for label in LABELS:
        df[f"probability_{label.replace('-', '_')}"] = probabilities[label]

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "muril_local_predictions.csv"
    df.to_csv(pred_path, index=False, encoding="utf-8-sig")

    report_lines = [
        "LOCAL MURIL DISASTER CLASSIFIER EVALUATION",
        "=" * 72,
        f"Checkpoint ZIP: {model_zip.resolve()}",
        f"Test CSV: {test_csv.resolve()}",
        f"Device: {device}",
        f"Rows evaluated: {len(df)}",
        "Label normalization: Hurricane -> Cyclone",
        "",
        "OVERALL RESULTS",
        json.dumps(calculate_metrics(df["actual_label"].tolist(), predictions),
                   indent=2, ensure_ascii=False),
        "",
        "CLASSIFICATION REPORT (fixed five-class order)",
        classification_report(
            df["actual_label"],
            df["predicted_label"],
            labels=LABELS,
            target_names=LABELS,
            digits=4,
            zero_division=0,
        ),
        "",
        "CONFUSION MATRIX (rows=true, columns=predicted)",
        str(confusion_matrix(df["actual_label"], df["predicted_label"], labels=LABELS)),
    ]

    # Per-language results.
    language_rows = []
    for language, part in df.groupby("language"):
        met = calculate_metrics(part["actual_label"].tolist(),
                                part["predicted_label"].tolist())
        language_rows.append({"language": language, **met})
    lang_df = pd.DataFrame(language_rows).sort_values("language")
    lang_df.to_csv(output_dir / "muril_metrics_by_language.csv", index=False)
    report_lines.extend(["\nLANGUAGE-WISE RESULTS", lang_df.to_string(index=False)])

    # Augmented vs non-augmented test subsets.
    augmentation_rows = []
    for augmented_value, part in df.groupby("augmented"):
        met = calculate_metrics(part["actual_label"].tolist(),
                                part["predicted_label"].tolist())
        augmentation_rows.append({"augmented": augmented_value, **met})
    aug_df = pd.DataFrame(augmentation_rows).sort_values("augmented")
    aug_df.to_csv(output_dir / "muril_metrics_by_augmentation.csv", index=False)
    report_lines.extend(["\nAUGMENTATION-WISE RESULTS", aug_df.to_string(index=False)])

    # Base/unaugmented examples only. For this CSV augmented is normally 0/1.
    original_mask = df["augmented"].str.lower().isin(["0", "false", "no", "original"])
    report_subset("UN-AUGMENTED ROWS ONLY", df[original_mask], report_lines)

    # Store machine-readable summary.
    summary = {
        "checkpoint": str(model_zip.resolve()),
        "test_csv": str(test_csv.resolve()),
        "device": str(device),
        "overall": calculate_metrics(df["actual_label"].tolist(), predictions),
        "per_language": lang_df.to_dict(orient="records"),
        "augmentation_groups": aug_df.to_dict(orient="records"),
        "rows": int(len(df)),
    }
    (output_dir / "muril_metrics_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Save confusion matrix image if matplotlib is installed.
    try:
        import matplotlib.pyplot as plt
        from sklearn.metrics import ConfusionMatrixDisplay

        cm = confusion_matrix(df["actual_label"], df["predicted_label"], labels=LABELS)
        disp = ConfusionMatrixDisplay(cm, display_labels=LABELS)
        fig, ax = plt.subplots(figsize=(8, 7))
        disp.plot(ax=ax, xticks_rotation=35, colorbar=False, cmap="Blues")
        ax.set_title("Local MuRIL — tweets_multilingual test set")
        fig.tight_layout()
        fig.savefig(output_dir / "muril_confusion_matrix.png", dpi=160)
        plt.close(fig)
    except Exception as exc:
        report_lines.append(f"\nConfusion matrix plot unavailable: {exc}")

    report_path = output_dir / "muril_local_test_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("\n" + "=" * 72)
    print("\n".join(report_lines))
    print("\nSaved results:")
    print(" -", pred_path.resolve())
    print(" -", report_path.resolve())
    print(" -", (output_dir / "muril_metrics_by_language.csv").resolve())
    print(" -", (output_dir / "muril_metrics_by_augmentation.csv").resolve())
    print(" -", (output_dir / "muril_confusion_matrix.png").resolve())
    print("\nNOTE: The provided original test CSV has no genuine Fire rows. Fire support is zero.")
    print("The all-five-class macro-F1 therefore includes an absent Fire class as zero.")
    print("Use macro_f1_present_classes for the supported-class comparison, and collect real Fire test data.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
