# Environment Variables Reference

Names only - never put values or secrets in this file. **(S)** = secret: must never appear in logs,
source control or error messages. `python scripts/check_env_docs.py` fails CI if code reads a variable
that is not listed here.

When `APP_ENV` is `staging` or `production` the backend refuses to start unless every variable marked
**required\*** is set and the secrets are not placeholders (`app/config.py: validate_for_environment`).

## Backend (FastAPI) - read in `backend/app/config.py`

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `APP_ENV` | no | `development` | `development`, `staging` or `production`. Controls startup validation, demo seeds, simulated-incident visibility, the sandbox payment endpoint. |
| `DATABASE_URL` (S) | **yes** | - | PostgreSQL 16 + PostGIS URI (Neon in staging/production). |
| `JWT_SECRET` (S) | **required\*** | - | HS256 signing key, 32+ chars, no placeholder words. |
| `MFA_ENCRYPTION_KEY` (S) | **required\*** | - | Fernet key encrypting staff TOTP secrets. Outside development it must be set (it is otherwise derived from `JWT_SECRET`, so rotating the JWT secret would lock out all staff). |
| `INGEST_TOKEN` (S) | **required\*** | - | Bearer token for `POST /api/v1/internal/ingest/run`; the DM poll action uses staff authentication instead. |
| `CORS_ALLOWED_ORIGINS` | **required\*** | `http://localhost:3000,http://127.0.0.1:3000` in development, empty otherwise | Comma-separated browser origins allowed to call the API. |
| `ACCESS_TOKEN_MINUTES` | no | `60` | Access-token lifetime. |
| `MFA_TOKEN_MINUTES` | no | `5` | MFA challenge lifetime. |
| `LOGIN_MAX_ATTEMPTS` | no | `5` | Failures before account lockout. |
| `LOGIN_LOCKOUT_MINUTES` | no | `15` | Lockout duration. |
| `DISPATCH_ACK_TIMEOUT_MINUTES` | no | `15` | Minutes before an unacknowledged dispatch is escalated. |
| `AI_TRIAGE_URL` | no | - | URL of the triage service (`.../triage`). Unset = triage returns `UNAVAILABLE`. |
| `AI_TRIAGE_TOKEN` (S) | no | - | Bearer token sent to the triage service; set the same value on `ai-workers`. |
| `AI_LOW_CONFIDENCE_THRESHOLD` | no | `0.6` | Below this a suggestion is `LOW_CONFIDENCE`. |
| `GOOGLE_MAPS_API_KEY` (S) / `GOOGLE_GEOCODING_API_KEY` (S) | no | - | Optional geocoder; falls back to OpenStreetMap Nominatim. |
| `BOUNDARY_SYNC_ENABLED` | no | `true` | Enable the periodic boundary sync worker. |
| `BOUNDARY_SYNC_INTERVAL_HOURS` | no | `720` | Minimum hours between upstream syncs. |
| `BOUNDARY_SYNC_CHECK_INTERVAL_SECONDS` | no | `86400` | Worker wake-up interval. |
| `GEOJSON_GUJARAT_DISTRICTS_URL` | no | empty | GeoJSON FeatureCollection of Gujarat districts. Empty = sync disabled (packaged state polygon + PostGIS data are used). |
| `PAYMENT_GATEWAY` | no | `mock` | Only `mock` is implemented. |
| `MOCK_GATEWAY_SECRET` (S) | when donations are used | - | HMAC key for the sandbox gateway. |
| `SACHET_FEED_URL` | no | empty | SACHET RSS feed URL; the adapter fetches linked CAP XML and honors ETags. Empty = adapter disabled. |
| `USGS_FEED_URL` | no | Gujarat GeoJSON query | USGS earthquake GeoJSON feed; results are checked against the Gujarat boundary before storage. |
| `SOCIAL_REPLAY_FILE` | no | packaged JSONL replay | Path to the team-authored, sanitised social replay fixture. Replay records are always marked simulated. |
| `INGEST_INTERVAL_SECONDS` | no | `600` | In-process adapter polling interval. Use a shorter value only for local scheduler checks. |
| `GIT_SHA` | no | `dev` | Commit id shown by `/api/v1/health` (CD smoke test). |
| `RATE_LIMIT_ENABLED` | no | `true` | Set `false` only in automated tests. |
| `RESQ_STAFF_PASSWORD` (S) | no | - | Non-interactive password for `python -m app.cli create-staff`. |
| `RESQ_FIELD_PASSWORD` (S) | no | - | Non-interactive password for the field-team provisioning command in `python -m app.cli`. |
| `DRCH_STAFF_PASSWORD` (S) | no | - | Backward-compatible alias for `RESQ_STAFF_PASSWORD`. |
| `DRCH_FIELD_PASSWORD` (S) | no | - | Backward-compatible alias for `RESQ_FIELD_PASSWORD`. |
| `RAZORPAY_KEY_ID` | no | - | Razorpay key id for the (not yet wired) Razorpay adapter; a `rzp_live` prefix marks live mode. |
| `RAZORPAY_KEY_SECRET` (S) | no | - | Razorpay key secret used to verify payment signatures. |
| `RAZORPAY_WEBHOOK_SECRET` (S) | no | - | Razorpay webhook signing secret. |
| `SMTP_HOST` | no | - | SMTP server for invitation and password-reset emails. When unset, emails are only logged and kept in the in-memory outbox (development). |
| `SMTP_PORT` | no | `587` | SMTP port (`465` uses implicit TLS, anything else uses STARTTLS when offered). |
| `SMTP_USERNAME`, `SMTP_PASSWORD` (S) | no | - | SMTP credentials. |
| `EMAIL_FROM` | no | `no-reply@drch.gujarat.gov.in` | Sender address of transactional emails. |
| `FRONTEND_URL` | no | `http://localhost:3000` | Base URL used to build the setup-account and reset-password links in emails. |
| `INVITATION_TOKEN_HOURS` | no | `48` | Lifetime of an account-invitation link. |
| `PASSWORD_RESET_TOKEN_MINUTES` | no | `15` | Lifetime of a password-reset link. |
| `GOOGLE_CLIENT_ID` | no | - | Google OAuth web client id. `POST /auth/google` returns 503 until it is set; tokens for any other audience are rejected. |
| `GOOGLE_CLIENT_SECRET` (S) | no | - | Google OAuth client secret (reserved; the ID-token flow does not need it yet). |

