# ResQ — Architecture Reference

## 1. System Overview

The **ResQ** platform is an operational incident coordination platform built specifically for the State of Gujarat. The system coordinates three distinct user groups:
1. **Citizens:** Submit geolocated disaster reports with media attachments, receive safety bulletins, track report status, and locate relief shelters.
2. **Disaster Management (DM) Staff & Dispatchers:** Triage and verify incoming citizen reports, inspect AI suggestions, monitor district operational heatmaps, and dispatch response teams and equipment with concurrency-safe resource locking.
3. **Field Teams & Responders:** Receive assignments, acknowledge dispatches, log progress timestamps (`EN_ROUTE`, `ON_SCENE`, `COMPLETED`), and provide ground situation updates.

### Scope & Supported Scenarios
The platform enforces a strict three-scenario operational scope:
- `cyclone` (Coastal inundation, severe windstorm damage)
- `industrial_fire` (Chemical, petrochemical, or urban major factory fires)
- `urban_flooding` (Monsoon waterlogging and urban gridlock across Gujarat municipal zones)

Any unsupported or out-of-scope events (e.g., earthquakes) are strictly categorized as `other_disaster` without automated triage escalation.

---

## 2. High-Level System Architecture

```mermaid
flowchart TD
    subgraph Clients["Client Layer"]
        CitizenUI["Citizen Portal & Mobile PWA<br/>Next.js 16 App Router"]
        DispatcherUI["DM Command Center Console<br/>Next.js 16 / Tailwind / Leaflet"]
        FieldUI["Field Team Operations View<br/>Mobile-responsive Web"]
    end

    subgraph Edge["Ingestion & Schedulers"]
        CronIngest["Ingestion Cron Scheduler<br/>GitHub Actions / cron-job.org"]
        VercelProxy["Vercel Next.js API Routes<br/>/api/dm/* & /api/citizen/*"]
    end

    subgraph BackendGateway["FastAPI Gateway & Core Application"]
        MainApp["FastAPI Core (backend/main.py)<br/>Uvicorn / Python 3.12"]
        AuthRouter["Auth & MFA Router<br/>Argon2id + TOTP RFC 6238"]
        DMRouters["DM Portals & Workspaces<br/>Incidents, Dispatches, Resources"]
        PublicRouter["Public Privacy-Preserving API<br/>Sanitized Verified Incidents"]
        InternalRouter["Internal Maintenance Router<br/>Advisory-Locked Ingest Runner"]
        GeoService["PostGIS Spatial Engine<br/>Gujarat Boundary Geofence & Fallback"]
        AuditService["Append-Only Audit Log<br/>Trigger SHA-256 Hash Chaining"]
        DispatchService["Dispatch & Resource Locking<br/>SELECT ... FOR UPDATE"]
    end

    subgraph DataStorage["Data & State Persistence"]
        NeonDB[("Neon PostgreSQL 16 + PostGIS<br/>Spatial Boundary & Relational Core")]
        AuditTable[("audit_logs<br/>Hash-Chained & Immutable Trigger")]
        InMemCache[("In-Memory Spatial RAM Cache<br/>Gujarat Boundaries & Districts")]
    end

    subgraph AIService["AI & Triage Services"]
        InProcessAI["Backend AI boundary<br/>ai_provider.py guardrails"]
        TriageAI["drch-ai-triage /triage<br/>rules baseline, optional trained model"]
        DisasterClassifier["IndicBERT /predict<br/>multilingual disaster class"]
        TextAI["Optional English Text Classifier<br/>/analyze-text (advisory; event-held-out baseline)"]
        VisionAI["PyTorch Vision Microservice<br/>models/image_classifier (timm backbone)"]
    end

    CitizenUI --> VercelProxy
    DispatcherUI --> VercelProxy
    FieldUI --> VercelProxy
    VercelProxy --> MainApp
    CronIngest --> InternalRouter

    MainApp --> AuthRouter
    MainApp --> DMRouters
    MainApp --> PublicRouter
    MainApp --> InternalRouter

    DMRouters --> DispatchService
    DMRouters --> GeoService
    DMRouters --> AuditService
    DMRouters --> InProcessAI
    InProcessAI -->|HTTP, AI_TRIAGE_URL| TriageAI
    InternalRouter -->|HTTP, DISASTER_CLASSIFIER_URL| DisasterClassifier

    DispatchService --> NeonDB
    GeoService --> NeonDB
    GeoService --> InMemCache
    AuditService --> AuditTable
    DMRouters -.-> VisionAI
```

