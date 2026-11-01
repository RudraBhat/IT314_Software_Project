---
name: test-plan
description: Design targeted test plans for new features, bug fixes, or regressions in DRCH.
---

# Test Planning Workflow (/test-plan)

Design a robust, targeted test plan before implementing or validating changes:

## 1. Test Architecture Rules
- **Non-DB Unit Tests:** Pure logic, enums, schema validations, and mockable routines must run quickly without requiring PostgreSQL (`TEST_DATABASE_URL` unset).
- **PostGIS DB Tests:** Integration tests requiring PostgreSQL PostGIS must be isolated, use transactions or clean fixtures, and adhere to `REQUIRE_DB_TESTS` CI conventions.
- **Three Scenarios:** Write scenario-specific assertions for `cyclone`, `industrial_fire`, and `urban_flooding`. Test that other events properly map to `other_disaster`.
- **Concurrency Tests:** Test race conditions on resource limits using multiple concurrent threads or simulated conflict assertions.

## 2. Test Plan Structure
1. **Scope:** Target module, routers, and functions.
2. **Unit Test Cases:** Fast, in-memory assertions (`backend/tests/test_units.py`).
3. **Integration Test Cases:** PostGIS database tests (`backend/tests/test_*.py`).
4. **Execution Command:** Specific pytest command to run only the relevant tests.

