---
name: implement-feature
description: Implement a feature using existing DRCH architecture, shared services, and technical constraints.
---

# Feature Implementation Workflow (/implement-feature)

Follow this structured workflow to implement features safely within DRCH:

## 1. Requirements & Architectural Scope
- Review the user's feature specification.
- Check `docs/architecture/ARCHITECTURE.md` and `docs/architecture/api_contracts.md` to identify affected layers:
  - Frontend (`frontend/src/app/`, `frontend/src/components/`)
  - Backend API (`backend/app/routers/`, `backend/app/services/`)
  - Database schema (`backend/db/migrations/`)
- Ensure the feature adheres to the 3 in-scope scenarios: `cyclone`, `industrial_fire`, `urban_flooding`.

## 2. Inspect Before Creating
- Search the codebase for existing reusable utilities, services, and components:
  - Backend: `app.services.dispatch`, `app.services.resources`, `app.services.recommendations`, `app.geo`, `app.audit`, `app.db`.
  - Frontend: `ui.tsx`, `badges.tsx`, `LiveOperationsLayer.tsx`, `ResQContext.tsx`, `lib/api.ts`.
- **Never create duplicate files or duplicate logic.**

## 3. DRCH Technical Constraints
Follow `AGENTS.md` section 4 and the matching `.agents/rules/*.md` file. Record state changes with `app.audit.log_audit_event()`.

## 4. Execution & Verification
1. Make minimal, targeted changes.
2. Add or update unit/integration tests in `backend/tests/`.
3. Run tests and lint checks:
   ```bash
   python -m pytest backend/tests/test_units.py -v
   ```
4. Inspect the full `git diff` to ensure no accidental files or unintended modifications.
5. Present changes for human review and follow `AGENTS.md` sections 5 and 6 for git, commit, PR and issue handling.
