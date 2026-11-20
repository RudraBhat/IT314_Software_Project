"""
Evaluate the deployed disaster-classifier API using this dataset's TSV split.

The TSV rows are tab-separated and look like:
IDR<TAB>1051850186446831618_0<TAB>data/aidr_disaster_types/hurricane_michael_2018/...jpg<TAB>hurricane

Your extracted data folder may not contain the "aidr_disaster_types" directory.
This script therefore strips that optional prefix and resolves the remaining
relative path inside --data-dir.

Install:
    pip install requests

Example:
    python test_image_api.py ^
      --api-url https://disaster-classifier-api.onrender.com ^
      --tsv "D:\\Study\\Python\\Project\\New folder\\data_disaster_types\\data_disaster_types\\consolidated_disaster_types_test_final.tsv" ^
      --data-dir "D:\\Study\\Python\\Project\\New folder\\data_disaster_types\\data_disaster_types\\data"

Optional first test:
    --limit 20
"""

import argparse
import csv
import mimetypes
import time
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import requests

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
KNOWN_PREFIXES = (
    "data/aidr_disaster_types/",
    "aidr_disaster_types/",
    "data/",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test the deployed API against a TSV-labelled image dataset."
    )
    parser.add_argument("--api-url", required=True, help="Render service base URL")
    parser.add_argument("--tsv", required=True, help="Path to test TSV file")
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Root folder containing the extracted image directories "
             "(the folder that directly contains natural_disaster, maria, etc.)",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[3] / "docs" / "ai" / "reports" / "image_classifier" / "deployment_test_results.csv"),
        help="Results CSV (default: docs/ai/reports/image_classifier/deployment_test_results.csv)",
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="Maximum number of rows to test; 0 means all")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--delay", type=float, default=0.2)
    return parser.parse_args()


def resolve_image_path(raw_path, data_dir):
    # TSV uses forward slashes, even on Windows.
    normalized = raw_path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]

    for prefix in KNOWN_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break

    # If an unrecognized leading folder exists, try both the full relative
    # path and the path with its first component removed.
    relative = Path(*PurePosixPath(normalized).parts)
    candidate = data_dir / relative
    if candidate.is_file():
        return candidate

    parts = PurePosixPath(normalized).parts
    if len(parts) > 1:
        candidate_without_first = data_dir.joinpath(*parts[1:])
        if candidate_without_first.is_file():
            return candidate_without_first

    return candidate


def read_tsv(tsv_path, data_dir, limit):
    samples = []
    missing = []
    with tsv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        for line_number, row in enumerate(reader, start=1):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) < 4:
                print(f"Skipping malformed TSV line {line_number}: {row}")
                continue

            # Dataset columns: source, post/image ID, relative image path, label.
            raw_image_path = row[2].strip()
            label = row[3].strip().lower()
            if not raw_image_path or not label:
                continue

            image_path = resolve_image_path(raw_image_path, data_dir)
            if image_path.suffix.lower() not in VALID_EXTENSIONS:
                continue
            if not image_path.is_file():
                missing.append((line_number, raw_image_path, str(image_path)))
                continue

            samples.append((image_path, label))
            if limit > 0 and len(samples) >= limit:
                break

    return samples, missing


