# AI evaluation report (S3-16 section, S3-05, S3-07)

Owner: Neeti. State on 15 Nov 2026. Every number below comes from a report file in the repository, named in the
table; nothing was measured on our own labelled data yet, because the S1-10 dataset is not frozen.

## 1. What runs in the release

| Part | Engine | Status |
|---|---|---|
| `/triage` (incidents and signal pre-labels) | `drch-triage-v1-rules` ([triage-rules.md](triage-rules.md), [model-card.md](model-card.md)) | In use; advisory; not yet scored on our data |
| Trained scenario model for `/triage` | loads through `TRIAGE_MODEL_DIR` when an artifact exists | Wiring built and tested with a stand-in model; no artifact trained (S2-05) |
| LLM second opinion and English summary | `ai-workers/service/llm.py` | Built, **off** (`LLM_ENABLED`); decision pending (section 5) |
| English relevance model, `POST /analyze-text` | `resq-english-crisis-text-v1` | Experimental, separate endpoint, not used by `/triage` |
| Photo analysis | ConvNeXt-Tiny image classifier | Not deployed in this release; the dispatcher sees the labelled "unavailable" state |

## 2. Guardrails (run in CI on every pull request; the Quality Gate must pass to merge)

| Check | Test | Last result |
|---|---|---|
| Malformed output and an unknown priority become `UNSAFE_OUTPUT` with no suggestion; an unsupported scenario is flagged out of scope | `backend/tests/test_ai.py::test_out_of_scope_and_malformed_outputs` | CI (DB-backed) |
| Confidence below the threshold is stored as `LOW_CONFIDENCE` | `backend/tests/test_ai_gate.py` | CI (DB-backed) |
| AI output never changes an incident; the human decision is recorded separately and once | `test_ai.py::test_generated_recommendation_never_changes_the_incident`, `test_human_decision_is_recorded_separately_and_only_once` | CI (DB-backed) |
| Email, phone and 12-digit ids are removed before text leaves the backend | `test_ai.py::test_scrub_pii_removes_contact_details_before_ai_calls` | CI |
| Ten prompt-injection posts stay inside the allowed labels and add no action fields | `ai-workers/tests/test_prompt_injection_posts.py` | passed locally, 15 Nov |
| LLM output limited to allowed labels, invalid answers dropped, no reporter identity in prompts | `ai-workers/tests/test_llm.py`, `test_triage_llm.py` | passed locally, 15 Nov |
| A trained model loads only with a matching SHA-256 and the same scikit-learn version, and must cover the three scenarios | `ai-workers/tests/test_triage_model.py` | passed locally, 15 Nov |

"Passed locally" is the full `ai-workers/tests` suite (57 tests). The DB-backed backend tests need PostGIS and are
read from the CI job **Backend / Migrations, Triggers & Test Suite**.

## 3. Existing model experiments (not on our labels)

| Model | Data and split | Result | Source |
|---|---|---|---|
| `resq-english-crisis-text-v1` (TF-IDF + logistic regression) | Appen disaster messages, event-held-out (train Haiti and news, validate Pakistan, test Sandy) | relevance accuracy 0.897; "not related" recall only 0.24; scenario, urgency and location heads `NOT_TRAINED` | `docs/ai/reports/text_model/evaluation.json` |
| TF-IDF reference on HumAID | HumAID events, event-held-out | macro-F1 0.565, accuracy 0.669 | `docs/ai/reports/text_model/humaid_tfidf_evaluation.json` |
| BERTweet on HumAID (research only) | same split | macro-F1 0.695, accuracy 0.815 | `docs/ai/reports/text_model/humaid_transformer_evaluation.json` |
| ConvNeXt-Tiny image classifier | 3,195 test images, 7 classes | accuracy 0.839, macro-F1 0.815; weakest `other_disaster` and `hurricane` | `docs/ai/image-classifier-model-check.md` |

None of these predicts our three scenarios, none was scored on Gujarat text, and HumAID is licensed for
non-commercial research (CC BY-NC-SA), so weights derived from it are not deployed without a rights review. They
are therefore **not** used by `/triage`.

## 4. Error analysis and threshold (S3-05): pending S1-10

To do once the dataset is frozen, in this order: run `python ai-workers/eval/baselines.py` (rules and TF-IDF v0) on
the validation split; train the S2-05 candidates; choose the threshold on validation; score once on the untouched
test split; break errors down by class and by language (English, Hindi, Gujarati); list the most confused pairs with
examples; fill part B of [model-card.md](model-card.md). Rehearsal decisions (accept or reject in the AI panel,
`GET /api/v1/dm/analytics`) are reported beside it as a sanity check, not as test data.

## 5. LLM versus model decision (S3-07): pending S2-05

Rule from the plan: the LLM is enabled only if, on the low-confidence subset (results below
`AI_LOW_CONFIDENCE_THRESHOLD`), it improves macro-F1 by **at least 5 points** within the provider's free quota, using
only public or synthetic text. **Current decision: the LLM stays off** (`LLM_ENABLED` unset), because there is no
labelled subset to measure it on. Record here: subset size, model macro-F1, LLM macro-F1, difference, quota used,
decision and date.

## 6. Limits to state in the demo

The suggestion is advisory and labelled "AI suggestion, not verified"; the rules read English keywords only; the
confidence is a rule score; out-of-scope events go to manual triage; the AI cannot verify, dispatch, escalate or
close anything.
