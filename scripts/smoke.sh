#!/usr/bin/env bash
# ==============================================================================
# Gujarat Disaster Management Platform (DRCH) - Core Loop Smoke Test Wrapper
# Thin wrapper around python scripts/smoke.py (N11)
# ==============================================================================
set -euo pipefail

# Find script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Verify required credentials
if [[ -z "${SMOKE_STAFF_EMAIL:-}" ]]; then
    echo "ERROR: Missing required environment variable: SMOKE_STAFF_EMAIL" >&2
    exit 1
fi
if [[ -z "${SMOKE_STAFF_PASSWORD:-}" ]]; then
    echo "ERROR: Missing required environment variable: SMOKE_STAFF_PASSWORD" >&2
    exit 1
fi
if [[ -z "${SMOKE_STAFF_TOTP_SECRET:-}" ]]; then
    echo "ERROR: Missing required environment variable: SMOKE_STAFF_TOTP_SECRET" >&2
    exit 1
fi

export SMOKE_STAFF_EMAIL
export SMOKE_STAFF_PASSWORD
export SMOKE_STAFF_TOTP_SECRET
export SMOKE_BASE_URL="${SMOKE_BASE_URL:-${API_URL:-http://localhost:8000}}"

PYTHON_BIN="python"
if ! command -v python &>/dev/null && command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" "${ROOT_DIR}/scripts/smoke.py" --base-url "${SMOKE_BASE_URL}" "$@"
