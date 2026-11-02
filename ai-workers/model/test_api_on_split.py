"""
Evaluate the running FastAPI image-classifier API on the dataset test split.

Run this from the ai-workers/model directory (where app.py and
train_disaster_types.py live), after starting the API.

Examples:
    python test_api_on_split.py
    python test_api_on_split.py --limit 50
    python test_api_on_split.py --base-url http://127.0.0.1:8000 --limit 100

By default, --limit 0 means test every existing image in the configured test split.
The script writes per-image predictions to CSV and aggregate metrics to a text file.
"""

import argparse
import json
import mimetypes
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

try:
    import train_disaster_types as T
except ImportError as exc:
    raise SystemExit(
        "Could not import train_disaster_types.py. Put this script in the same "
        "folder as train_disaster_types.py and run it with the project's environment."
    ) from exc


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate the /predict API on the model's held-out test split.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL for the running API (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum images to test; 0 means the full test split (default: 0).",
    )
    parser.add_argument(
        "--test-tsv",
        type=Path,
        default=None,
        help="Optional explicit path to the test TSV. Defaults to TEST_TSV in train_disaster_types.py.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Optional dataset root folder; overrides ROOT from train_disaster_types.py.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("api_test_results"),
        help="Directory for CSV and metric reports (default: ./api_test_results).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-image request timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        help="Optional delay between API requests in seconds (default: 0).",
    )
    return parser.parse_args()


def load_test_split(args):
    # Keep path resolution consistent with train_disaster_types.py.
    if args.data_root is not None:
        T.ROOT = args.data_root.resolve()

    test_tsv = args.test_tsv
    if test_tsv is None:
        if args.data_root is not None:
            test_tsv = T.ROOT / "consolidated_disaster_types_test_final.tsv"
        else:
            test_tsv = T.TEST_TSV

    test_tsv = Path(test_tsv)
    if not test_tsv.exists():
        raise FileNotFoundError(
            f"Test split TSV not found: {test_tsv}\n"
            "Pass --test-tsv PATH or configure DISASTER_DATA_ROOT / ROOT in "
            "train_disaster_types.py."
        )

    df = T.load_split(test_tsv, "test")
    if df.empty:
        raise RuntimeError("No test images were found. Check the dataset root and image paths.")
    return df


def check_api(session, base_url, timeout):
    url = base_url.rstrip("/")
    try:
        response = session.get(f"{url}/health", timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(
            f"Cannot reach API health endpoint at {url}/health.\n"
            "Start the API first, for example: uvicorn app:app --reload\n"
            f"Details: {exc}"
        ) from exc

    try:
        body = response.json()
    except ValueError:
        body = response.text
    print(f"API health: HTTP {response.status_code} | {body}")


def predict_one(session, base_url, image_path, timeout):
    url = base_url.rstrip("/") + "/predict"
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    start = time.perf_counter()

    try:
        with image_path.open("rb") as image_file:
            response = session.post(
                url,
                files={"file": (image_path.name, image_file, mime_type)},
                timeout=timeout,
            )
        latency_ms = (time.perf_counter() - start) * 1000

        if not response.ok:
            return {
                "status_code": response.status_code,
                "latency_ms": round(latency_ms, 2),
                "error": response.text[:1000],
            }

        try:
            data = response.json()
        except ValueError:
            return {
                "status_code": response.status_code,
                "latency_ms": round(latency_ms, 2),
                "error": "API response was not valid JSON: " + response.text[:500],
            }

        prediction = data.get("prediction")
        if not isinstance(prediction, str):
            return {
                "status_code": response.status_code,
                "latency_ms": round(latency_ms, 2),
                "error": f"Response has no string 'prediction' field: {data}",
            }

        top3 = data.get("top3", [])
        # The README example uses objects with label/confidence; preserve the
        # complete response in JSON so any response-shape variation is visible.
        return {
            "status_code": response.status_code,
            "latency_ms": round(latency_ms, 2),
            "prediction": prediction,
            "confidence": data.get("confidence"),
            "needs_review": data.get("needs_review"),
            "top3_json": json.dumps(top3, ensure_ascii=False),
            "response_json": json.dumps(data, ensure_ascii=False),
            "error": "",
        }

    except (requests.RequestException, OSError) as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status_code": None,
            "latency_ms": round(latency_ms, 2),
            "error": str(exc),
        }


