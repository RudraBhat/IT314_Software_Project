# Release Runbook

Owner: Siddh. Secret values are entered by the owner in the hosting consoles only; this file lists names, never values (see [env-variables.md](env-variables.md)).

## 1. Production-like deployment

| Layer | Where | Config source |
|---|---|---|
| Database | Neon PostgreSQL 16 + PostGIS | `DATABASE_URL` (S) on Render |
| Backend | Render web service `drch-backend` (image from GHCR) | `render.yaml`; every `sync: false` key is entered in the Render console |
| AI triage (advisory) | Render web service `drch-ai-triage` (`drch_ai_workers` image, port 8001) | `render.yaml`; set the same `AI_TRIAGE_TOKEN` on both services and `AI_TRIAGE_URL=https://<drch-ai-triage>.onrender.com/triage` on the backend. Optional: the backend answers `UNAVAILABLE` without it |
| Frontend | Vercel | `NEXT_PUBLIC_API_URL` pointing at the Render backend |
| Fallback | `docker-compose.prod.yml` on any Docker host | `.env` file with the required keys and `IMAGE_TAG` set to a release (`vX.Y.Z`) or commit (`sha-<short>`) tag; compose refuses to start when one is missing. App ports bind to localhost, so run a TLS reverse proxy in front |

GitHub Actions secrets used by the workflows are listed in [env-variables.md](env-variables.md#github-actions-secrets-cicd).

Order: (1) create the Neon branch `backup-pre-<tag>` (see [runbook-migration.md](runbook-migration.md) Step 1); (2) apply migrations with `python -m app.migrate` against the production-like database; (3) set Render variables, deploy the backend, wait for `/api/v1/health`; (4) set Vercel variables and deploy the frontend; (5) create staff accounts with `python -m app.cli create-staff`; (6) run `scripts/smoke.py` against the backend.

Cold start: Render free instances sleep. `.github/workflows/ingest-cron.yml` calls `/api/v1/health` every 10 minutes and retries up to 9 times before ingesting, which keeps the backend warm. Before a demo, open `/api/v1/health` once manually.

Done when a person who did not write these steps can deploy a fresh environment in 30 minutes or less (Dhruv's timed clean-deploy run).

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
2. CI green on the release pull requests (the `main` ruleset requires the Quality Gate check) and the release tag points at a commit on `main` (CD refuses other tags); pip-audit, npm audit and Trivy now fail CI on high or critical findings, so review any ignored or accepted findings and update the findings log in [security-review.md](security-review.md).
3. Create the release tag (maintainer action, not automated): `git tag -a vX.Y.Z-rc1 -m "Release candidate 1"` then `git push origin vX.Y.Z-rc1`.
4. The tag push makes `cd.yml` build all three images from the tagged commit and publish them as `vX.Y.Z-rc1`. When the run is green, deploy that build: in Render set `drch-backend` to `…/drch_backend:vX.Y.Z-rc1` and `drch-ai-triage` to `…/drch_ai_workers:vX.Y.Z-rc1` and redeploy; deploy the tagged commit on Vercel. Then run `scripts/smoke.py` and confirm `/api/v1/health` reports the tagged commit's `GIT_SHA`.
5. If smoke fails, roll back per section 2 and log the cause.
