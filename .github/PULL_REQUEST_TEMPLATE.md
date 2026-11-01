## Summary of Changes

## Sprint 2 Quality & Security Checklist
- [ ] **Scenario Scope:** Preserves strict 3-scenario scope (`cyclone`, `industrial_fire`, `urban_flooding`; no unauthorized additions).
- [ ] **Secret Hygiene:** Zero plaintext secrets, keys, or passwords committed; environment variable names only.
- [ ] **State Machine & Audit Integrity:** Uses shared `transition_dispatch` in `services/dispatch.py` and logs all actions via `audit.record` (hash chain verified).
- [ ] **Cross-Team Isolation:** Field routes verify team membership via `field_team_members` and return `404 Not Found` for unassigned dispatches.
- [ ] **Idempotency:** State-changing endpoints require and enforce unique `Idempotency-Key` headers.
- [ ] **Database Integrity:** Zero regressions in existing 59 tests; new DB tests run without skipping under `REQUIRE_DB_TESTS=1`.
- [ ] **Codeowner Review:** Reviewed and approved by the assigned module codeowner per `.github/CODEOWNERS`.
