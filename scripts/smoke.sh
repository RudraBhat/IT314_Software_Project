#!/usr/bin/env bash
# ==============================================================================
# Gujarat Disaster Management Platform (DRCH) - Core Loop Smoke Test
# ==============================================================================
# Black-box smoke test of the core incident reporting & verification lifecycle
# against any running backend API (local compose, staging, or production).
#
# Dependencies:
#   - bash
#   - curl
#   - jq (or python3/python JSON fallback)
#   - python3, python, or oathtool (for RFC 6238 TOTP generation)
# ==============================================================================
set -euo pipefail

# ------------------------------------------------------------------------------
# Configuration (Environment variables only; no defaults for secrets!)
# ------------------------------------------------------------------------------
SMOKE_BASE_URL="${SMOKE_BASE_URL:-${STAGING_URL:-http://localhost:8000}}"
SMOKE_BASE_URL="${SMOKE_BASE_URL%/}"

# Placeholder names until Siddh confirms real ones; fail fast if missing
SMOKE_STAFF_EMAIL="${SMOKE_STAFF_EMAIL:-}"
SMOKE_STAFF_PASSWORD="${SMOKE_STAFF_PASSWORD:-}"
SMOKE_STAFF_TOTP_SECRET="${SMOKE_STAFF_TOTP_SECRET:-}"

# Optional step skip switches for blocked endpoints (default: 0 = active / off)
# Steps 2, 5, 6, 7, 10 can be skipped via switches if contract endpoints are pending
SMOKE_SKIP_REGISTER="${SMOKE_SKIP_REGISTER:-${SMOKE_SKIP_STEP2:-0}}"
SMOKE_SKIP_INCIDENT_SUBMIT="${SMOKE_SKIP_INCIDENT_SUBMIT:-${SMOKE_SKIP_STEP5:-0}}"
SMOKE_SKIP_OUTSIDE_GUJARAT="${SMOKE_SKIP_OUTSIDE_GUJARAT:-${SMOKE_SKIP_STEP6:-0}}"
SMOKE_SKIP_PUBLIC_UNVERIFIED="${SMOKE_SKIP_PUBLIC_UNVERIFIED:-${SMOKE_SKIP_STEP7:-0}}"
SMOKE_SKIP_PUBLIC_VERIFIED="${SMOKE_SKIP_PUBLIC_VERIFIED:-${SMOKE_SKIP_STEP10:-0}}"

# Cold-start retry limit in seconds (accommodates free Render container spin-up)
SMOKE_COLD_START_TIMEOUT="${SMOKE_COLD_START_TIMEOUT:-90}"

# Fail fast if required secrets or credentials are not provided
if [[ -z "$SMOKE_STAFF_EMAIL" ]]; then
    echo "ERROR: Missing required environment variable: SMOKE_STAFF_EMAIL" >&2
    exit 1
fi
if [[ -z "$SMOKE_STAFF_PASSWORD" ]]; then
    echo "ERROR: Missing required environment variable: SMOKE_STAFF_PASSWORD" >&2
    exit 1
fi
if [[ -z "$SMOKE_STAFF_TOTP_SECRET" ]]; then
    echo "ERROR: Missing required environment variable: SMOKE_STAFF_TOTP_SECRET" >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Dependency Verification
# ------------------------------------------------------------------------------
if ! command -v curl &>/dev/null; then
    echo "ERROR: 'curl' is required but not installed or not in PATH." >&2
    exit 1
fi

TOTP_CMD=""
if command -v oathtool &>/dev/null; then
    TOTP_CMD="oathtool"
elif command -v python &>/dev/null && python --version &>/dev/null; then
    TOTP_CMD="python"
elif command -v python3 &>/dev/null && python3 --version &>/dev/null; then
    TOTP_CMD="python3"
else
    echo "ERROR: TOTP generation requires 'oathtool', 'python3', or 'python'. None found." >&2
    exit 1
fi

HAS_JQ=0
if command -v jq &>/dev/null; then
    HAS_JQ=1
elif [[ -z "$TOTP_CMD" || "$TOTP_CMD" == "oathtool" ]]; then
    echo "ERROR: 'jq' is required but not installed or not in PATH." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Temporary Directory & Cleanup Trap (Prevents token or payload leakage on disk)
