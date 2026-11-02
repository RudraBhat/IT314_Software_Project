# 📑 Disaster Response Coordination Hub (DRCH) - API Contracts Specification

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

---

## 2. Citizen Authentication & Reporting API (Owner: Zalak)

### 2.1 Citizen Registration
* **Path:** `POST /api/v1/auth/register`
* **Auth:** None (Public)
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
* **Response (201 Created):**
```json
{
  "user_id": "7a35eb42-6362-47d3-8e41-0f7300c14b43",
  "email": "citizen@example.in",
  "full_name": "Ramesh Patel",
  "role": "NORMAL_USER",
  "status": "ACTIVE"
}
```
* **Errors:**
  * `409 DUPLICATE_EMAIL`: Email already exists (`{"error": {"code": "DUPLICATE_EMAIL", "message": "An account with this email already exists."}}`).
  * `422 WEAK_PASSWORD`: Password does not meet security policy (minimum 8 chars, 1 digit, 1 special symbol).
  * `429 RATE_LIMITED`: Rate limit exceeded on registration attempts.

### 2.2 Citizen Login
* **Path:** `POST /api/v1/auth/login`
* **Auth:** None (Public)
* **Request Body:**
```json
{
  "email": "citizen@example.in",
  "password": "StrongPassword123!"
}
```
* **Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user": {
    "user_id": "7a35eb42-6362-47d3-8e41-0f7300c14b43",
    "email": "citizen@example.in",
    "role": "NORMAL_USER",
    "full_name": "Ramesh Patel"
  }
}
```
*(Citizens do NOT have MFA enabled by default; token is issued immediately).*

### 2.3 Submit Incident Report
* **Path:** `POST /api/v1/incidents`
* **Auth:** Bearer Token (`require_citizen`)
* **Headers:**
  * `Authorization: Bearer <token>`
  * `Idempotency-Key: <unique-uuid-or-client-key>`
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
  * Idempotent: repeated calls with same `Idempotency-Key` return identical response.

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

---

## 3. Field Team Responder API (Owner: Nisarg)

> [!NOTE]
> This section is a high-level summary stub retained for Sprint 1 traceability. For the complete, production-grade Sprint 2 API specification — including full request/response contracts, state transition rules, idempotency, isolation guarantees, and error codes — refer to **[Section 5: Field Operations API](#5-field-operations-api-sprint-2--s2-01)**.

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
* **Query Parameters:** `source` *(optional string: `USGS`, `SACHET`, `ALL`)*
* **Response (200 OK):**
```json
{
  "run_id": "e2f0980c-61cb-4bc1-90a8-bcf6b45a6c02",
  "source": "USGS",
  "items_fetched": 4,
  "items_stored": 2,
  "status": "SUCCESS"
}
```

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

---

## 5. Field Operations API (Sprint 2 — S2-01)

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

## 6. Team Recommendation Engine & Backup Decision API (Sprint 2 — S2-02)

> [!NOTE]
> The ranking engine scores candidates as: **Score = (Capability Overlap Count × 10) − (Distance km × 0.05)**. Higher score = higher rank. If incident coordinates are unavailable, the engine falls back to the district centroid from `get_district_centroid()` (33 Gujarat districts pre-loaded), and finally to Ahmedabad State HQ coordinates.

### 6.1 Query Recommended Teams

* **Path:** `GET /api/v1/dm/incidents/{incident_id}/team-recommendations`
* **Auth:** Staff Session (`DISASTER_MGMT`)
* **Query Parameters:**
  * `limit` *(optional integer, 1–20, default `5`)*: Maximum candidate teams to return.
* **Response (200 OK):**
```json
{
  "incident_id": "3c0b05b3-3a1e-450e-a226-bcfe69d0d939",
  "scenario": "urban_flooding",
  "requires_confirmation": true,
  "recommendations": [
    {
      "resource_id": "18e69001-f111-4ebc-87d0-c3d3bb7a0002",
      "team_name": "NDRF 602 Flood Rescue Unit (Ahmedabad Sabarmati)",
      "agency_id": "a0000000-0000-0000-0000-000000000001",
      "agency_name": "NDRF 6th Battalion (Vadodara)",
      "distance_km": 3.4,
      "capability_match": ["boat", "flood_rescue", "water_rescue"],
      "matched_count": 3,
      "score": 29.83,
      "rank": 1,
      "advisory": true,
      "reasons": "Exact capability match (boat, flood_rescue, water_rescue) and closest proximity (3.4 km)"
    },
    {
      "resource_id": "18e69001-f111-4ebc-87d0-c3d3bb7a0007",
      "team_name": "SDRF Flood Quick Response Team (Rajkot)",
      "agency_id": "a0000000-0000-0000-0000-000000000002",
      "agency_name": "SDRF Gujarat Command",
      "distance_km": 215.0,
      "capability_match": ["boat", "flood_rescue"],
      "matched_count": 2,
      "score": 9.25,
      "rank": 2,
      "advisory": true,
      "reasons": "Capability match available as regional backup reserve (215.0 km away)"
    }
  ],
  "generated_at": "2026-10-24T15:00:00Z"
}
```
* **Scenario → Capability Mapping:**

| Scenario | Critical Capabilities Ranked |
| :--- | :--- |
| `urban_flooding` | `boat`, `flood_rescue`, `water_rescue`, `dewatering_pump` |
| `cyclone` | `debris_clearing`, `shelter_management`, `high_wind_rescue`, `medical_first_aid` |
| `industrial_fire` | `hazmat`, `fire_tender`, `chemical_foam`, `breathing_apparatus` |
| `earthquake` | `search_and_rescue`, `collapse_rescue`, `structural_shoring`, `canine_unit`, `trauma_care` |

* **Constraints:**
  * Only `AVAILABLE` resources of `type = 'TEAM'` are ranked; unavailable or already-dispatched teams are **strictly excluded**.
  * `requires_confirmation: true` is **always** returned — this endpoint is **strictly advisory** and never auto-creates a dispatch.
* **Errors:**
  * `404 NOT_FOUND`: Incident does not exist.
  * `403 FORBIDDEN`: Caller lacks `DISASTER_MGMT` role.

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
* **Auth:** Staff Session (`DISASTER_MGMT`)
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
  * `404 NOT_FOUND`: Request ID does not exist.
  * `409 TEAM_REQUEST_ALREADY_DECIDED`: Request has already been approved or declined.
  * `422 VALIDATION_FAILED`: `action = DECLINE` requires non-empty `rationale`.

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
  "is_sandbox": true
}
```

### 7.2 Verify Payment & Issue Receipt
* **Path:** `POST /api/v1/donations/{id}/verify`
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
### 8.2 AI Service Health
* **Path:** `GET /health`
* **Response (200 OK):** `{"status": "ok", "service": "drch-ai-triage"}`

---

## 9. Owner Sign-Off Matrix

| Endpoint Domain | Responsible Owner | Contract Status |
| :--- | :--- | :--- |
| **Tech Lead & Integration Architect** | Siddh (@Siddhcreator-1706) | ✅ Approved & Signed |
| **Citizen & Public Backend** | Zalak | ✅ Standard Agreed |
| **Dispatch & Field Backend / Geo** | Nisarg | ✅ Standard Agreed |
| **Payments & Signal Promotion** | Shlok | ✅ Standard Agreed |
| **Ingestion & External Feeds** | Rudra | ✅ Standard Agreed |
| **AI Model & Evaluation Lead** | Neeti | ✅ Standard Agreed |
