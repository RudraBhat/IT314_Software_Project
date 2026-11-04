"""Lightweight, idempotent SQL migration and seed runner with version tracking."""

import logging
from pathlib import Path

from app import db
from app.config import get_settings

logger = logging.getLogger("drch.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"
SEEDS_DIR = Path(__file__).resolve().parents[1] / "db" / "seeds"

_MIGRATION_LOCK = 314_0099


def apply_migrations() -> list[str]:
    """Run pending scripts while holding a session advisory lock (safe with several instances)."""
    with db.get_pool().connection() as lock_conn:
        lock_conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK,))
        try:
            return _apply_pending()
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK,))


def _apply_pending() -> list[str]:
    """
    Applies any pending SQL migrations and seeds in ascending numerical order.
    Tracks applied scripts in the `schema_migrations` table so they are
    never re-executed (already-run scripts are automatically skipped).
    """
    applied = []
    # Ensure migrations tracking table exists
    with db.transaction() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        applied_versions = {r["version"] for r in rows}

    # 1. Apply pending migrations in ascending version order
    if MIGRATIONS_DIR.exists():
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)
        for filepath in migration_files:
            version_name = filepath.name
            if version_name not in applied_versions:
                logger.info("Applying database migration: %s", version_name)
                with open(filepath, "r", encoding="utf-8") as f:
                    sql_content = f.read()
                # Execute each migration in its own dedicated transaction
                with db.transaction() as conn:
                    conn.execute(sql_content)
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version_name,),
                    )
                applied.append(version_name)
                applied_versions.add(version_name)
            else:
                logger.debug("Skipping already applied migration: %s", version_name)

    # 2. Apply pending seeds: db/seeds/reference always; db/seeds/demo only when APP_ENV=development
    seed_files = sorted(SEEDS_DIR.glob("reference/*.sql"), key=lambda p: p.name)
    if get_settings().app_env == "development":
        seed_files += sorted(SEEDS_DIR.glob("demo/*.sql"), key=lambda p: p.name)
    for filepath in seed_files:
        version_name = f"seeds/{filepath.parent.name}/{filepath.name}"
        if version_name in applied_versions:
            logger.debug("Skipping already applied seed: %s", version_name)
            continue
        logger.info("Applying database seed: %s", version_name)
        sql_content = filepath.read_text(encoding="utf-8")
        with db.transaction() as conn:
            conn.execute(sql_content)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version_name,))
        applied.append(version_name)
        applied_versions.add(version_name)

    if applied:
        logger.info("Successfully applied %d script(s): %s", len(applied), ", ".join(applied))
    else:
        logger.info("Database schema and seeds are up to date (0 pending scripts).")
    return applied

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    apply_migrations()
