# Environment Variables Reference

All variable **names** only. No values, no secrets.
Secret marker (S) = must never appear in logs, source control, or error
messages in plain form.

Sources checked: `backend/app/config.py`, `backend/app/cli.py`,
`backend/tests/conftest.py`, `backend/main.py`, `docker-compose.yml`,
`docker-compose.prod.yml`, `.env.example`, `frontend/.env.example`,
`render.yaml`.

---

## Backend (FastAPI)

Read by `backend/app/config.py` via `os.getenv` at startup.

| Variable | Required | Secret | Read in file | Purpose |
|---|---|---|---|---|
| `DATABASE_URL` | Yes (unless `DEMO_MODE`) | S | `config.py` L62 | PostgreSQL connection URI for the backend |
| `JWT_SECRET` | Yes (unless demo fallback) | S | `config.py` L66 | HS256 signing key; minimum 32 characters |
| `MFA_ENCRYPTION_KEY` | No | S | `config.py` L71 | Fernet key for encrypting stored TOTP secrets; if absent, derived from `JWT_SECRET` |
| `DEMO_MODE` | No (default `false`) | — | `config.py` L63 | When `true` and no `DATABASE_URL`, enables a hardcoded demo user with no real DB |
| `AI_TRIAGE_URL` | No | — | `config.py` L73 | URL of the external AI triage service; if absent, the in-process `UnavailableProvider` is used |
| `ACCESS_TOKEN_MINUTES` | No (default 60) | — | `config.py` L74 | Lifetime of access JWTs in minutes |
| `MFA_TOKEN_MINUTES` | No (default 5) | — | `config.py` L75 | Lifetime of the MFA challenge JWT in minutes |
| `LOGIN_MAX_ATTEMPTS` | No (default 5) | — | `config.py` L76 | Failed login attempts before account lockout |
| `LOGIN_LOCKOUT_MINUTES` | No (default 15) | — | `config.py` L77 | Duration of account lockout in minutes |
| `DISPATCH_ACK_TIMEOUT_MINUTES` | No (default 15) | — | `config.py` L78 | Minutes before an unacknowledged dispatch is escalated |
| `AI_LOW_CONFIDENCE_THRESHOLD` | No (default 0.6) | — | `config.py` L79 | AI confidence below which a triage result is marked LOW_CONFIDENCE |
| `GOOGLE_MAPS_API_KEY` | No | S | `config.py` L80 | Google Maps Geocoding API key; falls back to OSM Nominatim when absent |
| `GOOGLE_GEOCODING_API_KEY` | No | S | `config.py` L80 | Alias for `GOOGLE_MAPS_API_KEY` (either name is accepted) |
| `BOUNDARY_SYNC_ENABLED` | No (default `true`) | — | `config.py` L81 | Toggle the monthly PostGIS boundary synchronisation worker |
| `BOUNDARY_SYNC_INTERVAL_HOURS` | No (default 720) | — | `config.py` L82 | How often the boundary sync worker checks for upstream updates |
| `BOUNDARY_SYNC_CHECK_INTERVAL_SECONDS` | No (default 86400) | — | `config.py` L83 | How often the in-process worker loop wakes to check if a sync is due |
| `GEOJSON_GUJARAT_DISTRICTS_URL` | No | — | `config.py` L84 | URL of the Gujarat district GeoJSON used by the boundary sync worker |

---

## Backend CLI (`app/cli.py`)

| Variable | Required | Secret | Read in file | Purpose |
|---|---|---|---|---|
| `DRCH_STAFF_PASSWORD` | No | S | `cli.py` L37 | Non-interactive password for `create-staff`; if absent, the CLI prompts interactively |

---

## Backend Test Suite (`backend/tests/conftest.py`)

| Variable | Required | Secret | Read in file | Purpose |
|---|---|---|---|---|
| `TEST_DATABASE_URL` | No | S | `conftest.py` L26 | Overrides the database URL used during tests; must end in `_test` |
| `REQUIRE_DB_TESTS` | No | — | `conftest.py` L101 | CI guard: set to `1` to fail the suite if zero `db`-marked tests executed |

Also read by `scripts/seed_reset.py` L20:

| Variable | Required | Secret | Read in file | Purpose |
|---|---|---|---|---|
| `TEST_DATABASE_URL` | No | S | `seed_reset.py` L20 | If set, preferred over `DATABASE_URL` for seed resets |

