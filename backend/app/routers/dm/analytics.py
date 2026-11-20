"""Operational and contribution analytics (DM-FR-14, DM-NFR-12) and the operational map (DM-FR-07)."""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from psycopg import sql

from app import db
from app.auth import DMUser
from app.common import Filters, IncidentStatus, Scenario, scenario_db

router = APIRouter()


def _incident_filters(scenario, from_, to) -> Filters:
    f = Filters()
    if scenario:
        f.add("i.scenario = %(scenario)s::scenario_type", scenario=scenario_db(scenario))
    if from_:
        f.add("i.submitted_at >= %(from_)s::date", from_=from_)
    if to:
        f.add("i.submitted_at < (%(to)s::date + 1)", to=to)
    return f


@router.get("/analytics")
def analytics(
    *,
    scenario: Scenario | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    principal: DMUser,
):
    f = _incident_filters(scenario, from_, to)
    where = f.where()
    with db.read_only() as conn:
        # Every statement is independent: send them in one pipeline (one network round trip) and read
        # the results afterwards.
        def run(query: str):
            return conn.execute(sql.SQL(query).format(where=where), f.params)

        with conn.pipeline():
            q_by_scenario_status = run(
                "SELECT lower(i.scenario::text) AS scenario, i.status, COUNT(*) AS n "
                "FROM incidents i {where} GROUP BY 1, 2 ORDER BY 1, 2"
            )
            q_by_priority = run(
                "SELECT COALESCE(i.verified_priority::text, 'UNASSIGNED') AS priority, COUNT(*) AS n "
                "FROM incidents i {where} GROUP BY 1 ORDER BY 1"
            )
            q_per_day = run(
                "SELECT date_trunc('day', i.submitted_at)::date AS day, COUNT(*) AS n "
                "FROM incidents i {where} GROUP BY 1 ORDER BY 1"
            )
            q_timings = run(
                "SELECT COUNT(*) FILTER (WHERE i.verified_at IS NOT NULL) AS verified, "
                "percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (i.verified_at - i.submitted_at))) "
                "  FILTER (WHERE i.verified_at IS NOT NULL) AS median_seconds_to_verify, "
                "COUNT(*) FILTER (WHERE i.closed_at IS NOT NULL) AS closed, "
                "percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (i.closed_at - i.submitted_at))) "
                "  FILTER (WHERE i.closed_at IS NOT NULL) AS median_seconds_to_close "
                "FROM incidents i {where}"
            )
            q_dispatch = run(
                "SELECT d.status, d.priority, COUNT(*) AS n, "
                "AVG(EXTRACT(EPOCH FROM (d.acknowledged_at - d.created_at))) "
                "  FILTER (WHERE d.acknowledged_at IS NOT NULL) AS avg_ack_seconds "
                "FROM dispatch_orders d JOIN incidents i ON i.incident_id = d.incident_id {where} "
                "GROUP BY 1, 2 ORDER BY 1, 2"
            )
            q_ai = run(
                "SELECT r.status, COALESCE(r.human_action::text, 'UNDECIDED') AS human_action, "
                "COUNT(*) FILTER (WHERE NOT COALESCE((r.factors->>'out_of_scope')::boolean, false)) AS in_scope, "
                "COUNT(*) FILTER (WHERE COALESCE((r.factors->>'out_of_scope')::boolean, false)) AS out_of_scope "
                "FROM ai_recommendations r JOIN incidents i ON i.incident_id = r.incident_id {where} "
                "GROUP BY 1, 2 ORDER BY 1, 2"
            )
            q_ai_by_decision = run(
                "SELECT lower(i.scenario::text) AS scenario, "
                "COALESCE(r.human_action::text, 'UNDECIDED') AS human_action, "
                "CASE "
                "  WHEN r.confidence >= 0.80 THEN 'HIGH' "
                "  WHEN r.confidence >= 0.60 THEN 'MEDIUM' "
                "  WHEN r.confidence IS NOT NULL THEN 'LOW' "
                "  ELSE 'UNKNOWN' "
                "END AS confidence_band, "
                "COUNT(*) AS n "
                "FROM ai_recommendations r JOIN incidents i ON i.incident_id = r.incident_id {where} "
                "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
            )
            # Contribution figures are not tied to incidents, so the incident filters do not apply.
            q_donations = conn.execute(
                "SELECT COALESCE(SUM(confirmed_amount), 0) AS confirmed, COALESCE(SUM(pending_amount), 0) AS pending, "
                "COALESCE(SUM(failed_amount), 0) AS failed FROM v_donation_summary"
            )
            q_aid = conn.execute(
                "SELECT status, SUM(contributions) AS contributions FROM v_aid_summary GROUP BY status ORDER BY status"
            )
            q_resources = conn.execute(
                "SELECT type::text AS type, status::text AS status, COUNT(*) AS n FROM v_resource_availability "
                "GROUP BY 1, 2 ORDER BY 1, 2"
            )
            q_fresh = conn.execute("SELECT MAX(updated_at) AS t FROM incidents")
        by_scenario_status = q_by_scenario_status.fetchall()
        by_priority = q_by_priority.fetchall()
        per_day = q_per_day.fetchall()
        timings = q_timings.fetchall()[0]
        dispatch = q_dispatch.fetchall()
        ai = q_ai.fetchall()
        ai_by_decision = q_ai_by_decision.fetchall()
        donations = q_donations.fetchone()
        aid = q_aid.fetchall()
        resources = q_resources.fetchall()
        fresh = q_fresh.fetchone()["t"]

    return {
        "filters": {"scenario": scenario, "from": from_, "to": to},
        "generated_at": datetime.now(UTC),
        "data_fresh_as_of": fresh,
        "incidents": {
            "by_scenario_status": by_scenario_status,
            "by_priority": by_priority,
            "per_day": per_day,
            "timings": timings,
        },
        "dispatches": dispatch,
        "ai_recommendations": ai,
        "ai_by_decision": ai_by_decision,
        "donations": donations,
        "aid": aid,
        "resources": resources,
        "definitions": {
            "UNASSIGNED": "No human-assigned priority yet; counted separately, never guessed.",
            "out_of_scope": "AI suggested a type outside the three supported scenarios; staff triaged manually.",
            "confidence_bands": "AI confidence at suggestion time: HIGH is 0.80 or more, MEDIUM is 0.60 to 0.79, LOW is below 0.60; "
            "rows without a recorded confidence are UNKNOWN. UNDECIDED means no human decision yet.",
            "median_seconds_to_verify": "Median time from submission to a recorded verification.",
            "avg_ack_seconds": "Average time from dispatch request to a recorded acknowledgement.",
            "donations": "Confirmed amounts only count gateway-confirmed payments; pending is shown apart.",
            "scope": "Incident, dispatch and AI figures follow the filters; contribution and resource figures are "
            "system-wide.",
        },
    }