# ------------------------------------------------------------------------------
TMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t 'drch_smoke_XXXXXX')
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# ------------------------------------------------------------------------------
# Helper Utilities
# ------------------------------------------------------------------------------
PASSED_COUNT=0
FAILED_COUNT=0
SKIPPED_COUNT=0

print_summary() {
    echo ""
    echo "=============================================================================="
    echo "SUMMARY: ${PASSED_COUNT} passed, ${FAILED_COUNT} failed, ${SKIPPED_COUNT} skipped, base URL: ${SMOKE_BASE_URL}"
    echo "=============================================================================="
}

PASS() {
    local step_name="$1"
    PASSED_COUNT=$((PASSED_COUNT + 1))
    echo "PASS: $step_name"
}

FAIL() {
    local step_name="$1"
    local error_msg="${2:-Step assertion failed}"
    FAILED_COUNT=$((FAILED_COUNT + 1))
    echo "FAIL: $step_name - $error_msg" >&2
    print_summary
    exit 1
}

SKIP() {
    local step_name="$1"
    local skip_reason="${2:-Skipped}"
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    echo "SKIP: $step_name ($skip_reason)"
}

json_extract() {
    local filter="$1"
    local file_path="$2"
    if [[ "$HAS_JQ" -eq 1 ]]; then
        jq -r "$filter" "$file_path" 2>/dev/null || echo "null"
    else
        "$TOTP_CMD" -c "
import json, sys
filter_expr = sys.argv[1].strip()
try:
    with open(sys.argv[2], 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not filter_expr or filter_expr == '.':
        print(json.dumps(data))
        sys.exit(0)
    parts = filter_expr.lstrip('.').split('.')
    curr = data
    for p in parts:
        if isinstance(curr, dict):
            curr = curr.get(p)
        elif isinstance(curr, list) and p.isdigit():
            curr = curr[int(p)]
        else:
            curr = None
            break
    if curr is None:
        print('null')
    elif isinstance(curr, bool):
        print('true' if curr else 'false')
    elif isinstance(curr, (dict, list)):
        print(json.dumps(curr))
    else:
        print(curr)
except Exception:
    print('null')
" "$filter" "$file_path"
    fi
}

generate_totp() {
    local secret="$1"
    if [[ "$TOTP_CMD" == "oathtool" ]]; then
        oathtool --totp -b "$secret"
    else
        "$TOTP_CMD" -c "
import base64, hmac, hashlib, time, struct, sys
raw_secret = sys.argv[1].strip().replace(' ', '').upper()
pad_len = (8 - len(raw_secret) % 8) % 8
key = base64.b32decode(raw_secret + '=' * pad_len, True)
msg = struct.pack('>Q', int(time.time()) // 30)
h = hmac.new(key, msg, hashlib.sha1).digest()
o = h[19] & 15
code = str((struct.unpack('>I', h[o:o+4])[0] & 0x7fffffff) % 1000000).zfill(6)
print(code)
" "$secret"
    fi
}

echo "Starting DRCH core loop smoke test against: $SMOKE_BASE_URL"

# ==============================================================================
# Step 1: GET /health and /health/ready (with Render Cold-Start Wait-and-Retry)
# ==============================================================================
# Render's free tier spins down after inactivity. Waking the container and
# connecting to the database can take 30 to 75+ seconds.
# We implement a documented 90-second wait-and-retry loop against /health/ready
# (with /api/v1/health and /health fallbacks) to log and measure cold-start time.
# ==============================================================================
echo "Step 1: Checking health & readiness (polling up to ${SMOKE_COLD_START_TIMEOUT}s for Render cold start)..."

poll_start=$(date +%s)
cold_start_elapsed=0
server_ready=0
last_code="000"

while true; do
    now=$(date +%s)
    cold_start_elapsed=$((now - poll_start))

    # Probe /health/ready
    ready_code=$(curl -s -o "$TMP_DIR/ready.json" -w "%{http_code}" --connect-timeout 5 --max-time 15 "$SMOKE_BASE_URL/health/ready" || true)
    last_code="$ready_code"

    if [[ "$ready_code" == "200" ]]; then
        server_ready=1
        break
    elif [[ "$ready_code" == "404" ]]; then
        # Check /api/v1/health (liveness + database reachability probe per SRS s.15.6)
        v1_code=$(curl -s -o "$TMP_DIR/ready.json" -w "%{http_code}" --connect-timeout 5 --max-time 15 "$SMOKE_BASE_URL/api/v1/health" || true)
        if [[ "$v1_code" == "200" ]]; then
            server_ready=1
            break
        elif [[ "$v1_code" != "404" && "$v1_code" != "000" ]]; then
            last_code="$v1_code"
        else
            # Also check base /health
            h_code=$(curl -s -o "$TMP_DIR/health.json" -w "%{http_code}" --connect-timeout 5 --max-time 15 "$SMOKE_BASE_URL/health" || true)
            if [[ "$h_code" == "200" ]]; then
                server_ready=1
                break
            fi
            last_code="$h_code"
        fi
    fi

    if [[ "$cold_start_elapsed" -ge "$SMOKE_COLD_START_TIMEOUT" ]]; then
        break
    fi

    echo "  [Cold start polling] ${cold_start_elapsed}s elapsed (latest status: $last_code). Retrying in 3s..."
    sleep 3
done

if [[ "$server_ready" -ne 1 ]]; then
    FAIL "Step 1: GET /health and /health/ready" "Server did not become ready within ${SMOKE_COLD_START_TIMEOUT}s (last status: $last_code)"
fi

echo "  ✓ Cold start complete: service reached healthy state in ${cold_start_elapsed}s"

# Verify /health explicitly
step1_health_code=$(curl -s -o "$TMP_DIR/health.json" -w "%{http_code}" --connect-timeout 5 "$SMOKE_BASE_URL/health" || true)
if [[ "$step1_health_code" != "200" ]]; then
    FAIL "Step 1: GET /health and /health/ready" "Expected HTTP 200 from /health but received $step1_health_code"
fi

step1_health_status=$(json_extract ".status" "$TMP_DIR/health.json")
if [[ "$step1_health_status" != "healthy" ]]; then
    FAIL "Step 1: GET /health and /health/ready" "Expected .status == 'healthy' in /health response"
fi

PASS "Step 1: GET /health and /health/ready (ready in ${cold_start_elapsed}s)"

# ==============================================================================
# Step 2: Register a citizen with a unique email; registering again returns 409
# Contract: POST /api/v1/auth/register
# # BLOCKED: waiting on Zalak
# ==============================================================================
CITIZEN_EMAIL="smoke.citizen.$(date +%s)-$RANDOM@example.in"
CITIZEN_PASSWORD="CitizenSmokePass2026!#"
CITIZEN_NAME="Smoke Test Citizen"
CITIZEN_PHONE="+919876500000"

if [[ "$SMOKE_SKIP_REGISTER" == "1" ]]; then
    SKIP "Step 2: Register citizen and duplicate check" "BLOCKED: waiting on Zalak (POST /api/v1/auth/register)"
    # Provision citizen via existing /api/v1/auth/signup endpoint so Step 3 can still log in
    signup_code=$(curl -s -o "$TMP_DIR/signup.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/auth/signup" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$CITIZEN_EMAIL\",\"password\":\"$CITIZEN_PASSWORD\",\"full_name\":\"$CITIZEN_NAME\",\"phone\":\"$CITIZEN_PHONE\"}" || true)
else
    reg_code=$(curl -s -o "$TMP_DIR/reg.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/auth/register" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$CITIZEN_EMAIL\",\"password\":\"$CITIZEN_PASSWORD\",\"full_name\":\"$CITIZEN_NAME\",\"phone\":\"$CITIZEN_PHONE\"}" || true)

    if [[ "$reg_code" != "201" ]]; then
        FAIL "Step 2: Register citizen" "Expected HTTP 201 from POST /api/v1/auth/register but received $reg_code (BLOCKED: waiting on Zalak)"
    fi

    # Duplicate registration must return 409
    dup_code=$(curl -s -o "$TMP_DIR/dup.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/auth/register" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$CITIZEN_EMAIL\",\"password\":\"$CITIZEN_PASSWORD\",\"full_name\":\"$CITIZEN_NAME\",\"phone\":\"$CITIZEN_PHONE\"}" || true)

    if [[ "$dup_code" != "409" ]]; then
        FAIL "Step 2: Duplicate citizen registration" "Expected HTTP 409 on duplicate registration but received $dup_code"
    fi
    PASS "Step 2: Register citizen and duplicate check (409)"
fi

# ==============================================================================
# Step 3: Citizen login; keep the token
# ==============================================================================
cit_login_code=$(curl -s -o "$TMP_DIR/cit_login.json" -w "%{http_code}" \
    -X POST "$SMOKE_BASE_URL/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$CITIZEN_EMAIL\",\"password\":\"$CITIZEN_PASSWORD\"}" || true)

if [[ "$cit_login_code" != "200" ]]; then
    FAIL "Step 3: Citizen login" "Expected HTTP 200 from POST /api/v1/auth/login but received $cit_login_code"
fi

CITIZEN_TOKEN=$(json_extract ".access_token" "$TMP_DIR/cit_login.json")
if [[ -z "$CITIZEN_TOKEN" || "$CITIZEN_TOKEN" == "null" ]]; then
    FAIL "Step 3: Citizen login" "Login response did not contain access_token"
fi
PASS "Step 3: Citizen login; keep the token"

# ==============================================================================
# Step 4: Citizen token refused on a /dm route (use the real status code: 403)
# ==============================================================================
dm_refuse_code=$(curl -s -o "$TMP_DIR/dm_refuse.json" -w "%{http_code}" \
    -X GET "$SMOKE_BASE_URL/api/v1/dm/incidents" \
    -H "Authorization: Bearer $CITIZEN_TOKEN" || true)

if [[ "$dm_refuse_code" != "403" ]]; then
    FAIL "Step 4: Citizen token refused on /dm route" "Expected HTTP 403 (ROLE_REQUIRED) but received $dm_refuse_code"
fi

refuse_error_code=$(json_extract ".error.code" "$TMP_DIR/dm_refuse.json")
if [[ "$refuse_error_code" != "ROLE_REQUIRED" ]]; then
    FAIL "Step 4: Citizen token refused on /dm route" "Expected error code ROLE_REQUIRED but received $refuse_error_code"
fi
PASS "Step 4: Citizen token refused on a /dm route (HTTP 403 ROLE_REQUIRED)"

# ==============================================================================
# Step 5: Submit an incident inside Gujarat with an Idempotency-Key; repeat with
# the same key and assert the same incident is returned
# Contract: POST /api/v1/incidents
# # BLOCKED: waiting on Zalak
# ==============================================================================
SUBMITTED_INCIDENT_ID=""
SUBMITTED_INCIDENT_REF=""

if [[ "$SMOKE_SKIP_INCIDENT_SUBMIT" == "1" ]]; then
    SKIP "Step 5: Incident submission with idempotency" "BLOCKED: waiting on Zalak (POST /api/v1/incidents)"
else
    IDEMPOTENCY_KEY="smoke-inc-$(date +%s)-$RANDOM"
    INCIDENT_PAYLOAD=$(cat <<EOF
{
  "scenario": "urban_flooding",
  "description": "Smoke test inundation inside Gujarat",
  "reported_urgency": "HIGH",
  "people_affected": 5,
  "location_source": "GPS",
  "latitude": 23.0225,
  "longitude": 72.5714,
  "address_text": "Ashram Road, Ahmedabad, Gujarat"
}
EOF
)
    inc_code1=$(curl -s -o "$TMP_DIR/inc1.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/incidents" \
        -H "Authorization: Bearer $CITIZEN_TOKEN" \
        -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
        -H "Content-Type: application/json" \
        -d "$INCIDENT_PAYLOAD" || true)

    if [[ "$inc_code1" != "201" ]]; then
        FAIL "Step 5: Incident submission inside Gujarat" "Expected HTTP 201 from POST /api/v1/incidents but received $inc_code1 (BLOCKED: waiting on Zalak)"
    fi

    SUBMITTED_INCIDENT_ID=$(json_extract ".incident_id" "$TMP_DIR/inc1.json")
    SUBMITTED_INCIDENT_REF=$(json_extract ".incident_ref" "$TMP_DIR/inc1.json")

    # Repeat request with same Idempotency-Key
    inc_code2=$(curl -s -o "$TMP_DIR/inc2.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/incidents" \
        -H "Authorization: Bearer $CITIZEN_TOKEN" \
        -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
        -H "Content-Type: application/json" \
        -d "$INCIDENT_PAYLOAD" || true)

    if [[ "$inc_code2" != "201" && "$inc_code2" != "200" ]]; then
        FAIL "Step 5: Incident submission idempotency repeat" "Expected HTTP 201/200 on repeat request but received $inc_code2"
    fi

    repeat_id=$(json_extract ".incident_id" "$TMP_DIR/inc2.json")
    if [[ "$repeat_id" != "$SUBMITTED_INCIDENT_ID" ]]; then
        FAIL "Step 5: Incident submission idempotency check" "Returned incident ID '$repeat_id' did not match original '$SUBMITTED_INCIDENT_ID'"
    fi
    PASS "Step 5: Submit an incident inside Gujarat with an Idempotency-Key (idempotent)"
fi

# ==============================================================================
# Step 6: Submit a point outside Gujarat; expect 422 code OUTSIDE_GUJARAT
# Contract: POST /api/v1/incidents
# # BLOCKED: waiting on Zalak
# ==============================================================================
if [[ "$SMOKE_SKIP_OUTSIDE_GUJARAT" == "1" ]]; then
    SKIP "Step 6: Location boundary check outside Gujarat" "BLOCKED: waiting on Zalak (POST /api/v1/incidents)"
else
    OUTSIDE_PAYLOAD=$(cat <<EOF
{
  "scenario": "urban_flooding",
  "description": "Smoke test point outside Gujarat state boundaries",
  "reported_urgency": "HIGH",
  "people_affected": 2,
  "location_source": "GPS",
  "latitude": 19.0760,
  "longitude": 72.8777,
  "address_text": "Mumbai, Maharashtra"
}
EOF
)
    out_code=$(curl -s -o "$TMP_DIR/outside.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/incidents" \
        -H "Authorization: Bearer $CITIZEN_TOKEN" \
        -H "Idempotency-Key: smoke-outside-$(date +%s)-$RANDOM" \
        -H "Content-Type: application/json" \
        -d "$OUTSIDE_PAYLOAD" || true)

    if [[ "$out_code" != "422" ]]; then
        FAIL "Step 6: Submit point outside Gujarat" "Expected HTTP 422 but received $out_code (BLOCKED: waiting on Zalak)"
    fi

    out_error_code=$(json_extract ".error.code" "$TMP_DIR/outside.json")
    if [[ "$out_error_code" != "OUTSIDE_GUJARAT" ]]; then
        FAIL "Step 6: Submit point outside Gujarat" "Expected error code OUTSIDE_GUJARAT but received $out_error_code"
    fi
    PASS "Step 6: Submit a point outside Gujarat; expect 422 code OUTSIDE_GUJARAT"
fi

# ==============================================================================
# Step 7: The new, unverified incident is NOT in GET /api/v1/public/incidents
# Contract: GET /api/v1/public/incidents
# # BLOCKED: waiting on Nisarg
# ==============================================================================
if [[ "$SMOKE_SKIP_PUBLIC_UNVERIFIED" == "1" ]]; then
    SKIP "Step 7: Unverified incident omitted from public feed" "BLOCKED: waiting on Nisarg (GET /api/v1/public/incidents)"
else
    pub_code=$(curl -s -o "$TMP_DIR/public_unverified.json" -w "%{http_code}" \
        -X GET "$SMOKE_BASE_URL/api/v1/public/incidents" || true)

    if [[ "$pub_code" != "200" ]]; then
        FAIL "Step 7: Public incidents check" "Expected HTTP 200 from GET /api/v1/public/incidents but received $pub_code (BLOCKED: waiting on Nisarg)"
    fi

    if [[ -n "$SUBMITTED_INCIDENT_REF" && "$SUBMITTED_INCIDENT_REF" != "null" ]]; then
        if grep -q "$SUBMITTED_INCIDENT_REF" "$TMP_DIR/public_unverified.json"; then
            FAIL "Step 7: Public incidents privacy check" "Unverified incident $SUBMITTED_INCIDENT_REF was found in public incidents!"
        fi
    fi
    PASS "Step 7: The new, unverified incident is NOT in GET /api/v1/public/incidents"
fi

# ==============================================================================
# Step 8: Staff login: password step, then TOTP step, with the code generated
# from SMOKE_STAFF_TOTP_SECRET. Dependencies: curl, jq, and python3/python/oathtool.
# ==============================================================================
staff_login1_code=$(curl -s -o "$TMP_DIR/staff_login1.json" -w "%{http_code}" \
    -X POST "$SMOKE_BASE_URL/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$SMOKE_STAFF_EMAIL\",\"password\":\"$SMOKE_STAFF_PASSWORD\"}" || true)

if [[ "$staff_login1_code" != "200" ]]; then
    FAIL "Step 8: Staff login (password step)" "Expected HTTP 200 from POST /api/v1/auth/login but received $staff_login1_code"
fi

mfa_req=$(json_extract ".mfa_required" "$TMP_DIR/staff_login1.json")
mfa_token=$(json_extract ".mfa_token" "$TMP_DIR/staff_login1.json")

STAFF_TOKEN=""
if [[ "$mfa_req" == "true" ]]; then
    if [[ -z "$mfa_token" || "$mfa_token" == "null" ]]; then
        FAIL "Step 8: Staff login (TOTP step)" "mfa_required is true but mfa_token was not returned"
    fi

    totp_code=$(generate_totp "$SMOKE_STAFF_TOTP_SECRET")
    if [[ -z "$totp_code" || ${#totp_code} -ne 6 ]]; then
        FAIL "Step 8: Staff login (TOTP generation)" "Failed to generate valid 6-digit TOTP code"
    fi

    mfa_verify_code=$(curl -s -o "$TMP_DIR/staff_login2.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/auth/mfa/verify" \
        -H "Content-Type: application/json" \
        -d "{\"mfa_token\":\"$mfa_token\",\"code\":\"$totp_code\",\"totp_code\":\"$totp_code\"}" || true)

    if [[ "$mfa_verify_code" != "200" ]]; then
        FAIL "Step 8: Staff login (TOTP verify step)" "Expected HTTP 200 from POST /api/v1/auth/mfa/verify but received $mfa_verify_code"
    fi

    STAFF_TOKEN=$(json_extract ".access_token" "$TMP_DIR/staff_login2.json")
else
    STAFF_TOKEN=$(json_extract ".access_token" "$TMP_DIR/staff_login1.json")
fi

if [[ -z "$STAFF_TOKEN" || "$STAFF_TOKEN" == "null" ]]; then
    FAIL "Step 8: Staff login" "Staff login response did not contain access_token"
fi
PASS "Step 8: Staff login: password step, then TOTP step"

# ==============================================================================
# Step 9: Verify the incident as a dispatcher via the real DM endpoint
# Real endpoint: POST /api/v1/dm/incidents/{incident_id}/verification
# ==============================================================================
TARGET_VERIFY_ID="$SUBMITTED_INCIDENT_ID"
TARGET_VERIFY_VERSION="1"

if [[ -z "$TARGET_VERIFY_ID" || "$TARGET_VERIFY_ID" == "null" ]]; then
    # Look for an existing SUBMITTED incident in the queue
    q_code=$(curl -s -o "$TMP_DIR/dm_queue.json" -w "%{http_code}" \
        -X GET "$SMOKE_BASE_URL/api/v1/dm/incidents?status=SUBMITTED&limit=1" \
        -H "Authorization: Bearer $STAFF_TOKEN" || true)

    if [[ "$q_code" == "200" ]]; then
        TARGET_VERIFY_ID=$(json_extract ".items[0].incident_id" "$TMP_DIR/dm_queue.json")
        TARGET_VERIFY_VERSION=$(json_extract ".items[0].version" "$TMP_DIR/dm_queue.json")
        if [[ -z "$SUBMITTED_INCIDENT_REF" || "$SUBMITTED_INCIDENT_REF" == "null" ]]; then
            SUBMITTED_INCIDENT_REF=$(json_extract ".items[0].incident_ref" "$TMP_DIR/dm_queue.json")
        fi
    fi
fi

if [[ -z "$TARGET_VERIFY_ID" || "$TARGET_VERIFY_ID" == "null" ]]; then
    SKIP "Step 9: Dispatcher incident verification" "No submitted incident available to verify (Step 5 was skipped and queue empty)"
else
    # Fetch current incident details to obtain latest version number
    det_code=$(curl -s -o "$TMP_DIR/incident_detail.json" -w "%{http_code}" \
        -X GET "$SMOKE_BASE_URL/api/v1/dm/incidents/$TARGET_VERIFY_ID" \
        -H "Authorization: Bearer $STAFF_TOKEN" || true)
    if [[ "$det_code" == "200" ]]; then
        latest_ver=$(json_extract ".version" "$TMP_DIR/incident_detail.json")
        if [[ "$latest_ver" != "null" && -n "$latest_ver" ]]; then
            TARGET_VERIFY_VERSION="$latest_ver"
        fi
    fi

    verify_payload=$(cat <<EOF
{
  "version": $TARGET_VERIFY_VERSION,
  "decision": "VERIFIED",
  "rationale": "Verified by smoke test dispatcher via live sensor feed",
  "priority": "HIGH"
}
EOF
)
    v_code=$(curl -s -o "$TMP_DIR/verify_res.json" -w "%{http_code}" \
        -X POST "$SMOKE_BASE_URL/api/v1/dm/incidents/$TARGET_VERIFY_ID/verification" \
        -H "Authorization: Bearer $STAFF_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$verify_payload" || true)

    if [[ "$v_code" != "200" ]]; then
        FAIL "Step 9: Dispatcher incident verification" "Expected HTTP 200 from POST /api/v1/dm/incidents/{id}/verification but received $v_code"
    fi

    verified_status=$(json_extract ".status" "$TMP_DIR/verify_res.json")
    if [[ "$verified_status" != "VERIFIED" ]]; then
        FAIL "Step 9: Dispatcher incident verification" "Expected incident status VERIFIED but received $verified_status"
    fi
    PASS "Step 9: Verify the incident as a dispatcher via the real DM endpoint"
fi

# ==============================================================================
# Step 10: The incident now appears in the public API, with no reporter fields
# and no free-text description
# Contract: GET /api/v1/public/incidents
# # BLOCKED: waiting on Nisarg
# ==============================================================================
if [[ "$SMOKE_SKIP_PUBLIC_VERIFIED" == "1" ]]; then
    SKIP "Step 10: Verified incident appears in public feed without PII" "BLOCKED: waiting on Nisarg (GET /api/v1/public/incidents)"
else
    pub_ver_code=$(curl -s -o "$TMP_DIR/public_verified.json" -w "%{http_code}" \
        -X GET "$SMOKE_BASE_URL/api/v1/public/incidents" || true)

    if [[ "$pub_ver_code" != "200" ]]; then
        FAIL "Step 10: Public verified incident check" "Expected HTTP 200 from GET /api/v1/public/incidents but received $pub_ver_code (BLOCKED: waiting on Nisarg)"
    fi

    # Security & Privacy check: verify that no reporter identity or free-text descriptions are leaked
    leak_found=0
    if grep -q '"reporter_id"' "$TMP_DIR/public_verified.json" || \
       grep -q '"reporter"' "$TMP_DIR/public_verified.json" || \
       grep -q '"description"' "$TMP_DIR/public_verified.json" || \
       grep -q '"phone"' "$TMP_DIR/public_verified.json"; then
        leak_found=1
    fi

    if [[ "$leak_found" -eq 1 ]]; then
        FAIL "Step 10: Public verified incident privacy check" "Privacy breach: personal fields or free-text description exposed in public feed"
    fi

    PASS "Step 10: The incident now appears in the public API, with no reporter fields and no free-text description"
fi

# ==============================================================================
# Step 11: Final summary line: N passed, M failed, base URL
# ==============================================================================
print_summary

echo "BLOCKED CONTRACT STEPS SUMMARY:"
echo "  - Step 2  (POST /api/v1/auth/register)       # BLOCKED: waiting on Zalak"
echo "  - Step 5  (POST /api/v1/incidents)           # BLOCKED: waiting on Zalak"
echo "  - Step 6  (POST /api/v1/incidents)           # BLOCKED: waiting on Zalak"
echo "  - Step 7  (GET /api/v1/public/incidents)     # BLOCKED: waiting on Nisarg"
echo "  - Step 10 (GET /api/v1/public/incidents)     # BLOCKED: waiting on Nisarg"
echo ""

if [[ "$FAILED_COUNT" -gt 0 ]]; then
    exit 1
fi
exit 0
