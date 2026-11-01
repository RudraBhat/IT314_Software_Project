# DRCH — Repository Instructions

## Core Engineering Rules
- **Inspect First:** Inspect existing code, dependencies, and `docs/ARCHITECTURE.md` before making changes.
- **Reuse Existing Code:** Reuse established services, utilities, schemas, and UI components; do not build duplicate functionality.
- **Zero Duplicate Files:** Never create redundant, duplicate, or unnecessary files.
- **Conventions & Architecture:** Follow existing folder structure, naming conventions, and FastAPI / Next.js patterns.
- **Minimal Changes:** Make minimal, targeted changes strictly focused on the requested task. Avoid unrelated refactoring.
- **Verify & Test:** Run relevant unit, integration, and lint checks after changes.
- **Review Diff:** Inspect the final `git diff` before reporting completion.
- **Git Restrictions:** NEVER automatically commit, push, merge, reset, or rewrite Git history.

## DRCH Technical Constraints
- **Database:** Neon PostgreSQL 16 with PostGIS. Never introduce Supabase Auth, `auth.users`, `auth.uid()`, or Supabase-specific SQL/triggers.
- **Authentication & RBAC:** Application-managed authentication; preserve Argon2id password hashing, TOTP MFA, and session/token revocation.
- **Audit Logging:** Maintain append-only, SHA-256 hash-chained audit logging with trigger-enforced immutability.
- **AI Boundaries:** AI recommendations are strictly advisory and stored separately (`triage_results`).
- **Human-in-the-Loop:** Human dispatcher approval is strictly required for incident verification, dispatch, escalation, and closure.
- **Privacy & PII:** Protect reporter PII and sensitive operational data. Truncate public incident coordinates to 4 decimal places.
- **Simulation Transparency:** Clearly label synthetic/fallback alert feeds and sandbox payment flows.

## Response Summary
Summarize changes made, reused code/modules, test results, and any remaining issues or manual steps.
