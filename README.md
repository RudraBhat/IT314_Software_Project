# ResQ — Disaster Response Coordination Hub for Gujarat

ResQ coordinates disaster response across Gujarat. Citizens report emergencies from a phone or browser. Disaster Management staff verify the reports, decide priority and dispatch agencies and field teams. Field teams receive their orders and report progress until the job is done. The public sees a live map of verified incidents, official early warnings, shelters and safety guidance.

The platform supports three disaster scenarios: **cyclone**, **industrial fire** and **urban flooding**.

---

## Contents

- [Who uses it](#who-uses-it)
- [Core principles](#core-principles)
- [Architecture](#architecture)
- [Technology](#technology)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [What is real and what is simulated](#what-is-real-and-what-is-simulated)
- [Testing and CI/CD](#testing-and-cicd)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Who uses it

| Role | Where | What they do |
|---|---|---|
| **Public** (no sign-in) | `/` live map, `/safety`, `/how-to`, `/donate` | See verified incidents and official alerts on a map of Gujarat, read safety guidance, find shelters, donate to relief campaigns (sandbox). |
| **Citizen** (`NORMAL_USER`) | `/citizen/dashboard`, `/report`, `/my-reports` | Report an incident with location and photos, track it from submission to closure, answer requests for more information, send a one-tap SOS. Sign-in with email and password or Google. |
| **Disaster Management staff** (`DISASTER_MGMT`) | `/dm` | Triage and verify reports, set priority, review advisory AI suggestions and duplicates, dispatch agencies and teams, record agency responses, publish public updates, manage shelters, resources, agencies and staff. What each person may do is set by permissions: Supervisor, Dispatch, Closure, Moderator and Publisher. |
| **Field team responders** (`FIELD_TEAM`) | `/field` | Acknowledge or reject orders, report en route, on scene, delays and situation updates, request backup and complete the mission. |
| **Administrators** (`APP_MGMT`) | `/admin` | Invite and manage platform accounts, review the audit log and system status. Administrators have no operational access. |

Staff, field and administrator accounts always sign in with a password **and** an authenticator (TOTP) code.

---

## Core principles

These rules are enforced in code and covered by tests in `backend/tests/`.

- **People decide; AI advises.** Verification, dispatch, escalation and closure always need a human. AI triage, duplicate detection and team recommendations are stored separately (`triage_results`) and are never applied automatically. (`backend/app/services/ai_provider.py`, `backend/app/routers/dm/ai.py`)
- **Every state change is audited.** Incident and dispatch transitions, sign-ins, access denials and administrative actions write to `audit_logs`. A PostgreSQL trigger chains each row to the previous one with SHA-256, and triggers block `UPDATE` and `DELETE` on the table. CI verifies the chain on every pull request (`python -m app.cli verify-audit`).
- **Strict incident lifecycle.** `SUBMITTED → NEEDS_INFORMATION → VERIFIED → DISPATCHED → RESOLVED → CLOSED` (or `REJECTED`). Each transition is checked by a state machine and recorded in `incident_status_history`, and the reporting citizen is notified. Verifying needs a priority and a rationale. (`backend/app/routers/dm/incidents.py`)
- **No over-allocation.** Resource rows are locked with `SELECT ... FOR UPDATE` before quantities change. A request that would over-allocate gets `409 RESOURCE_CONFLICT`, and nothing is written. Resources are released when an order is rejected or completed. (`backend/app/services/resources.py`, `backend/app/services/dispatch.py`)
- **Secure authentication.** Argon2id password hashing, TOTP multi-factor sign-in for staff, short-lived MFA challenges, account lockout after repeated failures, and session and token revocation. (`backend/app/routers/auth.py`, `backend/app/security.py`)
- **Gujarat only, privacy first.** Reports must fall inside Gujarat (PostGIS boundary check, with Google or OpenStreetMap geocoding as fallback). Public incident coordinates are rounded to 4 decimal places, reporter details never reach public endpoints, and text is scrubbed of personal data before it is sent to AI services. (`backend/app/geo.py`)
- **Simulation is always labelled.** Sample alerts, simulated signals, demo incidents and the sandbox payment gateway are marked as such in the data and in the UI.

---

## Architecture

```mermaid
flowchart LR
    subgraph Clients
        B[Browser / phone]
    end
    subgraph Frontend["Frontend (Next.js, Vercel)"]
        UI[Pages: public map, citizen, /dm, /field, /admin]
        PX[Same-origin API proxy routes<br/>session cookies]
    end
    subgraph Backend["Backend API (FastAPI, Render)"]
        API[REST API /api/v1]
        ING[Ingestion poller]
    end
    DB[(PostgreSQL 16 + PostGIS<br/>Neon)]
    AIW[AI triage service<br/>ai-workers]
    TXT[Multilingual text classifier<br/>models/text_classifier]
    IMG[Disaster image classifier<br/>models/image_classifier]
    EXT[Official and public feeds<br/>SACHET CAP, news, social]
    GEO[Geocoding<br/>Google / Nominatim]

    B --> UI --> PX --> API
    API --> DB
    ING --> DB
    API --> AIW
    ING --> TXT
    API --> IMG
    ING --> EXT
    API --> GEO
```

- The browser never calls the backend directly. Next.js route handlers under `frontend/src/app/api/` forward requests and keep the session in httpOnly cookies.
- The backend applies database migrations on startup and refuses to start in staging or production when a required secret is missing.
- AI services are optional. Without them the platform keeps working, and staff triage manually.

Read [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) for the full design and [docs/architecture/api_contracts.md](docs/architecture/api_contracts.md) for the REST contracts.

---

## Technology

| Layer | Stack |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Leaflet with OpenStreetMap tiles, Playwright for end-to-end tests |
| Backend | Python 3.12, FastAPI, psycopg 3 with a connection pool, Argon2id, PyOTP, Gunicorn and Uvicorn workers |
| Database | PostgreSQL 16 with PostGIS 3.4 (Neon in the cloud, `postgis/postgis` locally); SQL migrations in `backend/db/migrations/` |
| AI | Rules-based triage service with an optional trained scenario model (`ai-workers/`); an IndicBERT ONNX multilingual text classifier and a PyTorch image classifier (`models/`), each deployed as its own service |
| Delivery | Docker, GitHub Actions (CI and CD), GitHub Container Registry, Render (API and AI services), Vercel (frontend) |

---

## Repository layout

| Path | Contents |
|---|---|
| `frontend/` | Next.js web client: pages in `src/app/`, shared components in `src/components/`, API proxy routes in `src/app/api/`, Playwright tests in `e2e/` |
| `backend/` | FastAPI API (`main.py`, `app/`), SQL migrations and seeds (`db/`), pytest suite (`tests/`), admin CLI (`python -m app.cli`) |
| `ai-workers/` | AI triage service (`triage_service.py`, `rules.py`, `service/`) and its tests |
| `models/` | Model training, evaluation and deployment code for the text and image classifiers |
| `scripts/` | Smoke, scenario, load-test, backup and documentation-check scripts (see [scripts/README.md](scripts/README.md)) |
| `docs/` | Architecture, API contracts, environment variables, guides, runbooks and quality reports (see [docs/README.md](docs/README.md)) |
| `docker-compose.yml` | Local stack: PostGIS, backend, frontend and AI triage service |
| `docker-compose.prod.yml` | Self-hosted production stack from published images |
| `render.yaml` | Render service definitions |

---

## Getting started

The quickest way to run everything locally is Docker Compose. You need Docker and a `.env` file with a `JWT_SECRET`.

```bash
git clone https://github.com/Siddhcreator-1706/IT314_Software_Project.git
cd IT314_Software_Project
cp .env.example .env          # then set JWT_SECRET (see the comment in the file)
docker compose up --build
```

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs (Swagger UI) | http://localhost:8000/docs |
| API liveness | http://localhost:8000/health |
| API readiness (database) | http://localhost:8000/api/v1/health |
| AI triage service | http://localhost:8001/health |

For day-to-day development, run each service on its own with hot reload. Step-by-step instructions are in **[CONTRIBUTING.md → Local development](CONTRIBUTING.md#local-development)**. They cover:
- the database
- the backend
- the frontend
- the AI triage service
- the optional model services
- creating staff, administrator and field accounts
- running the tests

---

## What is real and what is simulated

**Real**
- Citizen reporting, verification, dispatch, field execution and closure, end to end against PostgreSQL and PostGIS.
- Official early warnings from the SACHET CAP feed when `SACHET_FEED_URL` is set.
- Optional live news and Bluesky signal sources (off unless `NEWS_RSS_ENABLED` / `BLUESKY_SEARCH_ENABLED` is set).
- AI triage and the model services, when their URLs are configured.

**Simulated, and labelled as such**
- **Demo data.** `backend/db/seeds/demo/` (sample incidents and signal clusters, flagged `is_simulated`) is applied only when `APP_ENV=development`. Staging and production receive only `backend/db/seeds/reference/` (roles, agencies, system accounts, safety content). Public endpoints hide simulated incidents outside development.
- **Social replay.** The `REPLAY` signal source reads a team-authored, sanitised fixture. It is off unless `SOCIAL_REPLAY_ENABLED=true`, and its rows are always marked simulated.
- **Sample alerts.** `python -m app.cli load-fallback-alerts` (development only) inserts three alerts flagged `is_fallback`. The UI marks them "Sample alert".
- **Donations.** Payments use a signed sandbox gateway (`PAYMENT_GATEWAY=mock`); no real money moves. See [docs/guides/payments.md](docs/guides/payments.md).

Ingested signals never become incidents or public alerts without a dispatcher's decision. Source access, caching and attribution are described in [docs/operations/ingestion-sources.md](docs/operations/ingestion-sources.md).

---

## Testing and CI/CD

| Check | Command |
|---|---|
| Backend unit tests | `python -m pytest backend/tests/test_units.py -v` |
| Full backend suite (needs PostGIS) | `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/drch_test python -m pytest backend/tests/ -v` |
| Backend lint | `python -m ruff check backend/` |
| Audit hash-chain check | `cd backend && python -m app.cli verify-audit` |
| AI triage tests | `cd ai-workers && python -m pytest tests/ -v` |
| Frontend lint and build | `cd frontend && npm run lint && npm run build` |
| End-to-end tests | `cd frontend && npx playwright test` (needs the web app and API running) |
| Core-loop smoke test | `python scripts/smoke.py --base-url http://localhost:8000` |

**Continuous integration** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs on every pull request to `main`. It runs:
- a Gitleaks secrets scan
- ESLint, a production build and `npm audit` for the frontend
- Ruff, Bandit and `pip-audit` for the Python code
- migrations, the audit-chain check, the full pytest suite with coverage and the smoke test against PostGIS
- the AI worker tests
- the Playwright tests
- for changed images: a container build and a Trivy scan

A single required check, **Pipeline Status / Quality Gate**, decides whether a pull request can merge.

**Continuous deployment** ([`.github/workflows/cd.yml`](.github/workflows/cd.yml)) runs on pushes to `main` and on release tags:
1. It publishes images to GHCR.
2. It deploys the backend to staging and runs the smoke test there.
3. Only after that passes, it deploys production.

The frontend and AI services deploy through their own hooks. Details: [docs/quality/testing.md](docs/quality/testing.md) and [docs/operations/release-runbook.md](docs/operations/release-runbook.md).

---

## Deployment

| Component | Host | Notes |
|---|---|---|
| Frontend | Vercel | Deployed by the CD workflow's deploy hook; pull requests get a preview. |
| Backend API | Render | Staging `drch-backend-latest` and production `it314-software-project-backend1`, defined in `render.yaml`. Health check at `/health`. |
| AI triage service | Render | `drch-ai-triage`, defined in `render.yaml`. |
| Text and image classifiers | Render | Deployed from `models/*/deployment/`; see [docs/ai/models.md](docs/ai/models.md). |
| Database | Neon | PostgreSQL 16 with PostGIS. |

Render's free tier sleeps when idle, so the first request after a pause can take 45–90 seconds. Smoke and polling scripts use a 90-second timeout.

To self-host from published images (put a TLS-terminating reverse proxy in front; app ports bind to localhost):

```bash
IMAGE_TAG=v1.0.0 docker compose -f docker-compose.prod.yml up -d
```

Every environment variable is documented in [docs/architecture/env-variables.md](docs/architecture/env-variables.md) (names and purpose only, never values).

---

## Documentation

| Topic | Document |
|---|---|
| System design | [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) |
| REST API and error format | [docs/architecture/api_contracts.md](docs/architecture/api_contracts.md) |
| Environment variables | [docs/architecture/env-variables.md](docs/architecture/env-variables.md) |
| Database diagram | [docs/architecture/er-diagram.md](docs/architecture/er-diagram.md) |
| Using the citizen and field apps | [docs/guides/frontend-citizen-field-guide.md](docs/guides/frontend-citizen-field-guide.md) |
| Using the dispatcher workspace and public portal | [docs/guides/frontend-dispatcher-public-guide.md](docs/guides/frontend-dispatcher-public-guide.md) |
| AI triage and models | [docs/ai/](docs/ai/) |
| Releases and migrations | [docs/operations/](docs/operations/) |
| Testing, load and security reviews | [docs/quality/](docs/quality/) |

The full index is in [docs/README.md](docs/README.md).

---

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). It covers local setup, the checks to run, branch naming, Conventional Commit messages and the pull request template. AI coding agents also follow [AGENTS.md](AGENTS.md).

---

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
