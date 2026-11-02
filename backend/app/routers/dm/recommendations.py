"""Geospatial Team Recommendations and Field Backup Request Triage API.

Provides advisory team ranking based on incident scenario and PostGIS proximity,
and dispatcher decision workflows for reviewing and resolving field reinforcement requests.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from app import audit, db
from app.auth import Dispatcher, DMUser
from app.common import notify
from app.config import get_settings
from app.errors import ApiError, not_found
from app.geo import get_district_centroid
from app.schemas.recommendations import (
    TeamRecommendationResponse,
    TeamRequestDecisionRequest,
    TeamRequestDecisionResponse,
    TeamRequestItem,
)
from app.services.recommendations import extract_capability_tags, recommend_candidate_teams

logger = logging.getLogger("drch.dm.recommendations")

router = APIRouter()


# ── 1. Advisory Team Recommendations ─────────────────────────────────────


@router.get(
    "/incidents/{incident_id}/team-recommendations",
    response_model=TeamRecommendationResponse,
)
def get_incident_team_recommendations(
    incident_id: uuid.UUID,
    principal: DMUser,
    limit: Annotated[int, Query(ge=1, le=20, description="Max candidate teams to return")] = 5,
) -> TeamRecommendationResponse:
    """Retrieve geospatial team ranking for a verified incident.

    Strictly advisory decision-support endpoint: returns requires_confirmation: true.
    Never creates a dispatch automatically. Dispatch creation requires human authorization.
    """
    if not get_settings().database_url:
        # Offline/mock fallback for demo resilience
        demo_teams = recommend_candidate_teams(23.0225, 72.5714, "URBAN_FLOODING", limit=limit)
        return TeamRecommendationResponse(
            incident_id=incident_id,
            scenario="URBAN_FLOODING",
            requires_confirmation=True,
            recommendations=demo_teams,
            generated_at=datetime.now(UTC),
        )

    with db.transaction() as conn:
        row = conn.execute(
            """
            SELECT incident_id, incident_ref, scenario, status, district,
                   ST_Y(geom::geometry) AS latitude, ST_X(geom::geometry) AS longitude
            FROM incidents
            WHERE incident_id = %(incident_id)s
            """,
            {"incident_id": incident_id},
        ).fetchone()

        if row is None:
            raise not_found("Incident")

        lat = float(row["latitude"]) if row["latitude"] is not None else None
        lon = float(row["longitude"]) if row["longitude"] is not None else None

        if lat is None or lon is None:
            centroid = get_district_centroid(row.get("district"))
            if centroid:
                lat, lon = centroid
            else:
                lat, lon = 23.0225, 72.5714  # Default fallback to State HQ centroid (Ahmedabad)

        candidates = recommend_candidate_teams(
            latitude=lat,
            longitude=lon,
            scenario=row["scenario"],
            limit=limit,
            conn=conn,
        )

        return TeamRecommendationResponse(
            incident_id=row["incident_id"],
            scenario=row["scenario"],
            requires_confirmation=True,
            recommendations=candidates,
            generated_at=datetime.now(UTC),
        )


# ── 2. Team Requests Listing ─────────────────────────────────────────────


@router.get("/team-requests", response_model=list[TeamRequestItem])
def list_team_requests(
    principal: DMUser,
    status: Annotated[
        Literal["OPEN", "APPROVED", "DECLINED", "ALL"],
        Query(description="Filter requests by operational status"),
    ] = "OPEN",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamRequestItem]:
    """List reinforcement and specialized backup requests submitted by field units."""
    if not get_settings().database_url:
        return []

    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT tr.request_id, tr.dispatch_id, d.dispatch_ref,
                   d.incident_id, i.incident_ref,
                   tr.requested_by, u.full_name AS requested_by_name,
                   team.name AS team_name,
                   tr.required_capability, tr.note, tr.status,
                   tr.decision_rationale,
                   du.full_name AS decided_by_name,
                   tr.decided_at, tr.created_at
            FROM team_requests tr
            JOIN dispatch_orders d ON d.dispatch_id = tr.dispatch_id
            JOIN incidents i ON i.incident_id = d.incident_id
            LEFT JOIN users u ON u.user_id = tr.requested_by
            LEFT JOIN users du ON du.user_id = tr.decided_by
            LEFT JOIN LATERAL (
                SELECT res.name FROM resource_assignments ra
                JOIN resources res ON res.resource_id = ra.resource_id
                WHERE ra.dispatch_id = d.dispatch_id
                ORDER BY ra.assigned_at ASC LIMIT 1
            ) team ON true
            WHERE (%(status)s = 'ALL' OR tr.status = %(status)s)
            ORDER BY (tr.status = 'OPEN') DESC, tr.created_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"status": status, "limit": limit, "offset": offset},
        ).fetchall()

    return [
        TeamRequestItem(
            request_id=r["request_id"],
            dispatch_id=r["dispatch_id"],
            dispatch_ref=r["dispatch_ref"],
            incident_id=r["incident_id"],
            incident_ref=r["incident_ref"],
            requested_by=r["requested_by"],
            requested_by_name=r["requested_by_name"],
            team_name=r["team_name"],
            required_capability=r["required_capability"],
            note=r["note"],
            status=r["status"],
            decision_rationale=r["decision_rationale"],
            decided_by_name=r["decided_by_name"],
            decided_at=r["decided_at"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ── 3. Team Request Decision ─────────────────────────────────────────────


@router.post(
    "/team-requests/{request_id}/decision",
    response_model=TeamRequestDecisionResponse,
)
def decide_team_request(
    request_id: uuid.UUID,
    body: TeamRequestDecisionRequest,
    principal: Dispatcher,
) -> TeamRequestDecisionResponse:
    """Authorize or decline a field responder's team backup request.

    Requires DISPATCH permission.
    Approving generates pre-filled dispatch draft parameters for rapid deployment.
    Declining requires an operational justification rationale.
    """
    with db.transaction() as conn:
        row = conn.execute(
            """
            SELECT tr.*, d.dispatch_ref, d.incident_id, i.incident_ref, i.scenario, i.priority,
                   ST_Y(i.geom::geometry) AS latitude, ST_X(i.geom::geometry) AS longitude
            FROM team_requests tr
            JOIN dispatch_orders d ON d.dispatch_id = tr.dispatch_id
            JOIN incidents i ON i.incident_id = d.incident_id
            WHERE tr.request_id = %(request_id)s
            FOR UPDATE OF tr
            """,
            {"request_id": request_id},
        ).fetchone()

        if row is None:
            raise not_found("Team Request")

        if row["status"] != "OPEN":
            raise ApiError(
                409,
                "TEAM_REQUEST_ALREADY_DECIDED",
                f"Team request is already {row['status']}",
            )

        now_utc = datetime.now(UTC)

        if body.action == "DECLINE":
            if not body.rationale or not body.rationale.strip():
                raise ApiError(
                    422,
                    "RATIONALE_REQUIRED",
                    "Mandatory explanation rationale is required when declining a backup request",
                )

            clean_rationale = body.rationale.strip()
            conn.execute(
                """
                UPDATE team_requests
                SET status = 'DECLINED', decision_rationale = %(rationale)s,
                    decided_by = %(actor)s, decided_at = now()
                WHERE request_id = %(request_id)s
                """,
                {
                    "rationale": clean_rationale,
                    "actor": principal.user_id,
                    "request_id": request_id,
                },
            )

            audit.record(
                conn,
                actor=principal,
                action="TEAM_REQUEST_DECLINED",
                entity_type="team_request",
                entity_id=request_id,
                rationale=clean_rationale,
                before={"status": "OPEN"},
                after={"status": "DECLINED", "rationale": clean_rationale},
                ip=principal.ip,
            )

            if row["requested_by"]:
                notify(
                    conn,
                    user_id=row["requested_by"],
                    event_code="TEAM_REQUEST_DECLINED",
                    title=f"Backup Request Declined for {row['dispatch_ref']}",
                    body=f"Declined: {clean_rationale}",
                    related_id=row["dispatch_id"],
                )

            return TeamRequestDecisionResponse(
                request_id=request_id,
                status="DECLINED",
                decision_rationale=clean_rationale,
                decided_at=now_utc,
                dispatch_draft=None,
            )

        # ── Approve Action ───────────────────────────────────────────────
        conn.execute(
            """
            UPDATE team_requests
            SET status = 'APPROVED', decision_rationale = %(rationale)s,
                decided_by = %(actor)s, decided_at = now()
            WHERE request_id = %(request_id)s
            """,
            {
                "rationale": body.rationale,
                "actor": principal.user_id,
                "request_id": request_id,
            },
        )

        audit.record(
            conn,
            actor=principal,
            action="TEAM_REQUEST_APPROVED",
            entity_type="team_request",
            entity_id=request_id,
            rationale=body.rationale or "Approved backup team deployment",
            before={"status": "OPEN"},
            after={"status": "APPROVED", "target_resource_id": body.target_resource_id},
            ip=principal.ip,
        )

        # Resolve target team resource for dispatch draft
        target_res: dict[str, Any] | None = None
        if body.target_resource_id:
            res_row = conn.execute(
                """
                SELECT resource_id, name, agency_id, status,
                       COALESCE(capability_tags, capability, '{}'::jsonb) AS capabilities
                FROM resources
                WHERE resource_id = %s
                """,
                (body.target_resource_id,),
            ).fetchone()
            if res_row is None:
                raise not_found("Resource")

            res_dict = dict(res_row)
            team_caps = {c.lower() for c in extract_capability_tags(res_dict.get("capabilities"))}
            req_cap = str(row["required_capability"]).strip().lower()
            if req_cap not in team_caps:
                raise ApiError(
                    422,
                    "CAPABILITY_MISMATCH",
                    f"Selected team '{res_dict['name']}' does not possess requested capability '{row['required_capability']}'",
                )
            target_res = res_dict
        else:
            lat = row["latitude"]
            lon = row["longitude"]
            if (lat is None or lon is None) and row.get("district"):
                centroid = get_district_centroid(row["district"])
                if centroid:
                    lat, lon = centroid

            if lat is not None and lon is not None:
                # Query candidate teams matching the specifically requested capability
                candidates = recommend_candidate_teams(
                    latitude=float(lat),
                    longitude=float(lon),
                    scenario=row["scenario"],
                    limit=5,
                    conn=conn,
                    required_capabilities=[row["required_capability"]],
                )
                if candidates:
                    top = candidates[0]
                    target_res = {
                        "resource_id": top.resource_id,
                        "name": top.team_name,
                        "agency_id": top.agency_id,
                    }

        instructions_text = (
            f"Reinforce {row['dispatch_ref']}: Deploy {row['required_capability']} unit as requested by frontline responders. {body.rationale or ''}".strip()
        )
        if target_res is None:
            instructions_text += f" [Note: No available team matched capability '{row['required_capability']}'; manual allocation required.]"

        dispatch_draft: dict[str, Any] = {
            "incident_id": str(row["incident_id"]),
            "incident_ref": row["incident_ref"],
            "required_capability": row["required_capability"],
            "suggested_resource_id": str(target_res["resource_id"]) if target_res else None,
            "suggested_resource_name": target_res["name"] if target_res else None,
            "receiving_agency_id": str(target_res["agency_id"]) if target_res else None,
            "priority": row.get("priority") or "HIGH",
            "instructions": instructions_text,
        }

        if row["requested_by"]:
            notify(
                conn,
                user_id=row["requested_by"],
                event_code="TEAM_REQUEST_APPROVED",
                title=f"Backup Request Approved for {row['dispatch_ref']}",
                body=f"Reinforcement team approved for capability '{row['required_capability']}'.",
                related_id=row["dispatch_id"],
            )

        return TeamRequestDecisionResponse(
            request_id=request_id,
            status="APPROVED",
            decision_rationale=body.rationale,
            decided_at=now_utc,
            dispatch_draft=dispatch_draft,
        )
