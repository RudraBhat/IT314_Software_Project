# AI folders: scope of `ai-workers/` and `models/`

This page says what each AI folder is for, what runs where, and where new code or documents go. All AI output is advisory: a human dispatcher makes every verification, dispatch, priority and closure decision.

- **`ai-workers/`** is the advisory triage *service*: the code the deployed `drch-ai-triage` container runs. It loads or calls trained models; it never trains them.
- **`models/`** holds every machine-learning *model*: data, training, export, research, the deployment apps of separately hosted models and their test harnesses. Nothing in `models/` is copied into the triage image.
- **`docs/ai/`** holds the documents about them, and `docs/ai/reports/` the saved evaluation results.

## Model and service map

| Model | Code | Reached through | Runs where |
|---|---|---|---|
| Triage rules (`drch-triage-v1-rules`) | `ai-workers/rules.py` | `AI_TRIAGE_URL` (`POST /triage`) | `drch-ai-triage` on Render (image `drch_ai_workers`, port 8001) |
| Multilingual text classifier (IndicBERT, ONNX INT8) | `models/text_classifier/` | `DISASTER_CLASSIFIER_URL` (ingestion) and `TRIAGE_TEXT_MODEL_URL` (triage scenario) | Its own Render service, weights on Hugging Face ([models.md](models.md)) |
| MuRIL text classifier | `models/text_classifier/MuRIL/` | Nothing: evaluated locally | Not deployed (too large for the free tier) |
| Disaster image classifier (ConvNeXt-Tiny) | `models/image_classifier/` | `AI_IMAGE_SERVICE_URL` (`POST /predict`) | Its own Render service, weights on Hugging Face ([models.md](models.md)); unset means photo analysis answers `503 AI_PHOTO_UNAVAILABLE` |
| English crisis text model (TF-IDF) | trained in `models/text_model/`, loaded by `ai-workers/service/text_analysis.py` | `POST /analyze-text` on the triage service, artifact from `TEXT_MODEL_DIR` | Inside the triage service, when an artifact is supplied |
| HumAID BERTweet experiment | `models/text_model/humaid/` | Nothing: offline research only | Local machine only; its data licence forbids deployment |

The deployed text and image services are built from their `deployment/` folders, pushed to their own GitHub repositories and hosted on Render (see [models.md](models.md)). This repository keeps their source; moving these folders does not change the live services.

## `ai-workers/`: advisory triage service

Run from `ai-workers/`: `uvicorn triage_service:app --port 8001`. Only `requirements.txt` is installed in the image.

| Path | Scope | In the image |
|---|---|---|
| `triage_service.py` | FastAPI entry point: `POST /triage`, `POST /analyze-text`, `GET /health`. Contract: [api_contracts.md](../architecture/api_contracts.md) section 7. | Yes |
| `rules.py` | Deterministic keyword and points rules, the baseline for every `/triage` answer. Written form: [triage-rules.md](triage-rules.md). | Yes |
| `service/` | Runtime helpers: `scenario_model.py` (a trained local artifact via `TRIAGE_MODEL_DIR`, or the hosted classifier via `TRIAGE_TEXT_MODEL_URL`, for `/triage`), `text_analysis.py` (checks and loads the English text model artifact for `/analyze-text`; the artifact is trained in `models/text_model/`) and `llm.py` (optional second opinion, off by default). | Yes |
| `artifacts/` | Local trained artifacts the service loads, such as the English text model in `artifacts/text_analysis/` (the `TEXT_MODEL_DIR` default). Ignored by Git and kept out of the image; deployments supply them through `TEXT_MODEL_DIR` or `TRIAGE_MODEL_DIR`. | No |
| `eval/` | Offline evaluation of the triage rules: `baselines.py` (rules against TF-IDF on the team dataset) and `agreement.py` (inter-annotator agreement). Needs `requirements-eval.txt`. | No |
| `data/` | Team-authored text data and fixtures (see below). | No |
| `tests/` | Pytest suite for the service, rules, LLM adapter, model loading and fixtures. Runs in CI. Needs `requirements-dev.txt`. | No |
| `Dockerfile`, `.dockerignore` | Image for the triage service. `.dockerignore` keeps `eval/`, `data/`, `tests/` and the non-runtime requirements files out. | — |

### Files in `ai-workers/data/`

