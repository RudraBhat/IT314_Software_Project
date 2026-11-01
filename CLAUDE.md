# DRCH — Claude Code Team Instructions

@AGENTS.md

## 1. Project Context & Documentation
- **Architecture Reference:** Read `docs/ARCHITECTURE.md` before making architectural or cross-module changes.
- **API Contracts:** Refer to `docs/api_contracts.md` for existing REST contracts and standardized error formats.
- **Environment Variables:** Refer to `docs/env-variables.md` for supported configuration variables.
- **Target Platform:** Disaster Response Coordination Hub (DRCH) for Gujarat (FastAPI + Neon PostgreSQL PostGIS + Next.js 14).

## 2. Working Workflow
1. **Analyze:** Understand the user request and scope the smallest viable change.
2. **Inspect:** Search existing codebase first (`backend/app/`, `frontend/src/`). Check for reusable services, components, and types.
3. **Implement:** Write minimal, targeted code following existing conventions. Do not create duplicate files.
4. **Test:** Run relevant tests (unit, integration, linting).
5. **Review:** Inspect the final `git diff` to ensure zero unintended edits and clean formatting.
6. **Report:** Summarize changes, reused modules, tests executed, and remaining issues.

## 3. Standard Verification Commands
- **Backend Unit Tests:**
  ```bash
  python -m pytest backend/tests/test_units.py -v
  ```
- **Full Backend Test Suite (with PostGIS DB):**
  ```bash
  export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/drch_test"
  python -m pytest backend/tests/ -v --tb=short
  ```
- **Backend Code Quality & Linting:**
  ```bash
  python -m ruff check backend/
  ```
- **Audit Hash-Chain Verification:**
  ```bash
  cd backend && python -m app.cli verify-audit
  ```
- **Frontend Typecheck & Build:**
  ```bash
  cd frontend && npm run build
  ```

## 4. Key Engineering Constraints
- **Zero Supabase:** Database is Neon PostgreSQL with PostGIS. Never use Supabase Auth, `auth.users`, or Supabase SQL.
- **Human Dispatcher Control:** AI recommendations are strictly advisory. Never automate dispatch, priority change, or incident verification.
- **Concurrency Protection:** Always use `SELECT ... FOR UPDATE` when allocating resources in `backend/app/services/resources.py`.
- **Append-Only Audit:** State transitions must write to `audit_logs` and maintain SHA-256 hash chains.
- **Strict Scenarios:** Only `cyclone`, `industrial_fire`, and `urban_flooding` are supported.
- **Git Restrictions:** You are explicitly forbidden from running `git commit`, `git push`, `git merge`, `git reset`, `git clean`, or `gh pr merge`.
