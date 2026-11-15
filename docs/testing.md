# ResQ Backend Test Suite Reference

Comprehensive guide to executing backend unit and integration tests, configuring database guards, starting the local PostGIS test container, and utilizing test fixtures.

---

## 1. How to Run Tests

The backend test suite is managed via `pytest` from the `backend/` directory.

### Quick Start (Unit Tests Only / No Database)

When `TEST_DATABASE_URL` is unset or PostgreSQL is unreachable, all DB-backed tests skip automatically. Only unit and fallback tests run:

```bash
cd backend
python -m pytest tests/ -v --tb=short
```

In that case `conftest.py` also clears `DATABASE_URL` for the test process, so a non-DB test that touches the app
gets "database not configured" at once instead of waiting on connection retries, and the app's connection pool is
closed when the session ends. The whole suite then finishes in well under a minute (14 Nov 2026: 277 passed,
586 skipped in about 18 s); before this it could hang for minutes on a machine whose `.env` pointed at a database
it could not log in to.

### Full Test Suite (With Database)

To run both unit tests and PostGIS-backed integration tests, configure `TEST_DATABASE_URL`:

**Linux / macOS / Git Bash:**
```bash
cd backend
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/drch_test"
python -m pytest tests/ -v --tb=short
```

**Windows PowerShell:**
```powershell
cd backend
$env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/drch_test"
python -m pytest tests/ -v --tb=short
```

### Running with CI Guard Active

To guarantee that DB-backed tests are not accidentally skipped:

```bash
export REQUIRE_DB_TESTS=1
python -m pytest tests/ -v --tb=short
```

If zero DB tests execute while `REQUIRE_DB_TESTS=1`, the test suite fails with exit status `1`.

---

## 2. How to Start the PostGIS Test Container

The integration suite requires PostgreSQL with PostGIS extensions. Start an isolated container using Docker:

```bash
docker run -d \
  --name drch_test_db \
  -p 5432:5432 \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=drch_test \
  postgis/postgis:16-3.4
```

Verify that the container is healthy and ready to accept connections:

```bash
docker exec -it drch_test_db pg_isready -U postgres -d drch_test
```

To stop and clean up the test database container:

```bash
docker stop drch_test_db && docker rm drch_test_db
```

---

## 3. Environment Variables Reference

| Variable | Required | Secret | Purpose |
|---|---|---|---|
| `TEST_DATABASE_URL` | No | S | Explicit connection string for the test database; must end with `_test`. If omitted, defaults to `/drch_test` on `DATABASE_URL`. |
| `REQUIRE_DB_TESTS` | No | — | CI test guard; set to `1` to fail the test run if zero DB-marked tests executed. |

---

## 4. Test Fixtures (`backend/tests/conftest.py`)

- `client`: Session-scoped FastAPI `TestClient` initialized without background worker loops.
- `sql`: Autocommit `psycopg` connection using `dict_row` row factory for direct database state arrangement and assertion.
- `make`: Factory instance bound to `sql` connection for creating test entities (users, incidents, agencies, resources, field users, and assigned field dispatches).
- `citizen_user`: Active `NORMAL_USER` citizen account with pre-issued bearer headers and no MFA.
- `staff_user`: Active `DISASTER_MGMT` staff account with TOTP MFA secret and `DISPATCH`, `SUPERVISOR` permissions.
- `field_user`: Active `FIELD_TEAM` user bound to a team resource and `field_team_members` record with verified MFA.
- `field_dispatch`: A realistic operational dispatch order (`REQUESTED`) assigned to the `field_user`'s team resource with active reservation.
- `source_signal`: A realistic raw ingested signal (`PENDING`) in `source_signals`.
- `campaign`: An active donation campaign (`ACTIVE`) in `donation_campaigns`.

---

## 5. Database Seed Reset (`make seed-reset`)

The seed reset utility safely cleans dynamic operational data and reapplies the baseline seed files (`backend/db/seeds/reference/` and `backend/db/seeds/demo/`). It is completely idempotent.

### Running Seed Reset

**Using Make (Linux / macOS / Git Bash):**
```bash
make seed-reset
```

**Using PowerShell (Windows without Make):**
```powershell
python scripts/seed_reset.py
```

**Custom Seed Files:**
By default the reference and demo seeds are used. To override, set `SEED_FILES` (the root `Makefile` passes it through when set) or use `--seed-files`. In PowerShell:
```powershell
$env:SEED_FILES="backend/db/seeds/reference/10_reference_data.sql"; python scripts/seed_reset.py
```

### Safety Guard
To prevent accidental data loss on external cloud environments (e.g. Neon, Render, AWS RDS), `seed_reset.py` refuses execution unless:
1. The host is `localhost`, `127.0.0.1`, `::1`, or a docker-compose service name (`postgres-postgis`, `postgres`, `db`), OR
2. The database name ends with `_test` or contains `dev`.

To override the guard on cloud staging databases, supply `FORCE=1`:
```bash
FORCE=1 make seed-reset
# Windows PowerShell:
$env:FORCE="1"; python scripts/seed_reset.py
```

### Post-Reset Verification Row Counts
After applying seeds, the script prints verified row counts:
- `users`: 3 (System Administrator, Automated Ingestion System, Dispatch Supervisor)
- `incidents`: 4 (Ahmedabad, Surat, Anjar, Veraval)
- `resources`: 5 (NDRF, SDRF, 108 Ambulance, Fire HQ, Medical)
- `donation_campaigns`: 3 (CM Relief Fund, Cyclone Relief, Flood Response)

