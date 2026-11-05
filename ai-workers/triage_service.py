"""DRCH AI triage service. Run: uvicorn triage_service:app --host 0.0.0.0 --port 8001

POST /triage  - advisory scenario/priority suggestion (contract: docs/api_contracts.md s.7.1)
GET  /health  - liveness (s.7.2)
Set AI_TRIAGE_TOKEN to require "Authorization: Bearer <token>" on /triage.
"""

import hmac
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

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


class TextAnalysisRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    source: str | None = Field(default=None, max_length=80)
    source_created_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_source_metadata(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if self.source_created_at is not None and self.source_created_at.tzinfo is None:
            raise ValueError("source_created_at must include a timezone")
        return self


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


@app.post("/analyze-text")
def analyze_text_endpoint(
    body: TextAnalysisRequest,
    authorization: str | None = Header(default=None),
):
    """Run the trained English text model without changing the existing triage contract."""
    expected = os.getenv("AI_TRIAGE_TOKEN")
    if expected:
        supplied = (authorization or "")[7:] if (authorization or "").lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid or missing token")

    from text_model.inference import ModelCompatibilityError, predict_text

    model_dir = os.getenv("TEXT_MODEL_DIR", str(Path(__file__).resolve().parent / "text_model" / "artifacts"))
    try:
        analysis = predict_text(body.description, model_dir=model_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="text model artifact is not configured") from exc
    except ModelCompatibilityError as exc:
        raise HTTPException(status_code=503, detail="text model artifact is incompatible with this runtime") from exc

    metadata_provided = any(
        value is not None
        for value in (body.source, body.source_created_at, body.latitude, body.longitude)
    )
    analysis["source_metadata"] = {
        "source": body.source,
        "created_at": body.source_created_at.isoformat() if body.source_created_at else None,
        "coordinates": (
            {"latitude": body.latitude, "longitude": body.longitude}
            if body.latitude is not None
            else None
        ),
        "provenance": "PROVIDED_BY_CALLER" if metadata_provided else "NOT_PROVIDED",
    }
    return analysis
