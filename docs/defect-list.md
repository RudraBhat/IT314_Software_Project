# Defect list (S3-17)

Kept by Dhruv; Siddh approves which P0 items block the release tag. Last updated 14 Nov 2026 from a review of
`main` (`ec4b2de`), the deployed backend and the member packages prepared the same day. **Done when:** no P0 is
open at the release tag and every P1 is fixed or has a written decision. Report the P0 count at each rehearsal.

Severity: **P0** blocks the demo or the release; **P1** breaks a planned feature or leaves a plan deliverable
missing; **P2** is a small defect, a stale document or housekeeping.

**P0 count today: 2** (D-01 and D-02 are fixed in code and wait for a real CD run and the staging service).

## Open

| ID | Sev | Defect | Module owner | Evidence | Next step |
|---|---|---|---|---|---|
| D-01 | P0 | CD could finish green while deploying nothing: a missing hook or URL secret was only a notice and the deploy jobs showed "Skipped" | Siddh | `cd.yml` check jobs and `deploy-*` jobs | Fixed by the `deploy-summary` job (Siddh's package). **Confirm on the first real CD run** that a missing secret now fails the run |
| D-02 | P0 | `render.yaml` had no staging service although `cd.yml` deploys to a staging backend first | Siddh | `render.yaml` defined one backend | Fixed in `render.yaml` (Siddh's package). **Create `drch-backend-staging` with its own database and secrets, and set `RENDER_STAGING_DEPLOY_HOOK`, `STAGING_BACKEND_URL` and the `SMOKE_*` secrets** |
| D-03 | P1 | The deployed backend runs an older build than `main` (health reported `54007f9`, `main` is `ec4b2de`) | Siddh | `GET /api/v1/health` on 14 Nov 2026 | Merge the packages, then check that CD deploys and that `/api/v1/health` reports the new commit |
| D-07 | P1 | The image classifier service is not deployed, so photo analysis returns 503 | Dhruvil, Siddh | no service in `render.yaml`; weights not in the repo | Decide hosting and the weight location (S1-14) |
| D-08 | P1 | The text dataset is not frozen and no model is trained on our three scenarios; `/triage` uses the rules baseline | Neeti | `ai-workers/data/` holds 200 draft rows; text model reports say `NOT_TRAINED` for our scenarios | S1-10, then S2-05 and S2-06 |
| D-10 | P1 | The 24-hour ingestion soak (at least 95% of runs complete, no duplicate alerts) has no recorded result | Rudra | no soak result in `docs/` | Run it on the deployed host and record it (S3-09) |
| D-11 | P1 | Rehearsals, the staging scenario runs (3 in a row), the timed clean deploy and the release tag are not done | Dhruv, Siddh | empty log in `docs/demo-script.md`; empty sheet in `docs/release-runbook.md` | The tools now exist (`scripts/scenario_run.py --runs 3`, the timing sheet); run them after D-02 |
| D-09 | P2 | Incident duplicate scoring uses default weights not yet tuned on labelled pairs | Dhruvil, Zalak | `backend/app/services/duplicate_similarity.py` (`WEIGHTS`) | Build the labelled pairs and tune the weights (S2-07); the scoring itself is in Zalak's package |
| D-16 | P2 | `.github/CODEOWNERS` has no GitHub handle for Janvi or Tanishq, and Dhruv's handle (`D202401433`) is inferred from his fork; two remote branches are unmerged (`dhruv/feature/admin-account-security`, `dhruvil/feature/disaster-classifier`, the second on an old base) | Siddh, Dhruv, Dhruvil | `.github/CODEOWNERS` (module owners added in Siddh's package); `git branch -r --no-merged origin/main` | Confirm the handles and write access; merge or close each branch (rebase the classifier work rather than merging it) |
| D-17 | P2 | Final-report sections are not signed by their authors | Zalak, all | sign-off table in `docs/final-report.md` | Each member signs their section |
| D-18 | P2 | The load test of report submission was not run: it creates real incidents, so it waits for the staging service | Shlok | `docs/load-test.md` | Run `scripts/load_test.py --report-submits 20` on staging and add the row |

## Fixed in the 14 Nov member packages

| ID | Sev | Defect | Fix | Package |
|---|---|---|---|---|
| D-04 | P1 | Server-side cancel and expiry of a donation were not built; endings existed only in the browser | `POST /donations/{id}/cancel` (ABANDONED), webhook `payment.failed` (GATEWAY_DECLINED) and expiry after 30 minutes (EXPIRED) end as `FAILED` with the reason recorded and audited (migration 12); a verified late payment still confirms; the donate page tells the server when an order is abandoned | Shlok |
| D-05 | P1 | No load-test script and no recorded p95 | `scripts/load_test.py`; public map p95 633 ms over 200 requests at concurrency 5, no errors ([load-test.md](load-test.md)) | Shlok |
| D-06 | P1 | No backup and restore script | `scripts/db_backup.py` with a guarded restore, documented in `docs/runbook-migration.md` Step 1 and the rollback procedure | Shlok |
| D-12 | P2 | The interactive API docs answered without authentication | `/docs`, `/redoc` and `/openapi.json` are off when `APP_ENV=production`; kept in development and staging | Siddh |
| D-13 | P2 | `CitizenDashboardView.tsx` showed an "Offline Mode" label for a localStorage mode that no longer stores reports | The amber state (shown when the dashboard's data calls fail) now says "Server unreachable" in English, Hindi and Gujarati instead of implying a local-storage mode | Janvi |
| D-14 | P2 | The full backend test run hung locally when no test database was reachable | `conftest.py` clears `DATABASE_URL` when the test database is unreachable and closes the pool at session end; the suite now finishes in about 18 s | Dhruv |
| D-15 | P2 | `AGENTS.md` and `.agents/rules/*` said Next.js 14; `frontend/package.json` has 16.4.3 | Corrected to 16 (`CLAUDE.md` no longer names a version) | Siddh |

## Fixed earlier in this review

| ID | Sev | Defect | Fix |
|---|---|---|---|
| D-F1 | P1 | `demo-script.md` said the payment webhook, `/me/donations` and the LLM adapter were not built | Known-gaps table rewritten from the code |
| D-F2 | P1 | `security-review.md` said dependency and image scans were advisory, and had two open rows | Policy rewritten from `ci.yml`; rows closed with test evidence; one action left (record the CI run at the freeze) |
| D-F3 | P1 | `cd.yml` ran `smoke.py --scenario field-loop`, an option the script does not accept | Fixed: the smoke step uses `--base-url` only |
| D-F4 | P2 | `docs/ARCHITECTURE.md` named Next.js 14 | Corrected to 16 |
| D-F5 | P2 | 31 fully merged local branches, and local references to Dependabot and review branches already deleted on GitHub | Merged branches deleted with `git branch -d`; stale remote-tracking references pruned with `git fetch --prune`. Nine local branches with commits that exist nowhere else remain for the owners to decide |
| D-F6 | P2 | The About and How-to pages told citizens they could report earthquakes (the API rejects that scenario with 422), and the USGS earthquake adapter produced alerts no supported scenario can use | Wording corrected to the three supported scenarios; USGS adapter, `USGS_FEED_URL` and their tests removed; the SACHET feed is unchanged. Earthquake safety guidance on `/safety` is kept as general public advice |

## Decisions needed from Siddh (S3-17)

1. Which of D-01 and D-02 must be verified on a real CD run before the release candidate is tagged (recommended: both).
2. For each open P1 (D-03, D-07, D-08, D-10, D-11), fix before the tag or record a written decision to accept it for the course demo.
