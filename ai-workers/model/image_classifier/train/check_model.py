"""Evaluate a trained disaster image classifier on the test split.

Run this AFTER ``train_disaster_types.py`` has produced ``best_model.pt``.

Produces (in --out-dir): metrics + per-class F1 chart, confusion matrices,
confidence / "needs review" table and histogram, sample grids of correct and
wrong predictions, optional single-image prediction.

Example:
    python check_model.py --data-root /path/to/data_disaster_types \
        --ckpt outputs/best_model.pt --out-dir model_check
    python check_model.py --data-root ... --image /path/to/photo.jpg
"""

import argparse
import random
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # save figures to files; no display needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from PIL import Image
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from torch.utils.data import DataLoader
from tqdm import tqdm

import disaster_common as C


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-root", default=str(C.ROOT),
                   help="Folder containing data/ and the .tsv files")
    p.add_argument("--ckpt", default="best_model.pt")
    p.add_argument("--out-dir", default="model_check")
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--inspect-class", default="landslide",
                   help="Class whose missed images are shown in detail")
    p.add_argument("--image", default=None, help="Optional: predict a single image file")
    p.add_argument("--review-threshold", type=float, default=0.6)
    return p.parse_args()


def show_samples(indices, title, path, paths, y_true, y_pred, conf, classes,
                 cols=4, size=3.2):
    indices = list(indices)
    if not indices:
        print(f"{title}: nothing to show.")
        return
    rows = (len(indices) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * size, rows * (size + 0.5)))
    axes = np.atleast_1d(axes).ravel()
    for ax in axes:
        ax.axis("off")
    for ax, i in zip(axes, indices):
        ax.imshow(Image.open(paths[i]).convert("RGB"))
        ok = y_pred[i] == y_true[i]
        ax.set_title(f"true: {classes[y_true[i]]}\npred: {classes[y_pred[i]]} ({conf[i]:.2f})",
                     fontsize=9, color="green" if ok else "red")
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print("Saved", path)


