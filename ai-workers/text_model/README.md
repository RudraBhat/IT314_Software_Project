# English crisis text model

This package adds an optional, separately callable text-analysis model. It does not change the existing `/triage` response or the image classifier. The 200-row team-authored draft and prompt-injection fixtures are not included in training.

## What it predicts

The model is trained on labels that exist in the source corpus:

- Disaster relevance: `RELATED`, `NOT_RELATED`, or `UNCERTAIN`.
- Candidate suggestions for help requests, direct eyewitness reports, and humanitarian information categories such as medical help, search and rescue, water, shelter, transport, infrastructure, floods, storms, fire, and earthquakes. These candidates are advisory. The pinned Appen training split contains no positive `offer` examples, so offer prediction is returned as `NOT_TRAINED`.

The `/analyze-text` response includes probabilities, validation-selected category thresholds (with a 0.50 minimum for multilabel candidate suggestions), and the strongest positive word-feature contributions. These terms are statistical indicators, not causal explanations. Relevance below its validation-selected confidence threshold is returned as `REVIEW` with a candidate label; every suggestion is advisory and must be reviewed by a human.

The corpus does **not** support the project's exact `CYCLONE`, `INDUSTRIAL_FIRE`, and `URBAN_FLOODING` distinctions, nor general urgency, mentioned location, or event-time extraction. Those fields are explicitly returned as `NOT_TRAINED`; the service does not guess them. Source timestamp and coordinates can be passed into the endpoint and are returned as caller-provided metadata, separate from text inference.

## Dataset and reuse

Training uses Robert Munro's *Disaster Response Messages* dataset, pinned to commit `1657e1c4e11acbfa56241d2b5cd627adbd989ca2` and licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The source describes English messages from 2010 Haiti and Pakistan SMS response services, Hurricane Sandy message-board posts, and news headlines. The `message` field is English text, including translations for messages originally written in other languages. Its currently published version excludes an earlier social-media subset.

