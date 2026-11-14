#!/usr/bin/env bash
# ==============================================================================
# Gujarat Disaster Management Platform (ResQ) - End-to-End Smoke Test Suite
#
# Covers:
#   1. Core Loop:
#      - /health & /api/v1/health readiness & DB connectivity
#      - Citizen registration with contract password policy
#      - Gujarat incident submission & Idempotency-Key replay
#      - Out-of-state incident rejection (422 OUTSIDE_GUJARAT)
#      - Public map isolation for unverified reports
#      - Dispatcher authentication (Password + TOTP MFA) & incident verification
#      - Public map presence for verified incident (no PII, 4-decimal coords)
#      - Citizen timeline tracking (SUBMITTED -> VERIFIED)
#   2. AI Advisory Triage Gate:
#      - AI-1: Advisory triage recommendation (advisory status or 503 fallback; zero incident mutation)
#   3. Field Operations Loop:
#      - F1: Dispatcher creates tactical dispatch for verified incident (Idempotency-Key)
#      - F2: Field team responder logs in; GET /field/assignments includes dispatch
#      - F3: Responder state transitions: acknowledge -> EN_ROUTE -> ON_SCENE -> complete
#            Verifies dispatch is COMPLETED and incident remains NOT closed
#      - F4: Responder from another team receives 404 NOT_FOUND (cross-team isolation)
#   3. Donation & Payment Loop:
#      - D1: Citizen creates donation order (Idempotency-Key); verifies marked SANDBOX
#      - D2: HMAC-SHA256 signature verification confirms donation with receipt number
#      - D3: Replay verification idempotency test
#      - D4: GET /me/donations reflects receipt (switchable via SMOKE_SKIP_D4)
#   4. Webhook Security:
#      - W1: Staging webhook probe rejects tampered/invalid signature
# ==============================================================================
set -euo pipefail

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES (Single Variable Block)
# All secrets and credentials must be supplied via environment variables.
# Credentials have no defaults; the only fallback is a dummy mock-gateway secret for local compose.
# ==============================================================================
SMOKE_BASE_URL="${STAGING_URL:-${SMOKE_BASE_URL:-${API_URL:-http://localhost:8000}}}"
SMOKE_COLD_START_TIMEOUT="${SMOKE_COLD_START_TIMEOUT:-90}"

# Staff / Dispatcher Credentials (Required for verification & dispatch)
SMOKE_STAFF_EMAIL="${SMOKE_STAFF_EMAIL:-}"
SMOKE_STAFF_PASSWORD="${SMOKE_STAFF_PASSWORD:-}"
SMOKE_STAFF_TOTP_SECRET="${SMOKE_STAFF_TOTP_SECRET:-}"

# Seeded Field Team Responder 1 (Primary team for F1-F3)
SMOKE_FIELD_EMAIL="${SMOKE_FIELD_EMAIL:-}"
SMOKE_FIELD_PASSWORD="${SMOKE_FIELD_PASSWORD:-}"
SMOKE_FIELD_TOTP_SECRET="${SMOKE_FIELD_TOTP_SECRET:-}"

# Seeded Field Team Responder 2 (Different team for F4 isolation)
SMOKE_FIELD2_EMAIL="${SMOKE_FIELD2_EMAIL:-}"
SMOKE_FIELD2_PASSWORD="${SMOKE_FIELD2_PASSWORD:-}"
SMOKE_FIELD2_TOTP_SECRET="${SMOKE_FIELD2_TOTP_SECRET:-}"

# Optional Team & Agency Overrides (resolved dynamically if unset)
SMOKE_TEAM_RESOURCE_ID="${SMOKE_TEAM_RESOURCE_ID:-}"
SMOKE_TEAM_AGENCY_ID="${SMOKE_TEAM_AGENCY_ID:-}"

# Gateway & Webhook Secrets (Dummy values only; never real production secrets)
SMOKE_MOCK_GATEWAY_SECRET="${SMOKE_MOCK_GATEWAY_SECRET:-${MOCK_GATEWAY_SECRET:-dev-only-mock-gateway-secret-0123456789}}"
SMOKE_DONATION_WEBHOOK_SECRET="${SMOKE_DONATION_WEBHOOK_SECRET:-}"

# Staging Webhook Verification URL (W1)
SMOKE_STAGING_WEBHOOK_URL="${SMOKE_STAGING_WEBHOOK_URL:-}"

# Step Skip Switches (Set to 1 to bypass pending or unmerged endpoints)
SMOKE_SKIP_REGISTER="${SMOKE_SKIP_REGISTER:-0}"
SMOKE_SKIP_INCIDENT_SUBMIT="${SMOKE_SKIP_INCIDENT_SUBMIT:-0}"
SMOKE_SKIP_OUTSIDE_GUJARAT="${SMOKE_SKIP_OUTSIDE_GUJARAT:-0}"
SMOKE_SKIP_PUBLIC_UNVERIFIED="${SMOKE_SKIP_PUBLIC_UNVERIFIED:-0}"
SMOKE_SKIP_PUBLIC_VERIFIED="${SMOKE_SKIP_PUBLIC_VERIFIED:-0}"
SMOKE_SKIP_AI="${SMOKE_SKIP_AI:-0}"
SMOKE_SKIP_F1="${SMOKE_SKIP_F1:-0}"
SMOKE_SKIP_F2="${SMOKE_SKIP_F2:-0}"
SMOKE_SKIP_F3="${SMOKE_SKIP_F3:-0}"
SMOKE_SKIP_F4="${SMOKE_SKIP_F4:-0}"
SMOKE_SKIP_D1="${SMOKE_SKIP_D1:-0}"
SMOKE_SKIP_D2="${SMOKE_SKIP_D2:-0}"
SMOKE_SKIP_D3="${SMOKE_SKIP_D3:-0}"
SMOKE_SKIP_D4="${SMOKE_SKIP_D4:-1}"       # Default skipped: GET /api/v1/me/donations not merged (DEFECT-S2-16-ME-DONATIONS-404)
SMOKE_SKIP_W1="${SMOKE_SKIP_W1:-0}"

