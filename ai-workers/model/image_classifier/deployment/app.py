"""
FastAPI service for the disaster image classifier.

Render start command:
    uvicorn app:app --host 0.0.0.0 --port $PORT

Required Render environment variable:
    HF_MODEL_REPO_ID=Dhruvil-14/disaster-classifier

Optional:
    HF_MODEL_FILENAME=best_model.pt
    HF_MODEL_REVISION=main
    HF_TOKEN=...  # only needed for a private/gated Hugging Face repo
"""

import gc
import io
import os
import threading
from contextlib import asynccontextmanager
from typing import Annotated

import timm
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from huggingface_hub import hf_hub_download
from PIL import Image, ImageFile, UnidentifiedImageError
from torch import nn
from torchvision import transforms

# ----------------------------- MEMORY SETTINGS -------------------------------
# Keep CPU thread usage low on small Render instances.
torch.set_num_threads(1)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    # PyTorch may already have initialized its inter-op thread pool.
    pass

ImageFile.LOAD_TRUNCATED_IMAGES = True

# ----------------------------- CONFIG ----------------------------------------
HF_MODEL_REPO_ID = os.getenv(
    "HF_MODEL_REPO_ID", "Dhruvil-14/disaster-classifier"
).strip()
HF_MODEL_FILENAME = os.getenv("HF_MODEL_FILENAME", "best_model.pt").strip()
HF_MODEL_REVISION = os.getenv("HF_MODEL_REVISION", "").strip() or None

REVIEW_THRESHOLD = 0.75
CLASS_THRESHOLDS = {
    "other_disaster": 0.70,
    "hurricane": 0.70,
}

MAX_FILE_MB = 10
MAX_IMAGE_SIDE = 1024
ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
}

# Only one model inference at a time to avoid simultaneous RAM spikes.
PREDICT_LOCK = threading.Lock()

# Model and preprocessing pipeline are initialized once at startup.
STATE = {}


class DisasterClassifier(nn.Module):
    """Architecture must match the model used during training."""

    def __init__(self, model_name: str, num_classes: int):
        super().__init__()
        self.backbone = timm.create_model(
            model_name,
            pretrained=False,
            num_classes=0,
        )
        self.head = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(self.backbone.num_features, num_classes),
        )

    def forward(self, x):
        return self.head(self.backbone(x))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not HF_MODEL_REPO_ID:
        raise RuntimeError(
            "HF_MODEL_REPO_ID is missing. Set it to "
            "'Dhruvil-14/disaster-classifier' in Render Environment."
        )

    device = torch.device("cpu")

    print(
        f"Downloading {HF_MODEL_FILENAME} from {HF_MODEL_REPO_ID} "
        f"(revision={HF_MODEL_REVISION or 'default'})...",
        flush=True,
    )

    checkpoint_path = hf_hub_download(
        repo_id=HF_MODEL_REPO_ID,
        filename=HF_MODEL_FILENAME,
        revision=HF_MODEL_REVISION,
        token=os.getenv("HF_TOKEN") or None,
    )

    # mmap avoids eagerly copying the entire checkpoint into RAM.
    # weights_only=True is appropriate for a state-dict checkpoint.
    checkpoint = torch.load(
        checkpoint_path,
        map_location="cpu",
        mmap=True,
        weights_only=True,
    )

    classes = checkpoint["classes"]
    img_size = int(checkpoint["img_size"])
    model_name = checkpoint["model_name"]

    # Build the same architecture used for training.
    model = DisasterClassifier(model_name, len(classes))

    # assign=True attaches checkpoint tensors to the model rather than
    # copying all weights into a second allocation.
    model.load_state_dict(checkpoint["model"], assign=True)
    model.to(device)
    model.eval()

    # Release the checkpoint dictionary; model parameters retain their storage.
    del checkpoint
    gc.collect()

    STATE["device"] = device
    STATE["model"] = model
    STATE["classes"] = classes
    STATE["tf"] = transforms.Compose(
        [
            transforms.Resize(int(img_size * 1.14)),
            transforms.CenterCrop(img_size),
            transforms.ToTensor(),
            transforms.Normalize(
                (0.485, 0.456, 0.406),
                (0.229, 0.224, 0.225),
            ),
        ]
    )

    print(
        f"Model loaded: {model_name} | classes: {classes} "
        f"| device: {device} | checkpoint: {checkpoint_path}",
        flush=True,
    )

    yield

    STATE.clear()
    gc.collect()


app = FastAPI(
    title="Disaster Image Classifier",
    version="1.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "Disaster Image Classifier API",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    if "model" not in STATE:
        return {"status": "starting", "classes": []}

    return {
        "status": "ok",
        "classes": STATE.get("classes", []),
    }


@app.post("/predict")
def predict(
    file: Annotated[
        UploadFile,
        File(description="Disaster image (JPEG, PNG, WEBP or BMP)"),
    ],
):
    if "model" not in STATE:
        raise HTTPException(
            status_code=503,
            detail="Model is not ready. Please try again shortly.",
        )

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{file.content_type}'. "
                "Use JPEG, PNG, WEBP or BMP."
            ),
        )

    data = file.file.read()
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_MB} MB.",
        )

    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        # Limit very large source images before preprocessing.
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Could not read this file as an image.",
        ) from None
    finally:
        del data

    try:
        tensor = STATE["tf"](image).unsqueeze(0)
        del image

        with PREDICT_LOCK:
            with torch.inference_mode():
                logits = STATE["model"](tensor)
                probabilities = torch.softmax(logits, dim=1)[0].cpu()

        del tensor, logits
        gc.collect()

        classes = STATE["classes"]
        top_probs, top_indices = probabilities.topk(min(3, len(classes)))

        top3 = [
            {
                "label": classes[index.item()],
                "confidence": round(probability.item(), 4),
            }
            for probability, index in zip(
                top_probs, top_indices, strict=True
            )
        ]

        predicted_label = top3[0]["label"]
        confidence = top3[0]["confidence"]
        threshold = CLASS_THRESHOLDS.get(
            predicted_label,
            REVIEW_THRESHOLD,
        )

        return {
            "filename": file.filename,
            "prediction": predicted_label,
            "confidence": confidence,
            "top3": top3,
            "all_probabilities": {
                label: round(probability.item(), 4)
                for label, probability in zip(
                    classes, probabilities, strict=True
                )
            },
            "needs_review": confidence < threshold,
            "review_threshold_used": threshold,
        }

    except HTTPException:
        raise
    except Exception as exc:
        # Log the real error in Render logs while returning a safe API message.
        print(f"Prediction failed: {type(exc).__name__}: {exc}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Prediction failed. Check the service logs.",
        ) from exc
