"""Disaster Management API: every route requires the DISASTER_MGMT role (SRS s.15.4)."""

from fastapi import APIRouter, Depends

from app.auth import require_dm
from app.routers.dm import (
    ai,
    aid,
    analytics,
    content,
    dashboard,
    dispatches,
    incidents,
    moderation,
    recommendations,
    resources,
    staff,
)

# Router-level guard as defence in depth; FastAPI caches it, so routes that also declare it cost nothing extra.
router = APIRouter(prefix="/api/v1/dm", tags=["disaster-management"], dependencies=[Depends(require_dm)])
for module in (dashboard, incidents, ai, resources, dispatches, content, moderation, aid, analytics, staff, recommendations):
    router.include_router(module.router)
