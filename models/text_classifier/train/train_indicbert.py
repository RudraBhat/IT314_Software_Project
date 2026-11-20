"""Fine-tune AI4Bharat IndicBERT on the V2 multilingual disaster dataset.

Five classes: Fire, Earthquake, Cyclone, Flood, Non-Disaster.
Model input: ``text``. Target: ``label``. ``language`` and ``scenario_group``
are metadata only (group-aware split and per-language evaluation).

Original ``tweets_multilingual.csv`` is the held-out test file. It is NOT used
for training, validation, checkpoint selection or early stopping. It uses the
label ``Hurricane``, which is mapped to ``Cyclone`` in an in-memory copy only.

NOTE: the 15,000 training rows are synthetic, so validation scores can be
optimistic. Judge real-world quality on the held-out test file (and on real
tweets if you can collect them), not on validation scores alone.

Example:
    python train_indicbert.py \
        --train-csv ../data/disaster_multilingual_train_v2_15000.csv \
        --test-csv  ../data/tweets_multilingual.csv \
        --output-dir outputs

A GPU is strongly recommended (Colab T4 / Kaggle). The base model is public,
so no Hugging Face token is needed.
"""

import argparse
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # save plots to files
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score,
                             classification_report, confusion_matrix, f1_score,
                             precision_recall_fscore_support)
from torch.utils.data import Dataset
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          DataCollatorWithPadding, EarlyStoppingCallback,
                          Trainer, TrainingArguments, set_seed)

LABELS = ["Fire", "Earthquake", "Cyclone", "Flood", "Non-Disaster"]
LABEL2ID = {name: i for i, name in enumerate(LABELS)}
ID2LABEL = {i: name for name, i in LABEL2ID.items()}
ALL_IDS = list(range(len(LABELS)))


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--train-csv", default="../data/disaster_multilingual_train_v2_15000.csv")
    p.add_argument("--test-csv", default="../data/tweets_multilingual.csv",
                   help="Held-out test CSV (set to '' to skip the final test)")
    p.add_argument("--output-dir", default="outputs")
    p.add_argument("--model-name", default="ai4bharat/indic-bert")
    p.add_argument("--max-length", type=int, default=160)
    p.add_argument("--train-batch-size", type=int, default=16)
    p.add_argument("--eval-batch-size", type=int, default=32)
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--learning-rate", type=float, default=2e-5)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--warmup-ratio", type=float, default=0.10)
    p.add_argument("--early-stopping-patience", type=int, default=2)
    p.add_argument("--val-group-fraction", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


class DisasterDataset(Dataset):
    def __init__(self, frame, tokenizer, max_length):
        self.labels = frame["label_id"].astype(int).tolist()
        self.encodings = tokenizer(frame["text"].astype(str).tolist(),
                                   truncation=True, max_length=max_length, padding=False)

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, index):
        item = {k: torch.tensor(v[index], dtype=torch.long)
                for k, v in self.encodings.items()}
        item["labels"] = torch.tensor(self.labels[index], dtype=torch.long)
        return item


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    precision, recall, macro_f1, _ = precision_recall_fscore_support(
        labels, predictions, labels=ALL_IDS, average="macro", zero_division=0)
    return {
        "accuracy": accuracy_score(labels, predictions),
        "macro_f1": macro_f1,
        "weighted_f1": f1_score(labels, predictions, average="weighted", zero_division=0),
        "macro_precision": precision,
        "macro_recall": recall,
    }


