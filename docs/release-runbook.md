# Release Runbook

Owner: Siddh. Secret values are entered by the owner in the hosting consoles only; this file lists names, never values (see [env-variables.md](env-variables.md)).

## 1. Production-like deployment

| Layer | Where | Config source |
|---|---|---|
| Database | Neon PostgreSQL 16 + PostGIS | `DATABASE_URL` (S) on Render |
| Backend (staging) | Render web service `drch-backend-latest`, `https://drch-backend-latest.onrender.com` (image from GHCR); deployed first on every merge to `main` and smoke-tested | `render.yaml`; its own database, `JWT_SECRET` and `MFA_ENCRYPTION_KEY`; GitHub secrets `RENDER_STAGING_DEPLOY_HOOK`, `STAGING_BACKEND_URL` and the `SMOKE_*` account |
| Backend (production) | Render web service `it314-software-project-backend1`, `https://it314-software-project-backend1.onrender.com` (image from GHCR); deployed only after the staging smoke test passed | `render.yaml`; every `sync: false` key is entered in the Render console; GitHub secrets `RENDER_DEPLOY_HOOK`, `PROD_BACKEND_URL` |
| AI triage (advisory) | Render web service `drch-ai-triage` (`drch_ai_workers` image, port 8001) | `render.yaml`; set the same `AI_TRIAGE_TOKEN` on both services and `AI_TRIAGE_URL=https://<drch-ai-triage>.onrender.com/triage` on the backend. Optional: the backend answers `UNAVAILABLE` without it |
| Frontend | Vercel | `NEXT_PUBLIC_API_URL` pointing at the Render backend |
| Fallback | `docker-compose.prod.yml` on any Docker host | `.env` file with the required keys and `IMAGE_TAG` set to a release (`vX.Y.Z`) or commit (`sha-<short>`) tag; compose refuses to start when one is missing. App ports bind to localhost, so run a TLS reverse proxy in front |