def main():
    args = parse_args()
    root = Path(args.data_root)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # ------------------------------------------------------------ 1. model
    state = torch.load(
        args.ckpt,
        map_location=device,
        weights_only=True
    )
    classes = state["classes"]
    img_size = int(state["img_size"])  # make sure preprocessing matches training
    model = C.DisasterClassifier(state["model_name"], len(classes)).to(device)
    model.load_state_dict(state["model"])
    model.eval()
    class_to_idx = {c: i for i, c in enumerate(classes)}
    _, eval_tf = C.build_transforms(img_size)
    print("Device:", device)
    print("Model:", state["model_name"], "| image size:", img_size)
    print("Classes:", classes)

    # ------------------------------------------------ 2. predict test set
    test_df = C.load_split(root / C.TEST_TSV_NAME, "test", root)
    test_ds = C.DisasterDataset(test_df, class_to_idx, eval_tf, img_size)
    loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    probs_list = []
    with torch.no_grad():
        for x, _ in tqdm(loader):
            probs_list.append(torch.softmax(model(x.to(device)), dim=1).cpu())
    probs = torch.cat(probs_list).numpy()
    y_true = np.array(test_ds.labels)
    y_pred = probs.argmax(1)
    conf = probs.max(1)
    paths = test_df["full_path"].tolist()
    print("Done:", len(y_true), "test images")

    # --------------------------------------------------------- 3. metrics
    print(f"\nAccuracy : {accuracy_score(y_true, y_pred):.4f}")
    print(f"Macro-F1 : {f1_score(y_true, y_pred, average='macro'):.4f}\n")
    print(classification_report(y_true, y_pred, target_names=classes, digits=3))

    f1s = f1_score(y_true, y_pred, average=None)
    order = np.argsort(f1s)
    plt.figure(figsize=(7, 4))
    plt.barh([classes[i] for i in order], f1s[order], color="#3b82f6")
    plt.xlim(0, 1)
    plt.xlabel("F1 score")
    plt.title("Per-class F1 (weakest at the top)")
    for y, v in enumerate(f1s[order]):
        plt.text(v + 0.01, y, f"{v:.2f}", va="center")
    plt.tight_layout()
    plt.savefig(out / "per_class_f1.png", dpi=150)
    plt.close()

    # -------------------------------------------- 4. confusion matrices
    cm = confusion_matrix(y_true, y_pred)
    cm_norm = confusion_matrix(y_true, y_pred, normalize="true")
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    for ax, data, title, fmt in [(axes[0], cm, "Counts", "d"),
                                 (axes[1], cm_norm, "Normalized (recall)", ".2f")]:
        im = ax.imshow(data, cmap="Blues")
        ax.set_xticks(range(len(classes)))
        ax.set_yticks(range(len(classes)))
        ax.set_xticklabels(classes, rotation=45, ha="right")
        ax.set_yticklabels(classes)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title(title)
        thr = data.max() / 2
        for i in range(len(classes)):
            for j in range(len(classes)):
                ax.text(j, i, format(data[i, j], fmt), ha="center", va="center",
                        color="white" if data[i, j] > thr else "black", fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "confusion_matrices.png", dpi=150)
    plt.close(fig)

    pairs = [(classes[i], classes[j], cm[i, j])
             for i in range(len(classes)) for j in range(len(classes))
             if i != j and cm[i, j] > 0]
    print("Top confusions (true -> predicted):")
    for t, p, n in sorted(pairs, key=lambda x: -x[2])[:8]:
        print(f"  {t:15s} -> {p:15s} {n}")

    # ------------------------------ 5. confidence / "needs review" table
    rows = []
    for th in [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        keep = conf >= th
        rows.append({
            "threshold": th,
            "auto-handled %": round(100 * keep.mean(), 1),
            "sent to review %": round(100 * (1 - keep.mean()), 1),
            "accuracy on auto-handled": round(float((y_pred[keep] == y_true[keep]).mean()), 4)
            if keep.any() else None,
        })
    table = pd.DataFrame(rows)
    print("\nConfidence threshold trade-off:\n", table.to_string(index=False))
    table.to_csv(out / "confidence_thresholds.csv", index=False)

    plt.figure(figsize=(7, 4))
    plt.hist(conf[y_pred == y_true], bins=20, alpha=0.7, label="correct", color="#22c55e")
    plt.hist(conf[y_pred != y_true], bins=20, alpha=0.7, label="wrong", color="#ef4444")
    plt.xlabel("Model confidence")
    plt.ylabel("Images")
    plt.legend()
    plt.title("Confidence: correct vs wrong")
    plt.tight_layout()
    plt.savefig(out / "confidence_histogram.png", dpi=150)
    plt.close()

    # ---------------------------------------------------- 6. examples
    random.seed(0)
    wrong = np.where(y_pred != y_true)[0]
    right = np.where(y_pred == y_true)[0]
    args_s = (paths, y_true, y_pred, conf, classes)
    show_samples(random.sample(list(right), min(8, len(right))),
                 "Random CORRECT predictions", out / "samples_correct.png", *args_s)
    show_samples(random.sample(list(wrong), min(8, len(wrong))),
                 "Random WRONG predictions", out / "samples_wrong.png", *args_s)
    # most confident mistakes: often label noise or truly ambiguous images
    worst = wrong[np.argsort(-conf[wrong])][:8]
    show_samples(worst, "Most CONFIDENT mistakes", out / "samples_confident_mistakes.png", *args_s)

    if args.inspect_class in class_to_idx:
        idx = class_to_idx[args.inspect_class]
        mis = np.where((y_true == idx) & (y_pred != idx))[0]
        print(f"\n{args.inspect_class}: {len(mis)} missed out of {(y_true == idx).sum()}")
        show_samples(mis[:8], f"Missed '{args.inspect_class}' images",
                     out / f"samples_missed_{args.inspect_class}.png", *args_s)
    else:
        print(f"--inspect-class '{args.inspect_class}' is not one of {classes}")

    # ---------------------------------------------- 7. your own image
    if args.image:
        result = C.predict_image(args.image, args.ckpt, args.review_threshold)
        print("\nSingle image prediction:", result)

    print(f"\nAll outputs saved to {out.resolve()}")


if __name__ == "__main__":
    main()
