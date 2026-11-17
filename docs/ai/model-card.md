# Model card: `/triage` scenario and priority suggestion (S3-05)

Owner: Neeti. Covers what `/triage` runs in this release. Part A is the engine in use today; part B is filled in
when a trained scenario model replaces the rules (S2-05), with numbers measured once on the untouched test set.

## Part A: `drch-triage-v1-rules` (in use)

| Item | Value |
|---|---|
| Type | Hand-written keyword and points rules, no training (`ai-workers/rules.py`) |
| Task | Suggest one of `CYCLONE`, `INDUSTRIAL_FIRE`, `URBAN_FLOODING` (else `OTHER`), a priority and a confidence for a citizen report or an ingested post |
| Output use | Advisory only. Stored in `ai_recommendations` (or on the signal), shown to a dispatcher as "AI suggestion, not verified"; never changes an incident, never dispatches |
| Rules | [triage-rules.md](triage-rules.md) |
| Inputs | Description and details with personal data removed, reported scenario and urgency, people affected, whether coordinates exist |
| Languages | English keywords only. Hindi and Gujarati text written in their own scripts matches nothing and falls to `OTHER` or the reported scenario; romanised Hindi or Gujarati matches only where an English keyword appears (for example "flood") |
| Confidence | A rule score, not a calibrated probability (triage-rules.md section 4); below 0.6 is stored as `LOW_CONFIDENCE` |
| Latency | Under a millisecond inside the service; end-to-end time is the HTTP call (Render free instances can take tens of seconds to wake) |
| Safety tests | Backend guardrails (`backend/tests/test_ai.py`, `test_ai_gate.py`), the `/triage` contract (`ai-workers/tests/test_triage.py`) and ten prompt-injection posts (`ai-workers/tests/test_prompt_injection_posts.py`), all in CI |

**Measured quality: none yet.** The rules have not been scored on a labelled set of our three scenarios, because
that set does not exist yet (S1-10). `python ai-workers/eval/baselines.py` scores them as soon as it does.

**Known limits.**

- Keyword matching: negation ("no flood here"), metaphors ("flood of messages") and sarcasm are counted as hits.
- A supported scenario chosen by the reporter is kept even when the text disagrees; only a note is added.
- Words such as "plant", "tank", "drain" and "wind" are common outside disasters, so false scenario hits occur.
- Priority rewards stated urgency and people counts; a calm report of a severe event is under-prioritised, and an
  exaggerated one over-prioritised. The dispatcher sets the real priority.
- No source reliability input (see triage-rules.md section 3).
- Out-of-scope events (earthquake, heatwave, landslide) end as `OTHER` and are triaged manually.

## Part B: trained scenario model (to fill in after S2-05)

Loaded only through `TRIAGE_MODEL_DIR` with a SHA-256-checked artifact (`ai-workers/service/scenario_model.py`).
Fill every row with numbers from the frozen dataset, measured once on the untouched test split.

| Item | Value |
|---|---|
| Model name and version | |
| Training data | rows per class and language, synthetic share (training split only), source licences |
| Test data | human-written only, split by event; rows per class and language |
| Macro-F1 (test) and against the rules | target: at least 0.75, and at least 0.10 above the rules |
| Per-class recall | target: at least 0.60 for every class |
| Per-language macro-F1 | English, Hindi, Gujarati |
| Confidence threshold | chosen on the validation split; `AI_LOW_CONFIDENCE_THRESHOLD` set to it |
| Latency and memory | on the Render free instance |
| Failure modes | from the S3-05 error analysis: most confused class pairs, language gaps, examples |
| Decision | in use, or why the rules stay (the miss written down) |

The LLM second opinion (S2-08) is not part of this card; whether it stays off is recorded in
[evaluation-report.md](evaluation-report.md) section 5 (S3-07).
