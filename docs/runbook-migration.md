# DRCH Deployment & Migration Runbook: Audit v2 Upgrade

> [!IMPORTANT]
> **OPERATIONAL RUNBOOK ONLY — DO NOT EXECUTE AUTOMATICALLY IN TESTING/CI.**
> This runbook is intended for operations and deployment engineers upgrading staging and production DRCH environments from legacy/Sprint 2 builds to the tested `fix/audit-v2` architecture.

---

## Pre-requisites & Verification

Ensure you have:
1. Operator CLI access with administrative credentials to Neon PostgreSQL 16 console.
2. Render (Backend) and Vercel (Frontend) dashboard deployment access.
3. Access to `python -m app.cli` execution within the container environment.
4. Python 3.11+ and dependencies installed locally for executing maintenance and verification scripts.

---

## Staged Execution Procedure

Perform these steps on **staging** first before executing on production.

### Step 1: Pre-Migration Database Snapshot (Neon)
1. Log in to the [Neon Console](https://console.neon.tech).
2. Select your DRCH project and create an instantaneous branch or snapshot:
   - Branch Name: `backup-pre-audit-v2-<YYYY-MM-DD>`
3. Alternatively, take an external logical dump:
   ```bash
   pg_dump "$DATABASE_URL" --format=custom --file=drch_backup_pre_v2.dump
   ```

### Step 2: Secret Rotation & Environment Configuration
Set or update the required environment variables across the deployment targets (see [docs/env-variables.md](file:///docs/env-variables.md)):

| Environment Variable | Required Target | Instructions |
|---|---|---|
| `APP_ENV` | `staging` or `production` | Enables startup validation and disables sandbox bypasses. |
| `JWT_SECRET` | 32+ char random string | HS256 signing secret. Generate via `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `MFA_ENCRYPTION_KEY` | 32-byte Fernet key | See Step 3 below before rotating. |
| `INGEST_TOKEN` | 48+ char random token | Bearer secret for scheduled feed runs (`/api/v1/internal/ingest/run`). |
| `CORS_ALLOWED_ORIGINS` | Comma-separated domains | E.g. `https://drch-staging.vercel.app` (rejects wildcards in prod). |
| `MOCK_GATEWAY_SECRET` | HMAC key string | Required if donation verification is exercised in staging. |
| `SACHET_FEED_URL` | Feed URL or empty | Common Alerting Protocol XML feed endpoint for SACHET/NDMA. |

The backend enforces startup configuration validation (`app.config:validate_for_environment`) and will refuse to start if any required secret is missing or contains placeholder markers.

### Step 3: Staff MFA Secret Key Migration
Existing staff TOTP secrets were previously encrypted using a key derived from the legacy `JWT_SECRET`. To prevent locking out active Disaster Management staff:

Choose **Option A** (Recommended for seamless migration) or **Option B** (Security reset):

- **Option A (Preserve Active Staff Authenticator Apps):**
  Derive the exact Fernet key that the legacy code used and set it as `MFA_ENCRYPTION_KEY`:
  ```bash
  python -c "import base64,hashlib,sys; print(base64.urlsafe_b64encode(hashlib.sha256(sys.argv[1].encode()).digest()).decode())" '<OLD_JWT_SECRET>'
  ```
  Once `MFA_ENCRYPTION_KEY` is saved in the environment, `JWT_SECRET` can be rotated freely to a fresh secret.

- **Option B (Re-enrol Staff Accounts):**
  Generate a brand-new Fernet key:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  Set this as `MFA_ENCRYPTION_KEY`. Then re-enrol each staff account using the CLI:
  ```bash
  python -m app.cli reset-mfa --email dispatcher@gujarat.gov.in
  ```

### Step 4: Backend Container Deployment & Demo Data Purge
1. Trigger backend deployment on Render pointing to the `fix/audit-v2` release image.
2. Migrations `05_totp_encryption.sql`, `06_audit_immutability.sql`, and `07_citizen_auth.sql` apply automatically upon connection pool startup.
3. Open a shell in the Render container and purge old simulated records left by previous seeds:
   ```bash
   python -m app.cli purge-demo-data
   ```
   *Note: If simulated incidents already have active dispatch orders, resolve or reassign them prior to purging.*
4. Manually review `/dm/resources` and `/dm/campaigns` to archive any remaining unlabelled sample entries.

### Step 5: Cryptographic Audit Chain Verification
Verify the SHA-256 hash chaining of all historical and new audit logs:
```bash
python -m app.cli verify-audit
```
- If the verification reports success across all rows, the chain is sound.
- If a break is reported at a legacy row created prior to Migration 06 (when triggers enforced immutable append-only chaining), record the `audit_id` and timestamp in the incident ops log. All rows subsequent to Migration 06 will maintain verifiable integrity.

### Step 6: Render Health Check Configuration
Ensure Render web service health check path is configured:
- **Path:** `/api/v1/health`
- **Expected Status:** HTTP 200 `{"status": "ok", "db": true, ...}`

### Step 7: Frontend Deployment & Smoke Testing
1. Deploy the Next.js frontend to Vercel with environment variable:
   - `API_URL`: Base URL of the deployed backend (e.g., `https://drch-backend.onrender.com`).
2. Run the non-interactive automated smoke test:
   ```bash
   export SMOKE_STAFF_EMAIL="dispatcher@example.org"
   export SMOKE_STAFF_PASSWORD="<STAFF_PASSWORD>"
   export SMOKE_STAFF_TOTP_SECRET="<STAFF_TOTP_SECRET>"
   python scripts/smoke.py --base-url "https://drch-backend.onrender.com"
   ```
3. Verify:
   - Public map displays active verified incidents or empty state (no mock demo data).
   - Citizen registration enforces strong passwords and issues session cookie.
   - Staff sign-in prompts for TOTP and grants DM workspace access.
   - Public donations page lists active campaigns with sandbox receipt confirmation (if enabled).

---

## Rollback Procedure
If a critical blocking issue arises:
1. Re-deploy the previous known-good backend container tag and frontend deployment.
2. In Neon console, point connection strings to the backup branch created in Step 1.
3. Notify the incident response lead and log all actions in the operational post-mortem log.