---

## Frontend (Next.js)

Read by `frontend/src/services/citizenApi.ts`, `frontend/src/services/authApi.ts`,
`frontend/src/lib/session.ts`, and `frontend/next.config.ts`.

| Variable | Required | Secret | Read in file | Purpose |
|---|---|---|---|---|
| `API_URL` | No | — | `session.ts` L2, `docker-compose.yml` L67 | Server-side base URL of backend API for Next.js proxy routes |
| `NEXT_PUBLIC_API_URL` | No (defaults to `http://localhost:8000`) | — | `authApi.ts` L3, `citizenApi.ts` L8, `session.ts` L3, `next.config.ts` L7 | Public base URL of the FastAPI backend; exposed to the browser |
| `NEXT_TELEMETRY_DISABLED` | No | — | `frontend/.env.example` | Disable Next.js anonymous usage telemetry; not read in application code |
| `NODE_ENV` | No | — | `frontend/.env.example`, build tooling | Node environment flag; managed by Next.js build, not read directly by app code |

---

## AI Workers (`ai-workers/`)

The `ai-workers/worker.py` file is a two-line stub and reads no environment
variables. The variables below are declared in Docker Compose for future use.

| Variable | Required | Secret | Declared in | Purpose (intended) |
|---|---|---|---|---|
| `RABBITMQ_URL` | — | S | `docker-compose.yml` L107, `docker-compose.prod.yml` L103 | RabbitMQ connection for the worker consumer (not yet implemented) |
| `REDIS_URL` | — | — | `docker-compose.yml` L108, `docker-compose.prod.yml` L104 | Redis connection for the worker (not yet implemented) |
| `DATABASE_URL` | — | S | `docker-compose.yml` L109, `docker-compose.prod.yml` L105 | Database access for the worker (not yet implemented) |
| `OPENAI_API_KEY` | — | S | `docker-compose.prod.yml` L106 | OpenAI API key for future LLM triage (not yet implemented) |
| `HUGGINGFACE_API_KEY` | — | S | `docker-compose.prod.yml` L107 | HuggingFace API key for future model inference (not yet implemented) |

---

## PostgreSQL container

Set as Docker container environment variables.

| Variable | Required | Secret | Declared in | Purpose |
|---|---|---|---|---|
| `POSTGRES_USER` | Yes | — | `docker-compose.yml` L11, `.env.example` L11 | Database superuser name |
| `POSTGRES_PASSWORD` | Yes | S | `docker-compose.yml` L12, `.env.example` L12 | Database superuser password |
| `POSTGRES_DB` | Yes | — | `docker-compose.yml` L13, `.env.example` L13 | Database name created on first start |
| `PGPASSWORD` | Yes (CI only) | S | `.github/workflows/ci.yml` L183 | Enables non-interactive `psql` commands in CI |

---

## Redis container

No configurable internal environment variables for the image. The container
uses its default configuration and listens on port 6379.

| Variable | Required | Secret | Declared in | Purpose |
|---|---|---|---|---|
| `REDIS_URL` | No | — | `docker-compose.yml` L85, `.env.example` L21 | Connection URI for Redis cache and broker |

---

## RabbitMQ container

| Variable | Required | Secret | Declared in | Purpose |
|---|---|---|---|---|
| `RABBITMQ_USER` | No (default `guest`) | — | `docker-compose.yml` L43, `.env.example` L23 | RabbitMQ admin username |
| `RABBITMQ_PASS` | No (default `guest`) | S | `docker-compose.yml` L44, `.env.example` L24 | RabbitMQ admin password |

---

## CI (GitHub Actions — `.github/workflows/ci.yml`)

These are set at job scope in the workflow file, not in `.env.example`.

| Variable | Required | Secret | Set in | Purpose |
|---|---|---|---|---|
| `DATABASE_URL` | Yes | S | `ci.yml` L181 | Backend DB URL pointing at the CI Postgres service container |
| `TEST_DATABASE_URL` | Yes | S | `ci.yml` L182 | DB URL passed to `conftest.py`; same value as `DATABASE_URL` in CI |
| `JWT_SECRET` | Yes | S | `ci.yml` L180 | Dummy signing key for CI (obvious placeholder value, not a real secret) |
| `PGPASSWORD` | Yes | S | `ci.yml` L183 | Enables password-less `psql` calls in migration steps |
| `REQUIRE_DB_TESTS` | Yes | — | `ci.yml` L259 | Set to `1` so the suite fails if DB tests are skipped unexpectedly |

