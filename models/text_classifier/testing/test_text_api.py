#!/usr/bin/env python3
"""
Test the deployed IndicBERT Disaster Classification API against tweets_multilingual.csv.

Default API:
    https://indicbert-disaster-api.onrender.com

Example:
    python test_text_api.py --csv ../data/tweets_multilingual.csv

Dependencies:
    pip install pandas requests scikit-learn

The script sends requests sequentially (one at a time) to avoid overwhelming a
small Render Free instance. "Hurricane" is normalized to "Cyclone" because the
model uses a five-class taxonomy and a hurricane is a type of tropical cyclone.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)


LABELS = ["Fire", "Earthquake", "Cyclone", "Flood", "Non-Disaster"]
DEFAULT_API_URL = "https://indicbert-disaster-api.onrender.com"


def normalize_label(value: Any) -> str:
    """Normalize known label variants to the classifier's five class names."""
    raw = str(value).strip()
    normalized = {
        "fire": "Fire",
        "earthquake": "Earthquake",
        "cyclone": "Cyclone",
        "hurricane": "Cyclone",
        "flood": "Flood",
        "non-disaster": "Non-Disaster",
        "nondisaster": "Non-Disaster",
        "non_disaster": "Non-Disaster",
    }
    return normalized.get(raw.lower(), raw)


def wait_for_model(
    session: requests.Session,
    api_url: str,
    wait_seconds: int,
    request_timeout: int,
) -> dict[str, Any]:
    """Wake Render if needed and wait until /health reports model_loaded=true."""
    health_url = f"{api_url.rstrip('/')}/health"
    deadline = time.monotonic() + wait_seconds
    last_problem = "No health response received."

    print(f"Checking API health: {health_url}")
    while time.monotonic() < deadline:
        try:
            response = session.get(health_url, timeout=min(request_timeout, 30))
            if response.ok:
                try:
                    health = response.json()
                except ValueError:
                    health = {}

                if health.get("model_loaded") is True or health.get("status") == "ok":
                    print("API is ready.")
                    print("Health response:", json.dumps(health, ensure_ascii=False))
                    return health

                last_problem = f"API is responding but model is not ready: {health}"
            else:
                last_problem = f"Health endpoint returned HTTP {response.status_code}: {response.text[:300]}"
        except requests.RequestException as exc:
            last_problem = f"{type(exc).__name__}: {exc}"

        print(f"Waiting for Render/model startup... ({last_problem})")
        time.sleep(10)

    raise TimeoutError(
        f"API did not become ready within {wait_seconds} seconds. "
        f"Last issue: {last_problem}"
    )


def post_prediction(
    session: requests.Session,
    predict_url: str,
    text: str,
    timeout: int,
    retries: int,
) -> tuple[dict[str, Any] | None, int | None, str | None, float]:
    """Send one prediction request, retrying transient server/network errors."""
    payload = {"text": text}
    last_error: str | None = None
    last_status: int | None = None

    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            response = session.post(predict_url, json=payload, timeout=timeout)
            elapsed = time.perf_counter() - started
            last_status = response.status_code

            if response.ok:
                try:
                    data = response.json()
                except ValueError:
                    return None, last_status, "API did not return valid JSON.", elapsed

                if not isinstance(data, dict) or "prediction" not in data:
                    return None, last_status, f"Unexpected API response: {str(data)[:300]}", elapsed

                return data, last_status, None, elapsed

            last_error = f"HTTP {response.status_code}: {response.text[:500]}"
            # Retry only transient service-side or rate-limit errors.
            if response.status_code not in (408, 425, 429) and response.status_code < 500:
                return None, last_status, last_error, elapsed

        except requests.RequestException as exc:
            elapsed = time.perf_counter() - started
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < retries:
            delay = min(2 ** attempt, 8)
            print(f"  Temporary request failure; retrying in {delay}s: {last_error}")
            time.sleep(delay)

    return None, last_status, last_error, elapsed