@router.get("/map")
def operational_map(
    *,
    scenario: Scenario | None = None,
    status: Annotated[list[IncidentStatus] | None, Query()] = None,
    include_closed: bool = False,
    principal: DMUser,
):
    f = Filters()
    if scenario:
        f.add("i.scenario = %(scenario)s::scenario_type", scenario=scenario_db(scenario))
    if status:
        f.add("i.status = ANY(%(status)s::incident_status[])", status=status)
    elif not include_closed:
        f.add("i.status NOT IN ('CLOSED', 'REJECTED')")

    where = f.where()
    with db.read_only() as conn:
        incidents = conn.execute(
            sql.SQL(
                "SELECT i.incident_id, i.incident_ref, lower(i.scenario::text) AS scenario, i.status, "
                "i.verified_priority, i.latitude, i.longitude, i.accuracy_m, i.location_source, i.address_text, "
                "i.people_affected, i.updated_at FROM incidents i {} ORDER BY i.updated_at DESC LIMIT 2000"
            ).format(where),
            f.params,
        ).fetchall()
        resources = conn.execute(
            """
            SELECT r.resource_id, r.name, r.type, r.status, r.quantity_available, r.quantity_total,
                   a.name AS agency_name,
                   ST_Y(r.current_geom::geometry) AS latitude, ST_X(r.current_geom::geometry) AS longitude,
                   r.updated_at
            FROM resources r LEFT JOIN agencies a ON a.agency_id = r.agency_id
            WHERE r.current_geom IS NOT NULL
            """
        ).fetchall()
    located = [i for i in incidents if i["latitude"] is not None and i["longitude"] is not None]
    return {
        "generated_at": datetime.now(UTC),
        "data_fresh_as_of": max((i["updated_at"] for i in incidents), default=None),
        "incidents": located,
        "incidents_without_coordinates": [
            {k: i[k] for k in ("incident_id", "incident_ref", "scenario", "status", "address_text")}
            for i in incidents
            if i["latitude"] is None or i["longitude"] is None
        ],
        "resources": resources,
    }


@router.get("/map/layers")
def map_layers(principal: DMUser):
    return {
        "layers": [
            {"id": "incidents", "label": "Incidents", "source": "incidents.geom (PostGIS)"},
            {"id": "resources", "label": "Resources", "source": "resources.current_geom (PostGIS)"},
        ],
        "basemap": {"provider": "OpenStreetMap", "attribution": "© OpenStreetMap contributors"},
        "unavailable": ["routes", "affected areas"],
    }