For disaster relevance only, training also uses the `INDIANTWEETMASTER.csv` subset from the [Hierarchical Disaster Tweet Classification Corpus (India + Nepal)](https://data.mendeley.com/datasets/psv6b4zy9f/1), version 1, DOI `10.17632/psv6b4zy9f.1`, licensed on Mendeley Data under CC BY 4.0. Its README reports 17,000 India posts (7,200 non-disaster and 9,800 disaster), including everyday posts such as exams. This gives the relevance head real social-media hard negatives closer to the project's context. Its public README does not describe the annotation procedure or inter-annotator agreement, so these labels are supplemental rather than gold-standard operational labels. The corpus contains X posts; confirm third-party content rights and platform terms before product use. The [X Developer Agreement](https://docs.x.com/developer-terms/agreement) requires explicitly approved analysis of X content accessed through its APIs and restricts use of that content to train foundation or frontier models. This small supervised classifier is not a foundation model, and the dataset is not a substitute for approved access to a live X feed.

Attribution: Robert Munro, [disaster_response_messages](https://github.com/rmunro/disaster_response_messages), CC BY 4.0; Ujjwal Sinha, Basudev Nath, and Kaliprasanna Swain, [Hierarchical Disaster Tweet Classification Corpus (India + Nepal)](https://doi.org/10.17632/psv6b4zy9f.1), CC BY 4.0. The Appen source requires that shared copies preserve attribution and not be combined with data in ways that reveal message authors. Both downloaders pin source versions and verify SHA-256 hashes. Raw data and trained weights are kept out of Git; they can be recreated locally.

The source labels include `related`, `request`, `offer`, `direct_report`, and humanitarian categories. Its `actionable_haiti` label is specific to one event and is intentionally not used as a general priority label.

## Train and evaluate

From `ai-workers/`:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m text_model.download_data
python -m text_model.download_india_data
python -m text_model.train
```

Training uses complete-event holdouts for Appen and a separate stratified split for the India relevance corpus:

- Appen training: Haiti earthquake and news rows from the source training split.
- Appen validation: Pakistan flood rows across the published splits.
- Appen test: all Hurricane Sandy rows across the published splits; never used for fitting or threshold selection.
- India relevance: rows detected as English with at least 0.80 language-identification confidence, then stratified 70/15/15 into train, validation, and test. These rows train only the disaster-relevance head; they are not treated as negative examples for humanitarian categories.
- Exact duplicate text is retained in the highest-priority held-out split and dropped from other splits.

The India split is random because its public master file has no event or time column. Its score is a same-source holdout and is less demanding than the event-held-out Sandy score. Language detection can also reject short English text as uncertain. The relevance review threshold is selected on Pakistan validation data to target at least 90% accuracy on accepted predictions while retaining at least 50% coverage; achieved validation coverage and accuracy are recorded in the report. Multilabel thresholds are selected on the same Appen Pakistan validation event.

The train command writes `artifacts/model.joblib`, `artifacts/metadata.json`, and `reports/evaluation.json`. The model artifact is local and ignored by Git. The tracked evaluation report contains metrics and hashes, not message text. Inference checks the scikit-learn version recorded in the artifact; keep the pinned version in `ai-workers/requirements.txt` aligned when rebuilding the image.

## Event-held-out transformer experiment (research only)

An additional experiment fine-tunes [BERTweet](https://huggingface.co/vinai/bertweet-base) on QCRI's [HumAID-events](https://huggingface.co/datasets/QCRI/HumAID-events) English tweet labels. HumAID covers humanitarian information categories, not the DRCH's exact incident scenario or urgency labels. Its `not_humanitarian` class means a post is not useful humanitarian information in a disaster dataset; it is not a general-purpose filter for everyday metaphorical posts such as “my exam was a disaster.” Keep the existing relevance head separate.

The downloader retrieves only the publicly available HumAID event set 1 at pinned revision `2e7ea23332006f075068b90d401b178d847b447a` and verifies each file against the tracked checksum manifest. It deliberately does not request event set 2. Raw posts and IDs remain local and are ignored by Git. The source is licensed CC BY-NC-SA 4.0 and the QCRI terms restrict the data to humanitarian-computing research; treat derived weights as research artifacts, do not publish or deploy them without a separate rights review, and delete local copies when required by the source terms.

This experiment uses event-level separation: eight events for training, Ecuador and Hurricane Matthew for validation, and Cyclone Idai, Greece wildfires, and Sri Lanka floods for a final held-out test. Exact duplicate text is assigned to the highest-priority held-out split. The test events are not used for fitting or threshold selection. The report contains aggregate scores and hashes only, never post text or IDs. These events are old and do not validate performance on current Gujarat feeds.

To reproduce the experiment from `ai-workers/` (a Python/PyTorch build supported by your machine may be needed):

```sh
pip install -r requirements-transformer.txt
python -m text_model.download_humaid_events
python -m text_model.evaluate_humaid_tfidf
python -m text_model.train_humaid_transformer --epochs 2 --batch-size 16 --max-length 96
```

The TF-IDF reference is tuned only on validation data and writes `text_model/reports/humaid_tfidf_evaluation.json`. Model files are local under `text_model/artifacts/humaid_bertweet`; the aggregate result is `text_model/reports/humaid_transformer_evaluation.json`. Compare both scores on the same held-out events. A local-only advisory prediction function is available as `text_model.humaid_inference.predict_humaid_category`; it requires the locally trained artifact and always marks human review as required. This is an offline research experiment and is not loaded by `/analyze-text` or `/triage`.

To test one message interactively from `ai-workers/`, activate an environment with `requirements-transformer.txt` installed, then run:

```sh
python -m text_model.predict_humaid
```

The command prompts for one English message, runs the local weights, and prints the weights-file SHA-256 so the artifact can be verified. It does not send the text to a server.

Recorded 2026-11-04 UTC run: BERTweet reached test macro-F1 `0.6954` and accuracy `0.8154` over 6,008 posts, versus `0.5652` and `0.6694` for the TF-IDF reference. Event macro-F1 improved from `0.5590` to `0.6831` on Cyclone Idai, `0.5114` to `0.6326` on Greece wildfires, and `0.4639` to `0.5737` on Sri Lanka floods. The validation-selected review gate accepted `82.6%` of test posts at `87.6%` accuracy; the reference accepted `50.1%` at `85.6%`. The `not_humanitarian` class remains weak and variable (event F1 `0.383`, `0.585`, and `0.333`), so this model is not dependable as a general off-topic filter. One exam-metaphor example was sent to review; that smoke check is not a measured benchmark.

## Run the analysis endpoint

Set `TEXT_MODEL_DIR` to the directory containing `model.joblib`, then start the existing worker from `ai-workers/`:

```sh
TEXT_MODEL_DIR=./text_model/artifacts uvicorn triage_service:app --host 127.0.0.1 --port 8001
```

Send a text and, if available, source metadata to `POST /analyze-text`:

```json
{
  "description": "The underpass is flooded and several people need rescue.",
  "source": "example-feed",
  "source_created_at": "2026-11-04T12:30:00Z",
  "latitude": 23.02,
  "longitude": 72.57
}
```

The endpoint returns `503` when no trained artifact is configured. It returns `LANGUAGE_UNCERTAIN` or `UNSUPPORTED_LANGUAGE` without running classification when text is not confidently detected as English. `/triage` remains unchanged. The Docker image installs the inference dependency, but deploying the weights requires providing the artifact directory through `TEXT_MODEL_DIR`; the model file is not baked into Git or the image.

## Limits before operational use

This is a reproducible real-data baseline, not a production-validated Gujarat dispatch model. The corpora are small relative to today's social feeds and have different annotation quality; the India tweets lack a documented annotation protocol and event/time identifiers. It must not be used to dispatch resources, set priority, or verify incidents. A production candidate needs independently reviewed English examples for the actual three supported scenarios, urgency, and hard negatives such as metaphoric uses of “disaster”; it also needs evaluation on newer, region-relevant events and a human-reviewed shadow period.

## Learning from reviewer corrections

For text classification, keep reviewer corrections as verified labels and use them for supervised fine-tuning and active-learning selection of uncertain or disagreement cases. Do not treat a single coordinator action as a reward for the text classifier: dispatch actions depend on resource availability, geography, policy, and outcomes beyond the wording of one post. Reinforcement learning may be evaluated later for dispatch ordering in a simulator with explicit safety and fairness constraints, but it does not replace reliable labels or event-held-out evaluation for this model.
