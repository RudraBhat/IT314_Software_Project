# Sprint 1 — Image Classifier Reproduction

## Status

The saved `check_model(1).ipynb` notebook contains a successful model-loading and evaluation run. It evaluates the image classifier on 3,195 test images.

**Important:** This note documents the notebook's saved results. It does not claim that the FastAPI `/predict` service has been tested, or that the required 50-image service test has been completed.

## Model details

- **Architecture:** ConvNeXt-Tiny
- **Input image size:** 224 × 224
- **Classes:** `earthquake`, `fire`, `flood`, `hurricane`, `landslide`, `not_disaster`, `other_disaster`
- **Evaluation set:** 3,195 images
- **Device shown in saved run:** CPU

## Saved evaluation results

| Metric | Result |
|---|---:|
| Accuracy | 0.8391 (83.91%) |
| Macro-F1 | 0.8153 (81.53%) |
| Weighted-F1 | 0.837 (83.7%) |

### Per-class results

| Class | Precision | Recall | F1-score | Support |
|---|---:|---:|---:|---:|
| `earthquake` | 0.836 | 0.871 | 0.853 | 404 |
| `fire` | 0.899 | 0.925 | 0.912 | 280 |
| `flood` | 0.869 | 0.878 | 0.874 | 599 |
| `hurricane` | 0.740 | 0.696 | 0.717 | 352 |
| `landslide` | 0.853 | 0.869 | 0.861 | 268 |
| `not_disaster` | 0.888 | 0.907 | 0.898 | 990 |
| `other_disaster` | 0.632 | 0.556 | 0.592 | 302 |

The weakest class in this run was `other_disaster` (F1 = 0.592). This class should be treated carefully and included in error analysis.

### Most frequent confusions in the saved run

| True class | Predicted class | Count |
|---|---|---:|
| `other_disaster` | `not_disaster` | 43 |
| `not_disaster` | `other_disaster` | 38 |
| `hurricane` | `flood` | 36 |
| `other_disaster` | `earthquake` | 33 |
| `flood` | `hurricane` | 29 |

## Confidence and human review

The notebook explored thresholds from 0.0 to 0.9. At a threshold of 0.6, the saved results show:

- 89.5% of images above the threshold
- 10.5% sent for review
- 88.31% accuracy among the above-threshold images

This is an exploratory result on the test set, not a finalized threshold recommendation. Choose and tune the threshold on a validation set before making a production decision. A high-confidence prediction should not be treated as verified incident evidence.

## How to reproduce the notebook evaluation

Place the notebook in the same directory as the matching training module and model checkpoint. The notebook expects:

- `check_model.ipynb`
- `train_disaster_types.py`
- `best_model.pt`
- The dataset split files and image paths expected by `train_disaster_types.py`

Install the dependencies required by the training module and notebook in your Python environment. At minimum, the notebook imports PyTorch, torchvision-compatible model dependencies, Pillow, NumPy, pandas, Matplotlib, scikit-learn, and tqdm.

Open Jupyter Notebook or JupyterLab, select the correct environment, and run the notebook cells in order. The model checkpoint must match the architecture and class metadata expected by the training module.

For custom-image testing, edit `IMAGE_PATH` in the notebook to point to a real image on your computer, then run the commented `predict_file(IMAGE_PATH)` lines.

## Required Sprint 1 follow-up

According to the Sprint 1 task, complete these items before marking image-classifier reproduction done:

- [ ] Confirm the checkpoint and `classes.json` from the project README/maintainer; keep model weights out of Git.
- [ ] Run the local prediction service and test at least 50 images through its prediction endpoint.
- [ ] Record the 50-image test method and observed results, and compare them with the README's reported accuracy where the datasets and metrics are comparable.
- [ ] Implement and test the class mapping:
  - `fire` → `INDUSTRIAL_FIRE`
  - `flood` → `URBAN_FLOODING`
  - `hurricane` → `CYCLONE`
  - `earthquake` → `EARTHQUAKE`
  - `landslide` and `other_disaster` → out of scope
  - `not_disaster` → no suggestion
- [ ] Ask Neeti to review the class mapping and accuracy note.
- [ ] If the weights cannot be obtained, inform Neeti and Siddh by Sprint Day 2 and mark image triage unavailable.

## Limitations

- The reported numbers are copied from the saved notebook outputs; they have not been independently rerun in this review.
- Notebook evaluation on a test dataset is different from testing the deployed/local API.
- The 50-image service test and class-mapping module are not demonstrated by this notebook alone.
- The notebook's custom-image example uses a placeholder path and must be updated before running it.
