"""AI-assisted triage (DM-FR-05): advisory recommendations and the separate human decision."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, model_validator

from app import audit, db
from app.auth import DMUser
from app.common import Priority, Rationale, Scenario, scenario_db
from app.errors import ApiError, conflict, not_found
from app.services.ai_provider import TriageProvider, get_provider, scrub_pii
from app.services.incidents import (
    check_version,
    ensure_open,
    lock_incident,
    update_incident,
)

router = APIRouter()

_REC_SELECT = """
SELECT r.recommendation_id, r.incident_id, r.model_name, r.status,
    lower(r.suggested_scenario::text) AS suggested_scenario, r.suggested_priority,
    r.confidence, r.uncertainty_note, r.factors, r.human_action, r.human_rationale,
    r.decided_at, u.full_name AS decided_by_name, r.created_at,
       COALESCE((r.factors->>'out_of_scope')::boolean, false) AS out_of_scope
FROM ai_recommendations r LEFT JOIN users u ON u.user_id = r.human_decided_by
"""


@router.post("/incidents/{incident_id}/ai-triage")
def request_ai_triage(
    incident_id: uuid.UUID,
    principal: DMUser,
    provider: Annotated[TriageProvider, Depends(get_provider)],
):
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM incidents WHERE incident_id = %s", (incident_id,)
        ).fetchone()
        if row is None:
            raise not_found("Incident")
        ensure_open(row)
    # Only permitted, non-identifying inputs leave the system.
    payload = {
        "incident_ref": row["incident_ref"],
        "reported_scenario": row["scenario"].lower(),
        "description": scrub_pii(row["description"]),
        "reported_urgency": row["reported_urgency"],
        "people_affected": row["people_affected"],
        "details": scrub_pii(row["details"]),
        "has_coordinates": row["latitude"] is not None,
    }
    outcome = provider.triage(payload)  # outside the transaction: may take seconds
    with db.transaction() as conn:
        rec = conn.execute(
            """
            INSERT INTO ai_recommendations
                (incident_id, model_name, status, suggested_scenario, suggested_priority,
                 confidence, uncertainty_note, factors)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING recommendation_id
            """,
            (
                incident_id,
                outcome.model_name,
                outcome.status,
                outcome.suggested_scenario,
                outcome.suggested_priority,
                outcome.confidence,
                outcome.uncertainty_note,
                Jsonb(outcome.factors),
            ),
        ).fetchone()
        audit.record(
            conn,
            actor=principal,
            action="AI_TRIAGE_REQUESTED",
            entity_type="incident",
            entity_id=incident_id,
            result="SUCCESS"
            if outcome.status in ("GENERATED", "LOW_CONFIDENCE")
            else "FAILURE",
            rationale=f"AI status {outcome.status}",
            after={"recommendation_id": str(rec["recommendation_id"])},
            ip=principal.ip,
        )
        stored = conn.execute(
            sql.SQL("{} WHERE r.recommendation_id = %s").format(sql.SQL(_REC_SELECT)),
            (rec["recommendation_id"],),
        ).fetchone()
    if outcome.status == "UNAVAILABLE":
        # 503: the dependency is unavailable (s.15.7). The attempt is still recorded.
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "AI_UNAVAILABLE",
                    "message": outcome.uncertainty_note,
                    "details": {"recommendation_id": str(rec["recommendation_id"])},
                }
            },
        )
    return stored


@router.get("/incidents/{incident_id}/ai-recommendations")
def list_recommendations(incident_id: uuid.UUID, principal: DMUser):
    with db.transaction() as conn:
        if (
            conn.execute(
                "SELECT 1 FROM incidents WHERE incident_id = %s", (incident_id,)
            ).fetchone()
            is None
        ):
            raise not_found("Incident")
        items = conn.execute(
            sql.SQL("{} WHERE r.incident_id = %s ORDER BY r.created_at DESC").format(
                sql.SQL(_REC_SELECT)
            ),
            (incident_id,),
        ).fetchall()
    return {
        "items": items,
        "advisory_notice": "AI output is advisory. Staff make every decision.",
    }


class AiDecision(BaseModel):
    action: Literal["ACCEPTED", "MODIFIED", "REJECTED"]
    rationale: str = Rationale
    final_scenario: Scenario | None = None
    final_priority: Priority | None = None
    apply_to_incident: bool = False
    version: int | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.action == "MODIFIED" and not (
            self.final_scenario or self.final_priority
        ):
            raise ValueError("A modification needs final_scenario or final_priority")
        if self.apply_to_incident and self.action == "REJECTED":
            raise ValueError("A rejected recommendation cannot be applied")
        if self.apply_to_incident and self.version is None:
            raise ValueError(
                "version is required when applying a decision to the incident"
            )
        return self


@router.post("/incidents/{incident_id}/ai-recommendations/{rec_id}/decision")
def decide_recommendation(
    incident_id: uuid.UUID,
    rec_id: uuid.UUID,
    body: AiDecision,
    principal: DMUser,
):
    with db.transaction() as conn:
        rec = conn.execute(
            "SELECT * FROM ai_recommendations WHERE recommendation_id = %s AND incident_id = %s FOR UPDATE",
            (rec_id, incident_id),
        ).fetchone()
        if rec is None:
            raise not_found("Recommendation")
        if rec["human_action"] is not None:
            raise conflict(
                "ALREADY_DECIDED",
                "A decision has already been recorded for this recommendation",
            )
        if rec["status"] in ("UNAVAILABLE", "UNSAFE_OUTPUT"):
            raise conflict(
                "NO_RECOMMENDATION", "There is no usable suggestion to decide on"
            )

        if body.action == "ACCEPTED":
            final_scenario, final_priority = (
                rec["suggested_scenario"],
                rec["suggested_priority"],
            )
            if final_scenario is None and body.apply_to_incident:
                raise conflict(
                    "OUT_OF_SCOPE",
                    "An out-of-scope suggestion cannot be applied; triage manually",
                )
        elif body.action == "MODIFIED":
            final_scenario = (
                scenario_db(body.final_scenario) or rec["suggested_scenario"]
            )
            final_priority = body.final_priority or rec["suggested_priority"]
        else:
            final_scenario = final_priority = None

        conn.execute(
            """
            UPDATE ai_recommendations
            SET human_action = %s, human_decided_by = %s, human_rationale = %s, decided_at = %s
            WHERE recommendation_id = %s
            """,
            (body.action, principal.user_id, body.rationale, datetime.now(UTC), rec_id),
        )
        audit.record(
            conn,
            actor=principal,
            action=f"AI_RECOMMENDATION_{body.action}",
            entity_type="incident",
            entity_id=incident_id,
            rationale=body.rationale,
            after={
                "recommendation_id": str(rec_id),
                "final_scenario": final_scenario,
                "final_priority": final_priority,
                "applied": body.apply_to_incident,
            },
            ip=principal.ip,
        )

        result = {
            "recommendation_id": rec_id,
            "human_action": body.action,
            "applied": False,
        }
        if body.apply_to_incident:
            incident = lock_incident(conn, incident_id)
            check_version(incident, body.version)
            ensure_open(incident)
            fields = {}
            if final_scenario and final_scenario != incident["scenario"]:
                fields["scenario"] = final_scenario
            if final_priority and incident["status"] != "REJECTED":
                fields["verified_priority"] = final_priority
                fields["priority_rationale"] = body.rationale
            if not fields:
                raise ApiError(
                    409,
                    "NOTHING_TO_APPLY",
                    "The incident already matches this decision",
                )
            updated = update_incident(
                conn,
                principal,
                incident,
                action="AI_DECISION_APPLIED",
                rationale=body.rationale,
                **fields,
            )
            result.update(applied=True, version=updated["version"])
    return result
