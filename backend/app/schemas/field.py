"""Data contracts and schemas for Field Operations API.

Provides request validation and response serialization models for field responders,
unit assignments, progress tracking, backup requests, and operational completions.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FieldProfileResponse(BaseModel):
    """Responder identity, team binding, and capability profile."""

    user_id: uuid.UUID
    email: str
    full_name: str
    phone: str | None = None
    role: str
    callsign: str | None = None
    is_leader: bool = False
    member_id: uuid.UUID
    team_resource_id: uuid.UUID
    team_name: str
    agency_id: uuid.UUID | None = None
    agency_name: str | None = None
    capabilities: dict[str, Any] | list[Any] = Field(default_factory=dict)
    status: str


class FieldAssignmentResponse(BaseModel):
    """Mission dispatch assigned to the field responder's team."""

    dispatch_id: uuid.UUID
    dispatch_ref: str
    status: str
    priority: str
    incident_id: uuid.UUID
    incident_ref: str
    scenario: str
    district: str | None = None
    address_text: str | None = None
    landmark: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    instructions: str
    dispatched_at: datetime
    acknowledged_at: datetime | None = None
    overdue: bool = False


class FieldProgressRequest(BaseModel):
    """Field progress status update."""

    status: Literal["EN_ROUTE", "ON_SCENE", "UPDATE", "DELAYED"]
    note: str | None = Field(None, max_length=1000, description="Field operational note")
    latitude: float | None = Field(None, ge=-90.0, le=90.0, description="Responder GPS latitude")
    longitude: float | None = Field(None, ge=-180.0, le=180.0, description="Responder GPS longitude")


class FieldProgressResponse(BaseModel):
    """Recorded progress tracking confirmation."""

    progress_id: uuid.UUID
    dispatch_id: uuid.UUID
    status: str
    note: str | None = None
    recorded_at: datetime


class FieldTeamRequest(BaseModel):
    """Request for additional backup capabilities or specialized units."""

    required_capability: str = Field(
        ..., min_length=2, max_length=100, description="Required capability tag (e.g. boat, hazmat)"
    )
    note: str | None = Field(None, max_length=1000, description="Justification and situational details")


class FieldTeamRequestResponse(BaseModel):
    """Confirmation of recorded additional team backup request."""

    request_id: uuid.UUID
    dispatch_id: uuid.UUID
    required_capability: str
    note: str | None = None
    status: str
    created_at: datetime


class FieldCompletionRequest(BaseModel):
    """Field mission completion summary and operational output metrics."""

    summary: str = Field(
        ..., min_length=5, max_length=2000, description="Operational resolution summary"
    )
    civilians_evacuated: int | None = Field(None, ge=0, description="Count of rescued/evacuated persons")
    civilians_treated: int | None = Field(None, ge=0, description="Count of treated casualties")
    notes: str | None = Field(None, max_length=1000, description="Optional handoff remarks")


class FieldAcknowledgementResponse(BaseModel):
    """Response confirming dispatch receipt and acknowledgement."""

    status: str
    dispatch_ref: str
    acknowledged_at: datetime


class FieldRejectionRequest(BaseModel):
    """Explicit refusal of assignment with operational reason."""

    reason: str = Field(..., min_length=3, max_length=1000, description="Operational justification for rejection")

