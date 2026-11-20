# Disaster Detection from Social Media: Text and Image Classifiers

A model that classifies social-media posts as disasters. It has two parts:

* a **text classifier** for short multilingual messages (English, Hindi, Gujarati, Hinglish, romanised Gujarati), and
* an **image classifier** for disaster photos.

Both are served as FastAPI apps on Render, with model files stored on Hugging Face.
This document covers the whole path: data, training, export, deployment and testing.

## Live services

| Service | URL | Model files on Hugging Face |
|---|---|---|
| Text API | https://indicbert-disaster-api.onrender.com | `Dhruvil-14/indicbert-disaster-api` |
| Image API | https://disaster-classifier-api.onrender.com | `Dhruvil-14/disaster-classifier` |

Both run on Render's free tier, so the first request after idle time can take a
while while the service wakes up and downloads its model. Docs are at `/docs`, health at `/health`.

* Text: `POST /predict` with `{"text": "..."}`
* Image: `POST /predict` with a multipart field named `file`

## Repository layout

```
models/
|
├── text_classifier/
│   ├── data/                     # synthetic training CSV + test CSV
│   ├── train/                    # IndicBERT fine-tuning + ONNX INT8 export
│   ├── MuRIL/                    # larger, more accurate model (not deployed)
│   ├── deployment/               # FastAPI app for Render (.python-version 3.11.11)
│   └── testing/                  # live-API test script
└── image_classifier/
    ├── train/                    # training + evaluation scripts
    ├── deployment/               # FastAPI app for Render (.python-version 3.11.11)
    └── testing/                  # API test script

docs/ai/reports/
├── text_classifier/              # saved API and MuRIL test results
└── image_classifier/             # saved API test results
```

Paths below are relative to `models/` unless they start with `docs/`. `models/` also holds the
English text model behind the triage service's `/analyze-text` ([text-model.md](text-model.md)); the scope of every
folder is in [folder-scope.md](folder-scope.md).

---

# Part 1: Text classifier

**Task.** Classify a short, tweet-style message into one of five classes:
`Fire`, `Earthquake`, `Cyclone`, `Flood`, `Non-Disaster`.
**Languages.** English (`en`), Hindi (`hi`), Gujarati (`gu`), Hinglish (`hinglish`), romanised Gujarati (`gu_roman`).

## 1.1 Data collection

### Training data is synthetic

We could not collect real social-media posts for training. We applied for social-media
API access (to pull real posts), but **our API key requests were rejected**, so no
real posts could be collected programmatically. The training data is therefore **synthetic**.

* File: `text_classifier/data/disaster_multilingual_train_v2_15000.csv`, 15,000 rows.
* Balanced: 3,000 rows per class and 3,000 per language, i.e. 600 per class x language pair.
* Written as templated scenarios, informed by public disaster-management and news
  sources (e.g. Gujarat Institute of Disaster Management, IMD, state disaster-management
  authorities and Indian news sites; the URLs are listed per row in `reference_urls`).
  Every row is tagged `synthetic_authored_reference_informed`.
* Ten message styles: local news, eyewitness, impact/recovery, help request, official alert,
  casual reply, routine update, casual chat, event announcement and fact-check.
  The last four exist mostly to teach `Non-Disaster` (hard negatives such as workshops or metaphors).
* 340 `scenario_group` values, used to keep near-duplicate scenarios out of validation (see 1.2).
* Columns used for training: `text`, `label`, `language`, `scenario_group`.

### Test data is separate and was not used in training

* File: `text_classifier/data/tweets_multilingual.csv`, 512 rows.
* It was collected/assembled separately from the training data, and was **never used for
  training, validation or early stopping**. Every number below comes from it.
* It labels cyclones as `Hurricane`; training and test scripts map that to `Cyclone`.
* Composition: Cyclone 144, Earthquake 112, Flood 112, Non-Disaster 112, Fire 32.
  Languages: `gu` 128, `hi` 128, `hinglish` 136, `gu_roman` 120. There are **no English test rows**.

### Data and honesty notes

