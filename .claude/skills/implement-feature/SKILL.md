---
name: implement-feature
description: Implement a feature using existing DRCH architecture, shared services, and technical constraints.
---

# Feature Implementation Workflow (/implement-feature)

Follow this structured workflow to implement features safely within DRCH:

## 1. Requirements & Architectural Scope
- Review the user's feature specification.
- Check `docs/ARCHITECTURE.md` and `docs/api_contracts.md` to identify affected layers:
  - Frontend (`frontend/src/app/`, `frontend/src/components/`)
  - Backend API (`backend/app/routers/`, `backend/app/services/`)
  - Database schema (`backend/db/migrations/`)
- Ensure the feature adheres to the 3 in-scope scenarios: `cyclone`, `industrial_fire`, `urban_flooding`.

## 2. Inspect Before Creating
- Search the codebase for existing reusable utilities, services, and components:
  - Backend: `app.services.dispatch`, `app.services.resources`, `app.services.recommendations`, `app.geo`, `app.audit`, `app.db`.
  - Frontend: `ui.tsx`, `badges.tsx`, `LiveOperationsLayer.tsx`, `ResQContext.tsx`, `lib/api.ts`.
- **Never create duplicate files or duplicate logic.**

## 3. Strict DRCH Technical Constraints
- **Database:** Neon PostgreSQL 16 with PostGIS. Zero Supabase dependencies or Supabase Auth.
- **Concurrency:** When modifying resource quantities, always lock rows via `SELECT ... FOR UPDATE`.
- **AI Integration:** Keep AI triage advisory. Store suggestions in `triage_results`. Never bypass human dispatcher verification.
- **Auditability:** Record all state changes in `audit_logs` using `app.audit.log_audit_event()`.
- **Privacy:** Never leak citizen reporter PII. Round coordinates on public feeds to 4 decimal places.

## 4. Execution & Verification
1. Make minimal, targeted changes.
2. Add or update unit/integration tests in `backend/tests/`.
3. Run tests and lint checks:
   ```bash
   python -m pytest backend/tests/test_units.py -v
   ```
4. Inspect the full `git diff` to ensure no accidental files or unintended modifications.
5. **Git Restriction:** NEVER commit or push. Present changes cleanly for human review.
