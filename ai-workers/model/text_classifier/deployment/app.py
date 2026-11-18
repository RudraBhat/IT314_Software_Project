import os
# Restrict numerical-library thread pools on a small CPU instance.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import json
import threading
import resource
from pathlib import Path
from contextlib import asynccontextmanager

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AlbertTokenizer

HF_MODEL_REPO = os.getenv("HF_MODEL_REPO", "").strip()
HF_REVISION = os.getenv("HF_REVISION", "main")
HF_TOKEN = os.getenv("HF_TOKEN") or None  # Required only for a private HF model repo.
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/tmp/indicbert_model"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MAX_LENGTH = int(os.getenv("MAX_LENGTH", "160"))
LABELS = ["Fire", "Earthquake", "Cyclone", "Flood", "Non-Disaster"]

MODEL_FILES = [
    "model_int8.onnx",
    "spiece.model",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "label_mapping.json",
    "config.json",
]

session = None
tokenizer = None
inference_lock = threading.Lock()


def peak_rss_mb():
    """Linux maximum resident set size in MiB."""
    try:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


def download_model_files():
    if not HF_MODEL_REPO:
        raise RuntimeError(
            "HF_MODEL_REPO is not set. Add it in Render Environment Variables, "
            "for example 'your-username/indicbert-disaster-classifier'."
        )

    for filename in MODEL_FILES:
        print(f"Downloading {filename} from {HF_MODEL_REPO}...")
        hf_hub_download(
            repo_id=HF_MODEL_REPO,
            filename=filename,
            revision=HF_REVISION,
            token=HF_TOKEN,
            local_dir=str(MODEL_DIR),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global session, tokenizer

    download_model_files()

    with open(MODEL_DIR / "label_mapping.json", "r", encoding="utf-8") as f:
        mapping = json.load(f)

    stored = mapping.get("id2label", {})
    stored_labels = [stored.get(str(i)) for i in range(len(LABELS))]
    if stored_labels != LABELS:
        raise RuntimeError(
            f"Label mapping mismatch. Expected {LABELS}, found {stored_labels}"
        )

    tokenizer = AlbertTokenizer.from_pretrained(
        str(MODEL_DIR),
        local_files_only=True,
        use_fast=False,
        keep_accents=True,
    )

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.enable_mem_pattern = True

    session = ort.InferenceSession(
        str(MODEL_DIR / "model_int8.onnx"),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )

    input_names = {item.name for item in session.get_inputs()}
    required_inputs = {"input_ids", "attention_mask"}
    if not required_inputs.issubset(input_names):
        raise RuntimeError(f"Unexpected ONNX inputs: {input_names}")

    print(
        "IndicBERT ONNX INT8 loaded successfully.",
        "HF repo:", HF_MODEL_REPO,
        "Inputs:", sorted(input_names),
        "Peak RSS MB:", peak_rss_mb(),
    )
    yield
    session = None
    tokenizer = None


app = FastAPI(
    title="IndicBERT Disaster Classification API",
    description="Five-class multilingual disaster classification using fine-tuned IndicBERT with ONNX Runtime INT8.",
    version="1.1.0",
    lifespan=lifespan,
)


class PredictRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


@app.get("/")
def root():
    return {
        "service": "IndicBERT Disaster Classification API",
        "status": "running",
        "health": "/health",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "ok" if session is not None and tokenizer is not None else "starting",
        "model_loaded": session is not None and tokenizer is not None,
        "model_format": "ONNX dynamic INT8",
        "model_repo": HF_MODEL_REPO,
        "classes": LABELS,
        "max_length": MAX_LENGTH,
        "peak_rss_mb": peak_rss_mb(),
    }


@app.post("/predict")
def predict(request: PredictRequest):
    if session is None or tokenizer is None:
        raise HTTPException(status_code=503, detail="Model is not ready.")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text cannot be empty.")

    encoded = tokenizer(
        text,
        truncation=True,
        max_length=MAX_LENGTH,
        padding=True,
        return_tensors="np",
    )

    available_inputs = {item.name for item in session.get_inputs()}
    feeds = {}
    for name in available_inputs:
        if name not in encoded:
            raise HTTPException(
                status_code=500,
                detail=f"Tokenizer did not produce required ONNX input: {name}",
            )
        feeds[name] = np.asarray(encoded[name], dtype=np.int64)

    try:
        # Keep only one inference running at a time to control memory usage.
        with inference_lock:
            logits = session.run(None, feeds)[0]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc

    logits = np.asarray(logits, dtype=np.float32)[0]
    exp_logits = np.exp(logits - np.max(logits))
    probabilities = exp_logits / np.sum(exp_logits)

    predicted_id = int(np.argmax(probabilities))
    return {
        "prediction": LABELS[predicted_id],
        "confidence": round(float(probabilities[predicted_id]), 6),
        "probabilities": {
            LABELS[i]: round(float(probabilities[i]), 6)
            for i in range(len(LABELS))
        },
    }
