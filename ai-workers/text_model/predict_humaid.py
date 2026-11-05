"""Interactively run the local, research-only HumAID model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from text_model.humaid_inference import predict_humaid_category


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "artifacts" / "humaid_bertweet",
    )
    args = parser.parse_args()
    model_dir = args.model_dir.expanduser().resolve()
    weights = model_dir / "model.safetensors"
    if not weights.is_file():
        raise SystemExit(f"Model weights not found: {weights}\nTrain/download the local research model first.")

    text = input("Paste one English message to analyze (or press Return to quit): ").strip()
    if not text:
        print("No message entered; exiting.")
        return

    result = predict_humaid_category(text, model_dir=model_dir)
    result["local_artifact"] = {
        "weights_file": str(weights),
        "sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
