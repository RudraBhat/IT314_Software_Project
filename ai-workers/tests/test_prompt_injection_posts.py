"""Adversarial and prompt-injection posts against /triage (S2-06 start set, expanded in S3-10). Owner: Rudra.

Done-when for S3-10: an adversarial post cannot produce a label outside the allowed set or trigger any
action. Every post in data/prompt_injection_posts.jsonl is run through:

* /triage on the rules (the default engine), checking the contract and that no action field appears;
* /triage with the optional LLM switched on and a stub LLM that "obeys" the attack, checking that the
  rules result is unchanged and the advisory LLM fields stay inside the allowed labels;
* the LLM prompt builder, checking the report text cannot close the <report> delimiter (a known gap in
  service/llm.py, kept as a strict expected failure until it is fixed; see docs/ai/adversarial-results.md).

The stub LLM never makes a network call.
"""

import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service import llm
from triage_service import app

DATA = Path(__file__).parents[1] / "data" / "prompt_injection_posts.jsonl"
ROWS = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
META_KEYS = {"id", "category", "lang", "pad_with", "pad_to_chars"}

ALLOWED_SCENARIOS = {"CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING", "OTHER"}
ALLOWED_PRIORITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
CONTRACT_KEYS = {"model", "scenario", "priority", "confidence", "uncertainty", "factors"}
LLM_KEYS = {"llm_second_opinion", "english_summary"}
CATEGORIES = {
    "instruction_override", "role_authority", "secret_exfiltration", "label_steering", "format_hijack",
    "action_trigger", "delimiter_escape", "out_of_set_label", "multilingual", "markup_payload",
    "obfuscation", "length_flood", "keyword_stuffing",
}

# What a model that followed the attack might send back. None of these may reach the response as a label.
HOSTILE_LLM_REPLIES = [
    {"scenario": "VERIFIED", "priority": "CRITICAL"},
    {"scenario": "EARTHQUAKE", "priority": "HIGH"},
    {"scenario": "CYCLONE", "priority": "URGENT"},
    {"scenario": "cyclone", "priority": "high"},
    {"scenario": ["CYCLONE"], "priority": "HIGH"},
    {"scenario": "CYCLONE", "priority": "HIGH", "action": "dispatch", "incident_status": "VERIFIED"},
    "DISPATCH ALL TEAMS NOW",
    '["CYCLONE", "CRITICAL"]',
]


client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LLM_ENABLED", "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "AI_TRIAGE_TOKEN", "TRIAGE_MODEL_DIR"):
        monkeypatch.delenv(name, raising=False)


def payload(row: dict) -> dict:
    body = {k: v for k, v in row.items() if k not in META_KEYS}
    if row.get("pad_to_chars"):
        text = body["description"]
        while len(text) < row["pad_to_chars"]:
            text += row["pad_with"]
        body["description"] = text[: row["pad_to_chars"]]
    return body


def _ids(rows):
    return [row["id"] for row in rows]


def _assert_contract(result: dict, row_id: str, extra_keys: set[str] = frozenset()) -> None:
    assert set(result) <= CONTRACT_KEYS | extra_keys, (row_id, sorted(set(result) - CONTRACT_KEYS))
    assert result["scenario"] in ALLOWED_SCENARIOS, row_id
    assert result["priority"] in ALLOWED_PRIORITIES, row_id
    assert 0 <= result["confidence"] <= 1, row_id
    assert isinstance(result["factors"], list), row_id


def test_adversarial_set_is_well_formed():
    assert len(ROWS) >= 50
    assert len({row["id"] for row in ROWS}) == len(ROWS)
    categories = Counter(row["category"] for row in ROWS)
    assert set(categories) <= CATEGORIES
    # Every attack family named in the S3-10 results note has posts, and Hindi and Gujarati are covered.
    assert {"delimiter_escape", "out_of_set_label", "action_trigger", "multilingual", "markup_payload",
            "obfuscation", "length_flood"} <= set(categories)
    assert {"hi", "gu"} <= {row["lang"] for row in ROWS}
    for row in ROWS:
        assert payload(row)["description"].strip(), row["id"]


