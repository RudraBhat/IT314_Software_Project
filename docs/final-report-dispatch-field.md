# Final report section: dispatch, field and public map API (S3-16)

Author: Nisarg. Part of the final report assembled by Zalak in [final-report.md](final-report.md) (section 6).
Written against `main` on 14 Nov 2026. Request and response shapes are in [api_contracts.md](api_contracts.md)
sections 1, 3, 5 and 6; this section explains how the pieces behave and what is real or simulated.

## What is real and what is simulated

| Part | Status |
| --- | --- |
| Dispatch creation, acknowledgement, progress, completion, failure, escalation and the audit trail | Real |
| Field accounts (password + TOTP), team isolation and the field screens | Real |
| Team recommendations, team-request decisions and the public map | Real logic on seeded Gujarat agencies and teams |
| Demo incidents used in rehearsals | Seeded with `is_simulated = TRUE` and hidden from the public map outside development |

## Public map and geofence (S1-07)

* `GET /api/v1/public/incidents` returns only incidents that a dispatcher verified (`VERIFIED`, `DISPATCHED` or
  `RESOLVED`) and that are not linked duplicates, with reference, scenario, district, status, verified time,
  priority and coordinates rounded to 4 decimals. No reporter fields and no free text are returned. Filters:
  district, scenario and bounding box.
* `app/geo.py` checks a point against the Gujarat polygon (bounding box first, then the polygon, with PostGIS
  boundaries loaded at start-up) and finds its district. Citizen reports outside Gujarat are refused with
  `422 OUTSIDE_GUJARAT`; promoted signals use the same check.

## Dispatch (shared with Shlok's transition functions)

* `POST /api/v1/dm/incidents/{id}/dispatches` needs the `DISPATCH` permission and an `Idempotency-Key`. Each
  requested resource row is locked with `SELECT ... FOR UPDATE` before it is reserved, so two dispatchers cannot
  book the same team; the second gets `409 RESOURCE_CONFLICT` and nothing partial is written.
* The dispatcher routes and the field routes call the same state-transition functions
  (`app/services/dispatch.py`), so both write the same history and audit rows:
  `REQUESTED → ACKNOWLEDGED → DISPATCHED (EN_ROUTE) → COMPLETED`, with `REJECTED` and `FAILED` as endings. An
  action that is not allowed from the current state is refused with `409` and audited. Incident changes (verify,
  resolve, close) take the incident's version, so a stale screen gets `409 VERSION_CONFLICT`.
* The incident moves to `DISPATCHED` when the team reports `EN_ROUTE`. Completing the dispatch releases the team
  but does **not** close the incident: the dispatcher resolves and closes it.
* A background loop escalates a dispatch still `REQUESTED` after `DISPATCH_ACK_TIMEOUT_MINUTES` (default 15), once
  per dispatch, guarded by an advisory lock so several workers never double-escalate.

## Field team API (S2-01)

* `require_field` loads the responder's team from `field_team_members`. `GET /field/me` returns the profile and
  team; `GET /field/assignments` lists only dispatches that include that team.
* `POST /field/dispatches/{id}/acknowledgement`, `/rejection` (reason required), `/progress` (`EN_ROUTE`,
  `ON_SCENE` plus a note, stored in `dispatch_progress`), `/team-requests` (capability and note, stored `OPEN`) and
  `/completion` (summary). Another team's dispatch answers `404`, never `403`, so its existence is not revealed.
* Field accounts are created with `python -m app.cli create-field` and sign in with password + TOTP like staff.

## Team recommendations and team requests (S1-11, S2-02, S3-14)

* `GET /dm/incidents/{id}/team-recommendations` ranks available teams for the incident's scenario: each required
  capability covered scores `PRIMARY_WEIGHT` (10), each secondary capability `SECONDARY_WEIGHT` (3), minus
  `DISTANCE_PENALTY_PER_KM` (0.08) per kilometre (PostGIS `ST_Distance`). Each team comes with plain reasons, and the
  response carries `requires_confirmation: true`. It never creates a dispatch; the dispatcher confirms with the
  dispatch route above, so a reserved team disappears from the next recommendation.
* `GET /dm/team-requests` lists field requests for more help; `POST /dm/team-requests/{id}/decision` needs
  `DISPATCH`: `APPROVE` returns a pre-filled dispatch draft (no dispatch is created) and `DECLINE` stores the
  rationale. A second decision answers `409 TEAM_REQUEST_ALREADY_DECIDED`.
* Tuning: `scripts/evaluate_team_recommendations.py` produces the review sheet for judging the top 3 teams for the
  rehearsal incidents; `test_recommendation_tuning.py` keeps the agreed rankings from regressing.

## Performance (S3-13, with Shlok)

`scripts/explain_queries.py` runs `EXPLAIN (ANALYZE, BUFFERS)` on the public-map and recommendation queries. No
index was added: add one by migration only if a plan on the staging database shows a sequential scan on a large
table. Shlok's load test measured the public map at p95 633 ms over 200 requests ([load-test.md](load-test.md)).

## Tests

| Area | Tests |
| --- | --- |
| Public map and geofence | `test_public_api.py`, `test_phase5_public_geo_integration.py` |
| Dispatch transitions and locking | `test_dispatch.py`, `test_dispatch_transitions.py` |
| Field API and isolation | `test_field.py`, `test_field_api.py`, `test_field_routes.py`, `test_field_auth_cli.py` |
| Recommendations and team requests | `test_recommendations.py`, `test_team_recommendations.py`, `test_recommendation_workflows.py`, `test_recommendation_tuning.py`, `test_recommendations_unavailable.py` |
| End to end over HTTP | `test_scenario_dispatch_field_flow.py` (PostGIS test database); `scripts/scenario_run.py` repeats the whole cyclone scenario against staging (Dhruv) |
| Query plans | `test_explain_queries.py` |

These are DB-backed and run in CI's PostGIS job.

## Known limits

* Recommendation weights were tuned by hand on a small set of rehearsal incidents, not learned from data.
* Distances are straight-line (PostGIS), not road distance.
* Escalation and team availability depend on the free-tier backend being awake; the ingestion cron keeps it warm.

Sign-off: Nisarg, 14 Nov 2026