* **Neither dataset is real social-media data.** The test set is more realistic than the
  training set, but we could not verify it against real platform data because API access was refused.
* **Validation scores are optimistic** because training and validation are both synthetic.
  Trust the held-out test numbers, not validation numbers.
* Per the file's own metadata, 360 of the 512 test rows are marked `augmented` (typo/emoji
  noise added), and the 32 Fire rows are tagged `synthetic_supplement_not_original_holdout`.
  So Fire results come from synthetic rows, and the Fire sample is small.
* Test rows are tweet-like (news, eyewitness, official, help, metaphor, hard negatives).
* Real tweets are still needed for a fair measurement.

## 1.2 Training

* Base model: [`ai4bharat/indic-bert`](https://huggingface.co/ai4bharat/indic-bert); script `text_classifier/train/train_indicbert.py`.
* Validation is split by `scenario_group` inside every class x language pair, so
  near-duplicate scenarios do not leak between train and validation.
* Defaults: max length 160, batch size 16, learning rate 2e-5, up to 6 epochs, early
  stopping after 2 epochs without macro-F1 gain. A GPU (Colab T4 / Kaggle) is strongly recommended.

```bash
cd text_classifier/train
pip install -r requirements.txt
python train_indicbert.py --train-csv ../data/disaster_multilingual_train_v2_15000.csv \
    --test-csv ../data/tweets_multilingual.csv --output-dir outputs
```

Extra training notes:

* Run `python train_indicbert.py --help` for all options.
* The base model is public, so no Hugging Face token is needed.
* Outputs in `outputs/`: the best model folder (`indicbert_disaster_classifier_v2_best/`) and its zip,
  training history, validation and held-out confusion matrices, per-language metrics and prediction CSVs.
* The `data/` columns used: training `text`, `label`, `language`, `scenario_group`; test `text`, `label`, `language`.

## 1.3 Two models: why the deployed one is not the best one

We trained two models.

1. **MuRIL** (`google/muril-base-cased`, in `text_classifier/MuRIL/`) is the **better classifier**,
   but it is **large** (a BERT-base-sized model with roughly 237 M parameters), too heavy for a
   free Render instance with 512 MB RAM. It was evaluated locally and **not deployed**.
2. **IndicBERT**, exported to **ONNX INT8**, is **smaller**, so we **trained it as the second model and deployed it**.

Held-out test set (512 rows):

| Model | Where evaluated | Accuracy | Macro-F1 |
|---|---|---:|---:|
| MuRIL (fp32 PyTorch, CPU) | local | **0.791** | **0.814** |
| IndicBERT ONNX INT8 | live Render API | 0.658 | 0.659 |

Accuracy by language:

| Language | Rows | MuRIL | IndicBERT INT8 (deployed) |
|---|---:|---:|---:|
| `hi` | 128 | 0.867 | 0.805 |
| `gu` | 128 | 0.844 | 0.813 |
| `hinglish` | 136 | 0.750 | 0.537 |
| `gu_roman` | 120 | 0.700 | 0.475 |

Caveats on this comparison:

* The two numbers measure different things: MuRIL is the full-precision local model, IndicBERT is the
  quantised model through the live API. We have no separate full-precision IndicBERT test score, so we cannot say how much of the
  gap comes from the model and how much from INT8 quantisation.
* The MuRIL script reads an earlier 12,500-row training file and splits randomly by class x language,
  whereas IndicBERT uses the 15,000-row v2 file with a scenario-grouped split.
* The two models were not trained under identical conditions, so treat the comparison as indicative.

MuRIL details: max length 192, batch 8 with gradient accumulation, lr 2e-5, up to 6 epochs, early stopping,
seed 42. Its weak spots: 39 of 112 Earthquake messages were predicted `Non-Disaster`, and 25 of 144 Cyclone
messages were predicted `Earthquake`. Full report: [`docs/ai/reports/text_classifier/muril_local_test_report.txt`](reports/text_classifier/muril_local_test_report.txt).

## 1.4 Export for deployment

The API needs ONNX INT8 files, not the PyTorch checkpoint:

```bash
python export_onnx_int8.py --model-dir outputs/indicbert_disaster_classifier_v2_best \
    --export-dir outputs/hf_export          # add --upload-repo USER/REPO to upload
```

This writes `model_int8.onnx`, `spiece.model`, `tokenizer_config.json`, `special_tokens_map.json`,
`label_mapping.json` and `config.json`. Upload them to a public Hugging Face model repository. Uploading is the only
step that needs a token: set a write token in `HF_TOKEN` on your own machine for that one command, never in a
deployed service.

## 1.5 Deployment

* Push `text_classifier/deployment/` to GitHub and create a Render web service from it. Model weights are **not** committed to Git.
* Set `PYTHON_VERSION=3.11.11` (also pinned in `.python-version`), `HF_MODEL_REPO=Dhruvil-14/indicbert-disaster-api`,
  `HF_REVISION=main`, `MAX_LENGTH=160` (must match training) and `MODEL_DIR=/tmp/indicbert_model`.
  The model repository is public, so no `HF_TOKEN` is needed.
* Build: `pip install --no-cache-dir -r requirements.txt`. Start: `uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1`. Health check: `/health`.
* ONNX Runtime CPU inference, one worker, one intra-op thread, serialised requests, to stay inside 512 MB.
  The last health check showed a peak RSS of about 387 MB. Re-check after changing the model.
* The label order in `app.py` must match `label_mapping.json` or the service refuses to start.
* GitHub repo contents: `.python-version` (at the repo root, containing `3.11.11`), `app.py`, `requirements.txt`,
  `render.yaml`, `.gitignore`, `README.md`. Render's native Python runtime uses `.python-version` or the
  `PYTHON_VERSION` variable (the variable wins); do not rely on `runtime.txt`.
* The Hugging Face repo must contain `model_int8.onnx`, `spiece.model`, `tokenizer_config.json`,
  `special_tokens_map.json`, `label_mapping.json`, `config.json`.
* Model files download into Render's ephemeral `/tmp` at startup, so restarts or spin-downs re-download them.
  This setup reduces overhead but does not guarantee the model fits a 512 MB instance.
* API routes: `GET /`, `GET /health`, `POST /predict`, `GET /docs`. Example body: `{"text": "તમારો સંદેશ અહીં લખો"}`.

## 1.6 Testing the deployed API

```bash
cd text_classifier/testing
pip install -r requirements.txt
python test_text_api.py --api-url https://indicbert-disaster-api.onrender.com   # --limit 20 for a quick try
```

Defaults: `--csv ../data/tweets_multilingual.csv`, output to `docs/ai/reports/text_classifier/`. The script waits for a sleeping
Render service to wake up and sends requests one at a time. Saved files: `api_test_report.txt`,
`metrics_summary.json`, `metrics_by_language.csv`, `metrics_by_augmentation.csv` and
`tweets_multilingual_api_predictions.csv`. All 512 requests succeeded. Results (accuracy 0.658, macro-F1 0.659) are in [`docs/ai/reports/text_classifier/`](reports/text_classifier/).

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| Fire | 0.619 | 0.813 | 0.703 | 32 |
| Earthquake | 0.584 | 0.777 | 0.667 | 112 |
| Cyclone | 0.868 | 0.500 | 0.634 | 144 |
| Flood | 0.720 | 0.482 | 0.578 | 112 |
| Non-Disaster | 0.601 | 0.875 | 0.713 | 112 |

Romanised and mixed-script text (`gu_roman`, `hinglish`) is much weaker than native script, and
Cyclone and Flood recall is low. Treat these as a prototype baseline.

---

# Part 2: Image classifier

**Task.** Classify a disaster image into one of seven classes: `earthquake`, `fire`, `flood`,
`hurricane`, `landslide`, `other_disaster`, `not_disaster`. The API also returns a confidence score,
the top-3 predictions and a `needs_review` flag for low-confidence results.

## 2.1 Data collection

* Dataset: the [CrisisNLP / MEDIC "Disaster types" task set](https://crisisnlp.qcri.org/crisis-image-datasets-asonam20)
  (about 3.2 GB), real social-media images with crowd-sourced labels. It is **not included** in this package.
* Download and extract so that one folder holds `data/` and the three TSV files
  `consolidated_disaster_types_{train,dev,test}_final.tsv`. The TSV paths contain an extra
  `aidr_disaster_types/` folder that does not exist after extraction; the code strips it.
  If the training log reports many missing images, the paths do not match your layout.
* The data is released for research use: read its terms and cite Alam et al., ASONAM 2020 (arXiv:2011.08916).
* Limits: social-media images only (drone imagery untested) and noisy crowd-sourced labels.

## 2.2 Training

* Scripts: `image_classifier/train/train_disaster_types.py` and shared code in `disaster_common.py` (PyTorch + timm).
* The best epoch is chosen by dev macro-F1. Outputs: `best_model.pt`, `classes.json`, `confusion_matrix.png`.

| Hardware | Model | Image size | Epochs | `--unfreeze-last-fraction` |
|---|---|---|---|---|
| GPU | `convnext_tiny` | 224 | 12 | 1 |
| CPU only | `mobilenetv3_large_100` | 192 | 6 | 0.3 |

```bash
cd image_classifier/train
pip install -r requirements.txt
python train_disaster_types.py --data-root /path/to/data_disaster_types --out-dir outputs
```

`--data-root` can also be set once with the `DISASTER_DATA_ROOT` environment variable. CPU-only run:

```bash
python train_disaster_types.py --data-root /path/to/data_disaster_types --out-dir outputs \
    --model-name mobilenetv3_large_100 --img-size 192 --epochs 6 --unfreeze-last-fraction 0.3
```

The deployed model is ConvNeXt-Tiny at 224 x 224. The checkpoint `best_model.pt` is not in this package;
a copy was shared at https://drive.google.com/file/d/1h8_TlYqEoUh_M_RfgIbnNGz2qmAOqk9a/view?usp=sharing
and the app downloads it from Hugging Face (`Dhruvil-14/disaster-classifier` by default).

## 2.3 Evaluation

```bash
python check_model.py --data-root /path/to/data_disaster_types --ckpt outputs/best_model.pt --out-dir model_check
```

To also predict a single image, add `--image photo.jpg`. It saves metrics, per-class F1, confusion matrices, a confidence-threshold table, and image grids of
correct, wrong and most-confident-wrong predictions. On the 3,195-image test split:
accuracy 0.8391, macro-F1 0.8153.

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| earthquake | 0.836 | 0.871 | 0.853 | 404 |
| fire | 0.899 | 0.925 | 0.912 | 280 |
| flood | 0.869 | 0.878 | 0.874 | 599 |
| hurricane | 0.740 | 0.696 | 0.717 | 352 |
| landslide | 0.853 | 0.869 | 0.861 | 268 |
| not_disaster | 0.888 | 0.907 | 0.898 | 990 |
| other_disaster | 0.632 | 0.556 | 0.592 | 302 |

Weakest classes: `other_disaster`, then `hurricane`. Common confusions: `other_disaster` <-> `not_disaster`,
`hurricane` <-> `flood`. In an exploratory threshold check, a 0.6 threshold flagged about 10.5% of images
for review; that threshold was explored on the test set and is not a tuned recommendation. A confident
prediction is not verified evidence of an incident. Judge the model by per-class F1 and recall, not accuracy alone;
rare or ambiguous classes (`landslide`, `earthquake`, `other_disaster`) need attention, which is what the review flag is for.
Notes from the saved evaluation run are in [`docs/ai/image-classifier-model-check.md`](image-classifier-model-check.md).

## 2.4 Deployment

* Push `image_classifier/deployment/` to GitHub; create a Render web service (Python, Free plan).
* Build: `pip install -r requirements.txt`. Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`. Health check: `/health`.
* Upload `best_model.pt` to a **public** Hugging Face model repo and set `HF_MODEL_REPO_ID=Dhruvil-14/disaster-classifier`
  on Render, plus `PYTHON_VERSION=3.11.11` (also pinned in `.python-version`). Optional: `HF_MODEL_FILENAME`
  (default `best_model.pt`) and `HF_MODEL_REVISION`. The repository is public, so no `HF_TOKEN` is needed.
  The checkpoint must contain the keys `classes`, `img_size`, `model_name` and `model`.
* `needs_review` is set when confidence is below a threshold (default 0.75, with per-class overrides in `app.py`).
* Hugging Face setup: create a Model repo, upload `best_model.pt`, keep it public, and copy the ID (`USERNAME/REPO_NAME`).
* Render setup: choose the Python runtime and the Free plan; do not add the `.pt` file to Git.
* Local run: set `HF_MODEL_REPO_ID`, then `pip install -r requirements.txt` and `uvicorn app:app --reload`.
* Free-tier caution: limited RAM and an ephemeral disk mean a large checkpoint may run out of memory,
  and the file is re-downloaded after a restart.

```javascript
const form = new FormData();
form.append("file", imageFile);   // field name must be "file"
const res = await fetch("https://disaster-classifier-api.onrender.com/predict", { method: "POST", body: form });
const result = await res.json();
```

Example response (shortened):
`{"prediction": "flood", "confidence": 0.91, "top3": [{"label": "flood", "confidence": 0.91}], "needs_review": false}`

## 2.5 Testing the API

```bash
cd image_classifier/testing
pip install -r requirements.txt
python test_image_api.py --api-url https://disaster-classifier-api.onrender.com \
    --tsv /path/to/data_disaster_types/consolidated_disaster_types_test_final.tsv \
    --data-dir /path/to/data_disaster_types/data --limit 20     # drop --limit for the full split
```

The full test split (3,195 images) was run through the API: 3,192 requests succeeded and 3 failed.
Accuracy 0.8396, macro-F1 0.8160, which matches the notebook evaluation (0.8391 / 0.8153). Per-image
results are in [`docs/ai/reports/image_classifier/deployment_test_results.csv`](reports/image_classifier/deployment_test_results.csv). The saved report
shows the run against a local server (`http://127.0.0.1:8000`) rather than the Render URL.

---

## 2.6 Planned follow-up (from the Sprint 1 notes)

[`docs/ai/image-classifier-model-check.md`](image-classifier-model-check.md) lists these open items: confirm the checkpoint and `classes.json`;
test at least 50 images through the prediction endpoint and compare with the reported accuracy; and implement a
class mapping to incident types (`fire` to INDUSTRIAL_FIRE, `flood` to URBAN_FLOODING, `hurricane` to CYCLONE,
`earthquake` to EARTHQUAKE; `landslide` and `other_disaster` out of scope; `not_disaster` no suggestion).
Treat these as planned work, not done. The full-split API run above already covers the 50-image check.

---

# Summary

| | Text | Image |
|---|---|---|
| Training data | Synthetic, 15,000 rows, 5 languages | Real social-media images (MEDIC), crowd-labelled |
| Test data | Separate 512-row tweet-style set, not used in training; not scraped from social platforms | Official MEDIC test split, 3,195 images |
| Best model | MuRIL: acc 0.791, macro-F1 0.814 (local, not deployed: too large) | ConvNeXt-Tiny: acc 0.840, macro-F1 0.816 |
| Deployed model | IndicBERT ONNX INT8: acc 0.658, macro-F1 0.659 | ConvNeXt-Tiny (same as best) |
| Main weakness | Romanised Gujarati and Hinglish; Flood/Cyclone recall | `other_disaster`, `hurricane` |

## Known limitations and next steps

* Our social-media API key applications were rejected, so no real posts were collected; the text training
  data is synthetic and the text test set is not real platform data.
* The Fire test class is small (32 rows, synthetic supplement) and the test set has no English rows.
* Close the quality gap on the deployed text model: try a larger instance to serve MuRIL, or distil/quantise MuRIL, and collect real tweets.
* Image: social-media only, noisy labels, weak `other_disaster` class.
* Free Render instances sleep when idle; expect slow first requests.
