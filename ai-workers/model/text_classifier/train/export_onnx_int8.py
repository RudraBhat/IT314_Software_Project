"""Export the fine-tuned IndicBERT classifier to ONNX INT8 for the Render API.

Creates the exact files that ``deployment/app.py`` downloads from Hugging Face:
    model_int8.onnx, spiece.model, tokenizer_config.json,
    special_tokens_map.json, label_mapping.json, config.json

Example:
    python export_onnx_int8.py \
        --model-dir outputs/indicbert_disaster_classifier_v2_best \
        --export-dir outputs/hf_export

Optional upload (needs a write token in HF_TOKEN):
    python export_onnx_int8.py --model-dir ... --export-dir ... \
        --upload-repo your-username/indicbert-disaster-api

The deployed API feeds only input_ids and attention_mask, so only those two
inputs are exported. Check the result with testing/test_text_api.py.
"""

import argparse
import os
import shutil
from pathlib import Path

import torch
from transformers import AlbertTokenizer, AutoModelForSequenceClassification

REQUIRED_FILES = ["model_int8.onnx", "spiece.model", "tokenizer_config.json",
                  "special_tokens_map.json", "label_mapping.json", "config.json"]


class LogitsOnly(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask):
        return self.model(input_ids=input_ids, attention_mask=attention_mask).logits


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", required=True, help="Folder saved by train_indicbert.py")
    p.add_argument("--export-dir", default="outputs/hf_export")
    p.add_argument("--max-length", type=int, default=160)
    p.add_argument("--opset", type=int, default=14)
    p.add_argument("--upload-repo", default=None, help="Optional HF repo id to upload to")
    args = p.parse_args()

    from onnxruntime.quantization import QuantType, quantize_dynamic

    model_dir, export_dir = Path(args.model_dir), Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    # These files are loaded from the local trained model directory.
    model = AutoModelForSequenceClassification.from_pretrained(
        str(model_dir),
        local_files_only=True,
    ).eval()  # nosec B615

    tokenizer = AlbertTokenizer.from_pretrained(
        str(model_dir),
        local_files_only=True,
        use_fast=False,
        keep_accents=True,
    )  # nosec B615

    enc = tokenizer("test message", return_tensors="pt", truncation=True,
                    max_length=args.max_length, padding="max_length")
    inputs = (enc["input_ids"], enc["attention_mask"])

    fp32_path = export_dir / "model_fp32.onnx"
    export_kwargs = dict(
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                      "attention_mask": {0: "batch", 1: "seq"},
                      "logits": {0: "batch"}},
        opset_version=args.opset,
    )
    with torch.no_grad():
        try:
            torch.onnx.export(LogitsOnly(model), inputs, str(fp32_path),
                              dynamo=False, **export_kwargs)  # legacy exporter
        except TypeError:  # older torch without the `dynamo` argument
            torch.onnx.export(LogitsOnly(model), inputs, str(fp32_path), **export_kwargs)
    print("Exported FP32 ONNX:", fp32_path)

    int8_path = export_dir / "model_int8.onnx"
    quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)
    print("Quantized INT8 ONNX:", int8_path,
          f"({int8_path.stat().st_size / 1024 ** 2:.1f} MB)")
    fp32_path.unlink()
    for extra in export_dir.glob("*.onnx_data"):
        extra.unlink()

    tokenizer.save_pretrained(str(export_dir))  # spiece.model, tokenizer_config, special tokens
    shutil.copy(model_dir / "config.json", export_dir / "config.json")
    shutil.copy(model_dir / "label_mapping.json", export_dir / "label_mapping.json")

    missing = [f for f in REQUIRED_FILES if not (export_dir / f).exists()]
    if missing:
        raise SystemExit(f"Export incomplete, missing: {missing}")
    print("All files ready in", export_dir.resolve())

    if args.upload_repo:
        from huggingface_hub import HfApi

        api = HfApi(token=os.environ.get("HF_TOKEN"))
        api.create_repo(args.upload_repo, repo_type="model", exist_ok=True)
        for name in REQUIRED_FILES:
            api.upload_file(path_or_fileobj=str(export_dir / name), path_in_repo=name,
                            repo_id=args.upload_repo, repo_type="model")
            print("Uploaded", name)


if __name__ == "__main__":
    main()