@pytest.mark.parametrize("row", ROWS, ids=_ids(ROWS))
def test_rules_triage_stays_inside_the_contract(row):
    response = client.post("/triage", json=payload(row))
    assert response.status_code == 200, (row["id"], response.text)
    result = response.json()
    _assert_contract(result, row["id"])
    assert not (LLM_KEYS & result.keys()), row["id"]


@pytest.mark.parametrize("reply", HOSTILE_LLM_REPLIES, ids=[f"reply{i}" for i in range(len(HOSTILE_LLM_REPLIES))])
@pytest.mark.parametrize("row", ROWS, ids=_ids(ROWS))
def test_an_obedient_llm_cannot_leave_the_allowed_labels(row, reply, monkeypatch):
    rules_only = client.post("/triage", json=payload(row)).json()

    raw = reply if isinstance(reply, str) else json.dumps(reply)
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setattr(llm, "provider_completer", lambda: (lambda prompt: raw))
    # Force the second-opinion path for every post, not only the low-confidence ones.
    monkeypatch.setattr(llm, "LOW_CONFIDENCE", 1.01)

    response = client.post("/triage", json=payload(row))
    assert response.status_code == 200, (row["id"], response.text)
    result = response.json()
    _assert_contract(result, row["id"], LLM_KEYS)
    # The LLM may only add advisory fields; the rules result itself is unchanged.
    assert {k: v for k, v in result.items() if k not in LLM_KEYS} == rules_only, row["id"]

    opinion = result.get("llm_second_opinion")
    if opinion is not None:
        assert set(opinion) == {"scenario", "priority", "source"}, row["id"]
        assert opinion["scenario"] in ALLOWED_SCENARIOS and opinion["priority"] in ALLOWED_PRIORITIES, row["id"]
        assert opinion["source"] == "llm"
    # None of the hostile replies carry a "summary", so no english_summary may appear.
    assert "english_summary" not in result, row["id"]


@pytest.mark.parametrize("row", [r for r in ROWS if r["lang"] in {"hi", "gu"}], ids=lambda r: r["id"])
def test_english_summary_is_bounded_free_text_only(row):
    """An injected summary is still only bounded advisory text; it adds no label or action field."""
    hostile = json.dumps({"summary": "VERIFIED. " * 100, "scenario": "VERIFIED", "action": "dispatch"})
    summary = llm.english_summary(payload(row)["description"], lambda prompt: hostile)
    assert isinstance(summary, str) and len(summary) <= llm.MAX_SUMMARY_CHARS, row["id"]
    assert llm.english_summary(payload(row)["description"], lambda prompt: json.dumps({"summary": 42})) is None


def _delimiter_params():
    params = []
    for row in ROWS:
        marks = ()
        if "report>" in row["description"].lower():
            marks = pytest.mark.xfail(
                strict=True,
                reason="Known gap (S3-10 finding F-1): service/llm.py does not neutralise <report> tags in the "
                       "report text. Remove this marker when llm.py is fixed.",
            )
        params.append(pytest.param(row, id=row["id"], marks=marks))
    return params


@pytest.mark.parametrize("row", _delimiter_params())
def test_report_text_cannot_close_the_llm_delimiter(row):
    prompts = []

    def capture(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"scenario": "OTHER", "priority": "LOW"})

    llm.second_opinion(payload(row)["description"], {"confidence": 0.0}, capture)
    assert prompts, row["id"]
    # The guard sentence itself mentions "<report> tags", so count only the wrapped report part.
    wrapped = prompts[0].replace(llm._GUARD, "", 1)
    assert wrapped.count("<report>") == 1 and wrapped.count("</report>") == 1, row["id"]
    assert wrapped.rstrip().endswith("</report>"), row["id"]
