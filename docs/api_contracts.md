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

### 2.3 Password Reset Policy
Until an enterprise transactional email provider is connected, public password reset endpoints (`POST /api/v1/auth/password-reset`) are deferred. Password or MFA resets must be requested through an authorized administrator using `python -m app.cli reset-mfa` or administrative staff tooling. Session tokens are automatically revoked upon credential replacement by incrementing the user's `token_version`.
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

### 3.1 Field Profile & Active Assignments
* **Path:** `GET /api/v1/field/me`
* **Auth:** Bearer Token (`require_field`)
* **Path:** `GET /api/v1/field/assignments`
* **Auth:** Bearer Token (`require_field`)
* **Response (200 OK):**
```json
[
  {
    "dispatch_id": "5f9e8312-328b-4921-995a-0e6e7d6cfb33",
    "dispatch_ref": "DISP-2026-000012",
    "status": "DISPATCHED",
    "incident_ref": "INC-GUJ-2026-001",
    "scenario": "urban_flooding",
    "priority": "HIGH",
    "address_text": "Usmanpura Underpass, Ahmedabad",
    "latitude": 23.0478,
    "longitude": 72.5694,
    "instructions": "Deploy inflatable boat squad for vehicle evacuation.",
    "dispatched_at": "2026-10-24T14:45:00Z"
  }
]
```

### 3.2 Acknowledge / Reject Dispatch
* **Path:** `POST /api/v1/field/dispatches/{id}/acknowledgement`
* **Auth:** Bearer Token (`require_field`)
* **Response (200 OK):** `{"status": "ACKNOWLEDGED", "updated_at": "..."}`
* **Path:** `POST /api/v1/field/dispatches/{id}/rejection`
* **Request Body:** `{"reason": "Vehicle mechanical breakdown en-route"}`
* **Response (200 OK):** `{"status": "REJECTED", "updated_at": "..."}`

### 3.3 Progress Update & Backup Team Request
* **Path:** `POST /api/v1/field/dispatches/{id}/progress`
* **Request Body:**
```json
{
  "status": "ON_SCENE",
  "note": "Arrived on location. Water level approx 4.5 feet. Commencing boat launch."
}
```
* **Path:** `POST /api/v1/field/dispatches/{id}/team-requests`
* **Request Body:**
```json
{
  "required_capability": "medical_ambulance",
  "note": "2 rescued elderly citizens require immediate hypothermia treatment."
}
```

### 3.4 Mission Completion
* **Path:** `POST /api/v1/field/dispatches/{id}/completion`
* **Request Body:**
```json
{
  "summary": "14 stranded civilians evacuated to dry shelter. Underpass barricaded."
}
```
*(Dispatch becomes `COMPLETED`; incident remains open for dispatcher resolution).*

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

## 5. Team Recommendation Engine API (Owner: Nisarg)

### 5.1 Query Recommended Teams
* **Path:** `GET /api/v1/dm/incidents/{id}/team-recommendations`
* **Auth:** Staff Session (`DISASTER_MGMT`)
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
      "agency": "NDRF 6th Battalion (Vadodara)",
      "distance_km": 3.4,
      "capability_match": ["boat", "flood_rescue", "water_rescue"],
      "rank": 1,
      "reasons": "Exact capability match (inflatable boat + flood rescue) and closest proximity (3.4 km)"
    },
    {
      "resource_id": "18e69001-f111-4ebc-87d0-c3d3bb7a0007",
      "team_name": "SDRF Flood Quick Response Team (Rajkot)",
      "agency": "SDRF Gujarat Command",
      "distance_km": 215.0,
      "capability_match": ["boat", "flood_rescue"],
      "rank": 2,
      "reasons": "Capability match available as regional backup reserve"
    }
  ]
}
```
*(Advisory only: query NEVER automatically reserves or dispatches a team without human confirmation).*

---

## 6. Payments & Donations Foundation API (Owner: Shlok)

### 6.1 Create Donation Order
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

### 6.2 Verify Payment & Issue Receipt
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

## 7. AI Triage Service Contract (Owner: Rudra / Neeti)

### 7.1 Fast Triage Prediction
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
### 7.2 AI Service Health
* **Path:** `GET /health`
* **Response (200 OK):** `{"status": "ok", "service": "drch-ai-triage"}`

---

## 8. Owner Sign-Off Matrix

| Endpoint Domain | Responsible Owner | Contract Status |
| :--- | :--- | :--- |
| **Tech Lead & Integration Architect** | Siddh (@Siddhcreator-1706) | ✅ Approved & Signed |
| **Citizen & Public Backend** | Zalak | ✅ Standard Agreed |
| **Dispatch & Field Backend / Geo** | Nisarg | ✅ Standard Agreed |
| **Payments & Signal Promotion** | Shlok | ✅ Standard Agreed |
| **Ingestion & External Feeds** | Rudra | ✅ Standard Agreed |
| **AI Model & Evaluation Lead** | Neeti | ✅ Standard Agreed |
