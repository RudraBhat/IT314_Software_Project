"""AI triage integration boundary (DM-FR-05, DM-NFR-09/10).

The project's AI worker (ai-workers/worker.py) is a placeholder, so there is no
live model. Requests go to an external triage service only when AI_TRIAGE_URL
is configured; otherwise the result is UNAVAILABLE. Output is never trusted:
it is validated and bounded here before anything is stored, and it can never
change an incident by itself.
"""

import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings

SUPPORTED = {"CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING"}
PRIORITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
TIMEOUT_SECONDS = 10

_PII_PATTERNS = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email removed]"),
    (re.compile(r"(?<!\w)\+?\d(?:[ -]?\d){8,}(?!\w)"), "[phone removed]"),  # 9+ digits, single space/hyphen
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[id number removed]"),  # Aadhaar-style 12 digits
)


def scrub_pii(value: Any) -> Any:
    """Remove emails, phone numbers and 12-digit ids from text before it leaves the system."""
    if isinstance(value, str):
        for pattern, replacement in _PII_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {k: scrub_pii(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_pii(v) for v in value]
    return value


@dataclass
class TriageOutcome:
    status: str  # ai_rec_status: GENERATED | LOW_CONFIDENCE | UNAVAILABLE | UNSAFE_OUTPUT
    model_name: str
    suggested_scenario: str | None = None
    suggested_priority: str | None = None
    confidence: float | None = None
    uncertainty_note: str | None = None
    factors: dict[str, Any] = field(default_factory=dict)

class _Factor(BaseModel):
    name: str = Field(max_length=120)
    detail: str | None = Field(None, max_length=500)
    weight: float | None = Field(None, ge=-1, le=1)

class _ProviderOutput(BaseModel):
    """The contract an external triage service must satisfy."""

    model: str = Field(min_length=1, max_length=100)
    scenario: str = Field(min_length=1, max_length=60)
    priority: str
    confidence: float = Field(ge=0, le=1)
    uncertainty: str | None = Field(None, max_length=1000)
    factors: list[_Factor] = Field(default_factory=list, max_length=20)

class TriageProvider:
    name = "none"

    def triage(self, payload: dict[str, Any]) -> TriageOutcome:
        raise NotImplementedError

class UnavailableProvider(TriageProvider):
    name = "not-configured"

    def triage(self, payload: dict[str, Any]) -> TriageOutcome:
        return TriageOutcome(
            status="UNAVAILABLE",
            model_name=self.name,
            uncertainty_note="No AI triage service is configured. Continue with manual triage.",
        )

class HttpTriageProvider(TriageProvider):
    name = "http"

    def __init__(self, url: str):
        self.url = url

    def triage(self, payload: dict[str, Any]) -> TriageOutcome:
        try:
            token = get_settings().ai_triage_token
            response = httpx.post(
                self.url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"} if token else None,
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError):
            return TriageOutcome(
                status="UNAVAILABLE",
                model_name=self.name,
                uncertainty_note="The AI triage service did not respond. Continue with manual triage.",
            )
        return apply_guardrails(raw)

def apply_guardrails(raw: Any) -> TriageOutcome:
    """Validate untrusted model output; anything malformed becomes UNSAFE_OUTPUT with no suggestion."""
    try:
        out = _ProviderOutput.model_validate(raw)
    except ValidationError:
        return TriageOutcome(
            status="UNSAFE_OUTPUT",
            model_name="unknown",
            uncertainty_note="The AI output failed validation and was discarded.",
        )
    priority = out.priority.upper()
    if priority not in PRIORITIES:
        return TriageOutcome(
            status="UNSAFE_OUTPUT",
            model_name=out.model,
            uncertainty_note="The AI suggested an unknown priority; output discarded.",
        )

    scenario = out.scenario.strip().upper().replace(" ", "_")
    factors: dict[str, Any] = {"items": [f.model_dump() for f in out.factors]}
    note = out.uncertainty
    suggested_scenario: str | None = scenario
    if scenario not in SUPPORTED:
        # DM-FR-05 / EH-25: flag Out of Scope; staff triage manually.
        suggested_scenario = None
        factors["out_of_scope"] = True
        factors["raw_scenario"] = out.scenario[:60]
        note = (note + " " if note else "") + "Suggested type is outside supported scenarios."

    low = out.confidence < get_settings().ai_low_confidence_threshold or suggested_scenario is None
    return TriageOutcome(
        status="LOW_CONFIDENCE" if low else "GENERATED",
        model_name=out.model,
        suggested_scenario=suggested_scenario,
        suggested_priority=priority,
        confidence=round(out.confidence, 3),
        uncertainty_note=note,
        factors=factors,
    )

def get_provider() -> TriageProvider:
    url = get_settings().ai_triage_url
    return HttpTriageProvider(url) if url else UnavailableProvider()