---

## 3. Repository Directory Structure

```text
IT314_Software_Project/
├── .agents/                    # Agent orchestration rules and guidelines
│   └── rules/                  # Architecture, backend, frontend, security rule definitions
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # PR validation (Lint, SAST, PostGIS DB tests, Quality Gate)
│   │   ├── cd.yml              # CD pipeline (GHCR container publish, Vercel/Render deploy, smoke gate)
│   │   └── ingest-cron.yml     # 15-minute staging ingestion trigger
│   ├── CODEOWNERS              # Pull request review assignment rules
│   └── PULL_REQUEST_TEMPLATE.md# Team PR template with verification checklist
├── ai-workers/                 # Advisory AI triage service; folder scope: docs/ai/folder-scope.md
│   ├── triage_service.py       # FastAPI entry point: /triage, /analyze-text, /health
│   ├── rules.py                # Keyword and points triage rules (drch-triage-v1-rules)
│   ├── service/                # Runtime helpers: scenario model, English text analysis, optional LLM
│   ├── artifacts/              # Local trained artifacts the service loads (ignored by Git)
│   ├── eval/                   # Offline baselines and inter-annotator agreement
│   ├── data/                   # Team text datasets and prompt-injection fixtures
│   ├── tests/                  # Service tests (CI)
│   └── Dockerfile              # Container for the triage service
├── models/                     # Every ML model: training, research, deployment apps; never in the triage image
│   ├── text_classifier/        # Multilingual IndicBERT classifier (deployed) and MuRIL (not deployed)
│   ├── image_classifier/       # ConvNeXt-Tiny disaster photo classifier (deployed)
│   └── text_model/             # English TF-IDF text model for /analyze-text (served by ai-workers)
│       ├── train/              # Data download and training
│       ├── testing/            # Training tests (CI)
│       └── humaid/             # HumAID BERTweet research experiment (offline only)
├── backend/                    # Core Python / FastAPI Backend application
│   ├── app/
│   │   ├── routers/            # API routing layer
│   │   │   ├── auth.py         # Staff login, Argon2id, TOTP MFA challenge & verify
│   │   │   ├── internal.py     # Scheduled ingestion runner protected by advisory locks
│   │   │   ├── public.py       # Public unauthenticated incidents & campaigns API
│   │   │   └── dm/             # Disaster Management command center endpoints
│   │   │       ├── ai.py           # Advisory AI triage and similarity endpoints
│   │   │       ├── dispatches.py   # Dispatch order creation & team status updates
│   │   │       ├── incidents.py    # Incident lifecycle transitions (VERIFY, RESOLVE, etc.)
│   │   │       ├── resources.py    # Resource inventory & warehouse supplies
│   │   │       └── staff.py        # Staff user and role administration
│   │   ├── schemas/            # Pydantic data transfer models
│   │   │   └── citizen.py      # Citizen report, incident, and alert schemas
│   │   ├── services/           # Reusable domain business logic
│   │   │   ├── ai_provider.py      # Triage provider boundary: HTTP call, PII scrub, guardrails
│   │   │   ├── dispatch.py         # Shared dispatch transitions & overdue escalation
│   │   │   ├── incidents.py        # Incident status validation & notification hooks
│   │   │   ├── recommendations.py  # Spatial team proximity & recommendation ranking
│   │   │   ├── signal_matching.py  # Advisory related-signal suggestions (distance, time, wording, label)
│   │   │   ├── resources.py        # Row-level locked resource allocations & release
│   │   │   └── spatial_sync.py     # Upstream Gujarat district GeoJSON sync worker
│   │   ├── audit.py            # Audit log recording & cryptographic hash-chain verifier
│   │   ├── auth.py             # Staff identity dependencies & token validation
│   │   ├── cli.py              # Administrative CLI commands (create-staff, verify-audit)
│   │   ├── common.py           # Shared system enums (IncidentStatus, ScenarioType, Role)
│   │   ├── config.py           # Settings management via pydantic_settings & env vars
│   │   ├── db.py               # Connection pool manager & transaction context
│   │   ├── errors.py           # Standardized API error handlers (SRS s.15.7)
│   │   ├── geo.py              # PostGIS boundary validation & OSM/Google fallback geocoder
│   │   ├── migrate.py          # Sequential SQL schema migration runner
│   │   └── security.py         # AES-GCM encryption & constant-time comparison helpers
│   ├── db/
│   │   ├── migrations/         # Version-controlled idempotent schema migrations
│   │   │   ├── 01_schema.sql             # Base tables, triggers, hash-chain audit log
│   │   │   ├── 02_dm_module.sql          # DM extensions, status history, triage results
│   │   │   ├── 03_core_extensions.sql    # Ingest runs, alerts, fallback flags, campaigns
│   │   │   ├── 04_spatial_boundaries.sql # PostGIS administrative boundary tables
│   │   │   └── 10_signal_matching.sql    # Signal geom sync trigger + pending-signal indexes
│   │   └── seeds/              # Seed data (applied by app.migrate and scripts/seed_reset.py)
│   │       ├── reference/      # 10_reference_data.sql: reference data, always applied
│   │       ├── demo/           # Demo incidents and signal clusters (development only)
│   │       └── optional/       # Extra demo data, loaded by hand
│   ├── tests/                  # Pytest automated test suite
│   │   ├── conftest.py         # Database fixtures, app client setup, CI test guards
│   │   ├── test_auth.py        # Staff 2FA authentication, lockouts & token revocation
│   │   ├── test_dispatch.py    # Concurrency resource locking & dispatch state transitions
│   │   ├── test_incidents.py   # Incident verification state machine & transition rules
│   │   ├── test_recommendations.py # Team ranking & spatial distance calculations
│   │   └── test_units.py       # Non-DB unit tests & /api/v1/health commit verification
│   ├── Dockerfile              # Production multi-stage runner for FastAPI
│   └── main.py                 # Primary FastAPI application entrypoint & lifespan
├── docs/                       # Project documentation; index: docs/README.md
│   ├── architecture/           # This document, API contracts, env variables, ER diagram, signal matching
│   ├── ai/                     # AI docs: models.md, text-model.md, folder-scope.md, model card, triage rules
│   │   └── reports/            # Saved evaluation results, one folder per model
│   ├── guides/                 # Citizen, field, dispatcher and payment guides, AI agent workflow
│   ├── operations/             # Release and migration runbooks, ingestion sources
│   ├── quality/                # Test suite reference, load test, security review, defects
│   └── project/                # Final report, demo script, future features, sprints
├── frontend/                   # Next.js 16 / React 19 / Tailwind CSS Web Application
│   ├── src/
│   │   ├── app/                # Next.js App Router pages and proxy endpoints
│   │   │   ├── api/            # Server-side API proxy routes (dm, citizen, session)
│   │   │   ├── citizen/        # Citizen dashboard
│   │   │   ├── dm/             # Dispatcher command center workspace
│   │   │   │   ├── incidents/  # Incident queue, triage, decision & dispatch panels
│   │   │   │   ├── dispatches/ # Active field dispatches
│   │   │   │   └── resources/  # Inventory management
│   │   │   ├── login/          # Staff 2FA login & Citizen login
│   │   │   ├── report/         # Citizen disaster reporting form
│   │   │   └── my-reports/     # Citizen tracking timeline
│   │   ├── components/         # Reusable UI components & role views
│   │   │   ├── dm/             # Tactical GIS map layers & operations UI
│   │   │   ├── role-views/     # Dedicated role views (Admin, Citizen, Responder)
│   │   │   ├── ui.tsx          # Base UI design system primitives
│   │   │   └── badges.tsx      # Severity, priority, and status indicators
│   │   ├── components/auth/    # sign-in widgets and the shared SessionProvider
│   │   ├── lib/                # Client utilities (api.ts, geo.ts, session.ts, format.ts)
│   │   └── services/           # Frontend API service adapters (authApi.ts, citizenApi.ts)
│   └── Dockerfile              # Next.js container build specification
├── scripts/                    # Automation and operational maintenance scripts
│   ├── seed_reset.py           # Automated DB reset & seed application
│   ├── smoke.py                # End-to-end smoke test runner (core loop: report, verify, public map)
│   └── sync_boundaries.py      # Standalone PostGIS boundary loader
├── docker-compose.yml          # Local multi-container development environment
├── docker-compose.prod.yml     # Production container stack
├── render.yaml                 # Render cloud deployment specification
└── ruff.toml                   # Python code quality and lint configuration
```

