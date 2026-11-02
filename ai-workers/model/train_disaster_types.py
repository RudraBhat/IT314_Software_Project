"""Reusable model, dataset, preprocessing, and evaluation utilities.

This module does not train a model when imported. Training utilities and
evaluation helpers can be executed standalone or imported.
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

ImageFile.LOAD_TRUNCATED_IMAGES = True

ROOT = Path(
    os.environ.get(
        "DISASTER_DATA_ROOT",
        r"D:\Study\Python\Project\New folder\data_disaster_types\data_disaster_types",
    )
)
# Dataset TSV paths
TRAIN_TSV = ROOT / "consolidated_disaster_types_train_final.tsv"
DEV_TSV = ROOT / "consolidated_disaster_types_dev_final.tsv"
TEST_TSV = ROOT / "consolidated_disaster_types_test_final.tsv"

IMG_SIZE = 224
MODEL_NAME = "convnext_tiny"
OUT_DIR = Path(os.environ.get("DISASTER_OUT_DIR", "outputs"))


def load_split(tsv_path, name="data"):
    """Load a TSV split and drop rows whose image files are missing."""
    df = pd.read_csv(tsv_path, sep="\t", quoting=csv.QUOTE_NONE, dtype=str)
    df = df[["image_path", "class_label"]].dropna().copy()
    df["class_label"] = df["class_label"].str.strip()
    df["full_path"] = df["image_path"].apply(
        lambda path: str(ROOT / path.strip().replace("data/aidr_disaster_types/", "data/", 1))
    )
    exists = df["full_path"].apply(os.path.exists)
    missing = int((~exists).sum())
    if missing:
        print(f"[{name}] dropping {missing} rows with missing image files")
    df = df[exists].reset_index(drop=True)
    print(f"[{name}] {len(df)} images")
    return df


class DisasterDataset(Dataset):
    """Image dataset used by the evaluation notebook."""

    def __init__(self, df, class_to_idx, transform):
        self.paths = df["full_path"].tolist()
        self.labels = [class_to_idx[label] for label in df["class_label"]]
        self.transform = transform

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx):
        try:
            with Image.open(self.paths[idx]) as image:
                image = image.convert("RGB")
        except (OSError, ValueError):
            image = Image.new("RGB", (IMG_SIZE, IMG_SIZE), (128, 128, 128))
        return self.transform(image), self.labels[idx]


class DisasterClassifier(nn.Module):
    """Backbone and classification head; architecture must match the checkpoint."""

    def __init__(self, model_name, num_classes):
        super().__init__()
        self.backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
        self.head = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(self.backbone.num_features, num_classes),
        )

    def forward(self, x):
        return self.head(self.backbone(x))


def build_transforms():
    """Return the training augmentation and deterministic evaluation transforms."""
    mean = (0.485, 0.456, 0.406)
    std = (0.229, 0.224, 0.225)
    train_tf = transforms.Compose(
        [
            transforms.RandomResizedCrop(IMG_SIZE, scale=(0.6, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomApply([transforms.GaussianBlur(5, sigma=(0.1, 2.0))], p=0.3),
            transforms.ColorJitter(0.3, 0.3, 0.3, 0.05),
            transforms.RandomRotation(10),
            transforms.ToTensor(),
            transforms.Normalize(mean, std),
        ]
    )
    eval_tf = transforms.Compose(
        [
            transforms.Resize(int(IMG_SIZE * 1.14)),
            transforms.CenterCrop(IMG_SIZE),
            transforms.ToTensor(),
            transforms.Normalize(mean, std),
        ]
    )
    return train_tf, eval_tf


@torch.no_grad()
def evaluate(model, loader, device, criterion=None):
    """Return loss, accuracy, macro-F1, true labels, and predicted labels."""
    model.eval()
    all_preds, all_labels = [], []
    total_loss = 0.0
    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)
        with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
            logits = model(images)
            if criterion is not None:
                total_loss += criterion(logits, labels).item() * images.size(0)
        all_preds.extend(logits.argmax(1).cpu().tolist())
        all_labels.extend(labels.cpu().tolist())
    macro_f1 = f1_score(all_labels, all_preds, average="macro")
    accuracy = float(np.mean(np.array(all_preds) == np.array(all_labels)))
    average_loss = total_loss / len(loader.dataset) if len(loader.dataset) else 0.0
    return average_loss, accuracy, macro_f1, all_labels, all_preds


def save_confusion_matrix(labels, preds, classes, path):
    """Save a row-normalized confusion matrix image."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matrix = confusion_matrix(labels, preds, normalize="true")
    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(range(len(classes)))
    ax.set_yticks(range(len(classes)))
    ax.set_xticklabels(classes, rotation=45, ha="right")
    ax.set_yticklabels(classes)
    for row in range(len(classes)):
        for col in range(len(classes)):
            ax.text(
                col,
                row,
                f"{matrix[row, col]:.2f}",
                ha="center",
                va="center",
                color="white" if matrix[row, col] > 0.5 else "black",
                fontsize=8,
            )
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    fig.colorbar(image)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
