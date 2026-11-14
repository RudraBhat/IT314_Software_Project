# 📑 ResQ — API Contracts Specification

**Lead & Integration Architect:** Siddh (@Siddhcreator-1706)  
**Standard Error Format:** Standardized according to SRS s.15.7 and `app.errors`:
```json
{
  "error": {
    "code": "STRING_ERROR_CODE",
    "message": "Human readable explanation",
    "details": null
  }
}
```

---

## 1. Public Data Endpoints (Owner: Nisarg)

### 1.1 Verified Public Incidents
* **Path:** `GET /api/v1/public/incidents`
* **Auth:** None (Public)
* **Query Parameters:**
  * `district` *(optional string)*: Filter by Gujarat district (e.g. `Ahmedabad`, `Surat`)
  * `scenario` *(optional string)*: `cyclone`, `industrial_fire`, `urban_flooding`
  * `bbox` *(optional string)*: `min_lon,min_lat,max_lon,max_lat`
* **Response (200 OK):**
```json
[
  {
    "reference": "INC-GUJ-2026-001",
    "scenario": "urban_flooding",
    "district": "Ahmedabad",
    "status": "VERIFIED",
    "verified_priority": "HIGH",
    "verified_at": "2026-10-24T14:30:00Z",
    "latitude": 23.0478,
    "longitude": 72.5694
  }
]
```
* **Security & Privacy Rules:**
  * Only incidents with status in `('VERIFIED', 'DISPATCHED', 'RESOLVED')` and `verified_by IS NOT NULL` are returned.
  * No reporter identity, citizen contact info, or raw free-text fields are exposed.
  * Coordinates are rounded to 4 decimal places (~11 meters).
* **Errors:**
  * `422 VALIDATION_FAILED`: Invalid bounding box or parameter format.

### 1.2 Public Active Campaigns
* **Path:** `GET /api/v1/public/campaigns`
* **Auth:** None (Public)
* **Response (200 OK):**
```json
[
  {
    "campaign_id": "c0000000-0000-0000-0000-000000000001",
    "title": "Gujarat Urban Flood Relief & Rehabilitation Fund 2026",
    "purpose": "Emergency relief and supply distribution across flood affected zones.",
    "scenario": "urban_flooding",
    "target_amount": 5000000.00,
    "currency": "INR",
    "status": "ACTIVE"
  }
]
```

### 1.3 Public Early Warnings & External Alerts
* **Path:** `GET /api/v1/public/alerts`
* **Auth:** None (Public)
* **Response (200 OK):**
```json
[
  {
    "alert_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "source": "IMD",
    "event_type": "CYCLONE",
    "severity": "HIGH",
    "area_text": "Kutch Border Region",
    "is_fallback": false,
    "effective_at": "2026-10-24T12:00:00Z",
    "expires_at": "2026-10-25T12:00:00Z"
  }
]
```

### 1.4 Published Safety Guidance & Public Updates (NU-FR-08)
* **Paths:** `GET /api/v1/public/safety-content` and `GET /api/v1/public/updates`. No authentication. Optional `scenario` filter (`cyclone`, `industrial_fire`, `urban_flooding`; anything else is `422`).
* **safety-content:** only guidance a publisher has published. Fields: `content_id`, `scenario`, `title`, `body`, `source`, `version`, `published_at`. Drafts, approved-but-unpublished and superseded versions are never returned.
* **updates:** only published broadcast updates. Fields: `update_id`, `scenario`, `title`, `body`, `area_label`, `published_at`; newest first, at most 50.
* **Privacy:** no author or approver names, no linked incident, no internal notes. The `/safety` page shows these above its general guidance and falls back to the general guidance when the service is unreachable.

---

## 2. Citizen Authentication & Reporting API (Owner: Zalak)

### 2.1 Citizen Registration
* **Path:** `POST /api/v1/auth/register` (alias: `POST /api/v1/auth/signup`)
* **Auth:** None (Public)
* **Rate limit:** 10 requests per hour per client IP (`429 RATE_LIMITED`).
* **Request Headers:** `Content-Type: application/json`
* **Request Body:**
```json
{
  "email": "citizen@example.in",
  "password": "StrongPassword123!",
  "full_name": "Ramesh Patel",
  "phone": "+919876543210",
  "preferred_language": "gu"
}
```
* **Response (201 Created):** the account fields below plus the sign-in fields of 2.2 (`access_token`, `expires_in`, `user`, …), so the client can start a session immediately.
```json
{
  "user_id": "7a35eb42-6362-47d3-8e41-0f7300c14b43",
  "email": "citizen@example.in",
  "full_name": "Ramesh Patel",
  "role": "NORMAL_USER",
  "status": "ACTIVE",
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600
}
```
* **Errors:**
  * `409 DUPLICATE_EMAIL`: Email already exists (`{"error": {"code": "DUPLICATE_EMAIL", "message": "An account with this email already exists."}}`).
  * `422 WEAK_PASSWORD`: Password does not meet security policy (minimum 8 chars, 1 digit, 1 special symbol).
  * `429 RATE_LIMITED`: Rate limit exceeded on registration attempts.

### 2.2 Sign In (citizens and staff)
* **Path:** `POST /api/v1/auth/login`
* **Auth:** None (Public)
* **Rate limit:** 20 requests per 5 minutes per client IP.
* **Request Body:**
```json
{
  "email": "citizen@example.in",
  "password": "StrongPassword123!"
}
```
* **Response (200 OK), citizen** — citizens do not use MFA, so the token is issued immediately:
```json
{
  "mfa_required": false,
  "access_token": "eyJhbGciOi...",
  "token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600,
  "role": "NORMAL_USER",
  "user": {
    "id": "7a35eb42-6362-47d3-8e41-0f7300c14b43",
    "email": "citizen@example.in",
    "name": "Ramesh Patel",
    "role": "NORMAL_USER"
  }
}
```
* **Response (200 OK), staff** (`DISASTER_MGMT`, `FIELD_TEAM`, `APP_MGMT`): `{"mfa_required": true, "mfa_token": "eyJ..."}`. The client then calls `POST /api/v1/auth/mfa/verify` with `{"mfa_token", "code"}` (6-digit TOTP; 20 requests per 5 minutes) and receives the citizen-shaped response above with `"mfa_required": false`. The `mfa_token` is valid for `MFA_TOKEN_MINUTES` (default 5).
* **Lifetimes:** access tokens last `ACCESS_TOKEN_MINUTES` (default 60; `expires_in` is in seconds). Repeated failures lock the account for `LOGIN_LOCKOUT_MINUTES` (default 15).
* **Errors:**
  * `401 INVALID_CREDENTIALS`: wrong email or password, locked or disabled account (one generic message, so account existence is not revealed).
  * `403 ACCOUNT_NOT_SETUP`: an invited account has not finished setup; use the emailed invitation link (9.2).
  * `403 MFA_NOT_ENROLLED`: a staff account has no authenticator enrolled.
  * `401 MFA_CHALLENGE_INVALID` / `401 MFA_INVALID` (MFA step): the challenge expired / the code is wrong.
  * `429 RATE_LIMITED`.
