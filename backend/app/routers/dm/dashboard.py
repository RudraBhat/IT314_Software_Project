"""DM-FR-02 dashboard: consolidated counts, queues and pending actions from live data."""

from datetime import UTC, datetime

from fastapi import APIRouter
from psycopg import Error as PsycopgError

from app import db
from app.auth import DMUser
from app.config import get_settings
from app.errors import ApiError

router = APIRouter()


@router.get("/dashboard")
def dashboard(principal: DMUser):
    timeout = get_settings().dispatch_ack_timeout_minutes
    if not get_settings().database_url:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "Database connection required")

    try:
        with db.transaction() as conn:
            counts = conn.execute(
                """
                SELECT
                  COUNT(*)                                                         AS total,
                  COUNT(*) FILTER (WHERE status IN ('SUBMITTED','NEEDS_INFORMATION')) AS pending_verification,
                  COUNT(*) FILTER (WHERE status = 'NEEDS_INFORMATION')            AS needs_information,
                  COUNT(*) FILTER (WHERE status IN ('VERIFIED','DISPATCHED'))     AS verified_active,
                  COUNT(*) FILTER (WHERE status NOT IN ('CLOSED','REJECTED','RESOLVED')
                                   AND verified_priority = 'CRITICAL')            AS critical_open,
                  COUNT(*) FILTER (WHERE status NOT IN ('CLOSED','REJECTED','RESOLVED')
                                   AND verified_priority = 'HIGH')                AS high_open,
                  COUNT(*) FILTER (WHERE status NOT IN ('CLOSED','REJECTED','RESOLVED')
                                   AND verified_priority IS NULL)                 AS unprioritised_open,
                  MAX(updated_at)                                                  AS data_fresh_as_of
                FROM incidents
                """
            ).fetchone()
            by_scenario = conn.execute(
                """
                SELECT lower(scenario::text) AS scenario,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status NOT IN ('CLOSED','REJECTED','RESOLVED')) AS open
                FROM incidents GROUP BY scenario ORDER BY scenario
                """
            ).fetchall()
            dispatch = conn.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE status IN ('REQUESTED','ACKNOWLEDGED','DISPATCHED')) AS active,
                  COUNT(*) FILTER (WHERE status = 'REQUESTED')                                AS awaiting_ack,
                  COUNT(*) FILTER (WHERE status = 'REQUESTED'
                                   AND created_at < now() - make_interval(mins => %s))        AS overdue
                FROM dispatch_orders
                """,
                (timeout,),
            ).fetchone()
            resources = conn.execute(
                """
                SELECT type::text AS type,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'AVAILABLE' AND quantity_available > 0) AS available
                FROM resources GROUP BY type ORDER BY type
                """
            ).fetchall()
            moderation = conn.execute(
                """
                SELECT COUNT(*) AS pending, MIN(uploaded_at) AS oldest
                FROM evidence_files WHERE scan_state IN ('PENDING','QUARANTINED','FAILED')
                """
            ).fetchone()
            aid = conn.execute(
                """
                SELECT (SELECT COUNT(*) FROM aid_contributions WHERE status = 'REGISTERED') AS awaiting_verification,
                       (SELECT COUNT(*) FROM aid_needs WHERE is_open)                     AS open_needs
                """
            ).fetchone()
            recent = conn.execute(
                """
                SELECT h.history_id, h.changed_at, h.from_status, h.to_status, h.reason,
                       i.incident_id, i.incident_ref, lower(i.scenario::text) AS scenario,
                       u.full_name AS changed_by_name
                FROM incident_status_history h
                JOIN incidents i ON i.incident_id = h.incident_id
                LEFT JOIN users u ON u.user_id = h.changed_by
                ORDER BY h.changed_at DESC, h.history_id DESC
                LIMIT 12
                """
            ).fetchall()
            queue = conn.execute(
                """
                SELECT incident_id, incident_ref, lower(scenario::text) AS scenario, status,
                       verified_priority, reported_urgency, people_affected, address_text, submitted_at
                FROM incidents
                WHERE status IN ('SUBMITTED','NEEDS_INFORMATION')
                ORDER BY reported_urgency NULLS LAST, submitted_at
                LIMIT 8
                """
            ).fetchall()

        return {
            "generated_at": datetime.now(UTC),
            "data_fresh_as_of": counts.pop("data_fresh_as_of"),
            "incidents": counts,
            "by_scenario": by_scenario,
            "dispatches": {**dispatch, "ack_timeout_minutes": timeout},
            "resources": {
                "by_type": resources,
                "available": sum(r["available"] for r in resources),
                "total": sum(r["total"] for r in resources),
            },
            "moderation": moderation,
            "aid": aid,
            "verification_queue": queue,
            "recent_activity": recent,
        }
    except PsycopgError as exc:
        raise ApiError(503, "DATABASE_ERROR", "Failed to retrieve live dashboard data") from exc