# ==============================================================================
# RUNTIME SETUP & DEPENDENCY RESOLUTION
# ==============================================================================
SMOKE_BASE_URL="${SMOKE_BASE_URL%/}"

PYTHON_BIN="python"
if ! command -v python &>/dev/null && command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
fi

if ! command -v curl &>/dev/null; then
    echo "ERROR: curl is required to run smoke tests" >&2
    exit 1
fi

TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t 'smoke-XXXXXX')"
trap 'rm -rf "$TMP_DIR"' EXIT

HTTP_RESP_FILE="${TMP_DIR}/resp.json"
HTTP_HEADERS_FILE="${TMP_DIR}/headers.txt"

PASSED=0
FAILED=0
SKIPPED=0

log() {
    echo "[SMOKE] $*"
}

pass_step() {
    local step="$1"
    local desc="$2"
    PASSED=$((PASSED + 1))
    echo "[SMOKE PASS] ${step}: ${desc}"
}

fail_step() {
    local step="$1"
    local desc="$2"
    local details="${3:-}"
    FAILED=$((FAILED + 1))
    echo "[SMOKE FAIL] ${step}: ${desc}" >&2
    if [[ -n "$details" ]]; then
        echo "             Details: ${details}" >&2
    fi
}

skip_step() {
    local step="$1"
    local desc="$2"
    local reason="${3:-skipped by configuration}"
    SKIPPED=$((SKIPPED + 1))
    echo "[SMOKE SKIP] ${step}: ${desc} (${reason})"
}

# ==============================================================================
# HELPER UTILITIES (JSON, TOTP, HMAC-SHA256, HTTP)
# ==============================================================================

# Evaluate Python expression against a JSON string or file
py_eval() {
    local json_content="$1"
    local py_expr="$2"
    "$PYTHON_BIN" -c "
import sys, json
try:
    raw = sys.argv[1]
    data = json.loads(raw) if raw else {}
    val = ${py_expr}
    if val is True:
        print('true')
    elif val is False:
        print('false')
    elif val is not None:
        print(val)
except Exception:
    sys.exit(1)
" "$json_content" 2>/dev/null || true
}

# Generate RFC 6238 TOTP token using python/pyotp
get_totp() {
    local secret="$1"
    "$PYTHON_BIN" -c "
import sys
try:
    import pyotp
    print(pyotp.TOTP(sys.argv[1]).now())
except Exception as e:
    sys.exit(1)
" "$secret" 2>/dev/null || ""
}

# Compute HMAC-SHA256 signature in hexadecimal
get_hmac_sha256() {
    local secret="$1"
    local message="$2"
    "$PYTHON_BIN" -c "
import sys, hmac, hashlib
s = sys.argv[1].encode('utf-8')
m = sys.argv[2].encode('utf-8')
print(hmac.new(s, m, hashlib.sha256).hexdigest())
" "$secret" "$message" 2>/dev/null || ""
}

# Generate unique UUID string
get_uuid() {
    "$PYTHON_BIN" -c "import uuid; print(uuid.uuid4())" 2>/dev/null || date +%s%N
}