* **Password reset, invitations and Google sign-in:** see section 9. Replacing a password increments the user's `token_version`, which revokes every session issued before.

### 2.3 Submit Incident Report
* **Path:** `POST /api/v1/incidents`
* **Auth:** Bearer Token (`require_citizen`)
* **Headers:**
  * `Authorization: Bearer <token>`
  * `Idempotency-Key: <unique-uuid-or-client-key>` — **required** (max 100 characters). Generate one key per report draft and reuse it on every retry of that draft.
* **Request Body:**
```json
{
  "scenario": "urban_flooding",
  "description": "Severe waterlogging on main market road, water entered shops.",
  "reported_urgency": "HIGH",
  "people_affected": 15,
  "location_source": "GPS",
  "latitude": 23.0225,
  "longitude": 72.5714,
  "address_text": "Near Usmanpura Underpass",
  "landmark": "Opposite Jain Temple"
}
```
* **Response (201 Created):**
```json
{
  "incident_id": "3c0b05b3-3a1e-450e-a226-bcfe69d0d939",
  "incident_ref": "INC-2026-000104",
  "status": "SUBMITTED",
  "district": "Ahmedabad",
  "created_at": "2026-10-24T15:00:00Z"
}
```
* **Validation & Security:**
  * Rejects locations outside Gujarat state boundaries with `422 OUTSIDE_GUJARAT`.
  * A missing or blank `Idempotency-Key` is rejected with `422 IDEMPOTENCY_KEY_REQUIRED` (same rule as `POST /api/v1/donations`); nothing is created.
  * Idempotent: a repeated call with the same `Idempotency-Key` returns `200 OK` with the same incident body instead of creating a duplicate.

### 2.4 My Incidents Listing & Timeline
* **Path:** `GET /api/v1/me/incidents`
* **Auth:** Bearer Token (`require_citizen`)
* **Path:** `GET /api/v1/me/incidents/{id}`
* **Auth:** Bearer Token (`require_citizen`)
* **Response (200 OK):**
```json
{
  "incident_id": "3c0b05b3-3a1e-450e-a226-bcfe69d0d939",
  "incident_ref": "INC-2026-000104",
  "scenario": "urban_flooding",
  "status": "VERIFIED",
  "timeline": [
    {
      "status": "SUBMITTED",
      "timestamp": "2026-10-24T15:00:00Z"
    },
    {
      "status": "VERIFIED",
      "timestamp": "2026-10-24T15:12:00Z"
    }
  ]
}
```
* **Isolation Rule:** Attempting to access another citizen's incident returns `404 NOT_FOUND` (no existence leak). Internal dispatcher notes and rationale are stripped.
* **Readable labels:** the incident has `status_label` and every timeline entry has `label` (for example "Report submitted", "More information requested"); clients show these instead of raw status codes.

### 2.5 Information Response
* **Path:** `POST /api/v1/me/incidents/{id}/information-response` (the earlier `/information` path still works)
* **Auth:** Bearer Token (`require_citizen`); own incident only (others return `404`)
* **When:** the incident is `NEEDS_INFORMATION` (a dispatcher asked with `POST /api/v1/dm/incidents/{id}/information-requests`). The question appears in the incident `timeline` (2.4) as the `message` of the `NEEDS_INFORMATION` entry.
* **Request Body:** `message` (3-2000 characters) and/or a corrected `latitude` + `longitude` (given together, with optional `address_text`); at least one is required.
```json
{ "message": "It is next to the Jain temple, water is waist deep." }
```
* **Response (201 Created):** `{"incident_id": "...", "status": "SUBMITTED", "status_label": "Report submitted"}`; the incident returns to `SUBMITTED` so it re-enters the verification queue. The reply is stored in the status history as `Reporter reply: <message>` (and "Reporter corrected the location" when a point is sent), visible to dispatchers, and an audit entry is written.
* **Errors:** `404 NOT_FOUND` (not your incident); `409 NOT_AWAITING_INFORMATION` unless the incident is in `NEEDS_INFORMATION`; `422 VALIDATION_FAILED` (bad message length or coordinates); `422 OUTSIDE_GUJARAT` for a corrected point outside Gujarat; `429 RATE_LIMITED` (the response does not state the limit).

---

### 2.6 Photo Attachments (NU-FR-05)
* **Upload:** `POST /api/v1/me/incidents/{id}/attachments`, citizen only, own open incident. The photo is the raw request body with `Content-Type: image/jpeg|image/png|image/webp` and an optional percent-encoded `X-Filename`. Returns `201` with `{evidence_id, file_name, mime_type, size_bytes, status, uploaded_at}`; the same photo again returns `200` with the first.
* **List / download / remove:** `GET .../attachments` (`{items, max_attachments}`), `GET .../attachments/{evidence_id}` (the image, `nosniff`, not cached), `DELETE .../attachments/{evidence_id}` (deletes the file and keeps an audit record).
* **Limits:** 5 MB per photo, 5 photos per report. The type is checked from the file's bytes, not the header. `status` is `Awaiting review` until a moderator decides (`Approved`, `Held for review`); removed photos are not listed.
* **Errors:** `413 FILE_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE` / `INVALID_IMAGE`, `409 TOO_MANY_ATTACHMENTS` / `INCIDENT_CLOSED`, `404` for anyone else's report or photo, `429 RATE_LIMITED`.
* **Storage:** bytes live in `evidence_blobs` (migration 11); metadata and moderation state stay in `evidence_files`, so photos appear in the moderation queue (`GET /api/v1/dm/moderation/queue`), where a moderator opens the image with `GET /api/v1/dm/moderation/{evidence_id}/content` (`MODERATOR` permission, audited). A photo is never shown publicly before a moderator approves it.

### 2.7 Account: Profile, Password, Notifications
* **Profile:** `GET /api/v1/me/profile` returns `{user_id, email, full_name, phone, preferred_language, alerts: {in_app, email, sms}, created_at, has_password}`; `has_password` is `false` for a Google sign-in account that never set one. `PATCH /api/v1/me/profile` accepts any of `full_name`, `phone`, `preferred_language` (`en`, `hi`, `gu`), `email_alerts`, `sms_alerts`. The email is the sign-in identity and is not editable; in-app notifications cannot be turned off; email and SMS are stored preferences only. Invalid values return `422`; changes are audited.
* **Password:** `POST /api/v1/me/password` with `{current_password, new_password}`. The new password follows the registration policy and must differ from the current one (`422 WEAK_PASSWORD` / `PASSWORD_UNCHANGED`); a wrong current password is `400 INVALID_CURRENT_PASSWORD` and is audited. An account with no password (Google sign-in only) gets `409 NO_PASSWORD_SET` and sets one through `POST /api/v1/auth/forgot-password` first. On success every session, including this one, is ended and the response is `{"changed": true, "sign_in_required": true}`. Rate limited.
* **Notifications:** `POST /api/v1/me/notifications/read-all` marks all of your in-app notifications read and returns `{"marked_read": n}`.
* **Email copy:** a citizen with email alerts on is also emailed each in-app notification (sent in the background, never blocks the action; simulated and logged when no SMTP is configured). SMS is only a stored preference; there is no SMS provider.
* **Withdraw request:** `POST /api/v1/me/incidents/{id}/withdrawal-request` with optional `{reason}`. Allowed for your own report while `SUBMITTED`, `NEEDS_INFORMATION` or `VERIFIED`; it only records the request (history row and audit entry, `withdrawal_requested: true` on the report) and never changes the status, because a dispatcher decides. `409 NOT_WITHDRAWABLE` after dispatch or closure, `409 ALREADY_REQUESTED`, `404` for another citizen's report. Rate limited.
* **Delete account:** `POST /api/v1/me/account/deletion` with `{password}`. Refused with `409 OPEN_REPORTS` while any report is not `RESOLVED`, `CLOSED` or `REJECTED`; a wrong password is `400 INVALID_CURRENT_PASSWORD` and audited; an account with no password gets `409 NO_PASSWORD_SET`, as above. On success the name, email, phone and address are erased, photos and notifications deleted, the account disabled and every session ended (`{"deleted": true, "sign_in_required": true}`). Reports stay on record for the audit trail without a link to an identity. Rate limited.