- `rudra_labelled_posts_draft.csv` holds 200 team-authored synthetic examples prepared as a labelling draft. They are all `train_only`; no synthetic item belongs in a test split. `label_draft` is a proposed label, not a final independent annotation: `labeler` says it is pending Rudra's review, and the Neeti and Dhruvil columns are blank. The first 60 rows are marked `shared_for_review` for independent three-person labelling. Reconcile these labels with the [label guideline](text-label-guideline.md) before using them for training.
- `prompt_injection_posts.jsonl` is the ten-post adversarial set for the `/triage` contract test. These posts are test fixtures and must never be added to a training corpus.
- `text_dataset_template.csv` is the schema checked by `validate_dataset.py`. Dataset sources and licences: [text-dataset-sources.md](text-dataset-sources.md).

## `models/`: every ML model

Each model folder follows the same pattern where it applies: `data/`, `train/`, `deployment/`, `testing/`, and an extra folder for a research or comparison model (`MuRIL/`, `humaid/`). Each subfolder has its own `requirements.txt`, and its scripts run from inside that folder (`cd train`, then `python train.py`). Training outputs (`outputs/`, `artifacts/`, checkpoints, weights, downloaded data) stay local and are ignored by Git.

| Path | Scope |
|---|---|
| `text_classifier/data/` | Synthetic multilingual training CSV (15,000 rows) and the separate 512-row test CSV |
| `text_classifier/train/` | IndicBERT fine-tuning (`train_indicbert.py`) and ONNX INT8 export (`export_onnx_int8.py`) |
| `text_classifier/MuRIL/` | MuRIL fine-tuning and local test, not deployed |
| `text_classifier/deployment/` | FastAPI app, Render config and `.python-version` (3.11.11) of the hosted text API. Configured by environment variables (see [env-variables.md](../architecture/env-variables.md), "Model services"); no token, because the model repository is public. |
| `text_classifier/testing/` | Live-API test (`test_text_api.py`); writes to `docs/ai/reports/text_classifier/` by default |
| `image_classifier/train/` | Training (`train_disaster_types.py`), shared helpers (`disaster_common.py`) and checkpoint evaluation (`check_model.py`) |
| `image_classifier/deployment/` | FastAPI app, Render config and `.python-version` (3.11.11) of the hosted image API. Configured by environment variables (see [env-variables.md](../architecture/env-variables.md), "Model services"); no token, because the model repository is public. |
| `image_classifier/testing/` | API test (`test_image_api.py`); writes to `docs/ai/reports/image_classifier/` by default |
| `text_model/train/` | English crisis text model: `download_data.py`, `download_india_data.py` (pinned, checksum-verified sources, saved to the ignored `text_model/data/external/`) and `train.py`. Writes the artifact to the ignored `text_model/artifacts/` and the report to `docs/ai/reports/text_model/`. Its `requirements.txt` reuses `ai-workers/requirements.txt`, so the scikit-learn version recorded in the artifact always matches what `ai-workers/service/text_analysis.py` loads. Details: [text-model.md](text-model.md). |
| `text_model/testing/` | Pytest tests for the training code (`test_training.py`; `conftest.py` puts `../train` on the import path). CI runs them in the AI test job with `python -m pytest` from this folder. |
| `text_model/humaid/` | HumAID BERTweet experiment: `download_events.py`, `train_transformer.py`, `evaluate_tfidf.py`, `inference.py`, `predict.py`, `checksums.json`. Research only, not deployed; needs its own `requirements.txt` (PyTorch). |

There are no Python packages under `models/`: every script runs from its own folder, so nothing there can clash with the triage service's imports.

## Documents and reports

| Document | Content |
|---|---|
| [models.md](models.md) | Multilingual text and image classifiers: data, training, export, deployment, testing, results |
| [text-model.md](text-model.md) | English text model: data, training, evaluation, HumAID experiment, limits |
| [image-classifier-model-check.md](image-classifier-model-check.md) | Image classifier checkpoint evaluation notes and open items |
| [model-card.md](model-card.md), [triage-rules.md](triage-rules.md) | Triage model card and written rules |
| [evaluation-report.md](evaluation-report.md) | Summary of model results |
| [text-dataset-sources.md](text-dataset-sources.md), [text-label-guideline.md](text-label-guideline.md) | Dataset sources and labelling rules |
| `reports/text_classifier/` | API test report, metrics by language and augmentation, per-row predictions, MuRIL local test report |
| `reports/image_classifier/` | API test report and per-image deployment test results |
| `reports/text_model/` | English text model and HumAID evaluation JSON (metrics and hashes only) |

## Where new work goes

- Code the triage service runs (`/triage`, `/analyze-text`): `ai-workers/`, within `ai-workers/requirements.txt`.
- A new model: its own folder under `models/`, using `data/`, `train/`, `deployment/` and `testing/` as needed, each with its own requirements file.
- Explanations and model notes: `docs/ai/`. Saved evaluation results: `docs/ai/reports/<model>/`.
