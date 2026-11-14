"""/triage with the optional LLM adapter (S2-08 wiring, owner Zalak). Uses a stub LLM, never a network call.

The rules result is always returned unchanged; the LLM may only add advisory fields, and only when
LLM_ENABLED is on (or a stub completer is passed).
"""

import json

import pytest
from fastapi.testclient import TestClient

from rules import triage
from service import llm
from triage_service import app, with_llm_opinion

client = TestClient(app)

LOW_REPORT = {"reported_scenario": "cyclone", "description": "tree down"}


@pytest.fixture(autouse=True)
def _llm_off(monkeypatch):
    for name in ("LLM_ENABLED", "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "AI_TRIAGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def _stub(answer: dict):
    calls = []

    def complete(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(answer)

    complete.calls = calls
    return complete


def test_llm_is_off_by_default_and_the_response_is_the_rules_result():
    body = client.post("/triage", json=LOW_REPORT).json()
    assert body == triage(LOW_REPORT | {"incident_ref": None, "reported_urgency": None, "people_affected": None,
                                        "has_coordinates": None, "details": {}})
    assert "llm_second_opinion" not in body and "english_summary" not in body


def test_low_confidence_result_gets_an_advisory_second_opinion():
    rules_result = triage(LOW_REPORT)
    assert rules_result["confidence"] < llm.LOW_CONFIDENCE
    out = with_llm_opinion(rules_result, LOW_REPORT["description"],
                           completer=_stub({"scenario": "CYCLONE", "priority": "MEDIUM"}))
    assert out["llm_second_opinion"] == {"scenario": "CYCLONE", "priority": "MEDIUM", "source": "llm"}
    for key, value in rules_result.items():
        assert out[key] == value, f"the LLM must not change the rules field {key}"


def test_confident_result_does_not_call_the_llm():
    rules_result = {**triage(LOW_REPORT), "confidence": 0.9}
    stub = _stub({"scenario": "CYCLONE", "priority": "LOW"})
    out = with_llm_opinion(rules_result, "tree down", completer=stub)
    assert out == rules_result and stub.calls == []


def test_an_answer_outside_the_allowed_labels_is_dropped():
    rules_result = triage(LOW_REPORT)
    out = with_llm_opinion(rules_result, "tree down", completer=_stub({"scenario": "VERIFY_INCIDENT", "priority": "NOW"}))
    assert "llm_second_opinion" not in out and out == rules_result


def test_gujarati_text_gets_an_english_summary_without_contact_details_in_the_prompt():
    text = "વાસણા બેરેજ પાસે ઘરમાં પાણી ભરાયું, મદદ માટે 9876543210 પર ફોન કરો"
    stub = _stub({"summary": "Water entered homes near Vasna barrage.", "scenario": "URBAN_FLOODING",
                  "priority": "HIGH"})
    out = with_llm_opinion(triage({"description": text}), text, completer=stub)
    assert out["english_summary"] == "Water entered homes near Vasna barrage."
    assert stub.calls and all("9876543210" not in prompt for prompt in stub.calls)


def test_enabled_without_a_provider_falls_back_to_the_rules_result(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "true")  # no LLM_PROVIDER / LLM_API_KEY: the adapter stays unused
    body = client.post("/triage", json=LOW_REPORT).json()
    assert "llm_second_opinion" not in body and body["model"] == triage(LOW_REPORT)["model"]