# Core HTTP request execution
# Usage: do_request METHOD ENDPOINT [AUTH_TOKEN] [IDEMPOTENCY_KEY] [JSON_PAYLOAD]
LAST_HTTP_CODE=0
do_request() {
    local method="$1"
    local endpoint="$2"
    local auth_token="${3:-}"
    local idemp_key="${4:-}"
    local json_payload="${5:-}"

    local url
    if [[ "$endpoint" =~ ^https?:// ]]; then
        url="$endpoint"
    else
        url="${SMOKE_BASE_URL}${endpoint}"
    fi
    : > "$HTTP_RESP_FILE"
    : > "$HTTP_HEADERS_FILE"

    local curl_cmd=(curl -s -S --connect-timeout 10 --max-time 30 -X "$method" "$url" -D "$HTTP_HEADERS_FILE" -o "$HTTP_RESP_FILE" -w "%{http_code}")
    curl_cmd+=(-H "Accept: application/json")

    if [[ -n "$auth_token" ]]; then
        curl_cmd+=(-H "Authorization: Bearer ${auth_token}")
    fi
    if [[ -n "$idemp_key" ]]; then
        curl_cmd+=(-H "Idempotency-Key: ${idemp_key}")
    fi
    if [[ -n "$json_payload" ]]; then
        curl_cmd+=(-H "Content-Type: application/json" --data "$json_payload")
    fi

    local code
    code="$("${curl_cmd[@]}" 2>/dev/null || echo "000")"
    LAST_HTTP_CODE="$code"
}

get_resp_body() {
    cat "$HTTP_RESP_FILE" 2>/dev/null || echo "{}"
}

# ==============================================================================
# PRE-FLIGHT CREDENTIAL VALIDATION
# ==============================================================================
log "Starting ResQ smoke verification against target: ${SMOKE_BASE_URL}"

HAVE_STAFF_CREDS=1
if [[ -z "${SMOKE_STAFF_EMAIL:-}" || -z "${SMOKE_STAFF_PASSWORD:-}" || -z "${SMOKE_STAFF_TOTP_SECRET:-}" ]]; then
    log "NOTICE: Staff credentials not fully provided; dispatcher verification and dispatch steps will be recorded as blocked."
    HAVE_STAFF_CREDS=0
fi

# ==============================================================================
# PART 1: CORE DISASTER REPORTING & VERIFICATION LOOP
# ==============================================================================

# 1. Health & Database Connectivity (wait-and-retry up to 90s for cold start)
log "Probing target readiness at ${SMOKE_BASE_URL} (polling up to ${SMOKE_COLD_START_TIMEOUT}s for cold start)..."
POLL_START=$(date +%s)
HEALTHY=0
COLD_START_TIME=0
LIVENESS_CODE="000"
READINESS_CODE="000"
DB_STATUS=""

while true; do
    do_request "GET" "/health"
    LIVENESS_CODE="$LAST_HTTP_CODE"

    do_request "GET" "/api/v1/health"
    READINESS_CODE="$LAST_HTTP_CODE"
    DB_STATUS="$(py_eval "$(get_resp_body)" "data.get('database')")"

    if [[ "$LIVENESS_CODE" -eq 200 && "$READINESS_CODE" -eq 200 && "$DB_STATUS" == "ok" ]]; then
        HEALTHY=1
        break
    fi

    # Fallback to /health/ready if defined
    do_request "GET" "/health/ready"
    if [[ "$LAST_HTTP_CODE" -eq 200 ]]; then
        HEALTHY=1
        break
    fi

    NOW=$(date +%s)
    ELAPSED=$((NOW - POLL_START))
    if [[ $ELAPSED -ge $SMOKE_COLD_START_TIMEOUT ]]; then
        break
    fi
    log "Target not ready yet (Liveness: ${LIVENESS_CODE}, Readiness: ${READINESS_CODE}, DB: ${DB_STATUS:-unknown}). Retrying in 3s (${ELAPSED}s elapsed)..."
    sleep 3
done

POLL_END=$(date +%s)
COLD_START_TIME=$((POLL_END - POLL_START))

if [[ "$HEALTHY" -eq 1 ]]; then
    pass_step "CORE-1" "Service liveness and database readiness verified (ready in ${COLD_START_TIME}s)"
else
    fail_step "CORE-1" "Readiness probe failed after ${COLD_START_TIME}s timeout" "HTTP liveness=${LIVENESS_CODE}, readiness=${READINESS_CODE}, database=${DB_STATUS:-unknown}"
fi

# 2. Citizen Registration
CITIZEN_TOKEN=""
if [[ "$SMOKE_SKIP_REGISTER" == "1" ]]; then
    skip_step "CORE-2" "Citizen registration" "SMOKE_SKIP_REGISTER=1"
else
    CITIZEN_EMAIL="smoke.citizen.$(get_uuid | cut -c1-8)@example.in"
    CITIZEN_PASS="SmokePass2026!#"
    REG_PAYLOAD="{\"email\": \"${CITIZEN_EMAIL}\", \"password\": \"${CITIZEN_PASS}\", \"full_name\": \"Smoke Citizen Responder\"}"
    do_request "POST" "/api/v1/auth/register" "" "" "$REG_PAYLOAD"
    if [[ "$LAST_HTTP_CODE" -eq 201 ]]; then
        CITIZEN_TOKEN="$(py_eval "$(get_resp_body)" "data.get('access_token')")"
        pass_step "CORE-2" "Citizen registered with compliant password"
    else
        fail_step "CORE-2" "Citizen registration failed" "HTTP ${LAST_HTTP_CODE}: $(get_resp_body | cut -c1-200)"
    fi
fi

# 3. Incident Submission & Idempotent Replay
INCIDENT_ID=""
INCIDENT_REF=""
if [[ "$SMOKE_SKIP_INCIDENT_SUBMIT" == "1" || -z "$CITIZEN_TOKEN" ]]; then
    skip_step "CORE-3" "Gujarat incident submission & idempotency replay" "SMOKE_SKIP_INCIDENT_SUBMIT=1 or missing citizen token"
else
    INC_KEY="smoke-inc-$(get_uuid)"
    INC_PAYLOAD="{\"scenario\": \"urban_flooding\", \"description\": \"Smoke test: Road flooded at Subhash Bridge approach.\", \"reported_urgency\": \"HIGH\", \"people_affected\": 8, \"location_source\": \"GPS\", \"latitude\": 23.0610, \"longitude\": 72.5810, \"address_text\": \"Subhash Bridge, Ahmedabad\"}"
    do_request "POST" "/api/v1/incidents" "$CITIZEN_TOKEN" "$INC_KEY" "$INC_PAYLOAD"
    if [[ "$LAST_HTTP_CODE" -eq 201 ]]; then
        INCIDENT_ID="$(py_eval "$(get_resp_body)" "data.get('incident_id')")"
        INCIDENT_REF="$(py_eval "$(get_resp_body)" "data.get('incident_ref')")"
        # Replay same payload with identical key
        do_request "POST" "/api/v1/incidents" "$CITIZEN_TOKEN" "$INC_KEY" "$INC_PAYLOAD"
        REPLAY_ID="$(py_eval "$(get_resp_body)" "data.get('incident_id')")"
        if [[ "$LAST_HTTP_CODE" -eq 200 && "$REPLAY_ID" == "$INCIDENT_ID" ]]; then
            pass_step "CORE-3" "Gujarat incident submitted and idempotency replay confirmed"
        else
            fail_step "CORE-3" "Idempotent replay failed" "HTTP ${LAST_HTTP_CODE}, replay_id=${REPLAY_ID}"
        fi
    else
        fail_step "CORE-3" "Incident submission failed" "HTTP ${LAST_HTTP_CODE}: $(get_resp_body | cut -c1-200)"
    fi
fi

# 4. Out-of-State Boundary Check (Refused 422 OUTSIDE_GUJARAT)
if [[ "$SMOKE_SKIP_OUTSIDE_GUJARAT" == "1" || -z "$CITIZEN_TOKEN" ]]; then
    skip_step "CORE-4" "Out-of-state incident rejection" "SMOKE_SKIP_OUTSIDE_GUJARAT=1 or missing citizen token"
else
    OUTSIDE_PAYLOAD="{\"scenario\": \"urban_flooding\", \"description\": \"Jaipur test.\", \"reported_urgency\": \"HIGH\", \"people_affected\": 2, \"location_source\": \"GPS\", \"latitude\": 26.9124, \"longitude\": 75.7873, \"address_text\": \"Jaipur, Rajasthan\"}"
    do_request "POST" "/api/v1/incidents" "$CITIZEN_TOKEN" "smoke-outside-$(date +%s)-$RANDOM" "$OUTSIDE_PAYLOAD"
    ERR_CODE="$(py_eval "$(get_resp_body)" "data.get('error', {}).get('code')")"
    if [[ "$LAST_HTTP_CODE" -eq 422 && "$ERR_CODE" == "OUTSIDE_GUJARAT" ]]; then
        pass_step "CORE-4" "Out-of-state incident refused with 422 OUTSIDE_GUJARAT"
    else
        fail_step "CORE-4" "Out-of-state incident was not properly refused" "HTTP ${LAST_HTTP_CODE}, error=${ERR_CODE}"
    fi
fi

# 5. Public Map Isolation for Unverified Incident
if [[ "$SMOKE_SKIP_PUBLIC_UNVERIFIED" == "1" || -z "$INCIDENT_REF" ]]; then
    skip_step "CORE-5" "Unverified incident map isolation" "SMOKE_SKIP_PUBLIC_UNVERIFIED=1 or missing incident ref"
else
    do_request "GET" "/api/v1/public/incidents"
    IS_PRESENT="$(py_eval "$(get_resp_body)" "'${INCIDENT_REF}' in [i.get('reference') for i in data]")"
    if [[ "$LAST_HTTP_CODE" -eq 200 && "$IS_PRESENT" != "true" ]]; then
        pass_step "CORE-5" "Unverified incident is strictly absent from public map feed"
    else
        fail_step "CORE-5" "Unverified incident leaked to public feed" "present=${IS_PRESENT}"
    fi
fi

# 6. Dispatcher Sign-In (Password + TOTP) & Incident Verification
STAFF_TOKEN=""
if [[ -z "$INCIDENT_ID" ]]; then
    skip_step "CORE-6" "Dispatcher verification" "Missing incident ID from submission step"
elif [[ "$HAVE_STAFF_CREDS" -eq 0 ]]; then
    skip_step "CORE-6" "Dispatcher verification" "Staff credentials (SMOKE_STAFF_*) not provided"
else
    LOGIN_PAYLOAD="{\"email\": \"${SMOKE_STAFF_EMAIL}\", \"password\": \"${SMOKE_STAFF_PASSWORD}\"}"
    do_request "POST" "/api/v1/auth/login" "" "" "$LOGIN_PAYLOAD"
    MFA_REQUIRED="$(py_eval "$(get_resp_body)" "data.get('mfa_required')")"
    MFA_CHALLENGE="$(py_eval "$(get_resp_body)" "data.get('mfa_token')")"

    if [[ "$LAST_HTTP_CODE" -eq 200 && "$MFA_REQUIRED" == "true" && -n "$MFA_CHALLENGE" ]]; then
        TOTP_CODE="$(get_totp "$SMOKE_STAFF_TOTP_SECRET")"
        MFA_PAYLOAD="{\"mfa_token\": \"${MFA_CHALLENGE}\", \"code\": \"${TOTP_CODE}\"}"
        do_request "POST" "/api/v1/auth/mfa/verify" "" "" "$MFA_PAYLOAD"
        if [[ "$LAST_HTTP_CODE" -eq 200 ]]; then
            STAFF_TOKEN="$(py_eval "$(get_resp_body)" "data.get('access_token')")"
        fi
    fi

    if [[ -n "$STAFF_TOKEN" ]]; then
        do_request "GET" "/api/v1/dm/incidents/${INCIDENT_ID}" "$STAFF_TOKEN"
        INC_VERSION="$(py_eval "$(get_resp_body)" "data.get('version')")"
        VERIFY_PAYLOAD="{\"decision\": \"VERIFIED\", \"rationale\": \"Smoke test verification passed\", \"priority\": \"HIGH\", \"version\": ${INC_VERSION:-1}}"
        do_request "POST" "/api/v1/dm/incidents/${INCIDENT_ID}/verification" "$STAFF_TOKEN" "" "$VERIFY_PAYLOAD"
        if [[ "$LAST_HTTP_CODE" -eq 200 ]]; then
            pass_step "CORE-6" "Dispatcher authenticated via MFA and verified incident"
        else
            fail_step "CORE-6" "Incident verification failed" "HTTP ${LAST_HTTP_CODE}: $(get_resp_body | cut -c1-200)"
        fi
    else
        fail_step "CORE-6" "Dispatcher authentication or MFA verification failed" "HTTP ${LAST_HTTP_CODE}"
    fi
fi

# 7. Public Map Presence for Verified Incident (No PII, <= 4 decimals)
if [[ "$SMOKE_SKIP_PUBLIC_VERIFIED" == "1" || -z "$INCIDENT_REF" ]]; then
    skip_step "CORE-7" "Public map verification check" "SMOKE_SKIP_PUBLIC_VERIFIED=1 or missing incident ref"
else
    do_request "GET" "/api/v1/public/incidents"
    CHECK_RESULT="$("$PYTHON_BIN" -c "
import sys, json
try:
    data = json.loads(sys.argv[1])
    ref = sys.argv[2]
    mine = [i for i in data if i.get('reference') == ref]
    if not mine:
        print('NOT_FOUND')
    else:
        item = mine[0]
        pii_keys = {'reporter_id', 'reporter_name', 'reporter_phone', 'description', 'address_text', 'incident_id', 'email', 'phone'}
        if pii_keys & set(item.keys()):
            print('PII_LEAK')
        else:
            coord_err = False
            for f in ('latitude', 'longitude'):
                parts = str(item.get(f, '')).split('.')
                if len(parts) > 1 and len(parts[1]) > 4:
                    coord_err = True
                    break
            if coord_err:
                print('COORD_PRECISION_EXCEEDED')
            else:
                print('OK')
except Exception as e:
    print('ERROR:' + str(e))
" "$(get_resp_body)" "$INCIDENT_REF")"

    if [[ "$LAST_HTTP_CODE" -eq 200 && "$CHECK_RESULT" == "OK" ]]; then
        pass_step "CORE-7" "Verified incident visible on public feed with 4-decimal precision and zero PII"
    else
        fail_step "CORE-7" "Public map check failed" "result=${CHECK_RESULT}"
    fi
fi

# 8. Citizen Timeline Validation
if [[ -z "$CITIZEN_TOKEN" || -z "$INCIDENT_ID" ]]; then
    skip_step "CORE-8" "Citizen timeline validation" "Missing citizen token or incident ID"
else
    do_request "GET" "/api/v1/me/incidents/${INCIDENT_ID}" "$CITIZEN_TOKEN"
    TL_STATUSES="$(py_eval "$(get_resp_body)" "','.join([t.get('status') for t in data.get('timeline', [])])")"
    if [[ "$LAST_HTTP_CODE" -eq 200 && "$TL_STATUSES" == *"SUBMITTED"* && "$TL_STATUSES" == *"VERIFIED"* ]]; then
        pass_step "CORE-8" "Citizen timeline correctly recorded SUBMITTED and VERIFIED milestones"
    else
        fail_step "CORE-8" "Citizen timeline invalid" "statuses=${TL_STATUSES}"
    fi
fi

# ==============================================================================
# AI ADVISORY TRIAGE GATE (AI-1)
# ==============================================================================
if [[ "$SMOKE_SKIP_AI" == "1" ]]; then
    skip_step "AI-1" "AI advisory triage check" "SMOKE_SKIP_AI=1"
elif [[ -z "$STAFF_TOKEN" || -z "$INCIDENT_ID" ]]; then
    skip_step "AI-1" "AI advisory triage check" "Missing staff token or incident ID"
else
    # Query incident before triage to compare state and priority
    do_request "GET" "/api/v1/dm/incidents/${INCIDENT_ID}" "$STAFF_TOKEN"
    PRE_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"
    PRE_PRIORITY="$(py_eval "$(get_resp_body)" "data.get('priority')")"

    do_request "POST" "/api/v1/dm/incidents/${INCIDENT_ID}/ai-triage" "$STAFF_TOKEN"
    AI_HTTP_CODE="$LAST_HTTP_CODE"
    AI_STATUS="$(py_eval "$(get_resp_body)" "data.get('status') or data.get('error', {}).get('code')")"

    # Query incident after triage to verify state and priority remain unchanged
    do_request "GET" "/api/v1/dm/incidents/${INCIDENT_ID}" "$STAFF_TOKEN"
    POST_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"
    POST_PRIORITY="$(py_eval "$(get_resp_body)" "data.get('priority')")"

    STATUS_UNCHANGED="false"
    if [[ "$PRE_STATUS" == "$POST_STATUS" && "$PRE_PRIORITY" == "$POST_PRIORITY" ]]; then
        STATUS_UNCHANGED="true"
    fi

    if [[ "$AI_HTTP_CODE" -eq 200 && ( "$AI_STATUS" == "GENERATED" || "$AI_STATUS" == "LOW_CONFIDENCE" ) && "$STATUS_UNCHANGED" == "true" ]]; then
        pass_step "AI-1" "AI advisory triage returned recommendation (${AI_STATUS}) with zero incident mutation"
    elif [[ "$AI_HTTP_CODE" -eq 503 && "$AI_STATUS" == "AI_UNAVAILABLE" && "$STATUS_UNCHANGED" == "true" ]]; then
        pass_step "AI-1" "AI service unavailable (503 AI_UNAVAILABLE recorded), incident status and priority preserved"
    else
        fail_step "AI-1" "AI advisory triage check failed" "HTTP ${AI_HTTP_CODE}, status=${AI_STATUS}, pre_status=${PRE_STATUS}, post_status=${POST_STATUS}"
    fi
fi

# ==============================================================================
# PART 2: FIELD OPERATIONS LIFECYCLE (F1 - F4)
# ==============================================================================

FIELD_TOKEN=""
FIELD_RESOURCE_ID="$SMOKE_TEAM_RESOURCE_ID"
FIELD_AGENCY_ID="$SMOKE_TEAM_AGENCY_ID"

# Authenticate primary field responder if credentials provided
if [[ -n "$SMOKE_FIELD_EMAIL" && -n "$SMOKE_FIELD_PASSWORD" ]]; then
    do_request "POST" "/api/v1/auth/login" "" "" "{\"email\": \"${SMOKE_FIELD_EMAIL}\", \"password\": \"${SMOKE_FIELD_PASSWORD}\"}"
    if [[ "$LAST_HTTP_CODE" -eq 200 ]]; then
        MFA_REQ="$(py_eval "$(get_resp_body)" "data.get('mfa_required')")"
        if [[ "$MFA_REQ" == "true" ]]; then
            TOTP_CODE="$(get_totp "${SMOKE_FIELD_TOTP_SECRET:-}")"
            do_request "POST" "/api/v1/auth/mfa/verify" "" "" "{\"mfa_token\": \"$(py_eval "$(get_resp_body)" "data.get('mfa_token')")\", \"code\": \"${TOTP_CODE}\"}"
            FIELD_TOKEN="$(py_eval "$(get_resp_body)" "data.get('access_token')")"
        else
            FIELD_TOKEN="$(py_eval "$(get_resp_body)" "data.get('access_token')")"
        fi
    fi

    # Retrieve profile to extract team binding and agency
    if [[ -n "$FIELD_TOKEN" && ( -z "$FIELD_RESOURCE_ID" || -z "$FIELD_AGENCY_ID" ) ]]; then
        do_request "GET" "/api/v1/field/me" "$FIELD_TOKEN"
        if [[ "$LAST_HTTP_CODE" -eq 200 ]]; then
            FIELD_RESOURCE_ID="${FIELD_RESOURCE_ID:-$(py_eval "$(get_resp_body)" "data.get('team_resource_id')")}"
            FIELD_AGENCY_ID="${FIELD_AGENCY_ID:-$(py_eval "$(get_resp_body)" "data.get('agency_id')")}"
        fi
    fi
fi

# Fallback: if field user not set or team not resolved, query available teams via DM API
if [[ -n "$STAFF_TOKEN" && ( -z "$FIELD_RESOURCE_ID" || -z "$FIELD_AGENCY_ID" ) ]]; then
    do_request "GET" "/api/v1/dm/resources?type=TEAM&status=AVAILABLE" "$STAFF_TOKEN"
    if [[ "$LAST_HTTP_CODE" -eq 200 ]]; then
        FIELD_RESOURCE_ID="${FIELD_RESOURCE_ID:-$(py_eval "$(get_resp_body)" "data.get('items', [{}])[0].get('resource_id')")}"
        FIELD_AGENCY_ID="${FIELD_AGENCY_ID:-$(py_eval "$(get_resp_body)" "data.get('items', [{}])[0].get('agency_id')")}"
    fi
fi

DISPATCH_ID=""

# F1: Dispatcher Creates Dispatch for Verified Incident (Idempotency-Key)
if [[ "$SMOKE_SKIP_F1" == "1" || -z "$STAFF_TOKEN" || -z "$INCIDENT_ID" || -z "$FIELD_RESOURCE_ID" || -z "$FIELD_AGENCY_ID" ]]; then
    skip_step "F1" "Dispatcher creates dispatch" "SMOKE_SKIP_F1=1 or missing required IDs (staff/incident/team/agency)"
else
    DISP_KEY="smoke-disp-$(get_uuid)"
    DISP_PAYLOAD="{\"receiving_agency_id\": \"${FIELD_AGENCY_ID}\", \"instructions\": \"Smoke test: Deploy response unit to Subhash Bridge sector.\", \"priority\": \"HIGH\", \"resources\": [{\"resource_id\": \"${FIELD_RESOURCE_ID}\", \"quantity\": 1}]}"
    do_request "POST" "/api/v1/dm/incidents/${INCIDENT_ID}/dispatches" "$STAFF_TOKEN" "$DISP_KEY" "$DISP_PAYLOAD"
    if [[ "$LAST_HTTP_CODE" -eq 201 || "$LAST_HTTP_CODE" -eq 200 ]]; then
        DISPATCH_ID="$(py_eval "$(get_resp_body)" "data.get('dispatch_id')")"
        pass_step "F1" "Dispatcher created tactical dispatch order for verified incident"
    else
        fail_step "F1" "Dispatcher dispatch creation failed" "HTTP ${LAST_HTTP_CODE}: $(get_resp_body | cut -c1-200)"
    fi
fi

# F2: Field User Logs In & Receives Assignment
if [[ "$SMOKE_SKIP_F2" == "1" || -z "$FIELD_TOKEN" || -z "$DISPATCH_ID" ]]; then
    skip_step "F2" "Field user assignment retrieval" "SMOKE_SKIP_F2=1 or missing field token / dispatch ID"
else
    do_request "GET" "/api/v1/field/assignments" "$FIELD_TOKEN"
    HAS_DISPATCH="$(py_eval "$(get_resp_body)" "'${DISPATCH_ID}' in [str(a.get('dispatch_id')) for a in data]")"
    if [[ "$LAST_HTTP_CODE" -eq 200 && "$HAS_DISPATCH" == "true" ]]; then
        pass_step "F2" "Field user authenticated and assignment listed in GET /field/assignments"
    else
        fail_step "F2" "Assignment not found in field assignments" "HTTP ${LAST_HTTP_CODE}, found=${HAS_DISPATCH}"
    fi
fi

# F3: Operational Progression (acknowledge -> EN_ROUTE -> ON_SCENE -> complete)
if [[ "$SMOKE_SKIP_F3" == "1" || -z "$FIELD_TOKEN" || -z "$DISPATCH_ID" ]]; then
    skip_step "F3" "Field operational progress & mission completion" "SMOKE_SKIP_F3=1 or missing field token / dispatch ID"
else
    # 1. Acknowledge
    do_request "POST" "/api/v1/field/dispatches/${DISPATCH_ID}/acknowledgement" "$FIELD_TOKEN"
    ACK_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"

    # 2. Progress: EN_ROUTE
    do_request "POST" "/api/v1/field/dispatches/${DISPATCH_ID}/progress" "$FIELD_TOKEN" "" "{\"status\": \"EN_ROUTE\", \"note\": \"Smoke unit rolling to site\"}"
    EN_ROUTE_OK="$([[ "$LAST_HTTP_CODE" -eq 200 ]] && echo "true" || echo "false")"

    # 3. Progress: ON_SCENE
    do_request "POST" "/api/v1/field/dispatches/${DISPATCH_ID}/progress" "$FIELD_TOKEN" "" "{\"status\": \"ON_SCENE\", \"note\": \"Smoke unit on scene assessing\"}"
    ON_SCENE_OK="$([[ "$LAST_HTTP_CODE" -eq 200 ]] && echo "true" || echo "false")"

    # 4. Completion
    COMP_PAYLOAD="{\"summary\": \"Smoke test mission complete: area stabilized.\", \"civilians_evacuated\": 5, \"civilians_treated\": 1}"
    do_request "POST" "/api/v1/field/dispatches/${DISPATCH_ID}/completion" "$FIELD_TOKEN" "" "$COMP_PAYLOAD"
    COMP_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"

    # Verify dispatch status is COMPLETED and incident remains open (NOT closed)
    DISP_FINAL_STATUS=""
    INC_FINAL_STATUS=""
    if [[ -n "$STAFF_TOKEN" ]]; then
        do_request "GET" "/api/v1/dm/dispatches/${DISPATCH_ID}" "$STAFF_TOKEN"
        DISP_FINAL_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"
        do_request "GET" "/api/v1/dm/incidents/${INCIDENT_ID}" "$STAFF_TOKEN"
        INC_FINAL_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"
    fi

    if [[ "$ACK_STATUS" == "ACKNOWLEDGED" && "$EN_ROUTE_OK" == "true" && "$ON_SCENE_OK" == "true" && "$COMP_STATUS" == "COMPLETED" && "$INC_FINAL_STATUS" != "CLOSED" ]]; then
        pass_step "F3" "Tactical flow acknowledged -> EN_ROUTE -> ON_SCENE -> COMPLETED (incident NOT closed)"
    else
        fail_step "F3" "Field lifecycle transitions failed" "ack=${ACK_STATUS}, comp=${COMP_STATUS}, incident_status=${INC_FINAL_STATUS}"
    fi
fi

# F4: Cross-Team Isolation (Second field responder gets 404 on dispatch)
if [[ "$SMOKE_SKIP_F4" == "1" || -z "$SMOKE_FIELD2_EMAIL" || -z "$SMOKE_FIELD2_PASSWORD" || -z "$DISPATCH_ID" ]]; then
    skip_step "F4" "Cross-team dispatch isolation" "SMOKE_SKIP_F4=1 or SMOKE_FIELD2_EMAIL not configured"
else
    FIELD2_TOKEN=""
    do_request "POST" "/api/v1/auth/login" "" "" "{\"email\": \"${SMOKE_FIELD2_EMAIL}\", \"password\": \"${SMOKE_FIELD2_PASSWORD}\"}"
    if [[ "$LAST_HTTP_CODE" -eq 200 ]]; then
        MFA2_REQ="$(py_eval "$(get_resp_body)" "data.get('mfa_required')")"
        if [[ "$MFA2_REQ" == "true" ]]; then
            TOTP2_CODE="$(get_totp "${SMOKE_FIELD2_TOTP_SECRET:-}")"
            do_request "POST" "/api/v1/auth/mfa/verify" "" "" "{\"mfa_token\": \"$(py_eval "$(get_resp_body)" "data.get('mfa_token')")\", \"code\": \"${TOTP2_CODE}\"}"
            FIELD2_TOKEN="$(py_eval "$(get_resp_body)" "data.get('access_token')")"
        else
            FIELD2_TOKEN="$(py_eval "$(get_resp_body)" "data.get('access_token')")"
        fi
    fi

    if [[ -n "$FIELD2_TOKEN" ]]; then
        do_request "POST" "/api/v1/field/dispatches/${DISPATCH_ID}/acknowledgement" "$FIELD2_TOKEN"
        if [[ "$LAST_HTTP_CODE" -eq 404 ]]; then
            pass_step "F4" "Second field team strictly refused with 404 NOT_FOUND on foreign dispatch"
        else
            fail_step "F4" "Cross-team isolation violated" "Expected HTTP 404, got ${LAST_HTTP_CODE}"
        fi
    else
        fail_step "F4" "Second field responder authentication failed" "HTTP ${LAST_HTTP_CODE}"
    fi
fi

# ==============================================================================
# PART 3: CITIZEN DONATION & PAYMENT VERIFICATION (D1 - D4)
# ==============================================================================

DONATION_ID=""
GATEWAY_ORDER_ID=""
ACTIVE_CAMPAIGN_ID=""

# D1: Citizen Creates Donation Order (Marked SANDBOX)
if [[ "$SMOKE_SKIP_D1" == "1" || -z "$CITIZEN_TOKEN" ]]; then
    skip_step "D1" "Citizen donation order creation" "SMOKE_SKIP_D1=1 or missing citizen token"
else
    do_request "GET" "/api/v1/public/campaigns"
    ACTIVE_CAMPAIGN_ID="$(py_eval "$(get_resp_body)" "data[0].get('campaign_id') if data else ''")"

    if [[ -n "$ACTIVE_CAMPAIGN_ID" ]]; then
        DON_KEY="smoke-don-$(get_uuid)"
        DON_PAYLOAD="{\"campaign_id\": \"${ACTIVE_CAMPAIGN_ID}\", \"amount\": 500.00, \"currency\": \"INR\"}"
        do_request "POST" "/api/v1/donations" "$CITIZEN_TOKEN" "$DON_KEY" "$DON_PAYLOAD"
        IS_SANDBOX="$(py_eval "$(get_resp_body)" "data.get('is_sandbox')")"
        DON_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"
        DONATION_ID="$(py_eval "$(get_resp_body)" "data.get('donation_id')")"
        GATEWAY_ORDER_ID="$(py_eval "$(get_resp_body)" "data.get('gateway_order_id')")"

        if [[ "$LAST_HTTP_CODE" -eq 201 && "$IS_SANDBOX" == "true" && "$DON_STATUS" == "PENDING" && -n "$DONATION_ID" ]]; then
            pass_step "D1" "Donation order created with Idempotency-Key; response marked is_sandbox=true"
        else
            fail_step "D1" "Donation order creation failed" "HTTP ${LAST_HTTP_CODE}, sandbox=${IS_SANDBOX}, status=${DON_STATUS}"
        fi
    else
        fail_step "D1" "No active donation campaign found in GET /api/v1/public/campaigns"
    fi
fi

# D2: Verify with Valid HMAC-SHA256 Signature (CONFIRMED with Receipt Number)
RECEIPT_NO=""
GATEWAY_PAYMENT_ID=""
VALID_SIGNATURE=""
if [[ "$SMOKE_SKIP_D2" == "1" || -z "$CITIZEN_TOKEN" || -z "$DONATION_ID" || -z "$GATEWAY_ORDER_ID" ]]; then
    skip_step "D2" "Donation signature verification" "SMOKE_SKIP_D2=1 or missing donation order details"
else
    GATEWAY_PAYMENT_ID="pay_mock_$(get_uuid | tr -d '-' | cut -c1-12)"
    VALID_SIGNATURE="$(get_hmac_sha256 "$SMOKE_MOCK_GATEWAY_SECRET" "${GATEWAY_ORDER_ID}|${GATEWAY_PAYMENT_ID}")"
    VERIFY_PAYLOAD="{\"gateway_payment_id\": \"${GATEWAY_PAYMENT_ID}\", \"signature\": \"${VALID_SIGNATURE}\"}"

    do_request "POST" "/api/v1/donations/${DONATION_ID}/verify" "$CITIZEN_TOKEN" "" "$VERIFY_PAYLOAD"
    VERIFY_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"
    RECEIPT_NO="$(py_eval "$(get_resp_body)" "data.get('receipt_no')")"

    if [[ "$LAST_HTTP_CODE" -eq 200 && "$VERIFY_STATUS" == "CONFIRMED" && -n "$RECEIPT_NO" ]]; then
        pass_step "D2" "Donation verified with valid HMAC signature; status CONFIRMED with receipt ${RECEIPT_NO}"
    else
        fail_step "D2" "Donation verification failed" "HTTP ${LAST_HTTP_CODE}, status=${VERIFY_STATUS}, receipt=${RECEIPT_NO}"
    fi
fi

# D3: Idempotent Verification Replay
if [[ "$SMOKE_SKIP_D3" == "1" || -z "$CITIZEN_TOKEN" || -z "$DONATION_ID" || -z "$RECEIPT_NO" ]]; then
    skip_step "D3" "Donation verification replay" "SMOKE_SKIP_D3=1 or missing receipt number from D2"
else
    REPLAY_VERIFY_PAYLOAD="{\"gateway_payment_id\": \"${GATEWAY_PAYMENT_ID}\", \"signature\": \"${VALID_SIGNATURE}\"}"
    do_request "POST" "/api/v1/donations/${DONATION_ID}/verify" "$CITIZEN_TOKEN" "" "$REPLAY_VERIFY_PAYLOAD"
    REPLAY_RECEIPT="$(py_eval "$(get_resp_body)" "data.get('receipt_no')")"
    REPLAY_STATUS="$(py_eval "$(get_resp_body)" "data.get('status')")"

    if [[ "$LAST_HTTP_CODE" -eq 200 && "$REPLAY_RECEIPT" == "$RECEIPT_NO" && "$REPLAY_STATUS" == "CONFIRMED" ]]; then
        pass_step "D3" "Replay of verified payment returns identical receipt number without state drift"
    else
        fail_step "D3" "Donation verify replay failed" "HTTP ${LAST_HTTP_CODE}, receipt=${REPLAY_RECEIPT}"
    fi
fi

# D4: Citizen Donations Feed (GET /api/v1/me/donations)
if [[ "$SMOKE_SKIP_D4" == "1" ]]; then
    skip_step "D4" "Citizen donations feed (GET /me/donations)" "SMOKE_SKIP_D4=1 (Pending backend route: DEFECT-S2-16-ME-DONATIONS-404)"
elif [[ -z "$CITIZEN_TOKEN" || -z "$RECEIPT_NO" ]]; then
    skip_step "D4" "Citizen donations feed" "Missing citizen token or receipt number"
else
    do_request "GET" "/api/v1/me/donations" "$CITIZEN_TOKEN"
    HAS_RECEIPT="$(py_eval "$(get_resp_body)" "'${RECEIPT_NO}' in [d.get('receipt_no') for d in data]")"
    if [[ "$LAST_HTTP_CODE" -eq 200 && "$HAS_RECEIPT" == "true" ]]; then
        pass_step "D4" "GET /me/donations includes issued receipt ${RECEIPT_NO}"
    else
        fail_step "D4" "Receipt not listed in GET /me/donations" "HTTP ${LAST_HTTP_CODE}, found=${HAS_RECEIPT}"
    fi
fi

# ==============================================================================
# PART 4: WEBHOOK SECURITY CHECK (W1)
# ==============================================================================

# W1: Staging Webhook Invalid Signature Refusal
if [[ "$SMOKE_SKIP_W1" == "1" ]]; then
    skip_step "W1" "Staging webhook endpoint security check" "SMOKE_SKIP_W1=1"
else
    WEBHOOK_TARGET="${SMOKE_STAGING_WEBHOOK_URL:-${SMOKE_BASE_URL}/api/v1/payments/webhook/razorpay}"
    if [[ ! "$WEBHOOK_TARGET" =~ ^https?:// ]]; then
        WEBHOOK_TARGET="${SMOKE_BASE_URL}${WEBHOOK_TARGET}"
    fi

    log "Checking webhook security at ${WEBHOOK_TARGET} with tampered signature..."
    : > "$HTTP_RESP_FILE"
    : > "$HTTP_HEADERS_FILE"

    # Send request with invalid HMAC signature (never send valid signature or real secrets)
    LAST_HTTP_CODE="$(curl -s -S --connect-timeout 10 --max-time 30 -X POST "$WEBHOOK_TARGET" \
        -D "$HTTP_HEADERS_FILE" -o "$HTTP_RESP_FILE" -w "%{http_code}" \
        -H "Accept: application/json" \
        -H "Content-Type: application/json" \
        -H "X-Razorpay-Signature: invalid_sig_probe_only_test_0000000000000000000000000000000000000000" \
        -H "X-Signature: invalid_sig_probe_only_test_0000000000000000000000000000000000000000" \
        --data '{"event": "payment.authorized", "payload": {}}' 2>/dev/null || echo "000")"

    # Refusal expected from reachable & secured endpoint: 400, 401, 403, or 422
    # If unmounted (e.g. DEFECT-S2-16-WEBHOOK-404): returns 404
    # If 200/201: SECURITY FAULT (accepted invalid signature)
    if [[ "$LAST_HTTP_CODE" -eq 400 || "$LAST_HTTP_CODE" -eq 401 || "$LAST_HTTP_CODE" -eq 403 || "$LAST_HTTP_CODE" -eq 422 ]]; then
        pass_step "W1" "Webhook endpoint verified reachable and secured against invalid signature (HTTP ${LAST_HTTP_CODE})"
    elif [[ "$LAST_HTTP_CODE" -eq 404 ]]; then
        fail_step "W1" "Webhook endpoint unmounted (HTTP 404 - DEFECT-S2-16-WEBHOOK-404, Owner: Shlok)"
    elif [[ "$LAST_HTTP_CODE" -ge 200 && "$LAST_HTTP_CODE" -lt 300 ]]; then
        fail_step "W1" "SECURITY CRITICAL: Webhook accepted payload with invalid signature" "HTTP ${LAST_HTTP_CODE}"
    else
        fail_step "W1" "Webhook endpoint check failed" "HTTP ${LAST_HTTP_CODE}"
    fi
fi

# ==============================================================================
# SUMMARY & EXIT STATUS
# ==============================================================================
echo ""
log "Test Execution Finished: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"
echo "${PASSED} passed, ${FAILED} failed"

if [[ "$FAILED" -gt 0 ]]; then
    exit 1
fi

exit 0