GitHub Actions secrets used by the workflows are listed in [env-variables.md](env-variables.md#github-actions-secrets-cicd).

Citizen photos are stored in the database (`evidence_blobs`), so there is no storage service to deploy; Cloudinary is
planned later ([ARCHITECTURE.md](ARCHITECTURE.md) section 8, "Photo storage"). The image classifier is not deployed
for this release: leave `AI_IMAGE_SERVICE_URL` unset and photo analysis answers `503 AI_PHOTO_UNAVAILABLE`.

### Staging service and secrets (D-02)

State on 14 Nov 2026: both `https://drch-backend-latest.onrender.com/api/v1/health` (staging) and
`https://it314-software-project-backend1.onrender.com/api/v1/health` (production) answer `healthy`, `database: ok`,
build `54007f9`. What is left is configuration in the consoles (values never go in the repository):

1. **Render, `drch-backend-latest`:** check that `APP_ENV=staging` and that `DATABASE_URL` points at a **different**
   database from production (a separate Neon branch, for example `staging`), with its own `JWT_SECRET` and
   `MFA_ENCRYPTION_KEY`. If it shares production's database, create the Neon branch, run `python -m app.migrate` and
   `python -m app.seed` against it, and switch `DATABASE_URL` before the first CD run, because the smoke test and
   `scripts/scenario_run.py` create real incidents. Set `MOCK_GATEWAY_SECRET` for the sandbox donation flow. Copy the
   service's deploy hook (Settings, Deploy Hook).
2. **Accounts on the staging database** (run from `backend/` with `DATABASE_URL` set to the staging database; the
   password is read from the prompt or `DRCH_STAFF_PASSWORD`, and the TOTP secret is printed once):
   `python -m app.cli create-staff --email smoke-staff@<your domain> --name "Smoke Staff" --permissions DISPATCH,CLOSURE,PUBLISHER,MODERATOR`
   for the smoke test, and
   `python -m app.cli create-field --email scenario-field@<your domain> --name "Scenario Field" --team "<an AVAILABLE team name>" --leader`
   for `scripts/scenario_run.py`.
3. **GitHub, environment `staging`** (Settings, Environments). With the GitHub CLI each command prompts for the value,
   so it is never typed on the command line: `gh secret set STAGING_BACKEND_URL --env staging` (value
   `https://drch-backend-latest.onrender.com`), `gh secret set RENDER_STAGING_DEPLOY_HOOK --env staging`,
   `gh secret set SMOKE_STAFF_EMAIL --env staging`, `gh secret set SMOKE_STAFF_PASSWORD --env staging`,
   `gh secret set SMOKE_STAFF_TOTP_SECRET --env staging`.
4. **GitHub, environment `production`:** `PROD_BACKEND_URL` is `https://it314-software-project-backend1.onrender.com`
   and `RENDER_DEPLOY_HOOK` is that service's hook (the scheduled `ingest-cron.yml` also reads `PROD_BACKEND_URL`).
5. Run CD once (`gh workflow run cd.yml --ref main`, or merge a pull request) and check that the **Deployment Summary**
   shows staging, smoke and production as deployed. Then D-01 and D-02 can be closed in `docs/defect-list.md`.

Reading a CD run: the last job, **Deployment Summary**, compares what the change needed (frontend, backend, AI triage) with what was actually deployed and fails the run if an expected deployment was skipped or failed. A missing hook or URL secret therefore shows as a red run with the component named in the summary table, not as a green run that deployed nothing. Skipping a component on purpose is declared in the repository variable `CD_SKIP_ALLOWED` (see [env-variables.md](env-variables.md#github-actions-secrets-cicd)).

Order: (1) create the Neon branch `backup-pre-<tag>` (see [runbook-migration.md](runbook-migration.md) Step 1); (2) apply migrations with `python -m app.migrate` against the production-like database; (3) set Render variables, deploy the backend, wait for `/api/v1/health`; (4) set Vercel variables and deploy the frontend; (5) create staff accounts with `python -m app.cli create-staff`; (6) run `scripts/smoke.py` against the backend.

Cold start: Render free instances sleep. `.github/workflows/ingest-cron.yml` calls `/api/v1/health` every 10 minutes and retries up to 9 times before ingesting, which keeps the backend warm. Before a demo, open `/api/v1/health` once manually.

Done when a person who did not write these steps can deploy a fresh environment in 30 minutes or less (Dhruv's timed clean-deploy run).

### Clean-deploy timing sheet (S3-12, filled in by Dhruv)

Use a clean machine and dummy values. Write down every step that did not work as documented, and the fix, in the last column.

| Step (from the order above) | Start | End | Minutes | Problem and fix |
|---|---|---|---|---|
| 1. Neon branch and database | | | | |
| 2. Migrations | | | | |
| 3. Render variables, backend deployed, `/api/v1/health` green | | | | |
| 4. Vercel variables, frontend deployed | | | | |
| 5. Staff account created | | | | |
| 6. `scripts/smoke.py` passes | | | | |
| **Total** (target: 30 minutes or less) | | | | |

## 2. Rollback tags

Every release candidate is tagged `vMAJOR.MINOR.PATCH-rcN` and the final release `vMAJOR.MINOR.PATCH`.

| Event | Images published by `cd.yml` | Deploys? |
|---|---|---|
| Push to `main` | `latest` and `sha-<short>` for each changed component (code reaches `main` only through a pull request whose Quality Gate passed) | Yes: staging first (deploy, wait for the commit, smoke test); production Render deploys only if smoke passed; Vercel and AI triage by their hooks |
| Push of a tag `vX.Y.Z` or `vX.Y.Z-rcN` | `vX.Y.Z[-rcN]` and `sha-<short>` for **all three** images (backend, frontend, AI workers); `latest` is not moved | No: the release is deployed on purpose (section 4) |

So every release and every merge has an image that can be redeployed by name.

Rollback:
1. Backend and AI triage: in Render set each service's image URL to the previous release tag (`…/drch_backend:vX.Y.Z`, `…/drch_ai_workers:vX.Y.Z`) or `sha-<short>` and redeploy. Frontend: promote the previous Vercel deployment.
2. Database: migrations are forward-only. Restore the Neon branch `backup-pre-<tag>` taken in step 1 if a migration must be undone, then redeploy the matching image.
3. Re-run `scripts/smoke.py` and confirm `/api/v1/health` reports the expected `GIT_SHA`.

### Rollback drill (S3-12)

Run it once on **staging** before the freeze, never on production. Part A needs no database and was done on
14 Nov 2026; part B needs the staging service, a Neon branch and the PostgreSQL 16 client tools.

**Part A: guards and procedure (done 14 Nov 2026, local, no database).**

| Check | Command | Result |
|---|---|---|
| Restore over a live database is refused | `python scripts/db_backup.py restore --file <dump> --target-url postgresql://.../neondb` | refused, exit 1: the name must end in `_restore` or `_test`, or `--force` for a declared rollback |
| Missing backup file is refused | `restore --file missing.dump --target-url postgresql://.../neondb_restore` | refused, exit 1: "backup file not found" |
| Missing client tools are reported | `restore` into `drch_restore` on a machine without `pg_restore` | stops with "pg_restore was not found. Install the PostgreSQL 16 client tools" |
| Backup without a database URL is refused | `DATABASE_URL= python scripts/db_backup.py backup` | argument error "set DATABASE_URL or pass --database-url" |
| Unit tests of the guards | `python -m pytest backend/tests/test_ops_scripts.py` | 14 passed |
| Image rollback target exists | `/api/v1/health` on both backends | both report build `54007f9`, so `.../drch_backend:sha-54007f9` is the known-good image to roll back to until a release tag exists |

**Part B: live drill on staging (to do; fill in the times).**

| Step | Command or action | Start | End | Result |
|---|---|---|---|---|
| 1. Note the current build | `curl https://drch-backend-latest.onrender.com/api/v1/health` (write down `version`) | | | |
| 2. Backup point | Neon branch `drill-<date>` from the staging branch, and `python scripts/db_backup.py backup --database-url "$STAGING_DATABASE_URL" --out backups/drill.dump` | | | |
| 3. Restore test | restore `backups/drill.dump` into a new `drch_restore` database, then `python -m app.cli verify-audit` against it | | | |
| 4. Image rollback | in Render set `drch-backend-latest` to `.../drch_backend:sha-54007f9` (or the previous `sha-` or `v` tag) and redeploy; health reports that commit | | | |
| 5. Smoke on the old build | `SMOKE_BASE_URL=https://drch-backend-latest.onrender.com python scripts/smoke.py` | | | |
| 6. Roll forward | set the image back to `latest` (or the release tag) and redeploy; health reports the newest commit; smoke again | | | |
| 7. Clean up | delete `drch_restore`, the drill branch and `backups/drill.dump` (it contains personal data) | | | |
| **Total** (target: back on the known-good build in 15 minutes or less) | | | | |

## 3. Rehearsals

Roles, the step-by-step script, on-stage fallbacks and the rehearsal log are in [demo-script.md](demo-script.md) (sections 1, 3, 4 and 7). Run it twice. Each run:

- [ ] Staging is warm and `/api/v1/health` is green
- [ ] Citizen reports an incident (cyclone, industrial fire or urban flooding scenario)
- [ ] Dispatcher verifies it, reviews the advisory recommendation, confirms assignment
- [ ] Field team acknowledges and updates status; dispatcher closes
- [ ] Verified incident appears on the public map with rounded coordinates and no personal data
- [ ] Sandbox donation completes and the page labels it as sandbox
- [ ] Audit chain check passes: `python -m app.cli verify-audit`

Record the problems found in the defect list that Dhruv triages (S3-17).

## 4. Freeze, tag and release

1. Merge freeze announced; only P0 fixes (as approved in S3-17) merge afterwards.
2. CI green on the release pull requests (the `main` ruleset requires the Quality Gate check) and the release tag points at a commit on `main` (CD refuses other tags); pip-audit, npm audit and Trivy now fail CI on high or critical findings, so review any ignored or accepted findings, update the findings log and fill in the "Freeze evidence" table in [security-review.md](security-review.md).
3. Create the release tag (maintainer action, not automated): `git tag -a vX.Y.Z-rc1 -m "Release candidate 1"` then `git push origin vX.Y.Z-rc1`.
4. The tag push makes `cd.yml` build all three images from the tagged commit and publish them as `vX.Y.Z-rc1`. When the run is green, deploy that build: in Render set `it314-software-project-backend1` (and staging `drch-backend-latest`) to `…/drch_backend:vX.Y.Z-rc1` and `drch-ai-triage` to `…/drch_ai_workers:vX.Y.Z-rc1` and redeploy; deploy the tagged commit on Vercel. Then run `scripts/smoke.py` and confirm `/api/v1/health` reports the tagged commit's `GIT_SHA`.
5. If smoke fails, roll back per section 2 and log the cause.
