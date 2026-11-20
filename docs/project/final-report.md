# ResQ — Final Report (S3-16)

Gujarat Disaster Management Platform (ResQ / DRCH). Assembled by Zalak from the sections each member owns.
**Status: draft of 14 Nov 2026 against `main` (`ec4b2de`).** Facts below were read from the code, docs and the
deployed backend; the sign-off table at the end must be completed by each author before the release tag.
Every section says what is real and what is simulated.

## 1. What ResQ is

A coordination hub for disaster response in Gujarat. Citizens report incidents, disaster-management (DM)
dispatchers verify them and assign response teams, field teams report progress from the field, and verified
incidents appear on a public map with rounded coordinates and no personal data. Only three scenarios are
supported: `cyclone`, `industrial_fire` and `urban_flooding`. Every AI output is advisory; a human verifies,
dispatches, escalates and closes.

| Part | Real or simulated |
|---|---|
| Accounts, password + TOTP MFA, role-based access, audit hash chain, Gujarat geofence, concurrency-safe dispatch, field-team isolation | Real |
| SACHET (NDMA) alert feed | Real feed; fallback rows are labelled `is_fallback` |
| Social posts | Replayed team-written fixture (`social_replay.jsonl`), labelled as replay. Live Google News and Bluesky adapters exist and are off by default |
| Seed demo incidents | `is_simulated = TRUE`, hidden from the public map outside development |
| Payments | Sandbox mock gateway; a Razorpay test-mode adapter, webhook and receipts exist; no real money moves |
| AI triage | Rules baseline, advisory only; trained models are research artifacts, not wired in (section 8) |

## 2. Architecture and deployment (owner: Siddh)

- **Stack:** FastAPI backend, PostgreSQL 16 with PostGIS on Neon, Next.js 16 (React 19) frontend with a
  backend-for-frontend proxy and an httpOnly session cookie, a separate FastAPI AI service, Leaflet maps.
  See [ARCHITECTURE.md](../architecture/ARCHITECTURE.md).
- **Hosting:** Render (backend staging, backend production, AI triage, images from GHCR), Vercel (frontend),
  Neon (database), GitHub Actions (CI, CD, ingestion cron). Defined in `render.yaml`, `.github/workflows/`,
  [release-runbook.md](../operations/release-runbook.md) and [env-variables.md](../architecture/env-variables.md).
- **State on 14 Nov 2026:** the frontend answers on Vercel; the backend at
  `it314-software-project-backend1.onrender.com` answers `/api/v1/health` with `database: ok` and runs build
  `54007f9`, which is behind `main`. The staging backend `drch-backend-latest.onrender.com` answers the same
  way; its CD secrets are still to be set (defect D-02).
- **Photo storage:** citizen photos are stored in PostgreSQL (`evidence_blobs`) for this release, so they share the
  database's backups and access rules; Cloudinary is planned later. The image classifier is not deployed, so photo
  analysis shows its labelled "unavailable" state.
- **Delivery pipeline:** pull requests must pass the Quality Gate (secret scan, lint, SAST, dependency audit,
  unit and PostGIS-backed tests, Playwright e2e, container build with Trivy). Merges to `main` publish images,
  deploy staging, smoke-test it, then deploy production; the last CD job fails the run if an expected deployment
  was skipped. Releases are tagged `vX.Y.Z-rcN` and rolled back by image tag.

## 3. Data and schema (owner: Siddh, with Nisarg and Shlok for seeds)

Versioned SQL migrations `01` to `12` in `backend/db/migrations` (core schema, DM module, ingestion and
resource tables, spatial boundaries, citizen flow, audit chain lock, donation receipts, CAP metadata, account
invitations, signal matching, evidence blobs, payment webhook events, donation endings), applied by
`python -m app.migrate` and at startup. The audit log is append-only and SHA-256 hash-chained with trigger-enforced
immutability; verify it with `python -m app.cli verify-audit`. Reference data is seeded in every environment; demo
incidents only when `APP_ENV=development`.