def main():
    args = parse_args()
    if args.limit < 0:
        raise SystemExit("--limit must be 0 or a positive integer.")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero.")
    if args.pause < 0:
        raise SystemExit("--pause cannot be negative.")

    base_url = args.base_url.rstrip("/")
    df = load_test_split(args)
    if args.limit:
        df = df.head(args.limit).copy()

    if df.empty:
        raise SystemExit("There are no images to test.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"API: {base_url}")
    print(f"Images queued: {len(df)}")
    print("Starting requests; each image is uploaded individually to POST /predict.")

    session = requests.Session()
    check_api(session, base_url, args.timeout)

    results = []
    start_all = time.perf_counter()

    for index, row in enumerate(df.itertuples(index=False), start=1):
        image_path = Path(row.full_path)
        true_label = str(row.class_label).strip()

        if not image_path.is_file():
            result = {
                "image_path": str(image_path),
                "true_label": true_label,
                "status_code": None,
                "latency_ms": 0.0,
                "error": "Image file does not exist",
            }
        else:
            result = predict_one(session, base_url, image_path, args.timeout)
            result["image_path"] = str(image_path)
            result["true_label"] = true_label

        predicted = result.get("prediction")
        result["correct"] = bool(predicted == true_label) if predicted is not None else None
        results.append(result)

        if index == 1 or index % 25 == 0 or index == len(df):
            successful = sum(1 for item in results if item.get("prediction") is not None)
            print(
                f"[{index}/{len(df)}] successful predictions: {successful} | "
                f"last: true={true_label}, predicted={predicted or 'FAILED'}"
            )

        if args.pause:
            time.sleep(args.pause)

    elapsed = time.perf_counter() - start_all
    results_df = pd.DataFrame(results)
    csv_path = args.output_dir / "api_test_predictions.csv"
    results_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    successful_df = results_df[
        results_df["prediction"].notna()
        if "prediction" in results_df.columns
        else pd.Series(False, index=results_df.index)
    ].copy()
    report_path = args.output_dir / "api_test_report.txt"

    total = len(results_df)
    success_count = len(successful_df)
    failed_count = total - success_count
    lines = [
        "Image Classifier API Test Report",
        "=" * 34,
        f"API base URL: {base_url}",
        f"Test split TSV: {args.test_tsv or T.TEST_TSV}",
        f"Images attempted: {total}",
        f"Successful predictions: {success_count}",
        f"Failed predictions: {failed_count}",
        f"Total elapsed time: {elapsed:.2f} seconds",
        f"Average time per attempted image: {elapsed / total:.2f} seconds",
    ]

    if success_count:
        y_true = successful_df["true_label"].astype(str)
        y_pred = successful_df["prediction"].astype(str)
        lines.extend(
            [
                "",
                "Metrics on successful API responses only",
                "-" * 42,
                f"Accuracy: {accuracy_score(y_true, y_pred):.4f}",
                f"Macro-F1: {f1_score(y_true, y_pred, average='macro', zero_division=0):.4f}",
                f"Weighted-F1: {f1_score(y_true, y_pred, average='weighted', zero_division=0):.4f}",
                "",
                "Per-class classification report:",
                classification_report(y_true, y_pred, zero_division=0),
                "Confusion matrix (rows=true labels, columns=predicted labels):",
                str(confusion_matrix(y_true, y_pred, labels=sorted(set(y_true) | set(y_pred)))),
                f"Class label order: {sorted(set(y_true) | set(y_pred))}",
            ]
        )

        if "latency_ms" in successful_df:
            lines.extend(
                [
                    "",
                    "API latency (successful predictions)",
                    "-" * 36,
                    f"Mean: {successful_df['latency_ms'].mean():.2f} ms",
                    f"Median: {successful_df['latency_ms'].median():.2f} ms",
                    f"P95: {successful_df['latency_ms'].quantile(0.95):.2f} ms",
                ]
            )
    else:
        lines.extend(
            [
                "",
                "No successful predictions were returned; metrics were not calculated.",
                "Check the API logs and the error column in api_test_predictions.csv.",
            ]
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nFinished.")
    print(f"Per-image CSV: {csv_path.resolve()}")
    print(f"Metric report: {report_path.resolve()}")
    print(f"Successful: {success_count}/{total}; failed: {failed_count}")
    if success_count:
        print(f"API accuracy: {accuracy_score(successful_df['true_label'], successful_df['prediction']):.4f}")
        print(
            "API macro-F1: "
            f"{f1_score(successful_df['true_label'], successful_df['prediction'], average='macro', zero_division=0):.4f}"
        )
    if failed_count:
        print("Some requests failed. Check the CSV 'error' column and API logs.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