---

## 3. Field Team Responder API (Owner: Nisarg)

> [!NOTE]
> This section is a high-level summary stub retained for Sprint 1 traceability. For the complete, production-grade Sprint 2 API specification — including full request/response contracts, state transition rules, idempotency, isolation guarantees, and error codes — refer to **[Section 5: Field Operations API](#5-field-operations-api)**.

| Endpoint | Path | Method |
| :--- | :--- | :--- |
| Responder profile | `/api/v1/field/me` | `GET` |
| Active assignments | `/api/v1/field/assignments` | `GET` |
| Acknowledge dispatch | `/api/v1/field/dispatches/{id}/acknowledgement` | `POST` |
| Reject dispatch | `/api/v1/field/dispatches/{id}/rejection` | `POST` |
| Report progress | `/api/v1/field/dispatches/{id}/progress` | `POST` |
| Request backup team | `/api/v1/field/dispatches/{id}/team-requests` | `POST` |
| Complete mission | `/api/v1/field/dispatches/{id}/completion` | `POST` |

*(All routes require `Authorization: Bearer <token>` with `FIELD_TEAM` role. See Section 5 for full contracts.)*

---

## 4. Ingestion & Signal Promotion API (Owners: Rudra & Shlok)

### 4.1 Ingestion Trigger Endpoint
* **Path:** `POST /api/v1/internal/ingest/run`
* **Auth:** Header `X-Ingest-Token` or `Authorization: Bearer <INGEST_TOKEN>`
* **Query Parameters:** `source` *(optional string: `USGS`, `SACHET`, `REPLAY`, `GNEWS`, `BLUESKY`, `ALL`)*
* **Response (200 OK):** a single run for a named source; an array of per-source runs for `ALL`.
```json
{
  "run_id": "e2f0980c-61cb-4bc1-90a8-bcf6b45a6c02",
  "source": "USGS",
  "items_fetched": 4,
  "items_stored": 2,
  "status": "SUCCESS"
}
```

The backend scheduler runs configured sources every 10 minutes. `POST /api/v1/dm/ingestion/poll` starts an immediate poll for staff with `DISPATCH` or `SUPERVISOR`; `GET /api/v1/dm/ingestion/health` returns each source's latest run, 24-hour counts and latest error. Both require an MFA-verified staff session. `REPLAY` rows are always marked simulated; `GNEWS` and `BLUESKY` are live text sources, off unless `NEWS_RSS_ENABLED` / `BLUESKY_SEARCH_ENABLED` is set, and their rows are marked not simulated; the public alerts API returns only unexpired SACHET, USGS, GDACS or IMD alerts and includes the source and fallback flag.

### 4.2 Raw Signals Queue (DM Workspace)
* **Path:** `GET /api/v1/dm/signals`
* **Auth:** Staff Session (`DISASTER_MGMT`)
* **Query Parameters:** `status` (`PENDING`, `PROMOTED`, `DISMISSED`)
* **Response (200 OK):**
```json
[
  {
    "signal_id": "4b684531-ec7b-40eb-bdff-6e94f1be9eb6",
    "source": "MASTODON",
    "content_text": "Water rising rapidly near Ashram Road underpass. Cars floating!",
    "language": "en",
    "ai_label": "URBAN_FLOODING",
    "ai_confidence": 0.88,
    "status": "PENDING",
    "latitude": 23.0450,
    "longitude": 72.5680,
    "created_at": "2026-10-24T14:20:00Z"
  }
]
```

### 4.3 Signal Promotion to Incident
* **Path:** `POST /api/v1/dm/signals/{id}/promote`
* **Auth:** Staff Session (`DISASTER_MGMT` with `PUBLISHER` or `SUPERVISOR`)
* **Response (201 Created):**
```json
{
  "signal_id": "4b684531-ec7b-40eb-bdff-6e94f1be9eb6",
  "status": "PROMOTED",
  "incident_ref": "INC-2026-000105",
  "incident_status": "SUBMITTED"
}
```
*(Promoted incidents start as `SUBMITTED` and are NOT publicly visible until verified by a dispatcher).*

### 4.4 Related Signal Suggestions (advisory)
* **Path:** `GET /api/v1/dm/signals/related`
* **Auth:** Staff Session (`DISASTER_MGMT`)
* **Query Parameters:** `signal_id` *(optional UUID)*, `limit` *(1-500, default 100)*
* **Response (200 OK):** `{ method: "heuristic", advisory: true, requires_human_review: true, rules, pairs[], pairs_total, groups[], unlocated[], unlocated_total, truncated }`. Each pair has `signal_a`, `signal_b`, `distance_m`, `minutes_apart`, `label_agreement`, `ranking_score` (0-100 sort hint, not a probability), `reasons[]`, `warnings[]`.
* Read-only: it never promotes, dismisses, merges or dispatches. Full rules, thresholds, example and limitations: [signal-matching.md](signal-matching.md).

---

## 5. Field Operations API

> [!IMPORTANT]
> All field endpoints require `Authorization: Bearer <token>` issued to a `FIELD_TEAM` role user. Field users do **not** require TOTP MFA — password authentication only. Every dispatch-specific route enforces strict cross-team isolation: requesting another team's dispatch returns `404 NOT_FOUND` (never `403`) to eliminate enumeration attacks.

### 5.1 Field Responder Profile

* **Path:** `GET /api/v1/field/me`
* **Auth:** Bearer Token (`FIELD_TEAM` role)
* **Response (200 OK):**
```json
{
  "user_id": "a1b2c3d4-0000-0000-0000-000000000001",
  "email": "responder@ndrf.gov.in",
  "full_name": "Arjun Mehta",
  "phone": "+919876543210",
  "role": "FIELD_TEAM",
  "callsign": "NDRF-602-A",
  "is_leader": true,
  "member_id": "b2c3d4e5-0000-0000-0000-000000000002",
  "team_resource_id": "18e69001-f111-4ebc-87d0-c3d3bb7a0002",
  "team_name": "NDRF 602 Flood Rescue Unit (Ahmedabad Sabarmati)",
  "agency_id": "a0000000-0000-0000-0000-000000000001",
  "agency_name": "NDRF 6th Battalion (Vadodara)",
  "capabilities": ["boat", "flood_rescue", "water_rescue", "dewatering_pump"],
  "status": "AVAILABLE"
}
```
* **Errors:**
  * `401 UNAUTHORIZED`: Missing or expired token.
  * `403 FORBIDDEN`: Authenticated user does not have `FIELD_TEAM` role.
  * `404 NOT_FOUND`: Responder's team membership record not found.

---

### 5.2 Active Assignments

* **Path:** `GET /api/v1/field/assignments`
* **Auth:** Bearer Token (`FIELD_TEAM` role)
* **Query Parameters:**
  * `active` *(optional boolean, default `false`)*: If `true`, returns only dispatches in statuses `REQUESTED`, `ACKNOWLEDGED`, or `DISPATCHED`.
* **Response (200 OK):**
```json
[
  {
    "dispatch_id": "d0000000-0000-0000-0000-000000000001",
    "dispatch_ref": "DSP-2026-000042",
    "status": "ACKNOWLEDGED",
    "priority": "HIGH",
    "incident_id": "3c0b05b3-3a1e-450e-a226-bcfe69d0d939",
    "incident_ref": "INC-2026-000104",
    "scenario": "urban_flooding",
    "district": "Ahmedabad",
    "address_text": "Near Usmanpura Underpass",
    "landmark": "Opposite Jain Temple",
    "latitude": 23.0225,
    "longitude": 72.5714,
    "instructions": "Deploy inflatable boat to rescue stranded residents on 3rd floor.",
    "dispatched_at": "2026-10-24T15:00:00Z",
    "acknowledged_at": "2026-10-24T15:04:00Z",
    "overdue": false
  }
]
```
* **Isolation Rule:** Only dispatches assigned to the authenticated responder's team are returned. No other team's data is ever included.

---

### 5.3 Acknowledge Dispatch

* **Path:** `POST /api/v1/field/dispatches/{dispatch_id}/acknowledgement`
* **Auth:** Bearer Token (`FIELD_TEAM` role)
* **Request Body:** *(empty — no body required)*
* **Response (200 OK):**
```json
{
  "status": "ACKNOWLEDGED",
  "dispatch_ref": "DSP-2026-000042",
  "acknowledged_at": "2026-10-24T15:04:00Z"
}
```
* **State Transition:** `REQUESTED` → `ACKNOWLEDGED`
* **Idempotency:** If the dispatch is already `ACKNOWLEDGED`, returns `200 OK` without error (safe for mobile network retries).
* **Errors:**
  * `404 NOT_FOUND`: Dispatch does not exist or is not assigned to the caller's team.
  * `409 DISPATCH_STATE_CONFLICT`: Dispatch is in a terminal state and cannot be acknowledged.

---

### 5.4 Reject Dispatch

* **Path:** `POST /api/v1/field/dispatches/{dispatch_id}/rejection`
* **Auth:** Bearer Token (`FIELD_TEAM` role)
* **Request Body:**
```json
{
  "reason": "Team currently engaged in active rescue; capacity unavailable for secondary deployment."
}
```
* **Response (200 OK):**
```json
{
  "status": "REJECTED",
  "dispatch_ref": "DSP-2026-000042",
  "updated_at": "2026-10-24T15:06:00Z"
}
```
* **State Transition:** `REQUESTED` / `ACKNOWLEDGED` → `REJECTED`
* **Side Effect:** All reserved resources (`resource_assignments`) for the dispatch are released back to `status = 'AVAILABLE'`.
* **Errors:**
  * `422 VALIDATION_FAILED`: `reason` field is missing or too short (minimum 3 characters).
  * `404 NOT_FOUND`: Dispatch not found or not assigned to caller's team.
  * `409 DISPATCH_STATE_CONFLICT`: Dispatch is already in a non-rejectable state.

---

### 5.5 Report Operational Progress

* **Path:** `POST /api/v1/field/dispatches/{dispatch_id}/progress`
* **Auth:** Bearer Token (`FIELD_TEAM` role)
* **Request Body:**
```json
{
  "status": "EN_ROUTE",
  "note": "ETA 8 minutes. All equipment loaded.",
  "latitude": 23.0310,
  "longitude": 72.5650
}
```
* **Valid `status` values:** `EN_ROUTE`, `ON_SCENE`, `UPDATE`, `DELAYED`
* **Response (200 OK):**
```json
{
  "progress_id": "e5f6a7b8-0000-0000-0000-000000000003",
  "dispatch_id": "d0000000-0000-0000-0000-000000000001",
  "status": "EN_ROUTE",
  "note": "ETA 8 minutes. All equipment loaded.",
  "recorded_at": "2026-10-24T15:08:00Z"
}
```
* **State Transitions (automatic):**
  * `EN_ROUTE` + dispatch is `ACKNOWLEDGED` → dispatch advances to `DISPATCHED`; parent incident advances from `VERIFIED` → `DISPATCHED`.
  * All other events record progress milestone only (no dispatch status change).
* **GPS coordinates:** Optional. If provided, stored in `dispatch_progress` for audit and situational tracking.
* **Errors:**
  * `404 NOT_FOUND`: Dispatch not found or not assigned to caller's team.
  * `409 DISPATCH_NOT_ACKNOWLEDGED`: Cannot report `EN_ROUTE` without prior acknowledgement.

---

### 5.6 Request Backup / Reinforcement Team

* **Path:** `POST /api/v1/field/dispatches/{dispatch_id}/team-requests`
* **Auth:** Bearer Token (`FIELD_TEAM` role)
* **Request Body:**
```json
{
  "required_capability": "hazmat",
  "note": "Chemical spill detected in basement — require hazmat decontamination unit urgently."
}
```
* **Response (201 Created):**
```json
{
  "request_id": "f7a8b9c0-0000-0000-0000-000000000004",
  "dispatch_id": "d0000000-0000-0000-0000-000000000001",
  "required_capability": "hazmat",
  "note": "Chemical spill detected in basement — require hazmat decontamination unit urgently.",
  "status": "OPEN",
  "created_at": "2026-10-24T15:12:00Z"
}
```
* **Side Effects:**
  * Inserts a record into `team_requests` with `status = 'OPEN'`.
  * Sends an in-app notification to all active dispatchers (`DISPATCH` permission) with the requesting team name and capability needed.
* **Errors:**
  * `422 VALIDATION_FAILED`: `required_capability` missing or `note` exceeds 1000 characters.
  * `404 NOT_FOUND`: Dispatch not found or not assigned to caller's team.

---

### 5.7 Complete Mission

* **Path:** `POST /api/v1/field/dispatches/{dispatch_id}/completion`
* **Auth:** Bearer Token (`FIELD_TEAM` role)
* **Request Body:**
```json
{
  "summary": "All stranded residents evacuated. Area secured. No further immediate risk.",
  "civilians_evacuated": 14,
  "civilians_treated": 3,
  "notes": "Handoff to district relief camp. Structural damage assessment pending."
}
```
* **Response (200 OK):**
```json
{
  "status": "COMPLETED",
  "dispatch_ref": "DSP-2026-000042",
  "civilians_evacuated": 14,
  "civilians_treated": 3,
  "updated_at": "2026-10-24T17:45:00Z"
}
```
* **State Transition:** `DISPATCHED` → `COMPLETED`
* **Critical Rule:** The **parent incident remains open** (status is NOT changed to `RESOLVED`). The incident must be resolved separately by a dispatcher after all assigned teams report completion.
* **Side Effect:** All assigned team resources (`resource_assignments`) are released back to `status = 'AVAILABLE'`.
* **Errors:**
  * `422 VALIDATION_FAILED`: `summary` missing or too short (minimum 5 characters).
  * `404 NOT_FOUND`: Dispatch not found or not assigned to caller's team.
  * `409 DISPATCH_STATE_CONFLICT`: Dispatch is not in `DISPATCHED` state.

---

## 6. Team Recommendation Engine & Backup Decision API

> [!NOTE]
> **Ranking (S3-14):** `Score = (primary capability groups covered × 10) + (secondary capability tags × 3) − (distance km × 0.08)`.
> Primary capabilities are grouped by job (for example `boat`, `flood_rescue` and `water_rescue` are one "water rescue" group), so a team scores once per group, not once per synonym tag. Every team with at least one primary match ranks above every team without one. Higher score = higher rank; `distance_km` breaks ties.
> If the incident has no coordinates the engine uses the district centroid from `get_district_centroid()` (33 Gujarat districts), and finally Ahmedabad State HQ.
> With a configured database the PostGIS answer is authoritative: if no team is available the list is **empty** (it never falls back to in-memory seed teams). The in-memory seed teams are used only when `DATABASE_URL` is unset (offline demo).

### 6.1 Query Recommended Teams

* **Path:** `GET /api/v1/dm/incidents/{incident_id}/team-recommendations`
* **Auth:** Staff Session (`DISASTER_MGMT`, MFA verified)
* **Query Parameters:**
  * `limit` *(optional integer, 1–20, default `5`)*: Maximum candidate teams to return.
* **Response (200 OK):**
```json
{
  "incident_id": "3c0b05b3-3a1e-450e-a226-bcfe69d0d939",
  "scenario": "URBAN_FLOODING",
  "requires_confirmation": true,
  "recommendations": [
    {
      "resource_id": "18e69001-f111-4ebc-87d0-c3d3bb7a0002",
      "team_name": "NDRF 602 Flood & Water Rescue Unit (Ahmedabad Sabarmati)",
      "agency_id": "a0000000-0000-0000-0000-000000000007",
      "agency": "NDRF 6th Battalion (Vadodara)",
      "distance_km": 1.9,
      "capability_match": ["boat", "flood_rescue", "water_rescue"],
      "secondary_match": ["diver_squad", "inflatable_boats"],
      "matched_count": 3,
      "score": 15.85,
      "rank": 1,
      "reasons": "Partial capability match (boat, flood_rescue, water_rescue; covers 1 of 2 required capability groups); also offers diver_squad, inflatable_boats - 1.9 km away (nearest capable team)",
      "status": "AVAILABLE",
      "capabilities": {"boat": true, "water_rescue": true, "flood_rescue": true, "inflatable_boats": true, "diver_squad": true}
    }
  ],
  "generated_at": "2026-11-05T15:00:00Z"
}
```
* **Field notes for the frontend:**
  * `scenario` is the database enum value (`URBAN_FLOODING`, `INDUSTRIAL_FIRE`, `CYCLONE`).
  * `agency` (not `agency_name`) carries the agency display name.
  * `secondary_match`, `matched_count` and `score` were **added in S3-14**; they are additive and optional to display. `score` is advisory and only meaningful for ordering within one response.
  * `reasons` calls a team "nearest capable team" only when it is the closest team with a primary match.
* **Scenario → capability rules (S3-14):**

| Scenario | Primary capability groups (10 pts per group) | Secondary tags (3 pts each) |
| :--- | :--- | :--- |
| `urban_flooding` | water rescue: `boat`, `flood_rescue`, `water_rescue` · dewatering: `dewatering_pump` | `diver_squad`, `inflatable_boats`, `medical` |
| `industrial_fire` | firefighting: `fire`, `fire_tender`, `water_tender` · hazmat: `hazmat`, `chemical_foam`, `industrial_fire`, `breathing_apparatus` | `gas_leak`, `smoke_extraction`, `high_rise_rescue`, `medical` |
| `cyclone` | rescue: `search_and_rescue`, `cyclone_response`, `high_wind_rescue` · debris clearing: `debris_clearing` · shelter: `shelter_management` · first aid: `medical_first_aid` | `boat`, `heavy_extrication`, `water_rescue`, `heavy_machinery`, `medical` |

* **Constraints:**
  * Only `AVAILABLE` resources of `type = 'TEAM'` with `quantity_available > 0` are ranked; reserved, maintenance or already-dispatched teams are **strictly excluded** (so a dispatched team disappears from the list: no double booking).
  * `requires_confirmation: true` is **always** returned — this endpoint is **strictly advisory** and never creates a dispatch. Dispatch creation stays on `POST /api/v1/dm/incidents/{id}/dispatches` with the `DISPATCH` permission.
* **Errors:**
  * `404 NOT_FOUND`: Incident does not exist.
  * `401 MFA_REQUIRED`: Staff token without verified MFA.
  * `403 ROLE_REQUIRED`: Caller is not `DISASTER_MGMT`.

---

### 6.2 List Field Backup Requests

* **Path:** `GET /api/v1/dm/team-requests`
* **Auth:** Staff Session (`DISASTER_MGMT`)
* **Query Parameters:**
  * `status` *(optional, default `OPEN`)*: `OPEN` | `APPROVED` | `DECLINED` | `ALL`
  * `limit` *(optional integer, 1–100, default `50`)*
  * `offset` *(optional integer, default `0`)*
* **Response (200 OK):**
```json
[
  {
    "request_id": "f7a8b9c0-0000-0000-0000-000000000004",
    "dispatch_id": "d0000000-0000-0000-0000-000000000001",
    "dispatch_ref": "DSP-2026-000042",
    "incident_id": "3c0b05b3-3a1e-450e-a226-bcfe69d0d939",
    "incident_ref": "INC-2026-000104",
    "requested_by": "a1b2c3d4-0000-0000-0000-000000000001",
    "requested_by_name": "Arjun Mehta",
    "team_name": "NDRF 602 Flood Rescue Unit (Ahmedabad Sabarmati)",
    "required_capability": "hazmat",
    "note": "Chemical spill detected in basement.",
    "status": "OPEN",
    "decision_rationale": null,
    "decided_by": null,
    "decided_at": null,
    "created_at": "2026-10-24T15:12:00Z"
  }
]
```

---

### 6.3 Decide on a Backup Request (Approve / Decline)

* **Path:** `POST /api/v1/dm/team-requests/{request_id}/decision`
* **Auth:** Staff Session (`DISASTER_MGMT`) with the **`DISPATCH`** permission
* **Request Body:**
```json
{
  "action": "APPROVE",
  "target_resource_id": "18e69001-f111-4ebc-87d0-c3d3bb7a0009",
  "rationale": "Hazmat unit dispatched from Vatva Industrial Zone depot."
}
```
* **`action` values:** `APPROVE` | `DECLINE`
* **`rationale`:** Required for `DECLINE`; optional for `APPROVE`.
* **Response (200 OK — APPROVE):**
```json
{
  "request_id": "f7a8b9c0-0000-0000-0000-000000000004",
  "status": "APPROVED",
  "decision_rationale": "Hazmat unit dispatched from Vatva Industrial Zone depot.",
  "decided_at": "2026-10-24T15:20:00Z",
  "dispatch_draft": {
    "incident_id": "3c0b05b3-3a1e-450e-a226-bcfe69d0d939",
    "incident_ref": "INC-2026-000104",
    "required_capability": "hazmat",
    "suggested_resource_id": "18e69001-f111-4ebc-87d0-c3d3bb7a0009",
    "suggested_resource_name": "NDRF Hazmat Response Unit (Vadodara)",
    "receiving_agency_id": "a0000000-0000-0000-0000-000000000001",
    "priority": "HIGH",
    "instructions": "Reinforce DSP-2026-000042: Deploy hazmat unit as requested by frontline responders."
  }
}
```
* **Response (200 OK — DECLINE):**
```json
{
  "request_id": "f7a8b9c0-0000-0000-0000-000000000004",
  "status": "DECLINED",
  "decision_rationale": "No hazmat units currently available in district. Escalated to state HQ.",
  "decided_at": "2026-10-24T15:21:00Z",
  "dispatch_draft": null
}
```
* **Concurrency:** Uses `SELECT ... FOR UPDATE` row lock; double-deciding a request returns `409 TEAM_REQUEST_ALREADY_DECIDED`.
* **Side Effects:**
  * On `APPROVE`: Updates `team_requests.status = 'APPROVED'`; writes audit entry; notifies the requesting field user.
  * On `DECLINE`: Updates `team_requests.status = 'DECLINED'`; writes audit entry with rationale; notifies the requesting field user.
  * `dispatch_draft` (approve only): Pre-populated dispatch creation payload — dispatcher must **manually** create the dispatch using this data.
* **Errors:**
  * `403 PERMISSION_REQUIRED`: Caller lacks the `DISPATCH` permission.
  * `404 NOT_FOUND`: Request ID (or `target_resource_id`) does not exist.
  * `409 TEAM_REQUEST_ALREADY_DECIDED`: Request has already been approved or declined.
  * `422 RATIONALE_REQUIRED`: `action = DECLINE` requires a non-empty `rationale`.
  * `422 CAPABILITY_MISMATCH`: `target_resource_id` does not have the requested capability.
* **Auto-suggestion (approve without `target_resource_id`):** ranks AVAILABLE teams that have the requested capability (Section 6.1 engine). If none is available, `suggested_resource_id` is `null` and `instructions` ends with "manual allocation required"; no team is invented.

---

## 7. Payments & Donations Foundation API (Owner: Shlok)

### 7.1 Create Donation Order
* **Path:** `POST /api/v1/donations`
* **Auth:** Optional Citizen Bearer Token or Guest Email
* **Headers:** `Idempotency-Key: <unique-key>`
* **Request Body:**
```json
{
  "campaign_id": "c0000000-0000-0000-0000-000000000001",
  "amount": 2500.00,
  "currency": "INR",
  "guest_name": "Suresh Mehta",
  "guest_email": "suresh@example.in",
  "is_anonymous": false
}
```
* **Response (201 Created):**
```json
{
  "donation_id": "a189f782-b7e1-45df-911b-3ca976ebff12",
  "gateway_name": "MOCK_GATEWAY",
  "gateway_order_id": "order_mock_sandbox_9921",
  "amount": 2500.00,
  "currency": "INR",
  "status": "PENDING",
  "is_sandbox": true,
  "checkout_key": null
}
```
* **`checkout_key`:** the public Razorpay key id the browser needs to open Razorpay Checkout; `null` for the mock gateway. It is never a secret. After checkout succeeds, the browser sends Razorpay's `razorpay_payment_id` and `razorpay_signature` to 7.2 as `gateway_payment_id` and `signature`.

* **Gateway:** selected with `PAYMENT_GATEWAY` (`mock` or `razorpay`); `gateway_name` is `MOCK_GATEWAY` or `RAZORPAY`. `is_sandbox` comes from the gateway: always `true` for the mock gateway, `true` for Razorpay test keys, `false` only for `rzp_live` keys.
* **Errors:** `422 IDEMPOTENCY_KEY_REQUIRED`, `409 IDEMPOTENCY_CONFLICT`, `409 CAMPAIGN_NOT_ACTIVE`, `502 GATEWAY_UNAVAILABLE` (the gateway refused or could not be reached; nothing is stored).

### 7.2 Verify Payment & Issue Receipt
* **Path:** `POST /api/v1/donations/{id}/verify`
* **Signature:** mock gateway: HMAC-SHA256 (`MOCK_GATEWAY_SECRET`) over `<order_id>|<payment_id>|<amount with 2 decimals>|<currency>`, so a signature for another amount or currency is rejected. Razorpay: Razorpay's checkout signature over `<order_id>|<payment_id>`; the amount is fixed by the server-created order.
* **Request Body:**
```json
{
  "gateway_payment_id": "pay_mock_12345678",
  "signature": "hmac_sha256_mock_signature"
}
```
* **Response (200 OK):**
```json
{
  "donation_id": "a189f782-b7e1-45df-911b-3ca976ebff12",
  "status": "CONFIRMED",
  "receipt_no": "REC-2026-000412",
  "receipt_issued_at": "2026-10-24T15:30:00Z"
}
```
* **Errors:** `400 INVALID_SIGNATURE` (audited; donation stays `PENDING`), `409 ALREADY_CONFIRMED` (confirmed with a different payment), `409 DONATION_NOT_PENDING`, `409 GATEWAY_MISMATCH` (created under another gateway).
* **Idempotent:** if the webhook (7.3) confirmed the donation first, the same payment returns `200` with the same receipt.

### 7.3 Payment Webhook (server-to-server)
* **Path:** `POST /api/v1/payments/webhook/{gateway}` — `{gateway}` is `mock` or `razorpay` and must match `PAYMENT_GATEWAY` (otherwise `404`).
* **Auth:** none; authenticated by an HMAC-SHA256 signature over the raw body: `X-Mock-Signature` (`MOCK_GATEWAY_SECRET`) or `X-Razorpay-Signature` (`RAZORPAY_WEBHOOK_SECRET`).
* **Event id:** `X-Razorpay-Event-Id` / `X-Mock-Event-Id` header (mock also accepts a top-level `id`); without one, a SHA-256 of the body is used. Each event id is processed once (`payment_webhook_events`, migration 11).
* **Body:** Razorpay payment event shape for both gateways:
```json
{
  "event": "payment.captured",
  "payload": {"payment": {"entity": {"id": "pay_123", "order_id": "order_123", "amount": 250000, "currency": "INR"}}}
}
```
* **Response (200 OK):** `{"received": true, "event_id": "evt_1", "outcome": "CONFIRMED", "donation_id": "…"}`. Every verified event answers 200 so the gateway stops retrying; `outcome` is one of `CONFIRMED`, `ALREADY_CONFIRMED`, `DUPLICATE_EVENT`, `AMOUNT_MISMATCH` (amount in paise or currency differs from the donation; nothing changes, audited), `PAYMENT_CONFLICT`, `FAILED` (`payment.failed` on a `PENDING` donation), `UNKNOWN_ORDER`, `IGNORED_EVENT_TYPE`, `IGNORED_NOT_PENDING`.
* **Errors:** `400 INVALID_SIGNATURE` (audited, nothing changes).

### 7.4 My Donations & Receipts
* **Path:** `GET /api/v1/me/donations?page=1&limit=25`
* **Auth:** Bearer Token (`require_citizen`). Guest donations have no account and are not listed.
* **Response (200 OK):**
```json
{
  "items": [
    {
      "donation_id": "a189f782-b7e1-45df-911b-3ca976ebff12",
      "campaign_id": "c0000000-0000-0000-0000-000000000001",
      "campaign_title": "Cyclone relief - Porbandar",
      "amount": 2500.00,
      "currency": "INR",
      "status": "CONFIRMED",
      "is_anonymous": false,
      "is_sandbox": true,
      "receipt_no": "REC-2026-000412",
      "receipt_issued_at": "2026-10-24T15:30:00Z",
      "created_at": "2026-10-24T15:28:00Z",
      "confirmed_at": "2026-10-24T15:30:00Z"
    }
  ],
  "page": 1, "limit": 25, "total": 1, "pages": 1
}
```

---

## 8. AI Triage Service Contract (Owner: Rudra / Neeti)

### 8.1 Fast Triage Prediction
* **Path:** `POST /triage`
* **Request Body:**
```json
{
  "incident_ref": "INC-GUJ-2026-001",
  "reported_scenario": "urban_flooding",
  "description": "Heavy water accumulation, people stranded on rooftops near river bank.",
  "reported_urgency": "HIGH",
  "people_affected": 20,
  "has_coordinates": true,
  "details": {}
}
```
* **Response Contract (200 OK):**
```json
{
  "model": "drch-triage-v1-rules",
  "scenario": "URBAN_FLOODING",
  "priority": "CRITICAL",
  "confidence": 0.89,
  "uncertainty": null,
  "factors": [
    {"name": "people_affected", "detail": ">= 10 individuals involved", "weight": 0.4},
    {"name": "stranded_trapped", "detail": "High risk distress keywords detected", "weight": 0.5}
  ]
}
```
### 8.2 English Text Analysis (Experimental Advisory Endpoint)
* **Path:** `POST /analyze-text`
* **Auth:** Optional `Authorization: Bearer <AI_TRIAGE_TOKEN>` when the worker token is configured.
* **Purpose:** Run the separately trained English crisis-message model. This endpoint is additive and does not change `/triage` or the backend incident lifecycle.
* **Request Body:**
```json
{
  "description": "The underpass is flooded and several people need rescue.",
  "source": "example-feed",
  "source_created_at": "2026-11-04T12:30:00Z",
  "latitude": 23.02,
  "longitude": 72.57
}
```
* **Response (200 OK):** Includes advisory disaster relevance and probabilities for learned help intent, direct-report, and humanitarian information categories. Low-confidence relevance is returned as `REVIEW` with a candidate label. Text not confidently detected as English returns `LANGUAGE_UNCERTAIN` or `UNSUPPORTED_LANGUAGE` without classification. `source_metadata` is copied from the caller; it is not extracted from the text. The model explicitly returns `NOT_TRAINED` for the project's exact operational scenario and priority, location mentions, and event-time extraction.
* **Availability:** Returns `503` when `TEXT_MODEL_DIR` does not point to a trained model artifact. Human review is required; this response must not trigger incident verification or dispatch.

### 8.3 AI Service Health
* **Path:** `GET /health`
* **Response (200 OK):** `{"status": "ok", "service": "drch-ai-triage"}`

### 8.4 Optional LLM Adapter (`ai-workers/service/llm.py`)
* Not an HTTP endpoint: a library the triage service can call. **Off by default** (`LLM_ENABLED`); the provider key is read from `LLM_API_KEY` only.
* `second_opinion` runs only when the rules confidence is below 0.6 and returns `{"scenario", "priority", "source": "llm"}` limited to the allowed labels, otherwise nothing. `english_summary` summarises Hindi or Gujarati text. Replies that are not valid JSON or use other labels are rejected.
* Only the report text is sent, with emails and phone numbers masked; no reporter identity. The result is advisory and never decides anything.

### 8.5 AI Versus Human Decisions (`GET /api/v1/dm/analytics`)
* The `ai_by_decision` list counts AI suggestions by `scenario`, `human_action` and `confidence_band` (`n` per row). Filters: `scenario`, `from`, `to`.
* **Definitions:** `human_action` is what the dispatcher recorded: `ACCEPTED` (suggestion used as given), `MODIFIED` (used with changes) or `REJECTED`; `UNDECIDED` means no decision yet. `confidence_band` is the AI confidence at suggestion time: `HIGH` 0.80 or more, `MEDIUM` 0.60 to 0.79, `LOW` below 0.60, `UNKNOWN` when none was recorded. The same wording is returned in `definitions.confidence_bands`.
* Suggestions are advisory; this endpoint only counts what humans decided.

---

## 9. Account Security API: Password Reset, Invitations & Google Sign-In (Owner: Zalak / Siddh)

All endpoints below are under `/api/v1`, use the standard error format, and never reveal whether an email is registered. Tokens in links are single-use, random (32 bytes) and stored only as SHA-256 hashes. Links in emails are built from `FRONTEND_URL`.

| Item | Value | Setting |
| :--- | :--- | :--- |
| Password-reset link lifetime | 15 minutes | `PASSWORD_RESET_TOKEN_MINUTES` |
| Invitation link lifetime | 48 hours | `INVITATION_TOKEN_HOURS` |
| MFA setup session (after accepting an invitation) | 15 minutes | fixed |
| Access token | 60 minutes | `ACCESS_TOKEN_MINUTES` |

Rate limits are per client IP (sliding window, `429 RATE_LIMITED` with `details.retry_after_seconds`).

### 9.1 Password Reset
1. **Request a link** — `POST /auth/forgot-password`, body `{"email": "user@example.in"}`. Rate limit 5 per 15 minutes. Always `200 OK` with `{"message": "If this email is registered and active, a password reset link has been sent."}`; an email (link `…/reset-password?token=…`) is sent only to an active, unlocked account.
2. **Check the link** — `GET /auth/reset-password/verify?token=…` → `200 {"valid": true, "message": "Password reset token is valid"}` or `400 RESET_TOKEN_INVALID`.
3. **Set the password** — `POST /auth/reset-password`, body `{"token": "…", "new_password": "…"}` (`new_password` 12–1024 characters). Rate limit 10 per 15 minutes. `200 {"message": "…"}`; the token is cleared and `token_version` is incremented, so all existing sessions are revoked. MFA enrolment is kept. Errors: `400 RESET_TOKEN_INVALID` (unknown, used or expired), `422 VALIDATION_FAILED`.

### 9.2 Staff Invitations
Staff accounts (`DISASTER_MGMT`, `FIELD_TEAM`, `APP_MGMT`) are never created with a password chosen by someone else: they are invited and finish setup themselves.

* **Invite** — `POST /auth/invitations`
  * **Auth:** Bearer Token with verified MFA: an `APP_MGMT` administrator, or a `DISASTER_MGMT` user with the `SUPERVISOR` permission.
  * **Body:** `{"email", "full_name", "role": "DISASTER_MGMT" | "FIELD_TEAM" | "APP_MGMT", "phone"?, "designation"?, "permissions"?: ["DISPATCH", …]}` (`permissions` apply to `DISASTER_MGMT` only).
  * **Response (201 Created):** `{"user_id", "email", "role", "status": "PENDING_SETUP", "message"}`; an email with `…/setup-account?token=…` is sent.
  * **Errors:** `400 CANNOT_INVITE_CITIZEN` (citizens self-register, 2.1), `400 INVALID_ROLE`, `400 UNKNOWN_PERMISSION`, `403 PRIVILEGE_ESCALATION` (only `APP_MGMT` may invite `APP_MGMT`; a supervisor cannot grant permissions they do not hold), `403 INVITER_REQUIRED`, `401 MFA_REQUIRED`, `409 EMAIL_TAKEN`.
* **Check the link** — `GET /auth/invitation/verify?token=…` → `200 {"valid": true, "email", "full_name", "role", "requires_mfa": true}` or `400 INVITATION_INVALID` (unknown, used, expired, or the account is no longer `PENDING_SETUP`).
* **Accept** — `POST /auth/invitation/accept`, body `{"token", "password"}` (`password` 12–1024 characters). Rate limit 10 per 15 minutes. The token is cleared at once. For staff roles the response is `200 {"mfa_required": true, "mfa_setup_token", "mfa_secret", "mfa_uri", "message"}`: the invitee adds the secret to an authenticator app. Errors: `400 INVITATION_INVALID`, `422 VALIDATION_FAILED`.
* **Enrol TOTP and activate** — `POST /auth/invitation/verify-totp`, body `{"mfa_setup_token", "code"}`. Rate limit 20 per 5 minutes. On success the account becomes `ACTIVE` and the response is the signed-in response of 2.2 (with MFA verified). Errors: `401 MFA_SETUP_EXPIRED` (setup session older than 15 minutes: restart from the link), `401 MFA_INVALID` (wrong code; the account stays `PENDING_SETUP`), `401 INVALID_CREDENTIALS`.
* Until setup is complete, `POST /auth/login` answers `403 ACCOUNT_NOT_SETUP`.

### 9.3 Google Sign-In (citizens only)
* **Path:** `POST /auth/google`, body `{"credential": "<Google Identity Services ID token>"}`. Rate limit 20 per 5 minutes.
* **Behaviour:** the ID token is verified with Google and its audience must equal `GOOGLE_CLIENT_ID`; the Google email must be verified. An existing **citizen** is signed in; an unknown email is registered as a new citizen (`NORMAL_USER`) and signed in. The response is the signed-in response of 2.2.
* **Citizen-only rule:** a Google identity never yields a staff session. If the email belongs to a staff account the request is refused with `403 GOOGLE_STAFF_NOT_ALLOWED`; staff sign in with password and TOTP (2.2).
* **Errors:** `503 GOOGLE_AUTH_UNAVAILABLE` (`GOOGLE_CLIENT_ID` not configured), `401 GOOGLE_AUTH_FAILED` (invalid token, wrong audience or no email), `401 GOOGLE_EMAIL_NOT_VERIFIED`, `502 GOOGLE_SERVICE_UNAVAILABLE` (Google could not be reached), `401 INVALID_CREDENTIALS` (locked or inactive citizen), `403 GOOGLE_STAFF_NOT_ALLOWED`, `429 RATE_LIMITED`.

### 9.4 Auth Error Codes
| Code | HTTP | Meaning |
| :--- | :--- | :--- |
| `INVALID_CREDENTIALS` | 401 | Sign-in failed (generic on purpose) |
| `ACCOUNT_NOT_SETUP` | 403 | Invited account has not completed setup |
| `MFA_NOT_ENROLLED` | 403 | Staff account without an authenticator |
| `MFA_CHALLENGE_INVALID` | 401 | MFA sign-in challenge expired or invalid |
| `MFA_INVALID` | 401 | Wrong TOTP code |
| `MFA_SETUP_EXPIRED` | 401 | Invitation MFA setup session expired |
| `MFA_REQUIRED` | 401 | Route needs an MFA-verified session |
| `RESET_TOKEN_INVALID` | 400 | Password-reset link unknown, used or expired |
| `INVITATION_INVALID` | 400 | Invitation link unknown, used or expired |
| `CANNOT_INVITE_CITIZEN` / `INVALID_ROLE` / `UNKNOWN_PERMISSION` | 400 | Invalid invitation request |
| `PRIVILEGE_ESCALATION` / `INVITER_REQUIRED` | 403 | Caller may not issue this invitation |
| `EMAIL_TAKEN` / `DUPLICATE_EMAIL` | 409 | Email already registered (invitation / registration) |
| `WEAK_PASSWORD` | 422 | Registration password policy not met |
| `GOOGLE_AUTH_UNAVAILABLE` | 503 | Google sign-in not configured |
| `GOOGLE_AUTH_FAILED` / `GOOGLE_EMAIL_NOT_VERIFIED` | 401 | Google token rejected |
| `GOOGLE_SERVICE_UNAVAILABLE` | 502 | Google could not be reached |
| `GOOGLE_STAFF_NOT_ALLOWED` | 403 | Google sign-in attempted for a staff account |
| `RATE_LIMITED` | 429 | Too many requests from this IP |

---

## 10. Owner Sign-Off Matrix

| Endpoint Domain | Responsible Owner | Contract Status |
| :--- | :--- | :--- |
| **Tech Lead & Integration Architect** | Siddh (@Siddhcreator-1706) | ✅ Approved & Signed |
| **Citizen & Public Backend** | Zalak | ✅ Standard Agreed |
| **Dispatch & Field Backend / Geo** | Nisarg | ✅ Standard Agreed |
| **Payments & Signal Promotion** | Shlok | ✅ Standard Agreed |
| **Ingestion & External Feeds** | Rudra | ✅ Standard Agreed |
| **AI Model & Evaluation Lead** | Neeti | ✅ Standard Agreed |