def main():
    args = parse_args()
    tsv_path = Path(args.tsv).expanduser()
    data_dir = Path(args.data_dir).expanduser()
    if not tsv_path.is_file():
        raise SystemExit(f"TSV file not found: {tsv_path}")
    if not data_dir.is_dir():
        raise SystemExit(f"Image data directory not found: {data_dir}")

    base_url = args.api_url.rstrip("/")
    endpoint = base_url + "/predict"
    health_url = base_url + "/health"

    print("Checking deployed API...")
    try:
        health = requests.get(health_url, timeout=30)
        health.raise_for_status()
        health_json = health.json()
        print("Health check OK:", health_json)
    except requests.RequestException as exc:
        raise SystemExit(f"Health check failed: {exc}")

    samples, missing = read_tsv(tsv_path, data_dir, args.limit)
    if not samples:
        print("\nNo usable images were found.")
        print("Check --data-dir: it must be the folder directly containing")
        print("directories such as natural_disaster, maria, snow_storm_jonas.")
        if missing:
            print("\nFirst missing TSV paths:")
            for line, raw, resolved in missing[:10]:
                print(f"  TSV line {line}: {raw}")
                print(f"    Tried: {resolved}")
        raise SystemExit(1)

    counts = Counter(label for _, label in samples)
    print(f"\nLoaded {len(samples)} test images from {tsv_path.name}")
    print("Class counts:")
    for label, count in sorted(counts.items()):
        print(f"  {label}: {count}")
    if missing:
        print(f"\nWarning: {len(missing)} TSV rows point to missing image files.")
        for line, raw, resolved in missing[:5]:
            print(f"  Line {line}: {raw} -> tried {resolved}")

    rows = []
    matrix = defaultdict(Counter)
    successful = failed = correct = 0

    print("\nTesting images against the live deployment...\n")
    with requests.Session() as session:
        for i, (image_path, actual) in enumerate(samples, start=1):
            try:
                with image_path.open("rb") as image_file:
                    response = session.post(
                        endpoint,
                        files={"file": (image_path.name, image_file, mimetypes.guess_type(image_path.name)[0] or "application/octet-stream")},
                        timeout=args.timeout,
                    )
                response.raise_for_status()
                result = response.json()
                predicted = str(result["prediction"]).lower()
                confidence = result.get("confidence", "")
                is_correct = predicted == actual

                successful += 1
                correct += int(is_correct)
                matrix[actual][predicted] += 1
                rows.append({
                    "image": str(image_path),
                    "actual": actual,
                    "predicted": predicted,
                    "confidence": confidence,
                    "correct": is_correct,
                    "status": "OK",
                    "error": "",
                })
                print(
                    f"[{i}/{len(samples)}] "
                    f"{'PASS' if is_correct else 'WRONG'} | "
                    f"actual={actual} | predicted={predicted} | "
                    f"confidence={confidence}"
                )
            except Exception as exc:
                failed += 1
                rows.append({
                    "image": str(image_path),
                    "actual": actual,
                    "predicted": "",
                    "confidence": "",
                    "correct": False,
                    "status": "ERROR",
                    "error": str(exc),
                })
                print(f"[{i}/{len(samples)}] ERROR | {image_path.name}: {exc}")

            if args.delay > 0 and i < len(samples):
                time.sleep(args.delay)

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image", "actual", "predicted", "confidence",
                "correct", "status", "error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n========== SUMMARY ==========")
    print(f"Images found: {len(samples)}")
    print(f"Successful API calls: {successful}")
    print(f"Failed API calls: {failed}")
    print(f"Correct predictions: {correct}")
    if successful:
        print(f"Deployment accuracy: {correct / successful * 100:.2f}%")
    else:
        print("Deployment accuracy: N/A")

    labels = sorted(
        {actual for _, actual in samples}
        | {pred for class_counts in matrix.values() for pred in class_counts}
    )
    print("\nPer-class metrics:")
    print(f"{'Class':<20}{'Precision':>12}{'Recall':>12}{'F1':>12}{'Support':>12}")
    for label in labels:
        tp = matrix[label][label]
        predicted_total = sum(matrix[actual][label] for actual in matrix)
        actual_total = sum(matrix[label].values())
        precision = tp / predicted_total if predicted_total else 0.0
        recall = tp / actual_total if actual_total else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        print(
            f"{label:<20}{precision:>12.3f}{recall:>12.3f}"
            f"{f1:>12.3f}{actual_total:>12}"
        )

    print("\nConfusion matrix (rows=actual, columns=predicted):")
    print(f"{'Actual / Predicted':<20}" + "".join(f"{x[:12]:>14}" for x in labels))
    for actual in labels:
        print(
            f"{actual:<20}"
            + "".join(f"{matrix[actual][pred]:>14}" for pred in labels)
        )

    print(f"\nDetailed results saved to: {output.resolve()}")
    print("Accuracy is calculated over successful API responses only.")


if __name__ == "__main__":
    main()
