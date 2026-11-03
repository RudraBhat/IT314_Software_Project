"""Data contracts and schemas for Team Recommendation and Dispatch Decisions.

Provides request and response validation models for geospatial team ranking,
capability matching, and dispatcher triage of field backup requests.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CandidateTeam(BaseModel):
    """Ranked team candidate evaluated by the recommendation engine."""

    resource_id: uuid.UUID
    team_name: str
    agency_id: uuid.UUID | None = None
    agency: str
    distance_km: float = Field(..., ge=0.0, description="Straight-line or road distance from incident in km")
    capability_match: list[str] = Field(default_factory=list, description="Matched capability tags")
    rank: int = Field(..., ge=1, description="Recommendation priority rank")
    reasons: str = Field(..., description="Human-readable justification for the rank")
    status: str = Field(..., description="Current operational status of resource")
    capabilities: dict[str, Any] | list[Any] | None = None


class TeamRecommendationResponse(BaseModel):
    """Advisory team recommendations for an active verified incident."""

    incident_id: uuid.UUID
    scenario: str
    requires_confirmation: bool = Field(
        default=True,
        description="Strict safety flag indicating dispatcher confirmation is required",
    )
    recommendations: list[CandidateTeam] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TeamRequestItem(BaseModel):
    """Field-initiated request for additional team reinforcement."""

    request_id: uuid.UUID
    dispatch_id: uuid.UUID
    dispatch_ref: str
    incident_id: uuid.UUID
    incident_ref: str
    requested_by: uuid.UUID | None = None
    requested_by_name: str | None = None
    team_name: str | None = None
    required_capability: str
    note: str | None = None
    status: str
    decision_rationale: str | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    created_at: datetime


class TeamRequestDecisionRequest(BaseModel):
    """Decision by dispatcher to approve or decline a backup team request."""

    action: Literal["APPROVE", "DECLINE"]
    rationale: str | None = Field(
        None, max_length=1000, description="Mandatory explanation when declining request"
    )
    target_resource_id: uuid.UUID | None = Field(
        None, description="Optional team resource UUID to pre-fill on approval"
    )


class TeamRequestDecisionResponse(BaseModel):
    """Result of dispatcher decision on backup team request."""

    request_id: uuid.UUID
    status: str
    decision_rationale: str | None = None
    decided_at: datetime
    dispatch_draft: dict[str, Any] | None = None