---

## 4. Module Responsibilities

### 4.1 Backend Architecture

- **Application Lifespan & Startup ([`backend/main.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/main.py)):**
  - Instantiates the FastAPI application, mounts error handlers, and configures CORS.
  - Controls lifecycle initialization via `lifespan(app)`: executes schema migrations ([`backend/app/migrate.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/migrate.py)), preloads Gujarat PostGIS boundary polygons into RAM cache, and starts background workers.
  - Mounts routes under `/api/v1` namespaces (`/api/v1/auth`, `/api/v1/dm`, `/api/v1/public`, `/api/v1/internal`) alongside `/health` and `/api/v1/health`.

- **Authentication & Security ([`backend/app/auth.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/auth.py), [`backend/app/security.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/security.py)):**
  - **Zero Supabase:** Strictly application-managed authentication.
  - Staff authentication enforces a two-step handshake: Argon2id password verification followed by RFC 6238 TOTP validation using encrypted secrets (AES-GCM / Fernet).
  - Failed logins are tracked; five consecutive failed attempts lock the account for 15 minutes and invalidate active sessions by bumping `token_version`.

- **Database & Concurrency Management ([`backend/app/db.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/db.py)):**
  - Manages PostgreSQL connection pools using `psycopg_pool.ConnectionPool`.
  - Exposes atomic context-managed transactions (`with db.transaction() as conn:`) and `db.read_only()`, an autocommit connection for read-only handlers (a single query is one network round trip instead of three; each statement is its own transaction, so never use it for writes or locking reads).
  - Pings a pooled connection before reuse only when it sat idle for 30 seconds (Neon closes idle connections); a connection used a moment ago is not pinged, because every ping is a full round trip.
  - Round trips, not CPU, dominate request time against a remote database (measured about 0.5 s each from a laptop to Neon). The authenticated principal (user, role, status, lock, `token_version` and staff permissions) is loaded in one statement on every request and is deliberately never cached, so a role change, disable, lock or logout takes effect on the next request. Independent statements are pipelined (`conn.pipeline()`) in the dashboard, analytics and sign-in. Redis is not used: after removing the extra round trips every hot path is 1 to 3 round trips, and an external cache would add a network hop plus an invalidation problem for authorisation data.
  - Handles row-level resource allocation locks (`SELECT ... FOR UPDATE`) and PostgreSQL advisory session locks (`pg_try_advisory_xact_lock`).

- **Geospatial & Boundary Engine ([`backend/app/geo.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/geo.py)):**
  - Enforces Gujarat jurisdiction for incoming incident coordinates via PostGIS `ST_Contains` spatial queries against `administrative_boundaries`.
  - Provides a 2-tier geocoding fallback when coordinates are missing: Google Maps Geocoding API (if key configured) falling back to OpenStreetMap Nominatim.
  - Preloads boundary polygons into RAM for sub-millisecond in-process containment checks.