def metric_summary(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    """Return metrics with both present-class and fixed-five-class macro F1."""
    if not y_true:
        return {"rows": 0, "accuracy": None, "macro_f1_present_classes": None,
                "macro_f1_all_five_classes": None, "weighted_f1": None}

    present_labels = [label for label in LABELS if label in set(y_true)]
    return {
        "rows": len(y_true),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_present_classes": float(
            f1_score(y_true, y_pred, labels=present_labels,
                     average="macro", zero_division=0)
        ),
        "macro_f1_all_five_classes": float(
            f1_score(y_true, y_pred, labels=LABELS,
                     average="macro", zero_division=0)
        ),
        "weighted_f1": float(
            f1_score(y_true, y_pred, labels=LABELS,
                     average="weighted", zero_division=0)
        ),
        "classes_present": present_labels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run tweets_multilingual.csv through the deployed IndicBERT API."
    )
    parser.add_argument("--csv", default="../data/tweets_multilingual.csv",
                        help="Input CSV path (default: ../data/tweets_multilingual.csv)")
    parser.add_argument("--api-url", default=DEFAULT_API_URL,
                        help=f"Render service base URL (default: {DEFAULT_API_URL})")
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[3] / "docs" / "ai" / "reports" / "text_classifier"),
                        help="Directory for output reports (default: docs/ai/reports/text_classifier)")
    parser.add_argument("--health-wait-seconds", type=int, default=300,
                        help="Maximum time to wait for a sleeping Render service/model.")
    parser.add_argument("--request-timeout", type=int, default=120,
                        help="Timeout for each prediction request in seconds.")
    parser.add_argument("--retries", type=int, default=2,
                        help="Retries for transient HTTP/network errors.")
    parser.add_argument("--pause", type=float, default=0.05,
                        help="Pause between requests in seconds (default: 0.05).")
    parser.add_argument("--limit", type=int, default=0,
                        help="Test only the first N rows (0 means all rows).")
    args = parser.parse_args()

    csv_file = Path(args.csv)
    if not csv_file.exists():
        print(f"ERROR: CSV not found: {csv_file.resolve()}", file=sys.stderr)
        return 2

    try:
        df = pd.read_csv(csv_file, encoding="utf-8-sig")
    except Exception as exc:
        print(f"ERROR: Could not read CSV: {exc}", file=sys.stderr)
        return 2

    required = {"text", "label"}
    missing = required - set(df.columns)
    if missing:
        print(f"ERROR: CSV is missing required columns: {sorted(missing)}", file=sys.stderr)
        return 2

    if "language" not in df.columns:
        df["language"] = "unknown"
    if "augmented" not in df.columns:
        df["augmented"] = "unknown"
    if "seed_id" not in df.columns:
        df["seed_id"] = ""

    df = df.copy()
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
        print("ERROR: No non-empty test messages found.", file=sys.stderr)
        return 2

    print("=" * 72)
    print("IndicBERT Disaster API test")
    print("API:", args.api_url.rstrip("/"))
    print("CSV:", csv_file.resolve())
    print("Rows to test:", len(df))
    print("Class counts after Hurricane -> Cyclone normalization:")
    print(df["actual_label"].value_counts().reindex(LABELS, fill_value=0).to_string())
    print("=" * 72)

    session = requests.Session()
    session.headers.update({"User-Agent": "IndicBERT-API-Test/1.0"})

    try:
        health = wait_for_model(
            session,
            args.api_url.rstrip("/"),
            args.health_wait_seconds,
            args.request_timeout,
        )
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    predict_url = f"{args.api_url.rstrip('/')}/predict"
    predictions: list[str | None] = []
    confidences: list[float | None] = []
    response_times: list[float | None] = []
    statuses: list[int | None] = []
    errors: list[str | None] = []
    probabilities: dict[str, list[float | None]] = {
        label: [] for label in LABELS
    }

    total_started = time.perf_counter()
    for idx, row in df.iterrows():
        data, status, error, elapsed = post_prediction(
            session=session,
            predict_url=predict_url,
            text=row["text"],
            timeout=args.request_timeout,
            retries=args.retries,
        )

        statuses.append(status)
        response_times.append(round(elapsed, 4))
        errors.append(error)

        if data is None:
            predictions.append(None)
            confidences.append(None)
            for label in LABELS:
                probabilities[label].append(None)
        else:
            predicted = normalize_label(data.get("prediction", ""))
            if predicted not in LABELS:
                predictions.append(None)
                confidences.append(None)
                errors[-1] = f"API returned unknown prediction label: {data.get('prediction')}"
                for label in LABELS:
                    probabilities[label].append(None)
            else:
                predictions.append(predicted)
                confidence = data.get("confidence")
                confidences.append(float(confidence) if confidence is not None else None)
                prob_dict = data.get("probabilities") or {}
                for label in LABELS:
                    value = prob_dict.get(label)
                    probabilities[label].append(float(value) if value is not None else None)

        if (idx + 1) % 25 == 0 or idx + 1 == len(df):
            succeeded = sum(p is not None for p in predictions)
            elapsed_total = time.perf_counter() - total_started
            print(
                f"Progress: {idx + 1}/{len(df)} | "
                f"successful: {succeeded} | "
                f"elapsed: {elapsed_total:.1f}s"
            )

        if args.pause > 0:
            time.sleep(args.pause)

    df["predicted_label"] = predictions
    df["confidence"] = confidences
    df["http_status"] = statuses
    df["response_seconds"] = response_times
    df["api_error"] = errors
    for label in LABELS:
        df[f"probability_{label.replace('-', '_')}"] = probabilities[label]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = out_dir / "tweets_multilingual_api_predictions.csv"
    df.to_csv(predictions_path, index=False, encoding="utf-8-sig")

    successful = df[df["predicted_label"].notna()].copy()
    failed = df[df["predicted_label"].isna()].copy()

    report_lines: list[str] = []
    report_lines.append("INDICBERT DISASTER API TEST REPORT")
    report_lines.append("=" * 72)
    report_lines.append(f"API: {args.api_url.rstrip('/')}")
    report_lines.append(f"Input CSV: {csv_file.resolve()}")
    report_lines.append(f"Rows attempted: {len(df)}")
    report_lines.append(f"Successful predictions: {len(successful)}")
    report_lines.append(f"Failed predictions: {len(failed)}")
    report_lines.append(f"Health response: {json.dumps(health, ensure_ascii=False)}")

    if not successful.empty:
        y_true = successful["actual_label"].tolist()
        y_pred = successful["predicted_label"].tolist()
        summary = metric_summary(y_true, y_pred)

        report_lines.extend([
            "",
            "OVERALL METRICS (successful API responses)",
            json.dumps(summary, indent=2, ensure_ascii=False),
            "",
            "CLASSIFICATION REPORT (five fixed classes; absent Fire support remains zero)",
            classification_report(
                y_true, y_pred,
                labels=LABELS,
                target_names=LABELS,
                digits=4,
                zero_division=0,
            ),
            "",
            "CONFUSION MATRIX (rows=true, columns=predicted; fixed label order)",
            str(confusion_matrix(y_true, y_pred, labels=LABELS)),
            "",
            "LANGUAGE-WISE METRICS",
        ])

        lang_rows = []
        for language, part in successful.groupby("language"):
            met = metric_summary(part["actual_label"].tolist(),
                                 part["predicted_label"].tolist())
            lang_rows.append({"language": language, **met})
        lang_df = pd.DataFrame(lang_rows).sort_values("language")
        report_lines.append(lang_df.to_string(index=False))
        lang_df.to_csv(out_dir / "metrics_by_language.csv", index=False)

        report_lines.extend(["", "AUGMENTATION-WISE METRICS"])
        aug_rows = []
        for aug, part in successful.groupby("augmented"):
            met = metric_summary(part["actual_label"].tolist(),
                                 part["predicted_label"].tolist())
            aug_rows.append({"augmented": aug, **met})
        aug_df = pd.DataFrame(aug_rows).sort_values("augmented")
        report_lines.append(aug_df.to_string(index=False))
        aug_df.to_csv(out_dir / "metrics_by_augmentation.csv", index=False)

        # Also report only the original unaugmented rows when the column is 0/1.
        original_mask = successful["augmented"].astype(str).str.lower().isin(
            ["0", "false", "no", "original"]
        )
        original_only = successful[original_mask]
        if not original_only.empty:
            original_summary = metric_summary(
                original_only["actual_label"].tolist(),
                original_only["predicted_label"].tolist(),
            )
            report_lines.extend([
                "",
                "UN-AUGMENTED ORIGINAL ROWS ONLY",
                json.dumps(original_summary, indent=2, ensure_ascii=False),
            ])

        metrics_json = {
            "api_url": args.api_url.rstrip("/"),
            "rows_attempted": int(len(df)),
            "successful_predictions": int(len(successful)),
            "failed_predictions": int(len(failed)),
            "overall": summary,
            "health": health,
        }
        (out_dir / "metrics_summary.json").write_text(
            json.dumps(metrics_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        report_lines.extend(["", "No predictions succeeded; metrics were not calculated."])

    if not failed.empty:
        report_lines.extend([
            "",
            "FAILED REQUESTS",
            failed[["text", "actual_label", "http_status", "api_error"]].to_string(index=False),
        ])

    report_text = "\n".join(report_lines)
    report_path = out_dir / "api_test_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    print("\n" + report_text)
    print("\nSaved outputs:")
    print(" -", predictions_path.resolve())
    print(" -", report_path.resolve())
    if (out_dir / "metrics_by_language.csv").exists():
        print(" -", (out_dir / "metrics_by_language.csv").resolve())
    if not failed.empty:
        print("Some requests failed. See api_error column in predictions CSV.")

    return 0 if failed.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