**ER diagram:** [er-diagram.md](../architecture/er-diagram.md) — 32 tables and 51 foreign-key relationships, generated from the
migrations by `python scripts/generate_er_diagram.py`. Re-run it after any new migration; `--check` fails when the
diagram is out of date.

## 4. API (owners: Zalak for citizen and public, Nisarg for dispatch and field, Shlok for payments and signals)

[api_contracts.md](../architecture/api_contracts.md) lists every endpoint, its authentication and the standard error shape
`{error:{code,message,details}}`. Route groups: `auth` (staff login with MFA, citizen register and login, Google
sign-in, invitations, password reset), `citizen` and `/me/*`, `public`, `field`, `donations` and the payment
webhook, `internal` (token-guarded ingestion), and `dm/*` (incidents, dispatches, resources, recommendations,
signals, AI, analytics, ingestion health, aid, content, moderation, staff).

## 5. Citizen, public and field features (owners: Zalak, Janvi, Tanishq)

Citizen registration and login, incident reporting with an idempotency key and Gujarat check, a timeline with
readable labels, replying to an information request, optional photo evidence, withdrawal requests, account
deletion and email copies. The public map is locked to Gujarat with a district filter and an alerts layer. Field
teams see only their own team's dispatches and report acknowledgement, progress, team requests and completion.
Screens are described in [frontend-citizen-field-guide.md](../guides/frontend-citizen-field-guide.md) and
[frontend-dispatcher-public-guide.md](../guides/frontend-dispatcher-public-guide.md).

## 6. Dispatch, recommendations and signals (owners: Nisarg, Shlok)

Verification, rejection, requests for information, priority and closure with an optimistic-concurrency version;
row-locked resource reservation; automatic escalation of unacknowledged dispatches; ranked team recommendations
with reasons that never create a dispatch; team-request decisions; a signals queue with promote and dismiss; and
advisory related-signal suggestions ([signal-matching.md](../architecture/signal-matching.md)). The detailed dispatch and field API
section is Nisarg's [final-report-dispatch-field.md](final-report-dispatch-field.md).

**Duplicate grouping (S2-07):** `GET /dm/incidents/{id}/duplicates` still finds candidates with the scenario, time
and distance or address rules, and now ranks them with a 0–1 score that adds character-trigram wording similarity
(it works for Gujarati and Hindi script too) and returns a plain-language explanation (`"method": "rules+text"`).
The weights are reasoned defaults, not yet tuned on labelled pairs. It is advisory: nothing is linked or merged
automatically, and the dispatcher's link, merge or dismiss decision is unchanged.

## 7. Payments (owner: Shlok)

A payment-gateway interface with a sandbox mock and a Razorpay adapter, `POST /donations`, server-side signature
verification, a webhook that ignores repeated events and copes with arriving first, receipts and
`GET /me/donations`. A donation is confirmed only after server-side verification. Sandbox limits: the mock
gateway moves no money, and in `APP_ENV=production` the sandbox payment step is refused.

Every path now ends on the server: the donor's cancel (`POST /donations/{id}/cancel`, ABANDONED), a gateway
`payment.failed` webhook (GATEWAY_DECLINED) or 30 minutes without a verified payment (EXPIRED) all end as `FAILED`
with the reason recorded and audited. A verified payment of the right amount that arrives later still confirms the
donation, so captured money is never lost and nothing is confirmed without verification. See
[payment-gateway-findings.md](../quality/payment-gateway-findings.md).

**Load test (S3-13):** 200 public-map requests at concurrency 5 against the deployed backend gave **p95 633 ms**
(p50 475 ms, no errors) from a client in India to Render's Ohio region ([load-test.md](../quality/load-test.md)).
**Backups (S3-12):** `scripts/db_backup.py` takes a `pg_dump` backup and restores only into a `_restore` or `_test`
database unless forced ([runbook-migration.md](../operations/runbook-migration.md)).

## 8. Ingestion, signals and AI (owners: Rudra, Neeti, Dhruvil, Zalak)