- **Hash-Chained Audit Trail ([`backend/app/audit.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/audit.py)):**
  - Implements an immutable audit log table (`audit_logs`) governed by a database trigger (`fn_audit_log_hash_chain`).
  - Each entry stores a SHA-256 hash chaining the current row contents with the preceding row's `row_hash`.
  - Table triggers explicitly block `UPDATE` and `DELETE` operations.
  - Verifiable at runtime or via the administrative CLI (`python -m app.cli verify-audit`).

### 4.2 Frontend Architecture

- **Next.js App Router Structure ([`frontend/src/app/`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/app/)):**
  - Unified codebase serving Citizen, Dispatcher, Administrator, and Responder views through role-guarded routes and views.
  - Each role has its own area: Disaster Management (`DISASTER_MGMT`) works in `/dm`, with navigation filtered by permission; Application Management (`APP_MGMT`) uses the administration console at `/admin` (account directory, invitations, audit log and system status); field responders use `/field`; citizens use `/citizen/dashboard`. A signed-in visitor of another role is redirected to their own area (`homeFor(role)` in `lib/session.ts`), and `/dashboard` sends each role there too. Administrators still have no operational access: the backend answers 403 on every `/api/v1/dm`, `/api/v1/field`, `/api/v1/me` and `/api/v1/incidents` route (`test_admin_has_no_operational_access`).
  - Route protection has three layers. `proxy.ts` sends visitors with no session cookie to `/login` before anything is rendered; each workspace layout (`/dm`, `/field`) asks the backend who the user is (`currentUser()`), redirects to `/login` when nobody is signed in and to the user's own home (`homeFor(role)`) when the role is wrong; the backend re-checks role, MFA and permission on every API call. The BFF proxies (`/api/dm`, `/api/field`, `/api/invitations`, `/api/citizen`) answer 401 JSON without a session and forward nothing else. Static JavaScript bundles of staff pages are public like any Next.js asset but contain no data; all data comes from guarded API calls.
  - Uses server-side API proxy routes (`/api/dm/[...path]` and `/api/citizen/[...path]`) to securely forward requests to the FastAPI backend while managing session cookies.
- **Session state ([`frontend/src/components/auth/SessionProvider.tsx`](../../frontend/src/components/auth/SessionProvider.tsx)):**
  - The root layout mounts one `SessionProvider`. `useSession()` gives any component the signed-in state (`authenticated`, `role`, `name`) from `GET /api/session` without its own request; the provider stays mounted across client navigation, re-checks quietly after each route change and shows a placeholder only before the first answer, so the header does not flicker between pages.

### 4.3 AI Workers & Models Architecture

- **Backend AI boundary ([`backend/app/services/ai_provider.py`](../../backend/app/services/ai_provider.py)):**
  - Calls the triage service at `AI_TRIAGE_URL` (`HttpTriageProvider`); without it, or when the call fails, the result is `UNAVAILABLE` and staff triage manually. The backend has no classifier of its own.
  - Removes emails, phone numbers and id numbers before sending, then validates every answer (`apply_guardrails`): invalid output becomes `UNSAFE_OUTPUT`, unsupported scenarios are out of scope, confidence below `AI_LOW_CONFIDENCE_THRESHOLD` becomes `LOW_CONFIDENCE`.
  - Results are advisory, stored in `ai_recommendations`, and never alter an incident; the human decision is recorded separately.
- **Triage service ([`ai-workers/triage_service.py`](../../ai-workers/triage_service.py)):**
  - `POST /triage` answers with the keyword and points rules ([docs/ai/triage-rules.md](../ai/triage-rules.md)); when `TRIAGE_MODEL_DIR` holds a checked trained scenario model (`service/scenario_model.py`) its scenario and confidence are used instead, and priority still follows the rules. `GET /health` reports which engine is active.
  - The optional LLM second opinion (`service/llm.py`) is off by default. Model card and evaluation: [docs/ai/model-card.md](../ai/model-card.md), [docs/ai/evaluation-report.md](../ai/evaluation-report.md).
- **Ingested-text disaster classifier:** The ingestion worker sends PII-scrubbed text from new GNEWS/BLUESKY signals to `DISASTER_CLASSIFIER_URL` (`POST /predict`). It stores the raw class, disaster flag, confidence, and probabilities in the signal's `ai_details`; `Non-Disaster` is marked false. This stage does not assign priority or make incident/dispatch decisions. The configured endpoint is staging-only in `render.yaml`; live signal sources remain disabled unless explicitly enabled.
  - Its code is [`models/text_classifier/`](../../models/text_classifier/) (IndicBERT training, ONNX export, deployment app and API test); data, results and the MuRIL comparison are in [docs/ai/models.md](../ai/models.md).
- **English Text Analysis (trained in [`models/text_model/`](../../models/text_model/), served by [`ai-workers/service/text_analysis.py`](../../ai-workers/service/text_analysis.py)):**
  - Optional `/analyze-text` endpoint trained on an openly licensed, event-held-out English crisis-message corpus.
  - Predicts disaster relevance, help request/offer, direct reports, and available humanitarian information categories.
  - Does not replace `/triage` and does not infer the operational scenario, priority, location, or event time because the training labels do not support those outputs.
  - Requires a separately supplied local model artifact; ingestion is not connected to it yet.
  - Training, evaluation and limits: [docs/ai/text-model.md](../ai/text-model.md).
- **Standalone Vision Model Service ([`models/image_classifier/`](../../models/image_classifier/)):**
  - Separate from `ai-workers/`: its own dependencies and process. The backend reaches it only through `AI_IMAGE_SERVICE_URL`.
  - Microservice utilizing a `timm` PyTorch backbone for classifying disaster imagery; training, deployment app and API test harness are in `train/`, `deployment/` and `testing/`. Results: [docs/ai/models.md](../ai/models.md).
- **Folder scope:** what each `ai-workers/` and `models/` folder is for, and where new work goes: [docs/ai/folder-scope.md](../ai/folder-scope.md).

---

## 5. Existing Reusable Components & Services

Before introducing new components or functions, developers must inspect and reuse the following established modules:

### Reusable Backend Services & Utilities
| Module / Symbol | Location | Reusable Capabilities |
| :--- | :--- | :--- |
| `dispatch` service | [`backend/app/services/dispatch.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/services/dispatch.py) | `transition_dispatch()`, `escalate_overdue()`, shared state machine validation |
| `resources` service | [`backend/app/services/resources.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/services/resources.py) | Atomic row-locked resource allocation, `release_all_for_dispatch()` |
| `recommendations` engine | [`backend/app/services/recommendations.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/services/recommendations.py) | PostGIS distance calculation, team suitability ranking, workload scoring |
| `geo` module | [`backend/app/geo.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/geo.py) | `validate_coordinates_in_gujarat()`, `reverse_geocode_district()`, boundary cache |
| `audit` logger & verifier | [`backend/app/audit.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/audit.py) | `log_audit_event()`, `verify_audit_log_hash_chain()` |
| `db` transaction context | [`backend/app/db.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/db.py) | `with db.transaction() as conn:`, connection pool access |
| `errors` framework | [`backend/app/errors.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/errors.py) | `AppError`, standardized error response formatting conforming to SRS s.15.7 |
| `common` enums | [`backend/app/common.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/common.py) | `IncidentStatus`, `DispatchStatus`, `PriorityLevel`, `ScenarioType`, `Role` |

### Reusable Frontend Components & Libraries
| Component / Module | Location | Reusable Capabilities |
| :--- | :--- | :--- |
| `Brand.tsx` (Logo, LogoMark, Brand, SiteHeader, NavLink) | [`frontend/src/components/Brand.tsx`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/components/Brand.tsx) | Final Q-Radar logo (light/dark lockup, symbol) and the single shared top bar (56px, navy) used by every page; assets in `frontend/public/logo*.svg` and `frontend/src/app/icon.svg` |
| `ui.tsx` Primitives | [`frontend/src/components/ui.tsx`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/components/ui.tsx) | Base buttons, cards, modals, dialogs, form inputs, badges |
| `badges.tsx` | [`frontend/src/components/badges.tsx`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/components/badges.tsx) | Color-coded status badges for incidents, dispatches, and priority levels |
| `LiveOperationsLayer` | [`frontend/src/components/dm/LiveOperationsLayer.tsx`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/components/dm/LiveOperationsLayer.tsx) | Interactive Leaflet tactical map with incidents, teams, and shelter markers |
| `AlertsDrawer` | [`frontend/src/components/AlertsDrawer.tsx`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/components/AlertsDrawer.tsx) | Sliding tray displaying official emergency bulletins and warning alerts |
| `api.ts` Client Wrapper | [`frontend/src/lib/api.ts`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/lib/api.ts) | Unified HTTP client handling JWT headers, base URL resolution, and error parsing |
| `geo.ts` Helpers | [`frontend/src/lib/geo.ts`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/frontend/src/lib/geo.ts) | Haversine distance, Gujarat coordinate bounding box verification |

---

## 6. Architectural Principles & Operational Conventions

1. **Human-in-the-Loop Dispatcher Decisions:**
   - AI recommendations must never automatically verify incidents, modify incident priorities, or execute dispatch orders. All algorithmic outputs are purely advisory and stored in dedicated `triage_results` records. Human dispatcher action is strictly required.

2. **Strict Concurrency & Allocation Safety:**
   - Resource quantities must be allocated atomically using PostgreSQL `SELECT ... FOR UPDATE` row locks within a single transaction to prevent race conditions or over-allocation.
   - External ingestion loops use PostgreSQL transactional advisory locks (`pg_try_advisory_xact_lock`) to eliminate duplicate runs between webhooks and cron triggers.

3. **Public Privacy Protection (PII Scrubbing):**
   - The public incident feed ([`backend/app/routers/public.py`](file:///c:/Users/shahs/OneDrive/Desktop/My%20Folder/DAIICT/Sem5/Software/IT314_Software_Project/backend/app/routers/public.py)) strictly excludes reporter names, phone numbers, and citizen identifiers.
   - Coordinates on public feeds are truncated to 4 decimal places (~11m precision) to obscure exact private residential addresses.

4. **Cryptographic Auditability:**
   - All state transitions and administrative actions record immutable entries in `audit_logs`. Database triggers compute a SHA-256 hash incorporating the previous row's hash.

5. **Standardized API Error Envelope:**
   - Every non-2xx API error conforms strictly to the schema:
     ```json
     {
       "error": {
         "code": "STRING_CONSTANT_CODE",
         "message": "Human-readable explanation of error",
         "details": null
       }
     }
     ```

---

## 7. Implementation Status: Real vs. Simulated

To maintain factual engineering clarity, capabilities in the repository are catalogued by their verified implementation status:

| Capability / Module | Implementation Status | Verification Details |
| :--- | :--- | :--- |
| **Staff 2FA Authentication** | **Implemented (Real)** | Argon2id + RFC 6238 TOTP, account lockout, tested in `test_auth.py` |
| **Incident Verification Workflow** | **Implemented (Real)** | Strict transition validation, history recording, tested in `test_incidents.py` |
| **Resource Allocation Concurrency** | **Implemented (Real)** | `SELECT FOR UPDATE` row-level locks, conflict rejection, tested in `test_dispatch.py` |
| **Hash-Chained Audit Trail** | **Implemented (Real)** | SHA-256 trigger chain, UPDATE/DELETE blocked, verified by `verify-audit` CLI |
| **Gujarat Boundary Geofencing** | **Implemented (Real)** | PostGIS `ST_Contains` spatial checks, RAM caching, Nominatim/Google fallback |
| **Team Recommendation Engine** | **Implemented (Real)** | PostGIS proximity sorting, capability scoring, tested in `test_recommendations.py` |
| **Internal Ingestion Runner** | **Implemented (Real)** | Advisory lock protected `/api/v1/internal/ingest/run` & cron workflow |
| **Advisory Text AI Triage** | **Implemented (Real), rules baseline** | `drch-ai-triage` `/triage` keyword rules behind backend guardrails (`app.services.ai_provider`); a trained scenario model plugs in through `TRIAGE_MODEL_DIR` once S2-05 delivers one |
| **English Crisis Text Model** | **Experimental / Optional** | Real-data event-held-out baseline trained in `models/text_model`, served by `ai-workers/service/text_analysis.py`; separate `/analyze-text` endpoint, not connected to ingestion |
| **Image Disaster Classifier** | **Prototype / Isolated** | PyTorch service in `models/image_classifier/deployment/app.py`, evaluated offline on split data; not deployed for this release, so photo analysis answers `503 AI_PHOTO_UNAVAILABLE` |
| **Citizen Photo Storage** | **Implemented (Real), database** | Bytes in PostgreSQL `evidence_blobs` (migration 11), metadata and moderation in `evidence_files`; Cloudinary is planned later (see "Photo storage" in section 8) |
| **Payment Gateway Integration** | **Simulated (Sandbox)** | Sandbox `MockGateway` only; live Razorpay/Stripe integration is planned |
| **External Alert & Signal Ingestion** | **Implemented (Real feeds) + Replay** | SACHET CAP adapters (`app/services/ingest/`) run on the scheduler and the `ingest-cron.yml` workflow; the Bluesky and GNEWS text sources remain opt-in (`BLUESKY_SEARCH_ENABLED`, `NEWS_RSS_ENABLED`); new social/news text is sent to the configured multilingual disaster classifier, bounded to 50 signals per run; fallback alerts stay labelled `is_fallback = TRUE` |
| **Simulated Demo Incidents** | **Simulated** | 4 seeded Gujarat demo incidents flagged with `is_simulated = TRUE` |

---

## 8. Deployment & Release Overview

```mermaid
flowchart LR
    Dev["Pull request"] --> CI["ci.yml<br/>lint, tests on postgis/postgis:16-3.4,<br/>gitleaks, bandit, audits, image scan"]
    CI -->|"merge to main (ruleset: Quality Gate green, branch up to date)"| CD["cd.yml"]
    CD --> GHCR[("GHCR images<br/>drch_backend, drch_frontend, drch_ai_workers<br/>tags: latest, sha-&lt;short&gt;")]
    CD -->|1. hook, sha image| Staging["Render staging<br/>drch-backend-latest"]
    Staging --> Smoke["scripts/smoke.py on staging<br/>(waits until the new GIT_SHA is live)"]
    Smoke -->|2. passes| Render["Render production<br/>it314-software-project-backend1 (FastAPI)"]
    CD -->|hook, sha image| AI["Render<br/>drch-ai-triage (advisory)"]
    CD -->|deploy hook| Vercel["Vercel<br/>Next.js frontend + BFF"]
    Render --> Neon[("Neon PostgreSQL 16 + PostGIS")]
    Cron["ingest-cron.yml<br/>every 15 min: wake + ingest"] --> Render
    Tag["git tag vX.Y.Z[-rcN]"] --> CDTag["cd.yml (tag build)"] --> GHCRv[("GHCR images tagged vX.Y.Z")]
```

| Concern | How it is handled | Reference |
|---|---|---|
| Hosting | Neon (database), Render free web services for the backend and the AI triage service (`render.yaml`), a separate Render staging backend `drch-backend-latest` (`https://drch-backend-latest.onrender.com`) next to the production backend `it314-software-project-backend1`, both defined in `render.yaml`, Vercel (frontend and the BFF proxies) | `render.yaml`, [release-runbook.md](../operations/release-runbook.md) §1 |
| Configuration and secrets | Every secret is entered by Siddh in the Render, Vercel and GitHub consoles; the repository lists names only | [env-variables.md](env-variables.md) |
| Migrations | Forward-only SQL files applied by `python -m app.migrate` (also at backend start-up) under an advisory lock; a Neon branch is taken before each release | [runbook-migration.md](../operations/runbook-migration.md) |
| Continuous deployment | `cd.yml` runs only on `main` or a release tag (a release tag must point at a commit on `main`); the `main` branch ruleset already requires a pull request with the `Pipeline Status / Quality Gate` check green and the branch up to date, so CD does not re-run CI. CD compares each commit with the last CD run that succeeded (not just its parent), so a run cancelled by a newer merge, or one that failed, does not lose its changes. Vercel starts without waiting for any image build, and each Render job waits only for its own image. A merge to `main` publishes the changed images: when the merged tree equals the pull request head, CD retags the image CI already built and scanned (`ci-<head sha>` to `latest` and `sha-<short>`) instead of rebuilding it, and falls back to a normal build otherwise. It then deploys the backend image for that commit to staging, waits for its `GIT_SHA` on `/api/v1/health` and runs the smoke test there. Production (Render) deploys only if that passes, then waits for the same `GIT_SHA`. Vercel and the AI triage service deploy by their own hooks. A deploy whose hook secret is missing is shown as skipped, not successful. A newer push cancels an older CD run | `.github/workflows/cd.yml` |
| Releases and rollback | A `vX.Y.Z` / `vX.Y.Z-rcN` tag builds all images from that commit with the version as the image tag; releases are deployed and rolled back by pointing Render at a version (or `sha-`) tag | [release-runbook.md](../operations/release-runbook.md) §2, §4 |
| Cold start | Render free instances sleep; `ingest-cron.yml` wakes the backend every 15 minutes; open `/api/v1/health` before a demo | [release-runbook.md](../operations/release-runbook.md) §1 |
| Fallback hosting | `docker-compose.prod.yml` runs the same images (PostGIS, backend, frontend, AI workers) on any Docker host; it needs an explicit `IMAGE_TAG` (a release or `sha-` tag, never `latest`), binds the app ports to localhost behind a TLS reverse proxy, and refuses to start when a required secret is missing | `docker-compose.prod.yml` |
| Photo storage | **Decision (14 Nov 2026): keep citizen photos in the database for this release.** Bytes live in `evidence_blobs` (at most 5 photos of 5 MB per report), so they are covered by the same Neon branch and `scripts/db_backup.py` backup as the rest of the data, deleted with the report or account, and served only through the authenticated citizen and moderator endpoints. No storage service, bucket or extra secret is needed on Render. **Later: Cloudinary.** When storage size or load makes it worth it, upload new photos to a private (authenticated) Cloudinary folder, record it in `evidence_files.storage_key` as `cloudinary:<public id>` (today every row is `db:<evidence id>`, so the prefix tells the two apart and both can be served during the move), serve them through short-lived signed URLs from the same endpoints, copy the existing `evidence_blobs` rows once, and only then drop the bytes. That change needs `CLOUDINARY_URL` on Render and an update to `docs/architecture/env-variables.md`; it is not started | `backend/app/routers/citizen.py`, `backend/app/routers/dm/moderation.py`, migration 11 |
| Backups | Neon branches before releases; `pg_dump` / `pg_restore` for a portable copy | [runbook-migration.md](../operations/runbook-migration.md) |
| Demo and rehearsal | Roles, script, on-stage fallbacks and rehearsal log | [demo-script.md](../project/demo-script.md) |