def load_training_data(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    print("Dataset:", df.shape, "| columns:", df.columns.tolist())

    required = {"text", "label", "language", "scenario_group"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = df.copy()
    for col in ["text", "label", "language"]:
        df[col] = df[col].astype("string").str.strip()
    before = len(df)
    df = df.dropna(subset=["text", "label", "language"])
    df = df[df["text"].str.len() > 0].reset_index(drop=True)
    print("Removed missing/empty rows:", before - len(df))

    unknown = sorted(set(df["label"].unique()) - set(LABELS))
    if unknown:
        raise ValueError(f"Unexpected training labels: {unknown}")

    print("\nClass counts:\n", df["label"].value_counts().reindex(LABELS).to_string())
    print("\nLanguage counts:\n", df["language"].value_counts().to_string())
    print("\nClass x language:\n", pd.crosstab(df["label"], df["language"]).reindex(LABELS))

    duplicates = int(df["text"].duplicated().sum())
    print("\nExact duplicate texts:", duplicates)
    if duplicates:
        print("Removing exact duplicate text rows.")
        df = df.drop_duplicates(subset=["text"]).reset_index(drop=True)

    df["label_id"] = df["label"].map(LABEL2ID).astype(int)
    df["scenario_group"] = df["scenario_group"].astype(str)

    group_counts = df.groupby(["label", "language"])["scenario_group"].nunique()
    if (group_counts < 2).any():
        raise ValueError("Every label-language pair needs at least two scenario groups.")
    return df


def group_aware_split(df, val_fraction, seed):
    """Hold out whole scenario groups inside every label x language pair."""
    rng = np.random.default_rng(seed)
    train_indices, val_indices = [], []
    for (_, _), part in df.groupby(["label", "language"]):
        groups = np.asarray(part["scenario_group"].unique())
        n_val = max(1, int(round(len(groups) * val_fraction)))
        heldout = set(rng.choice(groups, size=n_val, replace=False).tolist())
        is_val = part["scenario_group"].isin(heldout)
        val_indices.extend(part.index[is_val].tolist())
        train_indices.extend(part.index[~is_val].tolist())

    train_idx = np.asarray(sorted(train_indices), dtype=int)
    val_idx = np.asarray(sorted(val_indices), dtype=int)

    train_groups = set(df.loc[train_idx, "scenario_group"])
    val_groups = set(df.loc[val_idx, "scenario_group"])
    assert train_groups.isdisjoint(val_groups), "Scenario-group leakage detected."
    pair = df["label"] + "|" + df["language"]
    assert set(pair[train_idx]) == set(pair), "A label-language pair is missing from train."
    assert set(pair[val_idx]) == set(pair), "A label-language pair is missing from validation."

    train_df = df.iloc[train_idx].reset_index(drop=True)
    val_df = df.iloc[val_idx].reset_index(drop=True)
    print("\nTraining rows:", len(train_df), "| Validation rows:", len(val_df))
    print("Train/validation scenario group overlap:", len(train_groups & val_groups))
    return train_df, val_df


def plot_confusion(y_true, y_pred, title, path):
    cm = confusion_matrix(y_true, y_pred, labels=ALL_IDS)
    fig, ax = plt.subplots(figsize=(8, 7))
    ConfusionMatrixDisplay(cm, display_labels=LABELS).plot(
        ax=ax, xticks_rotation=35, colorbar=False, cmap="Blues")
    plt.title(title)
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_history(history, path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    if "loss" in history:
        rows = history[history["loss"].notna()]
        axes[0].plot(rows["epoch"], rows["loss"], marker="o", label="Training loss")
    if "eval_loss" in history:
        rows = history[history["eval_loss"].notna()]
        axes[0].plot(rows["epoch"], rows["eval_loss"], marker="o", label="Validation loss")
    axes[0].set_title("Loss")
    axes[0].set_xlabel("Epoch")
    axes[0].legend()
    axes[0].grid(alpha=0.3)
    for key, label in [("eval_macro_f1", "Validation macro-F1"),
                       ("eval_accuracy", "Validation accuracy")]:
        if key in history:
            rows = history[history[key].notna()]
            axes[1].plot(rows["epoch"], rows[key], marker="o", label=label)
    axes[1].set_title("Validation metrics")
    axes[1].set_xlabel("Epoch")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def per_language_metrics(frame, y_true, y_pred, with_weighted):
    rows = []
    for language in sorted(frame["language"].unique()):
        idx = np.where(frame["language"].to_numpy() == language)[0]
        yt, yp = y_true[idx], y_pred[idx]
        row = {"language": language, "rows": len(idx),
               "accuracy": accuracy_score(yt, yp),
               "macro_f1": f1_score(yt, yp, average="macro", zero_division=0)}
        if with_weighted:
            row["weighted_f1"] = f1_score(yt, yp, average="weighted", zero_division=0)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    args = parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    best_dir = out / "indicbert_disaster_classifier_v2_best"
    ckpt_dir = out / "training_checkpoints"
    set_seed(args.seed)

    print("PyTorch:", torch.__version__, "| CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
    else:
        print("WARNING: no GPU found. Training on CPU will be very slow.")

    # ---------------------------------------------------------- data + split
    df = load_training_data(args.train_csv)
    train_df, val_df = group_aware_split(df, args.val_group_fraction, args.seed)

    # ------------------------------------------------------------ tokenizer
    print("\nLoading tokenizer:", args.model_name)
    MODEL_REVISION = "4d6f311e9ad72e1e09f0111f1877eadb29a04b29"
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_name,
        revision=MODEL_REVISION,
        use_fast=False,
        keep_accents=True,
    )

    texts = df["text"].astype(str).tolist()
    lengths = []
    for start in range(0, len(texts), 256):
        enc = tokenizer(texts[start:start + 256], truncation=False, padding=False)
        lengths.extend(len(ids) for ids in enc["input_ids"])
    lengths = np.asarray(lengths)
    for q in [50, 90, 95, 99, 100]:
        print(f"Token length p{q}: {np.percentile(lengths, q):.0f}")
    n_long = int((lengths > args.max_length).sum())
    print(f"Rows truncated at {args.max_length} tokens: {n_long} ({100 * n_long / len(lengths):.2f}%)")

    train_dataset = DisasterDataset(train_df, tokenizer, args.max_length)
    val_dataset = DisasterDataset(val_df, tokenizer, args.max_length)
    data_collator = DataCollatorWithPadding(
        tokenizer=tokenizer, padding=True,
        pad_to_multiple_of=8 if torch.cuda.is_available() else None)

    # ---------------------------------------------------------------- model
    MODEL_REVISION = "4d6f311e9ad72e1e09f0111f1877eadb29a04b29"
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        revision=MODEL_REVISION,
        num_labels=len(LABELS),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        problem_type="single_label_classification",
    )
    total = sum(p.numel() for p in model.parameters())
    print(f"Total parameters: {total:,} (five-class head is newly initialized)")

    # ------------------------------------------------------------- training
    training_args = TrainingArguments(
        output_dir=str(ckpt_dir),
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.train_batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        weight_decay=args.weight_decay,
        warmup_ratio=args.warmup_ratio,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_strategy="steps",
        logging_steps=50,
        load_best_model_at_end=True,
        metric_for_best_model="eval_macro_f1",  # best checkpoint = validation macro-F1
        greater_is_better=True,
        save_total_limit=2,
        fp16=torch.cuda.is_available(),
        dataloader_num_workers=2,
        dataloader_pin_memory=torch.cuda.is_available(),
        report_to="none",
        seed=args.seed,
        data_seed=args.seed,
        optim="adamw_torch",
        max_grad_norm=1.0,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        tokenizer=tokenizer,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience)],
    )
    trainer.train()
    print("Best checkpoint:", trainer.state.best_model_checkpoint)
    print("Best validation metric:", trainer.state.best_metric)

    trainer.save_model(str(best_dir))
    tokenizer.save_pretrained(str(best_dir))
    with open(best_dir / "label_mapping.json", "w", encoding="utf-8") as f:
        json.dump({"label2id": LABEL2ID,
                   "id2label": {str(k): v for k, v in ID2LABEL.items()},
                   "max_length": args.max_length,
                   "base_model": args.model_name}, f, ensure_ascii=False, indent=2)
    print("Best model saved to:", best_dir)

    history = pd.DataFrame(trainer.state.log_history)
    history.to_csv(out / "training_history.csv", index=False)
    plot_history(history, out / "training_history.png")

    # ------------------------------------------------ validation evaluation
    val_output = trainer.predict(val_dataset)
    val_true = val_output.label_ids
    val_pred = np.argmax(val_output.predictions, axis=-1)
    print("\nValidation metrics:")
    print(json.dumps(compute_metrics((val_output.predictions, val_true)), indent=2))
    print("\nValidation classification report:")
    print(classification_report(val_true, val_pred, labels=ALL_IDS, target_names=LABELS,
                                digits=4, zero_division=0))
    plot_confusion(val_true, val_pred, "IndicBERT validation confusion matrix",
                   out / "validation_confusion_matrix.png")

    val_results = val_df[["text", "label", "language"]].copy()
    val_results["predicted_label"] = [ID2LABEL[int(x)] for x in val_pred]
    val_results.to_csv(out / "validation_predictions.csv", index=False)
    lang_val = per_language_metrics(val_df, val_true, val_pred, with_weighted=True)
    print("\nValidation performance by language:\n", lang_val.to_string(index=False))
    lang_val.to_csv(out / "validation_metrics_by_language.csv", index=False)

    # ----------------------------------------- final held-out test (optional)
    if args.test_csv:
        test_df = pd.read_csv(args.test_csv, encoding="utf-8-sig")
        if not {"text", "label"}.issubset(test_df.columns):
            raise ValueError(f"Test file must contain text and label. Found: {test_df.columns.tolist()}")
        test_df = test_df.copy()
        test_df["text"] = test_df["text"].astype("string").str.strip()
        test_df["label"] = test_df["label"].astype("string").str.strip()
        if "language" not in test_df.columns:
            test_df["language"] = "unknown"
        test_df = test_df.dropna(subset=["text", "label"])
        test_df = test_df[test_df["text"].str.len() > 0].reset_index(drop=True)

        # Normalize only this in-memory copy (the source file is not edited).
        test_df["label"] = test_df["label"].replace(
            {"Hurricane": "Cyclone", "hurricane": "Cyclone", "HURRICANE": "Cyclone"})
        unknown = sorted(set(test_df["label"].unique()) - set(LABELS))
        if unknown:
            raise ValueError(f"Unexpected test labels: {unknown}")

        print("\nTest rows:", len(test_df))
        print(test_df["label"].value_counts().reindex(LABELS, fill_value=0).to_string())
        missing_classes = [x for x in LABELS if x not in set(test_df["label"])]
        if missing_classes:
            print("No real test examples for:", missing_classes)
        overlap = test_df["text"].astype(str).isin(set(df["text"].astype(str))).sum()
        print(f"Exact text overlap with training data: {overlap}/{len(test_df)}")

        test_df["label_id"] = test_df["label"].map(LABEL2ID).astype(int)
        test_output = trainer.predict(DisasterDataset(test_df, tokenizer, args.max_length))
        test_true = test_output.label_ids
        test_pred = np.argmax(test_output.predictions, axis=-1)

        print("\nFINAL HELD-OUT TEST RESULTS")
        print("Accuracy:", round(accuracy_score(test_true, test_pred), 4))
        print("Macro-F1 across all five labels (absent class counted as zero):",
              round(f1_score(test_true, test_pred, labels=ALL_IDS, average="macro",
                             zero_division=0), 4))
        print(classification_report(test_true, test_pred, labels=ALL_IDS, target_names=LABELS,
                                    digits=4, zero_division=0))

        test_results = test_df.copy()
        test_results["predicted_label"] = [ID2LABEL[int(x)] for x in test_pred]
        test_results.to_csv(out / "heldout_test_predictions.csv", index=False)
        plot_confusion(test_true, test_pred, "Held-out test confusion matrix",
                       out / "heldout_confusion_matrix.png")
        lang_test = per_language_metrics(test_df, test_true, test_pred, with_weighted=False)
        print("\nTest metrics by language:\n", lang_test.to_string(index=False))
        lang_test.to_csv(out / "heldout_metrics_by_language.csv", index=False)

    # ------------------------------------------------------- quick samples
    samples = [
        "સુરતના ગોડાઉનમાં આગ લાગી અને ફાયર બ્રિગેડ પહોંચી.",
        "bhukamp na aachka pachi loko ghar ni bahar aavi gaya",
        "भारी बारिश से कई गांवों में बाढ़ आ गई है।",
        "A cyclone warning has been issued for coastal villages.",
        "The college is organising its annual cultural festival next week.",
    ]
    trainer.model.eval()
    device = next(trainer.model.parameters()).device
    for text in samples:
        enc = tokenizer(text, truncation=True, max_length=args.max_length, return_tensors="pt")
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.inference_mode():
            probs = torch.softmax(trainer.model(**enc).logits.float(), dim=-1)[0].cpu().numpy()
        best = int(np.argmax(probs))
        print(f"\nTEXT: {text}\nPREDICTION: {ID2LABEL[best]} ({probs[best]:.3f})")

    # ------------------------------------------------------ package model
    zip_base = out / "indicbert_disaster_classifier_v2_best"
    shutil.make_archive(str(zip_base), "zip", root_dir=best_dir)
    print(f"\nModel folder: {best_dir}\nModel archive: {zip_base}.zip")
    print("Next: run export_onnx_int8.py to create the files the API needs.")


if __name__ == "__main__":
    main()