**Ingestion** ([ingestion-sources.md](../operations/ingestion-sources.md)): a SACHET (Gujarat feed) adapter, a replay
source, optional Google News and Bluesky text signals (off by default), a ten-minute scheduler, a token-guarded
trigger for the GitHub cron, a Poll-now action and a health panel. Signal text is sanitised, language-detected
and stored with its source and simulated flag; nothing becomes an incident without a human promoting it.

**AI** ([ai/text-label-guideline.md](../ai/text-label-guideline.md), [ai/text-dataset-sources.md](../ai/text-dataset-sources.md)):
`/triage` runs a rules baseline with guardrails and a human decision is recorded. Measured so far:

| Model | Result | Limit |
|---|---|---|
| Image classifier (ConvNeXt-Tiny, 3,195 test images, via its API) | accuracy 0.840, macro-F1 0.816; weakest `other_disaster` 0.59, `hurricane` 0.72 | weights and service not deployed; photo analysis returns 503 |
| English text model (`resq-english-crisis-text-v1`) | relevance on an unseen event: F1 0.944 for "related", only 0.24 recall for "not related" | does not classify our three scenarios (`NOT_TRAINED`); not wired into `/triage` |
| BERTweet research run (HumAID unseen events) | macro-F1 0.695 against 0.565 for TF-IDF | research-only data licence; not deployed |

The plan targets (macro-F1 at least 0.75, per-class recall at least 0.60) are **not met**; the miss and the ten
improvement steps are written down in `docs/sprints/remaining-work.md`. The optional LLM adapter is wired into
`/triage` and off by default (`LLM_ENABLED`): when enabled it only adds an advisory `llm_second_opinion` for
low-confidence results and an `english_summary` of Hindi or Gujarati text beside the unchanged rules result;
whether it stays on is the S3-07 decision. Photo analysis is advisory, audited and never stored as verification.

## 9. Frontend (owners: Janvi, Tanishq)

Next.js App Router with a searchable language selector (including Hindi and Gujarati), keyboard and mobile polish for citizen and
field screens, dispatcher and admin consoles, the public map, About, How-to and a safety page with sources for each
guide. Browser requests go through BFF proxies that attach the session token and reject cross-site writes.

## 10. Quality assurance and security (owners: Dhruv, Siddh)

| Area | Evidence |
|---|---|
| Automated tests | 818 backend tests collected; 8 Playwright e2e specs (citizen reply, three scenarios, language selector, alerts, password reset, layout); AI-service tests; all run in CI |
| Smoke test | `scripts/smoke.py` (register, report, verify, public map) is run by CI against a local stack and by CD against staging |
| Scenario test (S3-01) | `scripts/scenario_run.py` drives the cyclone scenario from citizen report to closure over HTTP and can repeat it (`--runs 3`) against staging |
| Load test (S3-13) | [load-test.md](../quality/load-test.md) |
| Security | role matrix, public and `/me` data checks, BFF CSRF checks, blocking scans: [security-review.md](../quality/security-review.md) |
| Rehearsals and demo script | [demo-script.md](demo-script.md) (log still empty) |
| Defects | [defect-list.md](../quality/defect-list.md) |

## 11. Known limits and future work

See [future-features.md](future-features.md) and the open items in [defect-list.md](../quality/defect-list.md): no model on
our three scenarios, no hosted image service, untuned duplicate-scoring weights, and no recorded 24-hour ingestion
soak.

## Sign-off

Each author confirms their section matches the tagged release and says correctly what is real and what is
simulated. Blank means not yet signed.

| Section | Author | Signed (name, date) |
|---|---|---|
| 1, 10 (QA) | Dhruv | |
| 2, 3, 10 (security) | Siddh | Siddh Shah, 15 Nov 2026 |
| 4, 5 (citizen and public API) | Zalak | |
| 4, 6 (dispatch and field API) | Nisarg | |
| 4, 6, 7 (payments, signals) | Shlok | |
| 8 (ingestion) | Rudra | |
| 8 (AI evaluation, dataset) | Neeti | |
| 8 (image model, photo path) | Dhruvil | |
| 5, 9 (citizen and field UI) | Janvi | |
| 5, 9 (dispatcher and public UI) | Tanishq | |
