"""Train the disaster-type image classifier (PyTorch + timm).

Fine-tunes a pretrained backbone on the CrisisNLP / MEDIC "Disaster types"
dataset (7 classes: earthquake, fire, flood, hurricane, landslide,
other_disaster, not_disaster).

Examples
--------
GPU (Colab / Kaggle):
    python train_disaster_types.py --data-root /path/to/data_disaster_types \
        --out-dir outputs

CPU only:
    python train_disaster_types.py --data-root /path/to/data_disaster_types \
        --model-name mobilenetv3_large_100 --img-size 192 --epochs 6 \
        --unfreeze-last-fraction 0.3

Outputs (in --out-dir): best_model.pt, classes.json, confusion_matrix.png
"""

import argparse
import json
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import classification_report
from torch import nn
from torch.utils.data import DataLoader
from tqdm import tqdm

import disaster_common as C


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-root", default=str(C.ROOT),
                   help="Folder containing data/ and the three .tsv files "
                        "(default: $DISASTER_DATA_ROOT or ./data_disaster_types)")
    p.add_argument("--out-dir", default="outputs")
    p.add_argument("--model-name", default="convnext_tiny")
    p.add_argument("--img-size", type=int, default=224)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--lr-backbone", type=float, default=1e-4)
    p.add_argument("--lr-head", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=0.05)
    p.add_argument("--num-workers", type=int, default=2)
    p.add_argument("--unfreeze-last-fraction", type=float, default=1.0,
                   help="1 = full fine-tuning (GPU); ~0.3 is faster on CPU")
    p.add_argument("--patience", type=int, default=4, help="early-stopping patience")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def main():
    args = parse_args()
    root = Path(args.data_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Device:", device)

    # ---------------------------------------------------------------- data
    train_df = C.load_split(root / C.TRAIN_TSV_NAME, "train", root)
    dev_df = C.load_split(root / C.DEV_TSV_NAME, "dev", root)
    test_df = C.load_split(root / C.TEST_TSV_NAME, "test", root)

    classes = sorted(train_df["class_label"].unique())
    class_to_idx = {c: i for i, c in enumerate(classes)}
    print("Classes:", class_to_idx)
    print("\nTrain class counts:\n", train_df["class_label"].value_counts(), "\n")

    # a label in dev/test that is not in train would crash later; catch it now
    for name, df in (("dev", dev_df), ("test", test_df)):
        unknown = set(df["class_label"]) - set(classes)
        assert not unknown, f"{name} has unknown labels: {unknown}"

    with open(out_dir / "classes.json", "w") as f:
        json.dump(classes, f)

    train_tf, eval_tf = C.build_transforms(args.img_size)
    train_ds = C.DisasterDataset(train_df, class_to_idx, train_tf, args.img_size)
    dev_ds = C.DisasterDataset(dev_df, class_to_idx, eval_tf, args.img_size)
    test_ds = C.DisasterDataset(test_df, class_to_idx, eval_tf, args.img_size)

    kw = {
        "num_workers": args.num_workers,
        "pin_memory": device.type == "cuda",
        "persistent_workers": args.num_workers > 0,
    }
    train_loader = DataLoader(train_ds, args.batch_size, shuffle=True, drop_last=True, **kw)
    dev_loader = DataLoader(dev_ds, args.batch_size * 2, shuffle=False, **kw)
    test_loader = DataLoader(test_ds, args.batch_size * 2, shuffle=False, **kw)

    # ------------------------------------------- class weights (imbalance)
    counts = train_df["class_label"].value_counts().reindex(classes).values.astype(float)
    weights = counts.sum() / (len(classes) * counts)
    weights = torch.tensor(weights, dtype=torch.float32, device=device)
    criterion = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.1)
    eval_criterion = nn.CrossEntropyLoss()

    # --------------------------------------------------- model + optimizer
    torch.set_num_threads(os.cpu_count() or 4)
    model = C.DisasterClassifier(args.model_name, len(classes), pretrained=True).to(device)

    # freeze the early part of the backbone (big speedup on CPU)
    bb_params = list(model.backbone.parameters())
    n_trainable = int(len(bb_params) * args.unfreeze_last_fraction)
    for i, prm in enumerate(bb_params):
        prm.requires_grad = i >= len(bb_params) - n_trainable
    print(f"Backbone tensors trainable: {n_trainable}/{len(bb_params)}")

    param_groups = [{"params": model.head.parameters(), "lr": args.lr_head}]
    if n_trainable:
        param_groups.append({"params": [q for q in bb_params if q.requires_grad],
                             "lr": args.lr_backbone})
    optimizer = torch.optim.AdamW(param_groups, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    scaler = torch.amp.GradScaler(device.type, enabled=device.type == "cuda")

    # --------------------------------------------------------------- train
    best_f1, bad_epochs = 0.0, 0
    ckpt_path = out_dir / "best_model.pt"

    for epoch in range(1, args.epochs + 1):
        model.train()
        running = 0.0
        for imgs, labels in tqdm(train_loader, desc=f"epoch {epoch}/{args.epochs}"):
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
                loss = criterion(model(imgs), labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            running += loss.item() * imgs.size(0)
        scheduler.step()

        train_loss = running / (len(train_loader) * args.batch_size)
        dev_loss, dev_acc, dev_f1, _, _ = C.evaluate(
            model, dev_loader, device, eval_criterion, show_progress=True)
        print(f"epoch {epoch}: train_loss={train_loss:.4f} dev_loss={dev_loss:.4f} "
              f"dev_acc={dev_acc:.4f} dev_macro_f1={dev_f1:.4f}")

        if dev_f1 > best_f1:
            best_f1, bad_epochs = dev_f1, 0
            torch.save({"model": model.state_dict(), "classes": classes,
                        "model_name": args.model_name, "img_size": args.img_size},
                       ckpt_path)
            print(f"  saved best model (dev macro-F1 {best_f1:.4f})")
        else:
            bad_epochs += 1
            if bad_epochs >= args.patience:
                print("Early stopping.")
                break

    # ------------------------------------- final test evaluation (run once)
    print("\nLoading best model for final TEST evaluation...")
    state = torch.load(
        ckpt_path,
        map_location=device,
        weights_only=True
    )
    model.load_state_dict(state["model"])
    _, test_acc, test_f1, y_true, y_pred = C.evaluate(
        model, test_loader, device, show_progress=True)
    print(f"\nTEST accuracy: {test_acc:.4f} | macro-F1: {test_f1:.4f}\n")
    print(classification_report(y_true, y_pred, target_names=classes, digits=3))
    C.save_confusion_matrix(y_true, y_pred, classes, out_dir / "confusion_matrix.png")
    print(f"Saved best_model.pt, classes.json, confusion_matrix.png in {out_dir.resolve()}")


if __name__ == "__main__":
    main()
