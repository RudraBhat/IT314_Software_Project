"""Shared dataset, model, transform and evaluation code for the image classifier.

Imported by ``train_disaster_types.py`` and ``check_model.py``. Importing this
module never starts training.

The dataset root can be set with the ``DISASTER_DATA_ROOT`` environment
variable or passed explicitly to ``load_split``.
"""

import csv
import os
from pathlib import Path

import numpy as np
import pandas as pd
import timm
import torch
from PIL import Image, ImageFile
from sklearn.metrics import confusion_matrix, f1_score
from torch import nn
from torch.utils.data import Dataset
from torchvision import transforms

ImageFile.LOAD_TRUNCATED_IMAGES = True  # tolerate slightly truncated JPEGs

# Folder that contains the `data/` directory and the three .tsv files.
ROOT = Path(os.environ.get("DISASTER_DATA_ROOT", "data_disaster_types"))

TRAIN_TSV_NAME = "consolidated_disaster_types_train_final.tsv"
DEV_TSV_NAME = "consolidated_disaster_types_dev_final.tsv"
TEST_TSV_NAME = "consolidated_disaster_types_test_final.tsv"

IMG_SIZE = 224
MODEL_NAME = "convnext_tiny"
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


def load_split(tsv_path, name="data", root=None):
    """Read a TSV split and drop rows whose image file is missing.

    The TSV paths contain an extra ``aidr_disaster_types/`` folder that does not
    exist after extraction; it is stripped here.
    """
    root = Path(root) if root is not None else ROOT
    df = pd.read_csv(tsv_path, sep="\t", quoting=csv.QUOTE_NONE, dtype=str)
    df = df[["image_path", "class_label"]].dropna().copy()
    df["class_label"] = df["class_label"].str.strip()
    df["full_path"] = df["image_path"].apply(
        lambda p: str(root / p.strip().replace("data/aidr_disaster_types/", "data/", 1))
    )
    exists = df["full_path"].apply(os.path.exists)
    missing = int((~exists).sum())
    if missing:
        print(f"[{name}] dropping {missing} rows with missing image files")
    df = df[exists].reset_index(drop=True)
    print(f"[{name}] {len(df)} images")
    return df


class DisasterDataset(Dataset):
    def __init__(self, df, class_to_idx, transform, img_size=IMG_SIZE):
        self.paths = df["full_path"].tolist()
        self.labels = [class_to_idx[c] for c in df["class_label"]]
        self.transform = transform
        self.img_size = img_size

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx):
        try:
            with Image.open(self.paths[idx]) as img:
                img = img.convert("RGB")
        except (OSError, ValueError):
            img = Image.new("RGB", (self.img_size, self.img_size), (128, 128, 128))
        return self.transform(img), self.labels[idx]


class DisasterClassifier(nn.Module):
    """Backbone + head (so a drone head can be added later).

    The architecture must match the checkpoint and ``deployment/app.py``.
    """

    def __init__(self, model_name, num_classes, pretrained=False):
        super().__init__()
        self.backbone = timm.create_model(model_name, pretrained=pretrained, num_classes=0)
        self.head = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(self.backbone.num_features, num_classes),
        )

    def forward(self, x):
        return self.head(self.backbone(x))


def build_transforms(img_size=IMG_SIZE):
    """Return (train_transform, eval_transform)."""
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(img_size, scale=(0.6, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomApply([transforms.GaussianBlur(5, sigma=(0.1, 2.0))], p=0.3),
        transforms.ColorJitter(0.3, 0.3, 0.3, 0.05),
        transforms.RandomRotation(10),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])
    eval_tf = transforms.Compose([
        transforms.Resize(int(img_size * 1.14)),
        transforms.CenterCrop(img_size),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])
    return train_tf, eval_tf


@torch.no_grad()
def evaluate(model, loader, device, criterion=None, show_progress=False):
    """Return loss, accuracy, macro-F1, true labels and predicted labels."""
    model.eval()
    all_preds, all_labels, total_loss = [], [], 0.0
    iterator = loader
    if show_progress:
        from tqdm import tqdm

        iterator = tqdm(loader, leave=False, desc="eval")
    for imgs, labels in iterator:
        imgs, labels = imgs.to(device), labels.to(device)
        with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
            logits = model(imgs)
            if criterion is not None:
                total_loss += criterion(logits, labels).item() * imgs.size(0)
        all_preds.extend(logits.argmax(1).cpu().tolist())
        all_labels.extend(labels.cpu().tolist())
    macro_f1 = f1_score(all_labels, all_preds, average="macro")
    acc = float(np.mean(np.array(all_preds) == np.array(all_labels)))
    avg_loss = total_loss / len(loader.dataset) if len(loader.dataset) else 0.0
    return avg_loss, acc, macro_f1, all_labels, all_preds


def save_confusion_matrix(labels, preds, classes, path):
    """Save a row-normalized confusion matrix image."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cm = confusion_matrix(labels, preds, normalize="true")
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(classes)))
    ax.set_yticks(range(len(classes)))
    ax.set_xticklabels(classes, rotation=45, ha="right")
    ax.set_yticklabels(classes)
    for i in range(len(classes)):
        for j in range(len(classes)):
            ax.text(j, i, f"{cm[i, j]:.2f}", ha="center", va="center",
                    color="white" if cm[i, j] > 0.5 else "black", fontsize=8)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    fig.colorbar(im)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


@torch.no_grad()
def predict_image(image_path, ckpt_path="best_model.pt", review_threshold=0.6):
    """Predict one image file. Returns top-3 and a needs_review flag."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(
        ckpt_path,
        map_location=device,
        weights_only=True
    )
    classes = state["classes"]
    model = DisasterClassifier(state["model_name"], len(classes)).to(device)
    model.load_state_dict(state["model"])
    model.eval()

    _, eval_tf = build_transforms(int(state["img_size"]))
    with Image.open(image_path) as im:
        x = eval_tf(im.convert("RGB")).unsqueeze(0).to(device)
    probs = torch.softmax(model(x), dim=1)[0]
    top_p, top_i = probs.topk(min(3, len(classes)))
    top3 = [{"label": classes[i], "confidence": round(p.item(), 4)}
            for p, i in zip(top_p, top_i)]
    return {
        "prediction": top3[0]["label"],
        "confidence": top3[0]["confidence"],
        "top3": top3,
        "needs_review": top3[0]["confidence"] < review_threshold,
    }
