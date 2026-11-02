"""AI advisory triage: unavailable service, guardrails and the separate human decision."""

import pytest

from app.services.ai_provider import TriageProvider, apply_guardrails, get_provider

pytestmark = pytest.mark.db

BASE = "/api/v1/dm"


class FakeProvider(TriageProvider):
    name = "fake"

    def __init__(self, raw):
        self.raw = raw

    def triage(self, payload):
        assert "reporter" not in payload and "email" not in str(payload)  # no personal data leaves
        return apply_guardrails(self.raw)


@pytest.fixture
def use_provider(client):
    from main import app

    def _use(raw):
        app.dependency_overrides[get_provider] = lambda: FakeProvider(raw)

    yield _use
    app.dependency_overrides.pop(get_provider, None)


def test_unavailable_ai_returns_503_and_records_the_attempt(client, make, sql):
    staff = make.staff()
    inc = make.incident()
    r = client.post(f"{BASE}/incidents/{inc['incident_id']}/ai-triage", headers=staff["headers"])
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "AI_UNAVAILABLE"
    rec = sql.execute("SELECT * FROM ai_recommendations WHERE incident_id = %s", (inc["incident_id"],)).fetchone()
    assert rec["status"] == "UNAVAILABLE"
    assert rec["suggested_scenario"] is None and rec["suggested_priority"] is None


def test_generated_recommendation_never_changes_the_incident(client, make, sql, use_provider):
    use_provider({"model": "triage-x", "scenario": "urban_flooding", "priority": "CRITICAL", "confidence": 0.91,
                  "uncertainty": "Water depth not stated", "factors": [{"name": "stranded people"}]})
    staff = make.staff()
    inc = make.incident()
    r = client.post(f"{BASE}/incidents/{inc['incident_id']}/ai-triage", headers=staff["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "GENERATED"
    assert r.json()["suggested_priority"] == "CRITICAL"
    row = sql.execute("SELECT status, verified_priority, version FROM incidents WHERE incident_id = %s",
                      (inc["incident_id"],)).fetchone()
    assert row == {"status": "SUBMITTED", "verified_priority": None, "version": 1}


def test_out_of_scope_and_malformed_outputs(client, make, use_provider):
    staff = make.staff()
    inc = make.incident()
    use_provider({"model": "m", "scenario": "earthquake", "priority": "HIGH", "confidence": 0.99})
    r = client.post(f"{BASE}/incidents/{inc['incident_id']}/ai-triage", headers=staff["headers"]).json()
    assert r["out_of_scope"] is True and r["suggested_scenario"] is None
    use_provider({"model": "m", "scenario": "cyclone", "priority": "<script>", "confidence": 0.9})
    r = client.post(f"{BASE}/incidents/{inc['incident_id']}/ai-triage", headers=staff["headers"]).json()
    assert r["status"] == "UNSAFE_OUTPUT" and r["suggested_priority"] is None


def test_human_decision_is_recorded_separately_and_only_once(client, make, sql, use_provider):
    use_provider({"model": "m", "scenario": "urban_flooding", "priority": "HIGH", "confidence": 0.8})
    staff = make.staff()
    inc = make.incident()
    rec = client.post(f"{BASE}/incidents/{inc['incident_id']}/ai-triage", headers=staff["headers"]).json()
    url = f"{BASE}/incidents/{inc['incident_id']}/ai-recommendations/{rec['recommendation_id']}/decision"

    r = client.post(url, headers=staff["headers"], json={
        "action": "MODIFIED", "final_priority": "CRITICAL", "rationale": "Children among the stranded",
        "apply_to_incident": True, "version": 1,
    })
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True
    stored = sql.execute("SELECT human_action, human_decided_by, suggested_priority FROM ai_recommendations "
                         "WHERE recommendation_id = %s", (rec["recommendation_id"],)).fetchone()
    # The AI's suggestion is preserved; the human decision sits beside it.
    assert stored == {"human_action": "MODIFIED", "human_decided_by": staff["user_id"], "suggested_priority": "HIGH"}
    incident = sql.execute("SELECT status, verified_priority FROM incidents WHERE incident_id = %s",
                           (inc["incident_id"],)).fetchone()
    assert incident == {"status": "SUBMITTED", "verified_priority": "CRITICAL"}  # still needs human verification

    again = client.post(url, headers=staff["headers"], json={"action": "REJECTED", "rationale": "second try"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_DECIDED"


def test_cannot_decide_on_unavailable_recommendation(client, make):
    staff = make.staff()
    inc = make.incident()
    client.post(f"{BASE}/incidents/{inc['incident_id']}/ai-triage", headers=staff["headers"])
    recs = client.get(f"{BASE}/incidents/{inc['incident_id']}/ai-recommendations", headers=staff["headers"]).json()
    rec_id = recs["items"][0]["recommendation_id"]
    r = client.post(
        f"{BASE}/incidents/{inc['incident_id']}/ai-recommendations/{rec_id}/decision",
        headers=staff["headers"],
        json={"action": "ACCEPTED", "rationale": "looks right"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_RECOMMENDATION"


def test_scrub_pii_removes_contact_details_before_ai_calls():
    from app.services.ai_provider import scrub_pii

    text = "Call Ramesh on +91 98765 43210 or ramesh.p@example.in, Aadhaar 1234 5678 9012. 15 people on the roof."
    clean = scrub_pii(text)
    assert "98765" not in clean and "@" not in clean and "1234 5678" not in clean
    assert "15 people on the roof" in clean
    assert scrub_pii({"note": "mail a@b.in", "n": 3, "l": ["+919876543210"]}) == {
        "note": "mail [email removed]", "n": 3, "l": ["[phone removed]"]}
