"""Local inference for the research-only HumAID information-type model."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from text_model.train_humaid_transformer import preprocess_tweet


class HumAIDModelUnavailable(RuntimeError):
    """Raised when the local research artifact is missing or incomplete."""


@lru_cache(maxsize=2)
def _load_model(model_dir: str):
    artifact_dir = Path(model_dir).expanduser().resolve()
    metadata_path = artifact_dir / "metadata.json"
    if not metadata_path.is_file():
        raise HumAIDModelUnavailable(f"Missing local model metadata at {metadata_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HumAIDModelUnavailable("Could not read local HumAID model metadata") from exc
    if not metadata.get("human_review_required"):
        raise HumAIDModelUnavailable("Artifact is missing the required human-review safeguard")

    try:
        # This is a verified local artifact; remote Hugging Face downloads are disabled.
        tokenizer = AutoTokenizer.from_pretrained(
            artifact_dir,
            local_files_only=True,
            normalization=True,
        )  # nosec B615
        model = AutoModelForSequenceClassification.from_pretrained(
            artifact_dir,
            local_files_only=True,
        )  # nosec B615
    except (OSError, ValueError) as exc:
        raise HumAIDModelUnavailable("Could not load the local HumAID model artifact") from exc
    model.eval()
    return metadata, tokenizer, model


def predict_humaid_category(
    text: str,
    *,
    model_dir: str | Path,
) -> dict[str, Any]:
    """Suggest a broad HumAID category; this never verifies or prioritizes an incident."""
    if not text.strip():
        raise ValueError("text must contain at least one non-whitespace character")
    metadata, tokenizer, model = _load_model(str(Path(model_dir).expanduser().resolve()))
    normalized_text = preprocess_tweet(" ".join(text.split()))
    encoded = tokenizer(
        normalized_text,
        truncation=True,
        max_length=int(metadata["max_length"]),
        return_tensors="pt",
    )
    with torch.inference_mode():
        probabilities = torch.softmax(model(**encoded).logits[0], dim=-1).cpu().tolist()

    predicted_index = max(range(len(probabilities)), key=probabilities.__getitem__)
    label = metadata["labels"][predicted_index]
    confidence = float(probabilities[predicted_index])
    threshold = float(metadata["review_threshold"])
    return {
        "model": metadata["model"],
        "humanitarian_information_type": {
            "candidate": label,
            "confidence": round(confidence, 6),
            "status": "REVIEW" if confidence < threshold else "SUGGESTED",
            "review_threshold": threshold,
        },
        "human_review_required": True,
        "advisory_only": True,
        "limits": [
            "This model classifies broad humanitarian information types; it does not predict DRCH incident scenario or dispatch urgency.",
            "A prediction is not verification that an incident is real, current, or at the reported location.",
            "Research use only: the HumAID source terms restrict use, and derived weights need a separate rights review before publication or deployment.",
        ],
    }
