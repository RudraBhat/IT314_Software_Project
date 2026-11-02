import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import ConfigError, get_settings, validate_for_environment
from app.errors import install_error_handlers
from app.routers import auth, citizen, donations, field, internal
from app.routers.dm import router as dm_router
from app.routers.public import router as public_router  # Nisarg S1-07: public incidents API
from app.services.dispatch import escalate_overdue

logger = logging.getLogger("drch.backend")
logging.basicConfig(level=logging.INFO)

# ═══════════════════════════════════════════════════════════════════
# Background worker configuration
# ═══════════════════════════════════════════════════════════════════

WORKER_INTERVAL_SECONDS = 60
_SPATIAL_SYNC_LOCK = 314_0030


def _sync_spatial_boundaries_with_lock() -> list[dict]:
    with db.transaction() as conn:
        locked = conn.execute(
            "SELECT pg_try_advisory_xact_lock(%s) AS ok",
            (_SPATIAL_SYNC_LOCK,),
        ).fetchone()
        if not locked or not locked.get("ok"):
            return []
        from app.services.spatial_sync import check_and_sync_all_sources
        return check_and_sync_all_sources()


async def ai_workers_background_consumer():
    """
    In-process worker consumer loop:
    Runs concurrently with the FastAPI gateway to handle background tasks
    without requiring a separate paid cloud worker instance.
    Currently: escalates dispatches left unacknowledged past the timeout (DM-NFR-13).
    Guarded by Postgres advisory transaction lock (_ESCALATION_LOCK) so multiple
    workers (or WEB_CONCURRENCY > 1) do not duplicate escalations.
    """
    logger.info("Initializing in-process GenAI Triage & Emergency Worker...")
    try:
        while True:
            await asyncio.sleep(WORKER_INTERVAL_SECONDS)
            if not get_settings().database_url:
                continue
            try:
                await asyncio.to_thread(escalate_overdue)
            except Exception:
                logger.exception("Dispatch escalation check failed; will retry")
    except asyncio.CancelledError:
        logger.info("AI Worker consumer stopped gracefully.")


async def spatial_boundary_monthly_worker():
    """
    Monthly Background Spatial Boundary Worker:
    Periodically checks if official boundary datasets or upstream GIS providers
    have updated (ETag/Last-Modified check) and syncs changes into PostGIS without manual intervention.
    Guarded by Postgres advisory transaction lock (_SPATIAL_SYNC_LOCK).
    """
    settings = get_settings()
    if not settings.boundary_sync_enabled:
        return

    logger.info("Initializing monthly spatial boundary synchronization worker...")
    try:
        # Initial check on startup after short warm-up delay
        await asyncio.sleep(10)
        while True:
            if settings.database_url:
                try:
                    results = await asyncio.to_thread(_sync_spatial_boundaries_with_lock)
                    if any(r.get("status") == "synced" for r in results):
                        from app.geo import load_boundaries_from_db
                        await asyncio.to_thread(load_boundaries_from_db)
                except Exception:
                    logger.exception("Spatial boundary sync check encountered error; will retry next interval")
            await asyncio.sleep(settings.boundary_sync_check_interval_seconds)
    except asyncio.CancelledError:
        logger.info("Spatial boundary worker stopped gracefully.")


# ═══════════════════════════════════════════════════════════════════
# Application Lifespan (startup / shutdown)
# ═══════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = validate_for_environment(get_settings())
    if problems:
        raise ConfigError("; ".join(problems))
    # Startup: ensure database schema migrations are applied
    if get_settings().database_url:
        try:
            from app.migrate import apply_migrations
            await asyncio.to_thread(apply_migrations)
        except Exception:
            logger.exception("Database migration failed on startup")
            if get_settings().app_env != "development":
                raise  # never serve traffic on a half-migrated schema

        # Startup: load official PostGIS spatial boundaries into in-memory RAM cache (Option 2)
        try:
            from app.geo import load_boundaries_from_db
            loaded = await asyncio.to_thread(load_boundaries_from_db)
            if loaded:
                logger.info("Loaded Gujarat boundary and district cache from PostGIS into RAM.")
            else:
                logger.info("PostGIS boundary table not yet populated; active on static fallback.")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load boundary cache from PostGIS; using static fallback.")

    # Startup: spawn worker tasks in background
    worker_task = asyncio.create_task(ai_workers_background_consumer())
    spatial_task = asyncio.create_task(spatial_boundary_monthly_worker())
    yield
    # Shutdown: cancel worker tasks
    worker_task.cancel()
    spatial_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    try:
        await spatial_task
    except asyncio.CancelledError:
        pass
    db.close_pool()




app = FastAPI(
    title="DRCH API Gateway & Workers",
    version="1.0.0",
    lifespan=lifespan
)
install_error_handlers(app)
app.include_router(auth.router)
app.include_router(citizen.router)
app.include_router(field.router)
app.include_router(donations.router)
app.include_router(dm_router)
app.include_router(public_router)  # Nisarg S1-07: public incidents (no auth required)
app.include_router(internal.router)  # S2-09, S2-16: internal maintenance & ingestion cron


# CORS - origins come from CORS_ALLOWED_ORIGINS (see app/config.py)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


# ═══════════════════════════════════════════════════════════════════
# Existing root & health endpoints (preserved)
# ═══════════════════════════════════════════════════════════════════

@app.get('/')
def read_root():
    return {'message': 'DRCH API Gateway & In-Process AI Worker are running'}


@app.get('/health')
def health_check():
    return {'status': 'healthy', 'service': 'drch-backend'}


@app.get('/api/v1/health')
def api_health():
    """Liveness plus database reachability and deployed version (SRS s.15.6)."""
    database = "not_configured"
    if get_settings().database_url:
        try:
            with db.transaction() as conn:
                conn.execute("SELECT 1")
            database = "ok"
        except Exception:
            logger.exception("Database health check failed")
            database = "unavailable"
    return {
        'status': 'healthy',
        'service': 'drch-backend',
        'database': database,
        'version': os.getenv("GIT_SHA", "dev"),
    }
