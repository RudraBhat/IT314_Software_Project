# Sprint 3 Security, RBAC and Privacy Review (S3-02)

Owner: Siddh. Inputs still needed from others are marked **Open**.

## Checklist

| Item | Status | Evidence |
|---|---|---|
| Role matrix (public, citizen, field, dispatcher, admin) against every route group | Done | `backend/tests/test_rbac_matrix.py` is generated from the live route table; a new route without a guard fails it |
| `/public/*` contains no personal data, coordinates rounded to 4 decimals | Done | `test_public_api.py::test_no_pii_and_coordinates_rounded`, `test_security_review.py::test_public_routes_expose_no_personal_data` |
| `/me/*` contains no reporter identity or dispatcher-internal fields | Done | `test_security_review.py::test_me_routes_expose_no_personal_or_internal_data` |
| BFF proxies (`citizen`, `dm`, `field`, `session`) reject cross-site writes | Done | each handler checks `Origin` against the request host and returns 403 `CSRF_REJECTED`; `test_every_bff_proxy_rejects_cross_site_writes` fails if a new proxy lacks the check |
| SQLite stand-in and `X-User-Id` header trust removed | Done | `test_sqlite_stand_in_is_gone`, `test_no_route_trusts_an_identity_header`, `test_legacy_citizen_routes_are_not_mounted` |
| Secret scan, SAST, dependency audit, image scan in CI | Done, see merge policy | `.github/workflows/ci.yml` |
| Payment tamper and replay results | **Open** | Shlok to hand over |
| Matrix results from Dhruv's script, expected codes per route group | **Open** | Dhruv, Zalak, Nisarg, Shlok |

## CI scan merge policy

| Scan | Blocks a merge? | Reason |
|---|---|---|
| Gitleaks secret scan | Yes (`security-secrets-scan` is in the gate's `needs`) | A leaked secret cannot be un-leaked |
| Ruff, ESLint, TypeScript build | Yes | Deterministic |
| Bandit (`-ll -ii`, medium+ severity and confidence) | Yes | Deterministic and already tuned |
| `pip-audit`, `npm audit --audit-level=high` | No (advisory, `|| true`) | Findings depend on upstream releases and can appear without any code change; review the output at the release freeze and log findings below |
| Trivy image scan (CRITICAL, HIGH) | No (`exit-code: 0`) | Base-image findings are often unfixable by us; review at the release freeze |

Revisit at the freeze (S3-18): any HIGH or CRITICAL finding with a fix available is fixed or recorded in the findings log before tagging.

## Findings log

| ID | Finding | Severity | Decision |
|---|---|---|---|
| F-1 | Dependency and image scans are advisory only | Low | Accepted for the course timeline; reviewed manually at the freeze |
| F-2 | In-memory rate limiter is per process (`backend/app/ratelimit.py`), so limits are per Render instance | Low | Accepted: single free-tier instance |

Add new rows here as the Open items above come back.
