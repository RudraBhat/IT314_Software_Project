"""
FastAPI service for the disaster type classifier.

Install:
    pip install fastapi "uvicorn[standard]" python-multipart torch torchvision timm pillow

Run (from the folder containing this file and outputs/best_model.pt):
    uvicorn app:app --reload

Then open:  http://127.0.0.1:8000/docs
"""

import io
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import timm
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageFile, UnidentifiedImageError
from torch import nn
from torchvision import transforms

ImageFile.LOAD_TRUNCATED_IMAGES = True

# ----------------------------- CONFIG ---------------------------------------
CKPT_PATH = Path(__file__).resolve().parent / "best_model.pt"  # next to app.py
REVIEW_THRESHOLD = 0.60  # below this confidence -> needs_review = True
# Stricter threshold for the weakest classes in testing (other_disaster F1 0.59, hurricane 0.72).
# Tune these on the dev set.
CLASS_THRESHOLDS = {"other_disaster": 0.70, "hurricane": 0.70}
MAX_FILE_MB = 10
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
# ----------------------------------------------------------------------------


class DisasterClassifier(nn.Module):
    """Must match the architecture used in training."""

    def __init__(self, model_name, num_classes):
        super().__init__()
        self.backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
        self.head = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(self.backbone.num_features, num_classes),
        )

    def forward(self, x):
        return self.head(self.backbone(x))


# Loaded once at startup and reused for every request
STATE = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if not CKPT_PATH.exists():
        raise FileNotFoundError(f"Model file not found at {CKPT_PATH}. Copy best_model.pt into that folder.")
    ckpt = torch.load(CKPT_PATH, map_location=device, weights_only=True)  # nosec B614
    classes = ckpt["classes"]
    img_size = ckpt["img_size"]

    model = DisasterClassifier(ckpt["model_name"], len(classes)).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    STATE["device"] = device
    STATE["model"] = model
    STATE["classes"] = classes
    STATE["tf"] = transforms.Compose(
        [
            transforms.Resize(int(img_size * 1.14)),
            transforms.CenterCrop(img_size),
            transforms.ToTensor(),
            transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
        ]
    )
    print(f"Model loaded: {ckpt['model_name']} | classes: {classes} | device: {device}")
    yield
    STATE.clear()


app = FastAPI(title="Disaster Image Classifier", version="1.0", lifespan=lifespan)

# Allow your React/Vue frontend to call this API (tighten the origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "classes": STATE.get("classes", [])}


# A plain `def` endpoint runs in a worker thread, so model inference
# does not block other requests.
@app.post("/predict")
def predict(
    file: Annotated[UploadFile, File(description="Disaster image (jpg/png/webp)")],
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported file type '{file.content_type}'. Use jpg, png or webp.")

    data = file.file.read()
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_FILE_MB} MB).")

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "Could not read this file as an image.") from None

    x = STATE["tf"](img).unsqueeze(0).to(STATE["device"])
    with torch.no_grad():
        probs = torch.softmax(STATE["model"](x), dim=1)[0].cpu()

    classes = STATE["classes"]
    top_p, top_i = probs.topk(min(3, len(classes)))
    top3 = [{"label": classes[i], "confidence": round(p.item(), 4)} for p, i in zip(top_p, top_i, strict=True)]

    label, confidence = top3[0]["label"], top3[0]["confidence"]
    threshold = CLASS_THRESHOLDS.get(label, REVIEW_THRESHOLD)

    return {
        "filename": file.filename,
        "prediction": label,
        "confidence": confidence,
        "top3": top3,
        "all_probabilities": {c: round(p.item(), 4) for c, p in zip(classes, probs, strict=True)},
        "needs_review": confidence < threshold,
        "review_threshold_used": threshold,
    }
