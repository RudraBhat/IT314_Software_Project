# Contributing to ResQ

This guide covers how to run ResQ on your machine, which checks to run before you push, and how to get a change merged.

## Contents

1. [Prerequisites](#prerequisites)
2. [Local development](#local-development)
   - [1. Clone and configure](#1-clone-and-configure)
   - [2. Start the database](#2-start-the-database)
   - [3. Run the backend](#3-run-the-backend)
   - [4. Run the frontend](#4-run-the-frontend)
   - [5. Run the AI triage service (optional)](#5-run-the-ai-triage-service-optional)
   - [6. Run the model services (optional)](#6-run-the-model-services-optional)
   - [7. Create accounts](#7-create-accounts)
   - [Alternative: everything in Docker](#alternative-everything-in-docker)
3. [Checks before you push](#checks-before-you-push)
4. [Workflow: branches, commits and pull requests](#workflow-branches-commits-and-pull-requests)
5. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Git | any recent | source control |
| Python | 3.12 | backend and AI triage service (CI and the Docker images use 3.12) |
| Python | 3.11 | only the optional model services in `models/*/deployment/` (pinned in their `.python-version`) |
| Node.js | 22 LTS | frontend (CI and the Docker image use Node 22) |
| Docker Desktop | any recent | local PostgreSQL + PostGIS, or the whole stack |

Instead of the local PostGIS container you can use any PostgreSQL 16 database with the PostGIS extension, for example a Neon branch. Point `DATABASE_URL` at it.

Commands below are shown for **bash** (macOS, Linux, Git Bash) with the **PowerShell** equivalent where it differs.

---

## Local development

Each service runs in its own terminal with hot reload. Only the database and the backend are needed to use the app. The AI and model services are optional; without them staff triage manually.

| Service | Folder | Local URL |
|---|---|---|
| PostgreSQL + PostGIS | Docker | `localhost:5432` |
| Backend API | `backend/` | http://localhost:8000 (Swagger UI at `/docs`) |
| Frontend | `frontend/` | http://localhost:3000 |
| AI triage service | `ai-workers/` | http://localhost:8001 |
| Image classifier (optional) | `models/image_classifier/deployment/` | http://localhost:8002 |
| Text classifier (optional) | `models/text_classifier/deployment/` | http://localhost:8003 |

### 1. Clone and configure

```bash
git clone https://github.com/<your-username>/IT314_Software_Project.git
cd IT314_Software_Project
cp .env.example .env
```

PowerShell: `Copy-Item .env.example .env`

The backend reads `.env` (and `.env.local`, if present) from the **repository root**. Open `.env` and fill in the blanks:

| Variable | How to get a value |
|---|---|
| `JWT_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `MFA_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (after installing the backend requirements). Keep it fixed: changing it invalidates every enrolled authenticator. |
| `MOCK_GATEWAY_SECRET` | same command as `JWT_SECRET`; needed for the sandbox donation flow |
| `INGEST_TOKEN` | same command as `JWT_SECRET`; only needed to call the internal ingestion endpoint |

Leave `APP_ENV=development` and the default `DATABASE_URL`, which points at the local container. Every other variable is optional and documented in [docs/architecture/env-variables.md](docs/architecture/env-variables.md). Never commit `.env`.

### 2. Start the database

```bash
docker compose up -d postgres-postgis
```

This starts PostgreSQL 16 with PostGIS 3.4 on `localhost:5432`, using the `POSTGRES_*` credentials from `.env`. Data persists in the `pgdata` Docker volume.

### 3. Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate                 # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
uvicorn main:app --reload --port 8000
```

- On startup the backend applies any pending migrations from `backend/db/migrations/` and the reference seeds. In development it also loads the demo seeds. To migrate without starting the server, run `python -m app.migrate`.
- Check it is up: http://localhost:8000/api/v1/health should report `"database": "ok"`.
- To reset local data to the baseline seeds, run `make seed-reset` from the repository root. It refuses cloud databases unless `FORCE=1`.

### 4. Run the frontend

```bash
cd frontend
cp .env.example .env.local                # PowerShell: Copy-Item .env.example .env.local
npm ci
npm run dev
```

Open http://localhost:3000. `NEXT_PUBLIC_API_URL` in `.env.local` must point at the backend (default `http://localhost:8000`). The browser talks only to Next.js; the route handlers in `src/app/api/` forward requests to the backend.

### 5. Run the AI triage service (optional)

```bash
cd ai-workers
python -m venv .venv
source .venv/bin/activate                 # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn triage_service:app --reload --port 8001
```

Then add this to the root `.env` and restart the backend:

```
AI_TRIAGE_URL=http://localhost:8001/triage
```

If you set `AI_TRIAGE_TOKEN`, set the same value for both the backend and the triage service. By default the service uses the written triage rules. To use a trained scenario model, set `TRIAGE_MODEL_DIR` (see [docs/ai/](docs/ai/)).

### 6. Run the model services (optional)

Both services download their model from a public Hugging Face repository at startup, so the first start takes a while. Use **Python 3.11** and a separate virtual environment for each. Training, evaluation and hosting details are in [docs/ai/models.md](docs/ai/models.md).

**Multilingual text classifier** (labels ingested news and social signals):

```bash
cd models/text_classifier/deployment
python -m venv .venv
source .venv/bin/activate                 # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
export HF_MODEL_REPO=Dhruvil-14/indicbert-disaster-api   # PowerShell: $env:HF_MODEL_REPO="Dhruvil-14/indicbert-disaster-api"
uvicorn app:app --port 8003
```

Backend `.env`: `DISASTER_CLASSIFIER_URL=http://localhost:8003/predict`

**Disaster image classifier** (analyses report photos):

```bash
cd models/image_classifier/deployment
python -m venv .venv
source .venv/bin/activate                 # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
export HF_MODEL_REPO_ID=Dhruvil-14/disaster-classifier   # PowerShell: $env:HF_MODEL_REPO_ID="Dhruvil-14/disaster-classifier"
uvicorn app:app --port 8002
```

Backend `.env`: `AI_IMAGE_SERVICE_URL=http://localhost:8002`. Do not point it at the backend's own port 8000.

### 7. Create accounts

- **Citizens** sign up in the app at http://localhost:3000/signup. Google sign-in additionally needs `GOOGLE_CLIENT_ID` and `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
- **Staff, administrators and field responders** are created with the backend CLI. Run these from `backend/` with the virtual environment active. Each command asks for a password; to script it, set `RESQ_STAFF_PASSWORD` instead. It then prints a TOTP secret and QR code **once**: add it to an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password and similar). You need that code to sign in.

```bash
# Disaster Management staff (pick permissions from SUPERVISOR, DISPATCH, CLOSURE, MODERATOR, PUBLISHER)
python -m app.cli create-staff --email dispatcher@example.org --name "Local Dispatcher" --permissions SUPERVISOR,DISPATCH,CLOSURE,MODERATOR,PUBLISHER

# Administrator (account management and audit log only)
python -m app.cli create-admin --email admin@example.org --name "Local Admin"

# Field responder: the team must already exist as a TEAM resource (add one under /dm/resources)
python -m app.cli create-field --email responder@example.org --name "Local Responder" --team "<team name or resource id>"
```

Once an administrator or supervisor exists, further accounts can be invited from the app (`/admin` or `/dm/staff`). Invitation emails are only logged unless `SMTP_HOST` is set.

Other useful CLI commands: `set-permissions`, `reset-mfa`, `verify-audit`, `load-fallback-alerts` (development only) and `purge-demo-data`. Run `python -m app.cli --help` for the full list.

### Alternative: everything in Docker

```bash
docker compose up --build
```

This builds and starts PostGIS, the backend, the frontend (a production build, without hot reload) and the AI triage service. Ports are as in the table above. `JWT_SECRET` must be set in `.env`. Stop everything with `docker compose down`; add `-v` to also delete the database volume.

---

## Checks before you push

Run the checks for every part you changed. CI runs the same ones, and the **Pipeline Status / Quality Gate** check must pass before a pull request can merge.

**Backend** (from the repository root, backend virtual environment active)

```bash
python -m ruff check backend/
python -m pytest backend/tests/test_units.py -v
cd backend && bandit -r app -ll
```

The full suite also runs the database tests. It needs a disposable PostGIS database and **must not** point at real data:

```bash
TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/drch_test" python -m pytest backend/tests/ -v --tb=short
```

PowerShell: `$env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/drch_test"; python -m pytest backend/tests/ -v --tb=short`

Database tests are skipped when `TEST_DATABASE_URL` is unset. Set `REQUIRE_DB_TESTS=1` (as CI does) to fail the run if no database test actually ran. If you changed a migration, also run `cd backend && python -m app.cli verify-audit` and `python scripts/generate_er_diagram.py --check`.

**AI triage service**

```bash
cd ai-workers && python -m pytest tests/ -v
```

**Frontend**

```bash
cd frontend
npm run lint
npm run build
```

End-to-end tests run against a production build and a running backend:

```bash
npx playwright install chromium
npm run build && npx next start -p 3000      # in one terminal
npx playwright test                         # in another
```

Specs that call the API directly (the cyclone, industrial fire and urban flooding scenarios) need the backend on port 8000.

**Documentation**

If you read a new environment variable in code, document it in `docs/architecture/env-variables.md`. `python scripts/check_env_docs.py` fails otherwise. If you change an endpoint, update `docs/architecture/api_contracts.md`.

---

## Workflow: branches, commits and pull requests

### Fork and branch

1. Fork the repository on GitHub and clone your fork.
2. Add the main repository as `upstream`:
   ```bash
   git remote add upstream https://github.com/Siddhcreator-1706/IT314_Software_Project.git
   ```
3. Start every change from an up-to-date `main` on its own branch. Never commit to `main`.
   ```bash
   git fetch upstream
   git switch -c feat/citizen-offline-drafts upstream/main
   ```
   Name branches `<type>/<short-topic>`, for example `feat/…`, `fix/…`, `docs/…` or `chore/…`.
4. Before opening or updating a pull request, rebase on the latest `main`:
   ```bash
   git fetch upstream
   git rebase upstream/main
   # fix any conflicts, then: git add <files> && git rebase --continue
   git push --force-with-lease origin <your-branch>
   ```

### Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): imperative summary`.
- The subject is lowercase with no trailing period, for example `fix(field): attach device location to on-scene reports`.
- Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `revert`.
- The scope is the module, for example `citizen`, `dm`, `field`, `security`, `ai-workers` or `frontend`.
- Keep one concern per commit, and put unrelated documentation in its own commit.
- Every non-trivial commit has a body. It says what changed and why, which areas it touches, how it was verified, and any trade-offs.
- Reference issues in a footer (`Refs #123`, `Fixes #123`).
- Mark breaking changes with `!` or a `BREAKING CHANGE:` footer.

### Pull requests

- Open the pull request against `main`. The title is a Conventional Commit line.
- Fill in every section of [the pull request template](.github/PULL_REQUEST_TEMPLATE.md), and tick only what you actually did. Write "None" or "Not applicable" rather than deleting a section.
- Include only files that belong to the change. Never commit secrets, `.env` files or real personal or emergency-report data.
- Add screenshots for user-facing changes.
- Report bugs and request features with the forms in [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).

### Project rules worth knowing

These constraints are enforced in review (see [AGENTS.md](AGENTS.md) section 4):
- Only the `cyclone`, `industrial_fire` and `urban_flooding` scenarios are supported.
- AI output stays advisory, and a human approves verification, dispatch, escalation and closure.
- Every state change writes to the audit log.
- Resource allocation uses `SELECT ... FOR UPDATE`.
- Public coordinates are rounded to 4 decimal places, and simulated or sandbox data is always labelled.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| The backend exits at startup complaining about a missing setting | Check the root `.env`. Outside `APP_ENV=development`, `DATABASE_URL`, `JWT_SECRET`, `MFA_ENCRYPTION_KEY` and `INGEST_TOKEN` are required. |
| `/api/v1/health` shows `"database": "unavailable"` | The database is not reachable. Run `docker compose ps`, check that port 5432 is not taken by another PostgreSQL, and check `DATABASE_URL`. |
| The frontend loads but every request fails | The backend is not running on the URL in `frontend/.env.local` (`NEXT_PUBLIC_API_URL`). Restart `npm run dev` after editing `.env.local`. |
| A staff sign-in keeps asking for a code that never works | The device clock must be correct for TOTP. If the authenticator was lost, run `python -m app.cli reset-mfa --email <address>` from `backend/`. |
| PowerShell refuses to run `Activate.ps1` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. |
| `fatal: unable to access ... SSL certificate problem` on a campus or office network (Windows) | `git config --global http.sslBackend schannel` |
| CI did not start on your first pull request from a fork | A maintainer must click **Approve and run** on the Actions tab. |
