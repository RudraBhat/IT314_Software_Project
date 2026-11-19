"""Disaster Management API: every route requires the DISASTER_MGMT role (SRS s.15.4)."""

from fastapi import APIRouter, Depends

from app.auth import require_dm
from app.routers.dm import (
    agencies,
    ai,
    aid,
    analytics,
    content,
    dashboard,
    dispatches,
    exports,
    incidents,
    ingestion,
    moderation,
    notes,
    recommendations,
    resources,
    shelters,
    signals,
    staff,
)

# Router-level guard as defence in depth; FastAPI caches it, so routes that also declare it cost nothing extra.
router = APIRouter(prefix="/api/v1/dm", tags=["disaster-management"], dependencies=[Depends(require_dm)])
for module in (dashboard, exports, incidents, notes, ai, recommendations, resources, dispatches, content, moderation, aid, analytics, staff, signals, ingestion, shelters, agencies):
    router.include_router(module.router)
