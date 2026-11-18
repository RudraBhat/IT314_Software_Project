# Triage rules and label fields (S2-06, S2-09)

Owner: Neeti. This is the written form of the rules in `ai-workers/rules.py` (model name `drch-triage-v1-rules`) and
of what `/triage` returns, so dispatchers, reviewers and the S3-05 error analysis can check a suggestion by hand.
Everything here is **advisory**: `/triage` never changes an incident, and a dispatcher verifies, sets the priority,
dispatches and closes. If the code and this page disagree, the code is right and this page must be fixed.

## 1. What goes in

The backend sends only non-identifying fields (`backend/app/routers/dm/ai.py`): `incident_ref`, `reported_scenario`,
`description` and `details` with emails, phone numbers and 12-digit id numbers removed (`scrub_pii`),
`reported_urgency`, `people_affected` and `has_coordinates` (true or false, never the coordinates). For ingested
signals (section 6) only the post text is sent.

## 2. Scenario

Each supported scenario has a keyword list; a keyword counts once if it appears anywhere in the lower-cased text.

| Scenario | Keywords |
|---|---|
| `URBAN_FLOODING` | flood, waterlog, water level, inundat, submerged, overflow, rising water, drain |
| `INDUSTRIAL_FIRE` | fire, blaze, explosion, chemical, gas leak, smoke, factory, plant, tank |
| `CYCLONE` | cyclone, storm, wind, surge, uprooted, squall, coastal, hurricane |

1. If the reporter chose a supported scenario, it is kept. When another scenario has **at least two more** keyword
   hits, a note says the text reads more like that one.
2. Otherwise the scenario with the most hits is used if it has **at least two** hits, with a note that it was
   inferred.
3. Otherwise the answer is `OTHER`: the backend marks it out of scope and staff triage it manually.

When a trained scenario model is configured (`TRIAGE_MODEL_DIR`, see section 5), the model decides the scenario
instead and these keyword rules only feed priority.

## 3. Priority

Points are added up; the total gives the priority.

| Signal | Points |
|---|---|
| Reported urgency | CRITICAL 3, HIGH 2, MEDIUM 1, LOW 0 (none if not given) |
| People affected | +1 at 10 or more, +1 more at 50 or more |
| Distress words: trapped, stranded, rooftop, unconscious, drowning, collapsed, missing, injured, burn | +1 per word found, at most +2 |

| Total points | Priority |
|---|---|
| 4 or more | `CRITICAL` |
| 2 or 3 | `HIGH` |
| 1 | `MEDIUM` |
| 0 | `LOW` |

Example: urgency HIGH (2) + 20 people (1) + "trapped" and "rooftop" (2) = 5 points, `CRITICAL`.

The plan also lists **source reliability** as a priority input. It is not used: an incident is always a citizen
report, and ingested signals are only labelled, never prioritised for dispatch. Add it here and in `rules.py`
together if that changes.

## 4. Confidence

`0.5` + `0.1` per matched keyword of the chosen scenario (at most 3) + `0.1` if people affected is given + `0.05` if
an urgency is given, minus `0.2` when any note was added (disagreement or inference). `OTHER` is capped at `0.4`.
The result is kept between `0.05` and `0.95`.

This is a rule score, **not a calibrated probability**. The backend stores a result below
`AI_LOW_CONFIDENCE_THRESHOLD` (default `0.6`) as `LOW_CONFIDENCE`; the AI-versus-human analytics groups confidence
into HIGH (0.80 or more), MEDIUM (0.60 to 0.79) and LOW (below 0.60) (S3-06).

## 5. Factors and model output

`factors` explain the answer; each has a `name`, a `detail` and a `weight` between 0 and 1:

| Factor | When | Weight |
|---|---|---|
| `scenario_keywords` | keywords of the chosen scenario were found (rules only) | 0.15 per keyword, at most 0.45 |
| `text_model` | a trained scenario model answered; detail is the dataset label and probability | the probability |
| `reported_urgency` | an urgency was given | 0.1 per urgency point |
| `people_affected` | 10 or more people | 0.4 |
| `stranded_trapped` | a distress word was found | 0.5 |

With a trained model (`ai-workers/service/scenario_model.py`), `model` is the model's name, `scenario` and
`confidence` are the model's, the dataset labels map as cyclone → `CYCLONE`, flood → `URBAN_FLOODING`,
fire → `INDUSTRIAL_FIRE`, and earthquake, other_disaster and not_disaster → `OTHER`. Priority still follows
section 3. A note is added when the model disagrees with a supported reported scenario.

## 6. Pre-labels on ingested signals (S2-09)

Ingestion (`backend/app/services/ingestion.py`) calls `/triage` once per new or changed text signal and stores:

| Column on `source_signals` | Meaning |
|---|---|
| `ai_label` | the `/triage` scenario: `CYCLONE`, `INDUSTRIAL_FIRE`, `URBAN_FLOODING` or `OTHER`; anything else is discarded |
| `ai_confidence` | the `/triage` confidence (section 4), 0 to 1 |
| `ai_details` | `model`, `priority`, `uncertainty` and up to 20 `factors` (`name`, `detail`, `weight`) |
| `ai_triage_attempted_at` | when the call was made; set even when it failed, so a failing service is not called again for the same text |

A signal has no reporter, urgency or people count, so its priority comes only from distress words (`LOW`, or
`MEDIUM`/`HIGH` with one or two of them) and its confidence is lower than an incident's: read the label as "which
queue to look at first", nothing more. Promoting a
signal to an incident is a human decision (S2-10).

## 7. Guardrails that always apply

The backend validates every answer (`apply_guardrails` in `backend/app/services/ai_provider.py`): an invalid shape or
unknown priority becomes `UNSAFE_OUTPUT` with no suggestion; an unsupported scenario becomes out of scope; the
result is stored in `ai_recommendations`, never on the incident. The ten prompt-injection posts in
`ai-workers/data/prompt_injection_posts.jsonl` are run against `/triage` in CI
(`ai-workers/tests/test_prompt_injection_posts.py`) and must stay inside the allowed labels.
