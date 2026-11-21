# DRCH Sequence Diagrams

This document details the dynamic runtime interactions of the Disaster Response Coordination Hub (DRCH) for the State of Gujarat. The sequence diagrams trace the exact execution paths across the Next.js frontend, FastAPI routing layer, PostgreSQL/PostGIS persistence engine, in-process background consumers, and the advisory AI microservice.

### Source files used
- [citizen.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/routers/citizen.py) - Citizen report creation, location validation, and information-reply endpoints
- [internal.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/routers/internal.py) - Ingestion execution endpoint protected by session advisory locks
- [incidents.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/routers/dm/incidents.py) - Incident queue filtering, verification decisions, and closure
- [dispatches.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/routers/dm/dispatches.py) - Dispatch order creation, idempotent submission, and resource allocation
- [notes.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/routers/dm/notes.py) - Internal incident notes collaboration endpoint
- [field.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/routers/field.py) - Field team mission polling, acknowledgement, progress, and completion
- [auth.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/routers/auth.py) - Staff two-factor login, lockout counters, and citizen registration
- [security.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/security.py) - Argon2id hashing, RFC 6238 TOTP verification, and AES-GCM encryption
- [ingestion.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/services/ingestion.py) - Adapter execution, alert deduplication, and signal staging
- [ai_provider.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/services/ai_provider.py) - PII redaction, confidence checks, and guardrails
- [signal_matching.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/services/signal_matching.py) - Heuristic Jaccard and spatiotemporal signal clustering
- [duplicate_similarity.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/services/duplicate_similarity.py) - Trigram cosine similarity for incident deduplication
- [dispatch.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/services/dispatch.py) - Dispatch state transitions and automated background escalation
- [resources.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/services/resources.py) - Atomic row-level inventory reservations (`SELECT ... FOR UPDATE`)
- [geo.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/geo.py) - PostGIS Gujarat boundary containment checks
- [audit.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/app/audit.py) - Append-only SHA-256 hash-chained event logger
- [triage_service.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/ai-workers/triage_service.py) - Advisory AI FastAPI microservice
- [main.py](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/backend/main.py) - Lifespan background workers (`ai_workers_background_consumer`, `ingestion_background_worker`)
- [actions.ts](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/frontend/src/app/login/actions.ts) - Next.js server actions handling login and MFA handshake
- [page.tsx](file:///c:/Users/Dhruv/.gemini/antigravity-ide/scratch/IT314_Software_Project/frontend/src/app/field/page.tsx) - Frontline responder tactical interface and 15s auto-refresh polling

---

## 1. Sequence (a): Report Ingestion, Triage, Clustering, & Priority Scoring

This sequence shows an incoming emergency report passing through PostGIS boundary validation, PII redaction, advisory AI triage scoring, heuristic spatiotemporal clustering, and human dispatcher verification.

```mermaid
sequenceDiagram
    autonumber
    actor Citizen as Citizen / Ingest Source
    participant API as CitizenRouter / IngestionWorker
    participant Geo as GeoService (app.geo)
    participant AI as AiProvider (ai_provider.py)
    participant Triage as TriageService (ai-workers:8001)
    participant DB as Neon PostgreSQL (PostGIS)
    participant Matcher as SignalMatchingEngine
    actor Dispatcher as DM Dispatcher Console

    Citizen->>API: Submit Report (scenario, description, lat, lon)
    
    API->>Geo: is_in_gujarat(latitude, longitude)
    alt Point outside Gujarat boundary
        Geo-->>API: False
        API-->>Citizen: 422 OUT_OF_BOUNDS (Location must be within Gujarat)
    else Point within Gujarat boundary
        Geo-->>API: True
        API->>DB: INSERT INTO incidents (status=SUBMITTED, geom)
        DB-->>API: Return incident_id, incident_ref

        API->>AI: get_provider().triage(payload)
        Note over AI: scrub_pii removes emails, phone numbers, 12-digit IDs
        AI->>Triage: POST /triage (scrubbed text, scenario, urgency)
        
        alt AI Worker Unavailable or Timeout
            Triage-->>AI: HTTP Error or Timeout (10s)
            AI-->>API: TriageOutcome (status: UNAVAILABLE)
        else AI Worker Responds
            Triage-->>AI: 200 OK (model, scenario, priority, confidence, factors)
            Note over AI: apply_guardrails validates confidence >= 0.6 and schema
            alt Low confidence (<0.6) or unsupported scenario (OTHER)
                AI-->>API: TriageOutcome (status: LOW_CONFIDENCE, suggested_scenario: None)
            else Valid confidence and supported scenario
                AI-->>API: TriageOutcome (status: GENERATED, suggested_priority)
            end
        end

        API->>DB: INSERT INTO ai_recommendations (status, suggested_priority)
        API-->>Citizen: 201 Created (incident_id, incident_ref, status: SUBMITTED)

        Note over Matcher, DB: Background Clustering / Duplicate Analysis
        Dispatcher->>API: GET /api/v1/dm/incidents/:id/duplicates
        API->>Matcher: score_candidates(incident, candidate_rows)
        Matcher-->>API: Ranked candidate pairs (trigram cosine + distance + time)
        API-->>Dispatcher: Candidate duplicates with similarity explanation

        Dispatcher->>API: PATCH /api/v1/dm/incidents/:id (status: VERIFIED, priority: HIGH, rationale)
        API->>DB: UPDATE incidents SET status=VERIFIED, verified_priority=HIGH, version=version+1
        API->>DB: INSERT INTO incident_status_history (SUBMITTED -> VERIFIED)
        API->>DB: INSERT INTO audit_logs (action: INCIDENT_VERIFIED, hash_chain)
        API-->>Dispatcher: 200 OK (verified incident)
    end
```

This sequence captures the core ingestion pipeline. Coordinates are verified via PostGIS containment queries before database insertion. Before forwarding text to the advisory triage microservice (`ai-workers:8001`), the backend scrubs reporter PII. The model suggestion is validated by backend guardrails; confidence values below 0.6 or unsupported scenarios are flagged as `LOW_CONFIDENCE` and routed for manual inspection. A human dispatcher examines heuristic duplicate and related-signal scores before assigning an operational priority (`CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`) and recording the verification in the audit trail.

---

## 2. Sequence (b): Dispatcher Assigns Unit & Field Team Lifecycle (HTTP Polling)

This sequence illustrates dispatch order creation, row-level concurrency locking on inventory resources, frontline field responder updates via 15-second polling, operational progress milestones, and automated escalation upon acknowledgement timeout.

```mermaid
sequenceDiagram
    autonumber
    actor Dispatcher as DM Dispatcher Console
    participant DispRouter as DispatchesRouter (dm/dispatches.py)
    participant DispService as DispatchService (services/dispatch.py)
    participant ResService as ResourceService (services/resources.py)
    participant DB as Neon PostgreSQL
    participant Audit as AuditService (app.audit)
    participant Consumer as In-Process Worker (backend/main.py)
    participant FieldRouter as FieldRouter (routers/field.py)
    actor Responder as Field Responder (Mobile PWA)

    Dispatcher->>DispRouter: POST /api/v1/dm/incidents/:id/dispatches (resources, agency, instructions)
    DispRouter->>DispService: create_dispatch(conn, incident_id, resources)
    
    DispService->>DB: Lock incident row (SELECT FOR UPDATE)
    Note over ResService, DB: Concurrency Protection (Row-Level Locking)
    loop For each requested resource (sorted by ID to prevent deadlocks)
        ResService->>DB: Lock resource row (SELECT FOR UPDATE)
        alt Available quantity < Requested quantity
            DB-->>ResService: Insufficient quantity
            ResService-->>DispRouter: Raise 409 RESOURCE_CONFLICT
            DispRouter-->>Dispatcher: 409 Conflict (no partial allocation)
        else Sufficient quantity available
            ResService->>DB: Decrement available stock and bump version
            ResService->>DB: INSERT INTO resource_assignments (dispatch_id, resource_id, quantity)
        end
    end

    DispService->>DB: INSERT INTO dispatch_orders (status: REQUESTED, dispatch_ref)
    DispService->>DB: INSERT INTO agency_messages (status: QUEUED, recipient_agency_id)
    DispService->>Audit: record(action: DISPATCH_CREATED, actor: Dispatcher)
    DispRouter-->>Dispatcher: 201 Created (dispatch_ref, status: REQUESTED)

    Note over Responder, FieldRouter: Field Client Polling (SRS Requirement S2-04: 15s interval)
    loop Every 15 seconds
        Responder->>FieldRouter: GET /api/v1/field/assignments?active=true
        FieldRouter->>DB: SELECT dispatches assigned to responder team
        DB-->>FieldRouter: Active dispatches (status: REQUESTED)
        FieldRouter-->>Responder: 200 OK (Assignment list)
    end

    alt Case 1: Timeout Exceeded (No Acknowledgement within timeout)
        Consumer->>DispService: escalate_overdue (runs every 60s in background)
        DispService->>DB: Find overdue orders (FOR UPDATE SKIP LOCKED)
        DispService->>Audit: record(action: DISPATCH_ESCALATED, rationale: No acknowledgement)
        DispService->>DB: INSERT INTO notifications (event_code: DISPATCH_ESCALATED, role: SUPERVISOR)
    else Case 2: Responder Acknowledges in Time
        Responder->>FieldRouter: POST /api/v1/field/dispatches/:id/acknowledgement
        FieldRouter->>DispService: apply_acknowledgement(conn, dispatch_id)
        DispService->>DB: UPDATE dispatch_orders SET status=ACKNOWLEDGED, acknowledged_at=now()
        DispService->>DB: UPDATE agency_messages SET status=ACKNOWLEDGED WHERE dispatch_id=id
        DispService->>Audit: record(action: DISPATCH_ACKNOWLEDGED)
        FieldRouter-->>Responder: 200 OK (status: ACKNOWLEDGED)

        Responder->>FieldRouter: POST /api/v1/field/dispatches/:id/progress (status: EN_ROUTE)
        FieldRouter->>DispService: apply_progress(conn, event: EN_ROUTE)
        DispService->>DB: UPDATE dispatch_orders SET status=DISPATCHED
        DispService->>DB: UPDATE incidents SET status=DISPATCHED WHERE status=VERIFIED
        DispService->>Audit: record(action: DISPATCH_EN_ROUTE)
        FieldRouter-->>Responder: 200 OK (status: DISPATCHED)

        Responder->>FieldRouter: POST /api/v1/field/dispatches/:id/progress (status: ON_SCENE)
        FieldRouter->>DB: INSERT INTO dispatch_progress (status: ON_SCENE)
        FieldRouter-->>Responder: 200 OK

        Responder->>FieldRouter: POST /api/v1/field/dispatches/:id/completion (summary, evacuated, treated)
        FieldRouter->>DispService: apply_completion(conn, dispatch_id)
        DispService->>DB: UPDATE dispatch_orders SET status=COMPLETED
        DispService->>ResService: release_all_for_dispatch(dispatch_id)
        ResService->>DB: UPDATE resources SET quantity_available = available + qty
        DispService->>Audit: record(action: DISPATCH_COMPLETED)
        FieldRouter-->>Responder: 200 OK (status: COMPLETED, resources released)
    end
```

This sequence models the dispatch transaction and unit coordination flow. When a dispatcher assigns a resource, the system locks inventory rows (`SELECT ... FOR UPDATE`) in deterministic order to prevent race conditions and deadlocks. The frontend field client polls the assignment endpoint every 15 seconds. If the team acknowledges within the timeout, they advance their deployment through `EN_ROUTE` and `ON_SCENE` milestones before submitting a mission completion report that automatically returns reserved resources to inventory. If an assignment remains unacknowledged, an in-process background consumer automatically triggers an escalation event, notifying supervisors without human intervention.

---

## 3. Sequence (c): Staff & Citizen Authentication Flow (Argon2id + TOTP MFA)

This sequence traces the authentication handshake for staff members requiring two-factor authentication versus citizens utilizing single-factor access, detailing failed attempt tracking, automated account lockouts, and cryptographic token issuance.

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser / Client
    participant BFF as Next.js Server Action (actions.ts)
    participant AuthAPI as AuthRouter (routers/auth.py)
    participant Security as SecurityModule (app.security)
    participant DB as Neon PostgreSQL (users, user_auth)
    participant Audit as AuditService (app.audit)

    User->>BFF: Submit email and password
    BFF->>AuthAPI: POST /api/v1/auth/login (email, password)
    AuthAPI->>DB: Load account and user_auth (FOR UPDATE)

    alt Account locked (locked_until > now()) or disabled
        DB-->>AuthAPI: Account is locked or disabled
        AuthAPI-->>BFF: 401 INVALID_CREDENTIALS (Invalid credentials or unavailable)
        BFF-->>User: Show generic error message
    else Account active and unlocked
        AuthAPI->>Security: verify_password(stored_hash, password) using Argon2id
        alt Password does not match
            Security-->>AuthAPI: False
            AuthAPI->>DB: UPDATE user_auth SET failed_login_count = failed_login_count + 1
            alt failed_login_count >= 5
                AuthAPI->>DB: Lock account for 15m and increment token_version
                AuthAPI->>Audit: record(action: LOGIN_FAILED, rationale: Account locked after 5 failures)
            else failed_login_count < 5
                AuthAPI->>Audit: record(action: LOGIN_FAILED, rationale: wrong password)
            end
            AuthAPI-->>BFF: 401 INVALID_CREDENTIALS
            BFF-->>User: Show invalid credentials error
        else Password matches
            Security-->>AuthAPI: True
            alt Role is Citizen (NORMAL_USER)
                AuthAPI->>DB: Reset failure counter and update last_login_at
                AuthAPI->>Security: issue_token(user_id, token_version, typ: access, mfa: false)
                AuthAPI->>Audit: record(action: LOGIN_SUCCEEDED, rationale: password)
                AuthAPI-->>BFF: 200 OK (access_token, role: NORMAL_USER, mfa_required: false)
                BFF->>User: Set httpOnly session cookies and redirect to /citizen/dashboard
            else Role is Staff (DISASTER_MGMT, FIELD_TEAM, APP_MGMT)
                Note over AuthAPI: Mandatory Staff MFA Challenge (RFC 6238)
                AuthAPI->>Security: issue_token(user_id, token_version, typ: mfa, 5 mins)
                AuthAPI-->>BFF: 200 OK (mfa_required: true, mfa_token)
                BFF-->>User: Set short-lived mfa cookie and prompt for 6-digit TOTP code

                User->>BFF: Submit 6-digit TOTP code
                BFF->>AuthAPI: POST /api/v1/auth/mfa/verify (mfa_token, code)
                AuthAPI->>Security: decode_token(mfa_token, typ: mfa)
                AuthAPI->>DB: Load user_auth by user_id (FOR UPDATE)
                AuthAPI->>Security: decrypt_mfa_secret(stored_secret) via AES-GCM
                AuthAPI->>Security: verify_totp(secret, code)

                alt Code invalid or expired
                    Security-->>AuthAPI: False
                    AuthAPI->>DB: UPDATE user_auth SET failed_login_count = failed_login_count + 1
                    AuthAPI->>Audit: record(action: LOGIN_FAILED, rationale: wrong MFA code)
                    AuthAPI-->>BFF: 401 MFA_INVALID (Verification code invalid)
                    BFF-->>User: Show invalid verification code error
                else Code valid
                    Security-->>AuthAPI: True
                    AuthAPI->>DB: Reset failure counter and update last_login_at
                    AuthAPI->>Security: issue_token(user_id, token_version, typ: access, mfa: true)
                    AuthAPI->>DB: INSERT INTO refresh_tokens (token_hash, family_id)
                    AuthAPI->>Audit: record(action: LOGIN_SUCCEEDED, rationale: password + TOTP)
                    AuthAPI-->>BFF: 200 OK (access_token, refresh_token, role, user)
                    BFF->>User: Set httpOnly session and refresh cookies and redirect to workspace
                end
            end
        end
    end
```

This sequence specifies user authentication. Citizen accounts authenticate with passwords and receive access tokens directly. Staff accounts enforce a two-stage verification: password validation via Argon2id followed by an RFC 6238 TOTP verification using an AES-GCM encrypted secret. The system tracks consecutive login failures; five failed attempts trigger an automated 15-minute account lockout and an increment to `token_version`, which immediately invalidates all active sessions. Successful authentication yields a signed JWT access token and a rotating refresh session stored in HTTP-only cookies.

---

## 4. Sequence (d): Incident Collaboration & Notes Log Flow

This sequence models the internal communication mechanisms within DRCH: (1) the append-only dispatcher incident notes log used for shift handovers, and (2) the asynchronous two-way information request and reply flow between dispatchers and citizens.

```mermaid
sequenceDiagram
    autonumber
    actor Dispatcher as DM Dispatcher
    actor Citizen as Citizen Reporter
    participant CitizenAPI as CitizenRouter (routers/citizen.py)
    participant DMAPI as IncidentsRouter (dm/incidents.py)
    participant NotesAPI as NotesRouter (dm/notes.py)
    participant DB as Neon PostgreSQL
    participant Audit as AuditService (app.audit)

    Note over Dispatcher, NotesAPI: Flow 1: Dispatch Team Internal Notes (Append-Only Shift Log)
    Dispatcher->>NotesAPI: POST /api/v1/dm/incidents/:id/notes (body: Road flooded, advised team to use bypass)
    Note over NotesAPI: Rate Limit: 60 notes per hour
    NotesAPI->>DB: SELECT 1 FROM incidents WHERE incident_id = id
    NotesAPI->>DB: INSERT INTO incident_notes (incident_id, author_id, body)
    NotesAPI->>Audit: record(action: INCIDENT_NOTE_ADDED, entity_id: incident_id)
    NotesAPI-->>Dispatcher: 201 Created (note_id, author_name, created_at, mine: true)

    Dispatcher->>NotesAPI: GET /api/v1/dm/incidents/:id/notes
    NotesAPI->>DB: SELECT notes FROM incident_notes WHERE incident_id = id ORDER BY created_at DESC
    DB-->>NotesAPI: List of shift notes
    NotesAPI-->>Dispatcher: 200 OK (Shared chronological shift log)

    Note over Dispatcher, Citizen: Flow 2: Dispatcher-Citizen Information Clarification Protocol
    Dispatcher->>DMAPI: PATCH /api/v1/dm/incidents/:id (status: NEEDS_INFORMATION, rationale: Specify water depth)
    DMAPI->>DB: Lock incident row (SELECT FOR UPDATE)
    DMAPI->>DB: UPDATE incidents SET status=NEEDS_INFORMATION, version=version+1
    DMAPI->>DB: INSERT INTO incident_status_history (SUBMITTED -> NEEDS_INFORMATION)
    DMAPI->>Audit: record(action: INCIDENT_NEEDS_INFO, rationale: Specify water depth)
    DMAPI-->>Dispatcher: 200 OK (status: NEEDS_INFORMATION)

    Citizen->>CitizenAPI: GET /api/v1/me/incidents/:id
    CitizenAPI->>DB: Query incident scoped to reporter_id
    DB-->>CitizenAPI: Incident record with timeline
    CitizenAPI-->>Citizen: 200 OK (status: More information requested, rationale: Specify water depth)

    Citizen->>CitizenAPI: POST /api/v1/me/incidents/:id/information-response (message: Water depth is roughly 4 feet near market)
    Note over CitizenAPI: Rate Limit: 20 responses per hour
    CitizenAPI->>DB: Check incident status (SELECT FOR UPDATE)
    alt Incident status is not NEEDS_INFORMATION
        CitizenAPI-->>Citizen: 409 NOT_AWAITING_INFORMATION (No information requested)
    else Incident status is NEEDS_INFORMATION
        CitizenAPI->>DB: UPDATE incidents SET status=SUBMITTED, version=version+1
        CitizenAPI->>DB: INSERT INTO incident_status_history (NEEDS_INFORMATION -> SUBMITTED)
        CitizenAPI->>Audit: record(action: INFORMATION_PROVIDED, rationale: Reporter replied)
        CitizenAPI-->>Citizen: 200 OK (status: SUBMITTED, updated timeline)
    end
```

This sequence illustrates collaborative incident communication. Instead of unauthenticated free-text chat rooms, DRCH supports two formal, audit-logged mechanisms. First, dispatchers utilize `incident_notes` as an immutable shift log where notes cannot be edited or deleted, ensuring reliable handovers between disaster management shifts. Second, when additional field intelligence is required, dispatchers transition an incident to `NEEDS_INFORMATION`. The citizen receives the request on their report timeline and submits an `InformationReply` via `/information-response`, which automatically returns the incident to `SUBMITTED` for immediate re-evaluation.
