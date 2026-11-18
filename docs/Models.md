# Multilingual Disaster Detection (Text + Image)

This project detects disasters from **text** (Hindi, Gujarati, Hinglish, Roman Gujarati and English) and from **images**. It contains the data tools, the model training and evaluation code, and two deployed APIs.

The text model predicts one of five classes:

| Class | Notes |
|---|---|
| `Fire` | |
| `Earthquake` | |
| `Cyclone` | Hurricane tweets are merged into this class, because a hurricane is a tropical cyclone |
| `Flood` | |
| `Non-Disaster` | Includes hard negatives such as metaphors ("my inbox is a flood"), documentaries and drills |

---

## Live demos

| Model | URL |
|---|---|
| Text classifier (IndicBERT) | https://indicbert-disaster-api.onrender.com |
| Image classifier | https://disaster-classifier-api.onrender.com |

If a service has been idle, the first request may be slow while Render starts it again.

---

## Which text model is deployed, and why

We fine-tuned **MuRIL** (`google/muril-base-cased`), which is our best text model. It is too large to deploy on Render, so the live text API serves a **smaller IndicBERT-based model** instead.

- **MuRIL** is used for training experiments, local evaluation and as the quality reference (results below). The trained checkpoint (`muril_disaster_classifier_best.zip`) is large and is not stored in the repository.
- **MuRIL** drive link - https://drive.google.com/drive/folders/104V_1fC0FthZ8jAX043E72WID2KDmEvL?usp=sharing
- **IndicBERT** is the deployed model, chosen because it fits Render's size and memory limits. A smaller model usually gives up some accuracy, so the live service should be expected to score at or below the MuRIL numbers in this README.

---

## Project structure

```
Project/
├── README.md                                   <- this file (the only README)
├── text/
│   ├── MuRIL/
│   │   ├── fine_tune_muril_disaster_classifier.py   Colab notebook export: fine-tunes MuRIL
│   │   ├── test_muril_local.py                      local evaluation on the held-out test CSV
│   │   ├── muril_local_test_report.txt              evaluation report (summarized below)
│   │   ├── tweets_multilingual.csv                  held-out test set (512 rows)
│   │   └── muril_disaster_classifier_best.zip       trained checkpoint (large, not in git)
│   └── data tools/
│       ├── build_multilingual_tweets.py             builds the noisy multilingual seed/test data
│       ├── generate_tweets_llm.py                   generates more tweets with the Claude or Groq API
│       ├── human_style_tweets.csv                   100 English tweets for quick checks
│       ├── check_hurricane_cyclone.py / .ipynb      Hurricane vs Cyclone label analysis
│       └── groq_vs_anthropic_key.xlsx               notes on choosing an API provider
└── image/                                      image classifier code and API
```

---

## Text pipeline

### 1. Data

| File | Purpose | Details |
|---|---|---|
| `disaster_multilingual_train_12500.csv` | Training and validation | Columns `text`, `label`, `language`. Synthetic, with equally sized class x language groups. Only `text` is given to the model; `language` is used for stratified splitting and per-language reports. |
| `tweets_multilingual.csv` | Final held-out test | 512 rows: 480 hand-written tweets (120 seeds, each with 3 noisy copies; Hurricane relabeled Cyclone) plus 32 synthetic Fire rows. Languages: `hi`, `gu`, `hinglish`, `gu_roman`. |
| `human_style_tweets.csv` | Quick English sanity check | 100 tweets with a `style` column for error analysis. |

The test set is **never** used for training, tuning, epoch selection or checkpoint selection.

### 2. Training (MuRIL)

Run `fine_tune_muril_disaster_classifier.py` in Google Colab with a GPU (it is a Colab notebook exported as a script).

| Setting | Value |
|---|---|
| Base model | `google/muril-base-cased` |
| Max sequence length | 192 tokens |
| Batch size | 8, with gradient accumulation 4 (effective 32) |
| Learning rate / weight decay | 2e-5 / 0.01 |
| Max epochs | 6, early stopping after 2 epochs without improvement |
| Checkpoint selection | Best validation macro-F1 (not accuracy) |
| Validation split | 15%, stratified by class and language |
| Precision | FP16 mixed precision |

### 3. Local evaluation

```bash
pip install torch transformers sentencepiece scikit-learn pandas matplotlib
python test_muril_local.py --model-zip muril_disaster_classifier_best.zip --test-csv tweets_multilingual.csv
```

It runs on CPU by default (`--device cuda` if you have a GPU), maps Hurricane to Cyclone, and writes results to `muril_local_test_results/`: row-level predictions, metrics by language and by augmentation, a JSON summary, a text report and a confusion-matrix image (the image needs `matplotlib`).

