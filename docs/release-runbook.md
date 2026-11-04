# Release Runbook (S3-12 deployment, S3-15 rehearsal, S3-18 release)

Owner: Siddh. Secret values are entered by the owner in the hosting consoles only; this file lists names, never values (see [env-variables.md](env-variables.md)).

## 1. Production-like deployment (S3-12)

| Layer | Where | Config source |
|---|---|---|
| Database | Neon PostgreSQL 16 + PostGIS | `DATABASE_URL` (S) on Render |
| Backend + AI triage | Render (image from GHCR) | `render.yaml`; every `sync: false` key is entered in the Render console |
| Frontend | Vercel | `NEXT_PUBLIC_API_URL`, `API_URL` pointing at the Render backend |
| Fallback | `docker-compose.prod.yml` on any Docker host | `.env` file with the required keys (compose refuses to start when one is missing) |

Order: (1) create the Neon branch `backup-pre-<tag>` (see [runbook-migration.md](runbook-migration.md) Step 1); (2) apply migrations with `python -m app.migrate` against the production-like database; (3) set Render variables, deploy the backend, wait for `/api/v1/health`; (4) set Vercel variables and deploy the frontend; (5) create staff accounts with `python -m app.cli create-staff`; (6) run `scripts/smoke.py` against the backend.

Cold start: Render free instances sleep. `.github/workflows/ingest-cron.yml` calls `/api/v1/health` every 10 minutes and retries up to 9 times before ingesting, which keeps the backend warm. Before a demo, open `/api/v1/health` once manually.

Done when a person who did not write these steps can deploy a fresh environment in 30 minutes or less (Dhruv's timed clean-deploy run).

## 2. Rollback tags

Every release candidate is tagged `vMAJOR.MINOR.PATCH-rcN` and the final release `vMAJOR.MINOR.PATCH`. The `cd.yml` workflow publishes images tagged `latest` and `sha-<short>`.

Rollback:
1. Backend: in Render set the image URL to the previous `sha-<short>` tag (or the previous release tag) and redeploy. Frontend: promote the previous Vercel deployment.
2. Database: migrations are forward-only. Restore the Neon branch `backup-pre-<tag>` taken in step 1 if a migration must be undone, then redeploy the matching image.
3. Re-run `scripts/smoke.py` and confirm `/api/v1/health` reports the expected `GIT_SHA`.

## 3. Rehearsals (S3-15)

Assign roles (citizen, dispatcher, field team, presenter, operator) and run twice. Each run:

- [ ] Staging is warm and `/api/v1/health` is green
- [ ] Citizen reports an incident (cyclone, industrial fire or urban flooding scenario)
- [ ] Dispatcher verifies it, reviews the advisory recommendation, confirms assignment
- [ ] Field team acknowledges and updates status; dispatcher closes
- [ ] Verified incident appears on the public map with rounded coordinates and no personal data
- [ ] Sandbox donation completes and the page labels it as sandbox
- [ ] Audit chain check passes: `python -m app.cli verify-audit`

Record the problems found in the defect list that Dhruv triages (S3-17).

## 4. Freeze, tag and release (S3-18)

1. Merge freeze announced; only P0 fixes (as approved in S3-17) merge afterwards.
2. CI green on `main`; review the advisory scans (pip-audit, npm audit, Trivy) and update the findings log in [security-review.md](security-review.md).
3. Create the release tag (maintainer action, not automated): `git tag -a vX.Y.Z-rc1 -m "Release candidate 1"` then push the tag.
4. Build from the tag, deploy using section 1, run `scripts/smoke.py`, confirm `GIT_SHA` matches the tag.
5. If smoke fails, roll back per section 2 and log the cause.
