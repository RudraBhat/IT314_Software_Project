# DRCH — Future Features Backlog

The `fix/audit-v2` branch removed the legacy ResQ prototype (Mumbai demo, `localStorage`,
SQLite). The code is gone, but the ideas worth rebuilding on the DRCH stack (FastAPI + Neon
PostGIS + Next.js, Gujarat, scenarios `cyclone` / `industrial_fire` / `urban_flooding` only)
are listed here. Original sources remain in `main` history for reference.

Constraints for every item: AI stays advisory, humans approve verify/dispatch/escalate/close,
state changes write to `audit_logs`, public coordinates truncated to 4 decimals.

## Status

| # | Feature | Status | Where |
|---|---------|--------|-------|
| 1 | Nearby-incident hint while reporting | Done | `services/duplicateDetection.ts`, `/report` |
| 2 | Alerts drawer (unread / simulated filters, mark read) | Done | `components/dm/AlertsDrawer.tsx`, DM header |
| 3 | Analytics CSV export | Done | `dm/analytics/page.tsx` |
| 4 | Scenario walkthrough (links only, no data changes) | Done | `components/dm/ScenarioWalkthrough.tsx`, `/dm` |
| 5 | Responders roster | Already covered | `dm/staff`, `/field` assignments |
| 6 | Resources with allocation | Already covered | `dm/resources`; reservation happens through dispatch (`FOR UPDATE`) |
| 7 | Incident quick view on map | Already covered | `LiveOperationsLayer` popup links to `dm/incidents/[id]` |
| 8 | Permission-based home dashboard | Done | "Your focus" card on `/dm` |
| 9 | Urgent-needs checklist on report | Done | `services/preTriage.ts`, `/report` |
| 10 | Advisory pre-triage hint | Done | `services/preTriage.ts`, `/report` |

Items 7 and 5 could still grow (a side panel instead of a popup; a skills/availability roster).

Dropped for good (superseded): `ResQContext`/`resqStorage` (localStorage state), `authApi`
(replaced by app-managed auth + TOTP), SQLite `database.py`/`models.py`, root `main.py`,
`ai-workers/worker.py` stub, `test_citizen_api.py`.
