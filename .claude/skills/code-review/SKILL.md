---
name: code-review
description: Review DRCH code changes for bugs, security vulnerabilities, architectural consistency, and compliance.
---

# Code Review Workflow (/code-review)

Perform a rigorous, structured code review of recent changes or specified files against DRCH quality standards:

## 1. Review Checklist

### A. Correctness & Bug Prevention
- Are boundary conditions, null/empty states, and unexpected inputs properly handled?
- Are exceptions caught specifically rather than swallowed with bare `except:`?
- Are asynchronous tasks (`asyncio`) properly handled without blocking the event loop?

### B. Security & Compliance (DRCH Constraints)
- **Zero Supabase:** Ensure no `supabase-js`, Supabase Auth, or Supabase-specific SQL was introduced.
- **Server-Side RBAC:** Are privileged operations validated using `StaffUser` and `require_role`?
- **PII Protection:** Are citizen reporter IDs, names, or contact numbers shielded from public responses?
- **Audit Logging:** Are state transitions logged to `audit_logs` preserving the SHA-256 hash chain?
- **Advisory AI:** Are AI model outputs stored as advisory without bypassing human dispatcher approval?

### C. Database & Concurrency
- Are multi-table writes wrapped in `with db.transaction() as conn:`?
- Are shared resources locked via `SELECT ... FOR UPDATE` before allocation?
- Are migrations strictly additive and backward-compatible?

### D. Architectural Integrity & Reuse
- Does the code reuse existing services in `backend/app/services/` and components in `frontend/src/components/`?
- Are there duplicate files, redundant utilities, or unused dependencies?
- Does the code adhere to the 3-scenario scope (`cyclone`, `industrial_fire`, `urban_flooding`)?

### E. Test Coverage
- Are new endpoints and business logic accompanied by tests in `backend/tests/`?
- Does the test suite pass cleanly?

## 2. Output Format
Organize findings by severity:
- **[CRITICAL]** Security vulnerabilities, data corruption, concurrency deadlocks, PII leaks.
- **[MAJOR]** Broken business logic, unhandled errors, missing transaction boundaries.
- **[MINOR]** Code duplication, performance issues, missing tests.
- **[SUGGESTION]** Style, documentation, or minor simplification.

Provide file and line references (`path/to/file.py:L123`) for every finding.
Do NOT modify code automatically unless requested.
