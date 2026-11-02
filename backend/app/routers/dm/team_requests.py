"""DM team request decisions (docs/api_contracts.md / audit plan R-04). Owner: Tanishq / Nisarg.

When field teams request backup, the request is stored in team_requests (status=OPEN).
DM dispatchers can view pending team-requests and approve or decline them.
Approving does not dispatch anything automatically - the dispatcher still creates a dispatch order.
"""

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import audit, db
from app.auth import Dispatcher, DMUser
from app.common import notify
from app.errors import conflict, not_found

router = APIRouter()


class TeamRequestDecision(BaseModel):
    decision: Literal["APPROVED", "DECLINED"]
    rationale: str = Field(min_length=3, max_length=2000)


@router.get("/team-requests")
def list_team_requests(
    principal: DMUser,
    status: Literal["OPEN", "APPROVED", "DECLINED"] | None = "OPEN",
    dispatch_id: uuid.UUID | None = None,
):
    with db.transaction() as conn:
        return conn.execute(
            """
            SELECT tr.request_id, tr.dispatch_id, d.dispatch_ref, tr.required_capability,
                   tr.note, tr.status, u.full_name AS requested_by_name, tr.created_at,
                   tr.decision_rationale, tr.decided_at, du.full_name AS decided_by_name
            FROM team_requests tr
            JOIN dispatch_orders d ON d.dispatch_id = tr.dispatch_id
            LEFT JOIN users u ON u.user_id = tr.requested_by
            LEFT JOIN users du ON du.user_id = tr.decided_by
            WHERE (%(status)s::text IS NULL OR tr.status = %(status)s)
              AND (%(dispatch_id)s::uuid IS NULL OR tr.dispatch_id = %(dispatch_id)s)
            ORDER BY tr.created_at DESC
            """,
            {"status": status, "dispatch_id": dispatch_id},
        ).fetchall()


@router.post("/team-requests/{request_id}/decision")
def decide_team_request(
    request_id: uuid.UUID,
    body: TeamRequestDecision,
    principal: Dispatcher,
):
    with db.transaction() as conn:
        tr = conn.execute(
            """
            SELECT tr.request_id, tr.dispatch_id, tr.requested_by, tr.required_capability,
                   tr.status, d.dispatch_ref
            FROM team_requests tr
            JOIN dispatch_orders d ON d.dispatch_id = tr.dispatch_id
            WHERE tr.request_id = %s
            FOR UPDATE OF tr
            """,
            (request_id,),
        ).fetchone()
        if tr is None:
            raise not_found("Team request")
        if tr["status"] != "OPEN":
            raise conflict("ALREADY_DECIDED", f"Team request has already been {tr['status'].lower()}")

        conn.execute(
            """
            UPDATE team_requests
            SET status = %s,
                decision_rationale = %s,
                decided_by = %s,
                decided_at = now()
            WHERE request_id = %s
            """,
            (body.decision, body.rationale, principal.user_id, request_id),
        )

        action = f"TEAM_REQUEST_{body.decision}"
        audit.record(
            conn,
            actor=principal,
            action=action,
            entity_type="team_request",
            entity_id=request_id,
            rationale=body.rationale,
            ip=principal.ip,
        )

        if tr["requested_by"]:
            notify(
                conn,
                user_id=tr["requested_by"],
                event_code=action,
                title=f"Backup request {body.decision.lower()} on {tr['dispatch_ref']}",
                body=f"Your request for {tr['required_capability']} was {body.decision.lower()}: {body.rationale}",
                related_id=tr["dispatch_id"],
            )

        return {
            "request_id": request_id,
            "dispatch_id": tr["dispatch_id"],
            "status": body.decision,
            "decision_rationale": body.rationale,
        }
