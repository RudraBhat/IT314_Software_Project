---
name: debug
description: Diagnose and resolve defects in the DRCH platform using systematic root-cause analysis and regression testing.
---

# Defect Debugging Workflow (/debug)

Systematically trace and resolve bugs while maintaining system integrity and avoiding unrelated refactoring:

## 1. Issue Reproduction & Context
1. Reproduce the reported defect or examine the failing test / error log.
2. Identify the entrypoint (API endpoint, background worker, or React component).
3. Check application logs and review recent commits for regressions.

## 2. Root Cause Analysis
1. Trace the execution path through routers, services, and database layers:
   - Auth & Session: Check JWT validation, Argon2id verification, TOTP MFA state.
   - Concurrency & State: Check row locks (`SELECT ... FOR UPDATE`), transaction boundaries, advisory locks.
   - Geospatial & PostGIS: Check coordinate validity, boundary containment, polygon cache.
   - API & Schema: Compare request/response payloads against Pydantic schemas and `docs/api_contracts.md`.
2. Pinpoint the exact root cause before modifying any code.

## 3. Targeted Fix Implementation
1. Formulate the smallest, most targeted correction that completely resolves the root cause.
2. **Preserve Contracts:** Do not alter existing API contracts or database schemas unless the bug is directly caused by a schema defect.
3. **No Unrelated Refactoring:** Keep edits strictly scoped to the defect. Do not reformat or clean up unrelated code.

## 4. Regression Prevention & Verification
1. Add or update a targeted regression test in `backend/tests/` that exercises the edge case.
2. Run the test suite:
   ```bash
   python -m pytest backend/tests/ -k "test_name" -v
   ```
3. Run lint and quality checks:
   ```bash
   python -m ruff check backend/
   ```
4. Inspect `git diff` to confirm zero collateral changes.
5. **Git Restriction:** NEVER commit or push. Present root cause, fix explanation, and test results for review.