---

## 6. End-to-End Smoke Testing (`scripts/smoke.py`)

`scripts/smoke.py` is a strict black-box check of the core loop against any running DRCH backend: liveness and database readiness, citizen registration and incident submission (with an idempotent replay and an outside-Gujarat refusal), the incident staying off the public map until verified, dispatcher sign-in with password and TOTP, verification, the incident appearing on the public map with no personal data and 4-decimal coordinates, and the citizen timeline. Field operations, AI triage, donations and the rest are covered by the backend pytest suites (for example `test_field_routes.py`, `test_ai_gate.py`, `test_donations.py`).

CI runs it against a local API in the backend job; CD runs it against the staging backend before production deploys.

### Prerequisites

```bash
pip install httpx pyotp
```

Create a dispatcher once (the command prints the TOTP secret; keep it out of the repository):

```bash
cd backend && python -m app.cli create-staff --email smoke@example.in --name "Smoke Dispatcher" --permissions DISPATCH,CLOSURE
```

### Configuration

| Variable | Required | Description |
| :--- | :--- | :--- |
| `SMOKE_STAFF_EMAIL` | **Yes** | The staff account's email. |
| `SMOKE_STAFF_PASSWORD` | **Yes** | Its password (never logged). |
| `SMOKE_STAFF_TOTP_SECRET` | **Yes** | The base32 TOTP secret printed by `create-staff`. |
| `SMOKE_BASE_URL` / `API_URL` | No | Backend base URL (default `http://localhost:8000`); `--base-url` overrides them. |

### Running

Against a local stack (`docker compose up -d`):

```bash
export SMOKE_STAFF_EMAIL="smoke@example.in"
export SMOKE_STAFF_PASSWORD="<password>"
export SMOKE_STAFF_TOTP_SECRET="<secret>"
python scripts/smoke.py --base-url http://localhost:8000
```

PowerShell:

```powershell
$env:SMOKE_STAFF_EMAIL="smoke@example.in"
$env:SMOKE_STAFF_PASSWORD="<password>"
$env:SMOKE_STAFF_TOTP_SECRET="<secret>"
python scripts/smoke.py --base-url http://localhost:8000
```

Against staging, point `--base-url` at the staging backend and use the staging account. A successful run ends with `[SMOKE PASSED]`; any failure prints `[SMOKE FAILURE]` and exits 1. Each run leaves a registered citizen and a verified incident behind, so never point it at production.

---

## 7. Automated Cyclone Scenario (`scripts/scenario_run.py`, S3-01)

The scenario runner extends the smoke test to the whole lifecycle over HTTP: a citizen reports a cyclone in
Porbandar, the dispatcher verifies it, it appears on the public map without personal data, the dispatcher reads the
advisory recommendations and dispatches the field responder's team, the responder acknowledges, reports
`EN_ROUTE` and `ON_SCENE` and completes, the dispatcher resolves and closes, and the citizen's timeline shows
`SUBMITTED → VERIFIED → DISPATCHED → RESOLVED → CLOSED`.

```bash
python scripts/scenario_run.py --base-url https://<staging-backend>.onrender.com --runs 3
```

It needs the smoke staff account (with `DISPATCH` and `CLOSURE`) and a field account on the same backend whose team
is `AVAILABLE` and belongs to an agency: `SCENARIO_FIELD_EMAIL`, `SCENARIO_FIELD_PASSWORD` and
`SCENARIO_FIELD_TOTP_SECRET` (field accounts also use TOTP; see `scripts/README.md`). The S3-01 target is three
passing runs in a row; the runner prints `3/3 runs passed` and exits 1 if any run fails (`--json` prints per-step
timings). Every run creates and closes real records, so use staging only. The same steps run against the PostGIS
test database in `backend/tests/test_scenario_dispatch_field_flow.py`.

---

## 8. OpenAPI Automated RBAC Matrix Test (`test_rbac_matrix.py`)

The DRCH backend includes an automated Role-Based Access Control (RBAC) matrix test suite (`backend/tests/test_rbac_matrix.py`) that executes against all registered FastAPI routes:

1. **Route Introspection:** Introspects FastAPI's OpenAPI routing tree to verify every `/api/v1/*` endpoint has an explicit dependency check or role guard.
2. **Authentication Denial:** Asserts that anonymous requests to protected endpoints receive HTTP 401 `AUTHENTICATION_REQUIRED`.
3. **Role Segregation:**
   - Public/Citizen users (`NORMAL_USER`) calling `/api/v1/dm/*` or `/api/v1/field/*` receive HTTP 403 `ROLE_REQUIRED`.
   - Field responders (`FIELD_TEAM`) calling `/api/v1/dm/*` receive HTTP 403 `ROLE_REQUIRED`.
   - DM staff (`DISASTER_MGMT`) calling citizen-only endpoints (`/api/v1/me/*`, `/api/v1/incidents`) receive HTTP 403.
4. **Staff Permission Boundaries:** For each permission-gated DM route (`DISPATCH`, `CLOSURE`, `PUBLISHER`, `MODERATOR`, `SUPERVISOR`), tests systematically verify that staff accounts lacking that specific permission receive HTTP 403 `PERMISSION_DENIED` and an immutable audit log record is created.


