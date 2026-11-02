---
trigger: model_decision
description: Load when modifying FastAPI endpoints, backend services, database schemas, SQL queries, migrations, Redis, RabbitMQ or background workers.
---

# Backend & Database Engineering Rules

- **Database Engine & Tooling:**
  - Target database is **Neon PostgreSQL 16 with PostGIS** using `psycopg` / `psycopg_pool`.
  - **Zero Supabase:** Never use Supabase client libraries, Supabase Auth, `auth.users`, `auth.uid()`, or Supabase RLS helpers.
- **Connection & Transactions:**
  - Always use `with db.transaction() as conn:` from `app.db` for transactional state changes.
  - Never execute unparameterized SQL string formatting; always pass parameters via query tuples (`%s`).
- **Concurrency & Resource Locking:**
  - When allocating resources or changing inventory quantities, lock rows using `SELECT ... FOR UPDATE` before decrementing.
  - Return `409 RESOURCE_CONFLICT` on over-allocation and roll back state cleanly.
  - Use PostgreSQL transactional advisory locks (`pg_try_advisory_xact_lock`) for recurring ingestion and cron synchronization to prevent race conditions.
- **Migrations & Schema Evolution:**
  - Migrations reside in `backend/db/migrations/` with sequential numerical naming (`01_schema.sql`, `02_dm_module.sql`, etc.).
  - Migrations must be strictly idempotent, non-destructive, and backward-compatible.
  - Never alter existing migration files that have already been applied to staging or production.
- **Spatial Queries & Geofencing:**
  - Use PostGIS geometry functions (`ST_Contains`, `ST_Distance`, `ST_GeomFromText`) against `administrative_boundaries`.
  - Fall back to in-memory spatial cache in `app.geo` for rapid point-in-polygon containment checks.
- **Background Processing & Workers:**
  - Long-running maintenance loops (e.g. boundary sync, alert ingestion) must run in isolated `asyncio` background tasks spawned during application lifespan.
- **Testing Requirements:**
  - Run `python -m pytest backend/tests/ -v` after backend modifications.
  - Ensure tests respect `REQUIRE_DB_TESTS` CI guard and skip gracefully when `TEST_DATABASE_URL` is absent.