---

## Gap analysis

### Variables the code reads that `.env.example` does not mention

| Variable | Read by | Notes |
|---|---|---|
| `MFA_ENCRYPTION_KEY` | `config.py` L71 | Optional, but important for production. `.env.example` is silent. |
| `TEST_DATABASE_URL` | `conftest.py` L26, `seed_reset.py` L20 | Test-only; intentionally not in root `.env.example`, but should be documented somewhere for contributors |
| `REQUIRE_DB_TESTS` | `conftest.py` L101 | CI-only; not in `.env.example` |
| `DRCH_STAFF_PASSWORD` | `cli.py` L37 | Automation-only; not in `.env.example` |
| `GOOGLE_GEOCODING_API_KEY` | `config.py` L80 | Alias for `GOOGLE_MAPS_API_KEY`; `.env.example` only mentions `GOOGLE_MAPS_API_KEY` (commented out) |
| `ACCESS_TOKEN_MINUTES` | `config.py` L74 | Tuning knob; not in `.env.example` |
| `MFA_TOKEN_MINUTES` | `config.py` L75 | Tuning knob; not in `.env.example` |
| `LOGIN_MAX_ATTEMPTS` | `config.py` L76 | Tuning knob; not in `.env.example` |
| `LOGIN_LOCKOUT_MINUTES` | `config.py` L77 | Tuning knob; not in `.env.example` |
| `DISPATCH_ACK_TIMEOUT_MINUTES` | `config.py` L78 | Tuning knob; not in `.env.example` |
| `AI_LOW_CONFIDENCE_THRESHOLD` | `config.py` L79 | Tuning knob; not in `.env.example` |
| `BOUNDARY_SYNC_ENABLED` | `config.py` L81 | Not in `.env.example` |
| `BOUNDARY_SYNC_INTERVAL_HOURS` | `config.py` L82 | Commented out in `.env.example` but not set |
| `BOUNDARY_SYNC_CHECK_INTERVAL_SECONDS` | `config.py` L83 | Not in `.env.example` |
| `GEOJSON_GUJARAT_DISTRICTS_URL` | `config.py` L84 | Not in `.env.example` |
| `API_URL` | `session.ts` L2, `smoke.py` L34 | Backend base URL for Next.js server runtime and smoke test script |
| `NEXT_PUBLIC_API_URL` | `authApi.ts` L3, `citizenApi.ts` L8 | Documented in `frontend/.env.example` but missing from root `.env.example` |
| `STAGING_URL` | `smoke.sh` L19 | Staging base URL for smoke tests against deployed Render environment |
| `SMOKE_BASE_URL` | `smoke.sh` L19 | Smoke test target base URL (defaults to `STAGING_URL` or `http://localhost:8000`) |
| `SMOKE_STAFF_EMAIL` | `smoke.py` L35, `smoke.sh` L23 | Smoke test runner configuration |
| `SMOKE_STAFF_PASSWORD` | `smoke.py` L36, `smoke.sh` L24 | Smoke test runner configuration |
| `SMOKE_STAFF_TOTP_SECRET` | `smoke.py` L37, `smoke.sh` L25 | Smoke test runner configuration |
| `SMOKE_COLD_START_TIMEOUT` | `smoke.sh` L35 | Polling timeout in seconds for Render cold-start (default 90) |

### Variables in `.env.example` that no application code reads

| Variable | In `.env.example` | Notes |
|---|---|---|
| `REDIS_URL` | L21 | Present in `.env.example` and Compose, but no Python backend code or worker code reads it |
| `RABBITMQ_USER` | L23 | Consumed only by the Docker Compose `RABBITMQ_DEFAULT_USER` mapping; no Python code reads it directly |
| `RABBITMQ_PASS` | L24 | Same — only used by Compose to configure the RabbitMQ container image |
| `RABBITMQ_URL` | L25 | Declared in `.env.example` for completeness; no backend Python code reads `RABBITMQ_URL` at the moment (ai-workers stub does not read it) |
| `OPENAI_API_KEY` | L44 | Present in `.env.example` and prod Compose; no code in `backend/app/` or `ai-workers/` reads it today |
| `HUGGINGFACE_API_KEY` | L45 | Same — declared for future use, not consumed by any current code |
