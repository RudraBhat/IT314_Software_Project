"""DRCH AI triage service. Run: uvicorn triage_service:app --host 0.0.0.0 --port 8001

POST /triage  - advisory scenario/priority suggestion (contract: docs/api_contracts.md s.7.1)
GET  /health  - liveness (s.7.2)
Set AI_TRIAGE_TOKEN to require "Authorization: Bearer <token>" on /triage.
"""

import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from rules import triage

app = FastAPI(title="DRCH AI Triage", version="1.0.0")


class TriageRequest(BaseModel):
    incident_ref: str | None = Field(default=None, max_length=60)
    reported_scenario: str | None = Field(default=None, max_length=60)
    description: str = Field(default="", max_length=4000)
    reported_urgency: str | None = Field(default=None, max_length=20)
    people_affected: int | None = Field(default=None, ge=0, le=1_000_000)
    has_coordinates: bool | None = None
    details: dict = Field(default_factory=dict)


@app.get("/health")
def health():
    return {"status": "ok", "service": "drch-ai-triage"}


@app.post("/triage")
def triage_endpoint(body: TriageRequest, authorization: str | None = Header(default=None)):
    expected = os.getenv("AI_TRIAGE_TOKEN")
    if expected:
        supplied = (authorization or "")[7:] if (authorization or "").lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid or missing token")
    return triage(body.model_dump())
