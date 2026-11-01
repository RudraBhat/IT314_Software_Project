---
trigger: model_decision
description: Load when changing project structure, system architecture, module boundaries, APIs, or integrating frontend, backend and AI services.
---

# Architecture & Module Boundary Rules

- **Consult System Architecture:** Review `docs/ARCHITECTURE.md` to understand existing boundaries before proposing changes.
- **Maintain Tier Separation:**
  - `frontend/`: Next.js 14 App Router, UI components, client-side session management, Leaflet GIS layers.
  - `backend/`: FastAPI application, domain services (`app/services/`), routers (`app/routers/`), database access (`app/db.py`).
  - `ai-workers/`: Isolated model execution and training microservices; decouple from core backend request loops.
- **Service Layer Pattern:**
  - Route handlers in `backend/app/routers/` must delegate business logic to `backend/app/services/` (`dispatch.py`, `resources.py`, `incidents.py`, `recommendations.py`).
  - Do not place raw SQL queries or complex business workflows inside route handler definitions.
- **Scope Restriction:**
  - System operations support 3 core scenarios: `cyclone`, `industrial_fire`, and `urban_flooding`.
  - Unsupported events map to `other_disaster` (do not introduce new scenario types without explicit database migration).
- **API Versioning & Contracts:**
  - All public, dispatch, and operational endpoints live under `/api/v1/`.
  - Preserve standard API error contract conforming to SRS s.15.7 (`{ "error": { "code": "...", "message": "...", "details": null } }`).
- **No Unnecessary Abstractions:**
  - Avoid creating wrapper classes, abstract base classes, or auxiliary microservices unless explicitly requested.