---

## Results (MuRIL on the held-out multilingual test set)

Full report: `text/MuRIL/muril_local_test_report.txt`.

### Overall (512 rows)

| Metric | Value |
|---|---|
| Accuracy | 0.791 |
| Macro F1 | 0.814 |
| Weighted F1 | 0.793 |

### Per class

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| Fire | 0.968 | 0.938 | 0.952 | 32 |
| Earthquake | 0.657 | 0.634 | 0.646 | 112 |
| Cyclone | 1.000 | 0.694 | 0.820 | 144 |
| Flood | 0.911 | 0.821 | 0.864 | 112 |
| Non-Disaster | 0.651 | 1.000 | 0.789 | 112 |

### Per language

| Language | Rows | Accuracy | Macro F1 |
|---|---|---|---|
| Hindi (`hi`) | 128 | 0.867 | 0.885 |
| Gujarati (`gu`) | 128 | 0.844 | 0.856 |
| Hinglish (`hinglish`) | 136 | 0.750 | 0.765 |
| Roman Gujarati (`gu_roman`) | 120 | 0.700 | 0.722 |

### Confusion matrix (rows = true class, columns = predicted)

| True \ Predicted | Fire | Earthquake | Cyclone | Flood | Non-Disaster |
|---|---|---|---|---|---|
| Fire | 30 | 2 | 0 | 0 | 0 |
| Earthquake | 1 | 71 | 0 | 1 | 39 |
| Cyclone | 0 | 25 | 100 | 8 | 11 |
| Flood | 0 | 10 | 0 | 92 | 10 |
| Non-Disaster | 0 | 0 | 0 | 0 | 112 |

### Reading the results

- **Script matters.** Text written in Devanagari or Gujarati script scores clearly higher than Roman-script text (Hinglish and Roman Gujarati), which has no standard spelling.
- **Main weakness: disasters predicted as Non-Disaster.** 39 Earthquake, 11 Cyclone and 10 Flood rows were predicted as Non-Disaster. That is why Non-Disaster has perfect recall but only 0.65 precision.
- **Cyclone/Earthquake mix-up.** 25 of 144 Cyclone rows were predicted as Earthquake. The row-level predictions in `muril_local_test_results/` show which tweets are affected.
- **Noise is handled well.** Original (un-augmented) rows score 0.796 accuracy and noisy copies 0.789, so typos and slang did not hurt much.
- **Augmented-only macro F1 of 0.631** (over all five classes) is not a real weakness: Fire appears only in the un-augmented rows, so that class has no support in the augmented subset. Over the classes present it is 0.789.

---

## Limitations

- **The data is synthetic.** Both the training data and the test set were generated and hand-written, not collected from real users. Scores on real tweets will probably be lower. Test on real, independently labeled posts before relying on the model.
- **Fire is tested on synthetic rows.** The 32 Fire test rows were written as a supplement because the original test set had no Fire examples. The Fire score (0.95) is a diagnostic, not an independent benchmark.
- **Hurricane is merged into Cyclone.** The model cannot tell the two apart by design.
- **Gujarati and Roman Gujarati text should be reviewed by a native speaker**, because the data was not written by one.
- **The deployed model is not MuRIL.** Numbers above describe MuRIL; the live IndicBERT service has not been measured on this test set here.

---

## Ideas for improvement

- Add more real or independently written examples, especially Earthquake and Cyclone tweets in Roman script.
- Add more Non-Disaster hard negatives and re-check Earthquake vs Non-Disaster errors.
- Evaluate the deployed IndicBERT model on `tweets_multilingual.csv` with the same script, so both models are compared on the same data.
- To deploy MuRIL, use a larger host, or try a smaller version of it (distillation or quantization).

---

## Image classifier

The image classifier is deployed at https://disaster-classifier-api.onrender.com. Its code is in `image/`.

<!-- Add here: image model name, dataset, classes, accuracy, and how to call the API. -->

---

## Other data tools (text)

| File | What it does |
|---|---|
| `build_multilingual_tweets.py` | Writes the 120 hand-made seed tweets and adds noise (typos, slang, hashtags, emoji, code-mixing) to make the test set. |
| `generate_tweets_llm.py` | Generates large, varied multilingual tweets with the Claude API or the Groq free tier. It filters wrong-script text and duplicates, drops text too close to the test set, and assigns train/validation splits by call group. |
| `check_hurricane_cyclone.py` / `.ipynb` | TF-IDF baseline used to decide whether to merge Hurricane and Cyclone. |
| `groq_vs_anthropic_key.xlsx` | Comparison of API providers for data generation. |
