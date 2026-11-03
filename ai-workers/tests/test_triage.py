import pytest
from fastapi.testclient import TestClient

from rules import SUPPORTED, triage
from triage_service import app

client = TestClient(app)


def test_contract_example_is_critical():
    out = triage({"reported_scenario": "urban_flooding", "reported_urgency": "HIGH", "people_affected": 20,
                  "description": "Heavy water accumulation, people stranded on rooftops near river bank flood."})
    assert out["scenario"] == "URBAN_FLOODING" and out["priority"] == "CRITICAL"
    assert 0.6 <= out["confidence"] <= 0.95 and out["model"] == "drch-triage-v1-rules"
    assert {"name", "detail", "weight"} <= set(out["factors"][0])


@pytest.mark.parametrize("scenario", SUPPORTED)
def test_supported_scenarios_pass_through(scenario):
    assert triage({"reported_scenario": scenario, "description": "something happening"})["scenario"] == scenario


def test_unsupported_report_is_flagged_not_forced():
    out = triage({"reported_scenario": "earthquake", "description": "the ground shook and a wall cracked"})
    assert out["scenario"] == "OTHER" and out["confidence"] <= 0.4 and out["uncertainty"]


def test_low_information_is_low_priority():
    assert triage({"reported_scenario": "cyclone", "description": "tree down"})["priority"] == "LOW"


def test_mismatch_lowers_confidence():
    plain = triage({"reported_scenario": "cyclone", "description": "storm wind surge coastal"})
    conflict = triage({"reported_scenario": "cyclone", "description": "factory fire explosion chemical smoke tank"})
    assert conflict["confidence"] < plain["confidence"] and conflict["uncertainty"]


def test_http_contract_and_auth(monkeypatch):
    assert client.get("/health").json() == {"status": "ok", "service": "drch-ai-triage"}
    body = {"reported_scenario": "industrial_fire", "description": "factory fire, workers trapped", "people_affected": 12}
    assert client.post("/triage", json=body).status_code == 200
    monkeypatch.setenv("AI_TRIAGE_TOKEN", "s3cret-token")
    assert client.post("/triage", json=body).status_code == 401
    assert client.post("/triage", json=body, headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