## Frontend (Next.js)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `API_URL` | server runtime | falls back to `NEXT_PUBLIC_API_URL`, then `http://localhost:8000` | Backend base URL used by server code (BFF routes, server actions). |
| `NEXT_PUBLIC_API_URL` | build time | `http://localhost:8000` | Baked into the bundle; only used by `next.config.ts` rewrites. |
| `NEXT_PUBLIC_PAYMENT_SANDBOX` | no | `false` | When `true`, enables sandbox payment test flow on `/donate`; never set in production. |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | build time | - | Google OAuth web client id for the "Sign in with Google" button (same value as the backend `GOOGLE_CLIENT_ID`). |
| `NEXT_PUBLIC_DEMO_MODE` | no | `false` | **Development only.** Enables local demo fallbacks; must be unset in staging/production. |

## AI triage service (`ai-workers/`)

| Variable | Required | Purpose |
|---|---|---|
| `AI_TRIAGE_TOKEN` (S) | recommended | If set, `POST /triage` requires `Authorization: Bearer <token>`. |

## Database container

`POSTGRES_USER`, `POSTGRES_PASSWORD` (S), `POSTGRES_DB` - used by Docker Compose to create the local database.

## Tests and scripts

| Variable | Purpose |
|---|---|
| `TEST_DATABASE_URL` (S) | Test database; the name must end in `_test`. |
| `REQUIRE_DB_TESTS` | `1` = fail the run if no DB-backed test executed (CI guard). |
| `SMOKE_BASE_URL`, `STAGING_URL`, `SMOKE_STAFF_EMAIL`, `SMOKE_STAFF_PASSWORD` (S), `SMOKE_STAFF_TOTP_SECRET` (S), `SMOKE_COLD_START_TIMEOUT` | Smoke-test runner configuration. |

## Not used (removed)

`DEMO_MODE`, `REDIS_URL`, `RABBITMQ_*`, `OPENAI_API_KEY`, `HUGGINGFACE_API_KEY` - no code reads them.
