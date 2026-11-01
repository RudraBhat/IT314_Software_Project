---
name: security-audit
description: Audit DRCH codebase for security, privacy, authentication, RBAC, and audit log compliance.
---

# Security Audit Workflow (/security-audit)

Perform a comprehensive security, privacy, and regulatory compliance audit:

## 1. Security Checklist
- **Database Identity:** Verify zero Supabase Auth, `auth.users`, or Supabase client libraries exist.
- **Authentication:** Check password hashing (Argon2id), TOTP verification timing, and account lockout thresholds.
- **MFA Security:** Check that MFA challenge tokens are short-lived, purpose-bound, and cannot authenticate standard endpoints.
- **Session Revocation:** Check that token revocation works by incrementing `token_version`.
- **RBAC Checks:** Confirm privileged endpoints require `StaffUser` and enforce permission guards.
- **Privacy & PII:** Verify public endpoints (`/api/v1/public/*`) sanitize citizen phone numbers, names, and internal user IDs. Verify coordinate truncation to 4 decimals.
- **Audit Immutability:** Verify state changes write to `audit_logs` and do not break the SHA-256 hash chain trigger.
- **AI Safety:** Confirm AI outputs remain advisory and cannot automatically trigger dispatches or verification.

## 2. Findings Output
Group findings by severity:
- **[CRITICAL]** Authentication bypass, PII leaks, broken audit chains, direct SQL injection.
- **[MAJOR]** Inadequate RBAC enforcement, unencrypted credentials, missing rate limits.
- **[MINOR]** Verbose error messages, missing simulation flags.
- **[COMPLIANT]** Verified secure implementations with file and line references.

