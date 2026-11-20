# Scripts

Developer and CI helper scripts. Run them from the repository root.

| Script | Purpose | Typical use |
|---|---|---|
| `smoke.py` | End-to-end smoke test of the core loop: health, citizen registers and reports an incident, a dispatcher verifies it, and it appears on the public map without personal data. Strict: any unexpected response fails the run. | `python scripts/smoke.py --base-url http://localhost:8000` (also `make smoke`); CI runs it against a local API and CD against staging |
| `seed_reset.py` | Safely clears operational data and re-applies the baseline seeds. Refuses cloud databases unless forced. | `make seed-reset` (see `docs/quality/testing.md` section 5) |
| `check_env_docs.py` | Fails when code reads an environment variable that `docs/architecture/env-variables.md` does not document. | CI backend job |
| `check_no_demo_data.sh` | Fails when demo or mock data markers appear in tracked files. | CI frontend job |
| `sync_boundaries.py` | Checks and synchronizes Gujarat administrative boundaries. | `make sync-geo` |
| `explain_queries.py` | Runs `EXPLAIN (ANALYZE, BUFFERS)` on the public-map and team-recommendation queries. | See "When to add an index" in `docs/quality/load-test.md` |
| `evaluate_team_recommendations.py` | Review sheet for tuning the team-recommendation ranking. | Run by hand |
| `scenario_run.py` | Automated cyclone scenario (S3-01) over HTTP: citizen report, verification, recommendation, dispatch, field acknowledgement, progress and completion, resolution, closure and the public map. Repeats with `--runs`. Creates real records, so use staging. | `python scripts/scenario_run.py --base-url <staging> --runs 3` |
| `load_test.py` | Light load test (S3-13): p50/p95/p99 of the public map, optionally report submits on staging. | `python scripts/load_test.py --base-url <staging> --requests 200 --concurrency 5`; results in `docs/quality/load-test.md` |
| `db_backup.py` | `pg_dump` backup and guarded `pg_restore` (S3-12). Restores only into a `_restore` or `_test` database unless `--force`. Needs the PostgreSQL 16 client tools. | `python scripts/db_backup.py backup`; see `docs/operations/runbook-migration.md` Step 1 |
| `generate_er_diagram.py` | Regenerates `docs/architecture/er-diagram.md` (Mermaid) from the migrations; `--check` fails when it is out of date. | Run after adding a migration |
| `ai-dev.py` | Orchestrator for the AI-assisted development workflow. | See `docs/guides/AI_WORKFLOW.md` |

## Smoke test configuration

`smoke.py` takes all secrets from the environment and prints none of them.

| Variable | Required | Description |
|---|---|---|
| `SMOKE_STAFF_EMAIL` | yes | A `DISASTER_MGMT` staff user (create one with `python -m app.cli create-staff`). |
| `SMOKE_STAFF_PASSWORD` | yes | That user's password. |
| `SMOKE_STAFF_TOTP_SECRET` | yes | The base32 secret printed when the user was created. |
| `SMOKE_BASE_URL` or `API_URL` | no | Backend base URL; `--base-url` overrides both. Default `http://localhost:8000`. |

Requirements: `pip install httpx pyotp`. The HTTP timeout is 90 seconds so a cold Render instance can wake.

## Scenario run configuration

`scenario_run.py` needs the staff account above plus a field-team account on the same backend whose team is
available near the scenario location (create one with `python -m app.cli create-field`).

| Variable | Required | Description |
|---|---|---|
| `SMOKE_STAFF_EMAIL`, `SMOKE_STAFF_PASSWORD`, `SMOKE_STAFF_TOTP_SECRET` | yes | Dispatcher with the `DISPATCH` and `CLOSURE` permissions. |
| `SCENARIO_FIELD_EMAIL`, `SCENARIO_FIELD_PASSWORD`, `SCENARIO_FIELD_TOTP_SECRET` | yes | The field responder; field accounts also use TOTP. |
| `SMOKE_BASE_URL` or `API_URL` | no | Backend base URL; `--base-url` overrides both. |
