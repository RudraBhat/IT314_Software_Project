---
trigger: model_decision
description: Load when modifying authentication, authorization, user data, incident privacy, audit logs, payments, dispatch or other security-sensitive functionality.
---

# Security, Privacy & Compliance Rules

- **Authentication Architecture:**
  - Staff accounts require **Argon2id password hashing** and mandatory **RFC 6238 TOTP two-factor authentication**.
  - Account lockouts trigger after 5 consecutive failures; revokes active tokens by incrementing `token_version`.
  - MFA challenge tokens are short-lived (5 min), purpose-bound JWTs that cannot be exchanged for API access without TOTP verification.
- **Role-Based Access Control (RBAC):**
  - Enforce authorization strictly on the server side via `backend/app/auth.py` dependencies (`require_role`, `StaffUser`).
  - Never trust client-reported user roles (`X-User-Role` header) for privileged operations.
- **Audit Log Integrity:**
  - Every state change, dispatch order, and authentication event must write an entry to `audit_logs` via `app.audit.log_audit_event()`.
  - Never attempt to bypass or disable the PostgreSQL `fn_audit_log_hash_chain` trigger.
  - Table triggers explicitly reject `UPDATE` and `DELETE` operations on `audit_logs`.
- **Privacy & PII Protection:**
  - Never return citizen phone numbers, full names, or internal reporter IDs on public endpoints (`/api/v1/public/*`).
  - Public coordinates must be rounded to 4 decimal places (~11 meters) to mask exact residential locations.
- **Human-in-the-Loop AI Guardrails:**
  - AI classification is purely advisory. AI suggestions stored in `triage_results` must never automatically modify incident state, adjust priorities, or trigger dispatches.
  - Verification, dispatch, escalation, and incident closure strictly require human dispatcher confirmation.
- **Simulation Transparency:**
  - Simulated incidents (`is_simulated = TRUE`), fallback alerts (`is_fallback = TRUE`), and sandbox donations (`MockGateway`) must always be visibly marked in API responses and UI indicators.
