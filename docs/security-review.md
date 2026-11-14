# Security, RBAC and Privacy Review

Owner: Siddh. Last reviewed 14 Nov 2026 against `main`. Where a result comes from CI it is read from the
named job; this review was written without a local PostGIS database, so DB-backed tests were not re-run here.

## Checklist

| Item | Status | Evidence |
|---|---|---|
| Role matrix (public, citizen, field, dispatcher, admin) against every route group | Done | `backend/tests/test_rbac_matrix.py` is generated from the live route table, so a new route without a guard fails it. Admin (`APP_MGMT`) rows: `test_admin_has_no_operational_access` (403 on every `/dm`, `/field`, `/me`, `/incidents` route) and `test_only_admin_or_supervisor_passes_the_invitation_guard`. The DB-backed matrix runs in the CI job **Backend / Migrations, Triggers & Test Suite** |
| `/public/*` contains no personal data, coordinates rounded to 4 decimals | Done | `test_public_api.py::test_no_pii_and_coordinates_rounded`, `test_security_review.py::test_public_routes_expose_no_personal_data` |
| `/me/*` contains no reporter identity or dispatcher-internal fields | Done | `test_security_review.py::test_me_routes_expose_no_personal_or_internal_data` |
| BFF proxies (`citizen`, `dm`, `field`, `session`) reject cross-site writes | Done | each handler checks `Origin` against the request host and returns 403 `CSRF_REJECTED`; `test_every_bff_proxy_rejects_cross_site_writes` fails if a new proxy lacks the check |
| SQLite stand-in and `X-User-Id` header trust removed | Done | `test_sqlite_stand_in_is_gone`, `test_no_route_trusts_an_identity_header`, `test_legacy_citizen_routes_are_not_mounted` |
| Secret scan, SAST, dependency audit, image scan in CI | Done: every scan blocks a merge | see the merge policy below; `.github/workflows/ci.yml`, `.github/workflows/codeql.yml` |
| Payment tamper and replay | Covered by tests; record the CI run at the freeze | `backend/tests/test_donations.py`: `test_tampered_signature_is_rejected_and_donation_stays_pending`, `test_replay_verified_payment_changes_nothing`, `test_callback_signature_is_bound_to_the_amount`, `test_payments_webhook_tampered_signature_is_rejected`, `test_payments_webhook_replay_is_idempotent`, `test_payments_webhook_wrong_amount_or_currency_does_not_confirm`. They run in the same CI job as the role matrix |
| Matrix results and expected status codes per route group | Covered by tests; record the CI run at the freeze | the expected codes are encoded in `test_rbac_matrix.py` and reviewed with the route owners' guards, so no separate hand-over script is needed |

**One action is left for S3-18 (Siddh):** the pre-freeze evidence is recorded below; at the release freeze, fill
in the "Release commit" column from the CI run of the tagged commit. Until then the two "covered by tests" rows have
test evidence but no CI result for the release commit.

## CI scan merge policy

All of these run on every pull request. The **Pipeline Status / Quality Gate** check lists the jobs that contain
them, and the `main` ruleset requires that check.

| Scan | Job | Blocks a merge? | Setting |
|---|---|---|---|
| Gitleaks secret scan | `security-secrets-scan` | Yes | the gate requires it to succeed |
| Ruff, ESLint, TypeScript build | `python-check`, `frontend-check` | Yes | deterministic |
| Bandit | `python-check` | Yes | `-ll -ii` (medium and above, both severity and confidence) |
| `pip-audit` | `python-check` | Yes | `backend` and `ai-workers` requirements; no `|| true` |
| `npm audit` | `frontend-check` | Yes | `--audit-level=high` |
| Trivy image scan | `container-validation` | Yes | `CRITICAL,HIGH`, `exit-code: 1`, `ignore-unfixed: true` (findings that have no fix yet do not block) |
| CodeQL (python, javascript-typescript) | `codeql.yml` | Reports to GitHub code scanning on pull requests, pushes to `main` and weekly; it is a separate workflow, not part of the gate job | review its alerts at the freeze |
| Vercel preview | `vercel-preview` | No | a deploy preview, not a scan; informational so a Vercel outage cannot block merging |

Revisit at the freeze (S3-18): any HIGH or CRITICAL finding with a fix available is fixed or recorded in the
findings log before tagging, and the open CodeQL alerts are triaged.

## Findings log

| ID | Finding | Severity | Decision |
|---|---|---|---|
| F-1 | Dependency and image scans were advisory only | Low | **Fixed:** `pip-audit`, `npm audit` and Trivy now fail CI on high or critical findings (see the policy above) |
| F-2 | In-memory rate limiter is per process (`backend/app/ratelimit.py`), so limits are per Render instance | Low | Accepted: single free-tier instance per service |
| F-3 | The admin role (`APP_MGMT`) was not exercised by the role matrix, so an operational route that accepted any staff role would have gone unnoticed | Low | Fixed: admin rows added to `test_rbac_matrix.py` |
| F-4 | The interactive API docs (`/docs`, `/openapi.json`) answer without authentication on the deployed backend (checked 14 Nov 2026) | Low | **Fixed in code:** off when `APP_ENV=production`, kept on staging (`backend/main.py`, `test_api_docs_exposure.py`). Production still answers 200 on 14 Nov because it runs build `54007f9`; re-check after the next deploy (D-03) |
| F-5 | Donation endings declined, abandoned and timed out were client-side only; the server kept the donation `PENDING` | Low | **Fixed in code:** `POST /donations/{id}/cancel`, the `payment.failed` webhook and 30-minute expiry end the donation as `FAILED` with an audited reason (migration 12, `test_donation_endings.py`); a later verified payment still confirms it |

Add new rows here as findings come in.

## Freeze evidence (S3-18)

The pre-freeze column was recorded on 14 Nov 2026 on the tree that the seven member packages produce together
(`origin/main` `ec4b2de` plus the packages), with the same commands and flags as CI. The release column is filled
in by Siddh from the CI run of the tagged commit; nothing in it may be copied from the pre-freeze column.

| Item | Pre-freeze, 14 Nov 2026 (local, package tree) | Release commit |
|---|---|---|
| CI run of the release commit (link) | not applicable: the packages are not merged yet | |
| `Backend / Migrations, Triggers & Test Suite` result and test counts | without PostGIS: 277 passed, 586 skipped (the DB-backed tests, which only CI runs); ai-workers 48 passed | |
| Ruff | `ruff check backend/ scripts/ ai-workers/`: no findings | |
| Bandit (`-ll -ii`) | `backend/` and `ai-workers/` (local virtualenvs excluded, as in CI's checkout): 0 medium or high; `scripts/` with `--skip B104,B608`: 0 | |
| `pip-audit` (backend and ai-workers requirements) | no known vulnerabilities | |
| `npm audit --audit-level=high` | 0 vulnerabilities | |
| Gitleaks, Trivy | run only in CI | |
| `python -m app.cli verify-audit` on the release database | not run: needs the production `DATABASE_URL` | |
| Open CodeQL alerts (high or critical) | read in GitHub, Security, Code scanning (or `gh api repos/Siddhcreator-1706/IT314_Software_Project/code-scanning/alerts?state=open`) | |
| Accepted findings reviewed by Siddh | F-2 accepted (single instance); F-1, F-3, F-4, F-5 fixed in code | |

To fill the release column: `gh run list --workflow ci.yml --branch main --limit 1` gives the run link; its
**Backend / Migrations, Triggers & Test Suite** log ends with the test counts; run `python -m app.cli verify-audit`
from `backend/` with `DATABASE_URL` set to the production database.
