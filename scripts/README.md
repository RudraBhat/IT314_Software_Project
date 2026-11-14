# Scripts

Developer and CI helper scripts. Run them from the repository root.

| Script | Purpose | Typical use |
|---|---|---|
| `smoke.py` | End-to-end smoke test of the core loop: health, citizen registers and reports an incident, a dispatcher verifies it, and it appears on the public map without personal data. Strict: any unexpected response fails the run. | `python scripts/smoke.py --base-url http://localhost:8000` (also `make smoke`); CI runs it against a local API and CD against staging |
| `seed_reset.py` | Safely clears operational data and re-applies the baseline seeds. Refuses cloud databases unless forced. | `make seed-reset` (see `docs/testing.md` section 5) |
| `check_env_docs.py` | Fails when code reads an environment variable that `docs/env-variables.md` does not document. | CI backend job |
| `check_no_demo_data.sh` | Fails when demo or mock data markers appear in tracked files. | CI frontend job |
| `sync_boundaries.py` | Checks and synchronizes Gujarat administrative boundaries. | `make sync-geo` |
| `explain_queries.py` | Runs `EXPLAIN (ANALYZE, BUFFERS)` on the public-map and team-recommendation queries. | See `docs/sprint-3-dispatch-field-report.md` |
| `evaluate_team_recommendations.py` | Review sheet for tuning the team-recommendation ranking. | Run by hand |
| `ai-dev.py` | Orchestrator for the AI-assisted development workflow. | See `docs/AI_WORKFLOW.md` |

## Smoke test configuration

`smoke.py` takes all secrets from the environment and prints none of them.

| Variable | Required | Description |
|---|---|---|
| `SMOKE_STAFF_EMAIL` | yes | A `DISASTER_MGMT` staff user (create one with `python -m app.cli create-staff`). |
| `SMOKE_STAFF_PASSWORD` | yes | That user's password. |
| `SMOKE_STAFF_TOTP_SECRET` | yes | The base32 secret printed when the user was created. |
| `SMOKE_BASE_URL` or `API_URL` | no | Backend base URL; `--base-url` overrides both. Default `http://localhost:8000`. |

Requirements: `pip install httpx pyotp`. The HTTP timeout is 90 seconds so a cold Render instance can wake.
