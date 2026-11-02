"""Team recommendations for a verified incident (docs/api_contracts.md section 5). Owner: Nisarg.

Advisory only: this endpoint never reserves or dispatches anything. A dispatcher must
still create the dispatch order, which is where the human confirmation happens.
"""

import uuid

from fastapi import APIRouter

from app import db
from app.auth import DMUser
from app.errors import not_found
from app.services.recommendations import get_recommended_teams

router = APIRouter()


@router.get("/incidents/{incident_id}/team-recommendations")
def team_recommendations(incident_id: uuid.UUID, principal: DMUser):
    with db.transaction() as conn:
        incident = conn.execute(
            "SELECT lower(scenario::text) AS scenario, latitude, longitude FROM incidents WHERE incident_id = %s",
            (incident_id,),
        ).fetchone()
        if incident is None:
            raise not_found("Incident")
        teams = []
        if incident["latitude"] is not None and incident["longitude"] is not None:
            teams = get_recommended_teams(
                float(incident["latitude"]), float(incident["longitude"]), incident["scenario"], limit=5, conn=conn
            )
    return {
        "incident_id": incident_id,
        "scenario": incident["scenario"],
        "requires_confirmation": True,
        "recommendations": [
            {
                "resource_id": t.resource_id,
                "team_name": t.name,
                "agency": t.agency_name,
                "distance_km": t.distance_km,
                "capability_match": t.matched_capabilities,
                "rank": t.rank,
                "reasons": "; ".join(t.reasons),
            }
            for t in teams
        ],
    }
