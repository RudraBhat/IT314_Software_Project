# DRCH Secrets Register

**Owner:** Siddh Shah (@Siddhcreator-1706), Tech Lead & Integration Owner  
**Scope:** Staging and Production Environment Secrets Inventory  
**Security Policy:** Variable names, storage targets, and owners only. Secret values must NEVER be committed to Git, logged in console outputs, or shared across team chats.

---

## 1. Secrets Inventory

| Secret Name | Scope | Stored In | Assigned Owner | Rotation Policy | Purpose & Constraints |
|---|---|---|---|---|---|
| `INGEST_TOKEN` | Staging, Prod | GitHub Secrets (`staging`), Render Env | Rudra / Siddh | 30 Days | Authenticates scheduled calls to `/api/v1/internal/ingest/run`. Minimum 48-char random string. |
| `MOCK_GATEWAY_SECRET` | Staging Only | GitHub Secrets (`staging`), Render Env | Shlok / Siddh | Per Sprint | HMAC-SHA256 signature key for sandbox payment callbacks. Strictly forbidden in production (`APP_ENV=production`). |
| `LLM_API_KEY` | Staging, Prod | Render Env (never in Git) | Zalak / Siddh | 90 Days | API key for external LLM provider (Groq/Gemini). Service defaults to `LLM_ENABLED=false`. |
| `SMOKE_STAFF_EMAIL` | Staging Only | GitHub Secrets (`staging`) | Dhruv / Siddh | Standing | Email address for dedicated automated smoke testing dispatcher account. |
| `SMOKE_STAFF_PASSWORD` | Staging Only | GitHub Secrets (`staging`) | Dhruv / Siddh | Standing | Password for automated smoke test account. Meets 12+ character complexity policy. |
| `SMOKE_STAFF_TOTP_SECRET`| Staging Only | GitHub Secrets (`staging`) | Siddh | Standing | RFC 6238 Base32 secret for MFA token generation during CI/CD smoke test execution. |
| `STAGING_BACKEND_URL` | Staging | GitHub Secrets (`staging`) | Siddh | Standing | Base URL for deployed staging FastAPI service. Replaces generic `PROD_BACKEND_URL` for staging jobs. |
| `JWT_SECRET` | Staging, Prod | Render / Neon / Vercel Env | Siddh | 60 Days | HS256 secret key for signing auth tokens (minimum 32 characters). |

---

## 2. Environment Segregation Rules

1. **Production Guard against Mock Gateway:**
   In production (`APP_ENV=production`), configuring or requesting `PAYMENT_GATEWAY=mock` raises an immediate startup or runtime error to prevent fake payments from being processed live.
2. **Smoke Test Least-Privilege Account:**
   The `SMOKE_STAFF_*` account is exclusively provisioned in the staging and CI test databases. It must never have production supervisor rights or exist on live production instances.
3. **Ingestion Cron Token:**
   The `INGEST_TOKEN` is passed via `Authorization: Bearer <token>` or `X-Ingest-Token` and verified using constant-time comparison (`hmac.compare_digest`) to prevent timing side-channel attacks.
