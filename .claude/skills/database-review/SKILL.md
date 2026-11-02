---
name: database-review
description: Review database queries, transactions, PostGIS usage, migrations, and concurrency locks.
---

# Database Review Workflow (/database-review)

Review PostgreSQL PostGIS queries, transaction scopes, and concurrency safeguards:

## 1. Review Checklist
- **Concurrency & Locking:** Verify resource allocations use `SELECT ... FOR UPDATE` within an active transaction (`with db.transaction() as conn:`).
- **Advisory Locks:** Check that scheduled tasks use `pg_try_advisory_xact_lock` to avoid double-processing.
- **SQL Injection Prevention:** Confirm all queries use parameterized tuples (`%s`) instead of formatted f-strings.
- **Migration Safety:** Ensure SQL scripts in `backend/db/migrations/` are idempotent, additive, and backward-compatible.
- **PostGIS Geometries:** Verify spatial containment uses `ST_Contains` or `ST_Distance` with spatial indexes (`GIST`).
- **Audit Triggers:** Verify triggers like `fn_audit_log_hash_chain` remain active and are not disabled.

## 2. Output
List all query patterns reviewed, potential bottlenecks, lock contention risks, and compliance status with Neon PostgreSQL 16.

