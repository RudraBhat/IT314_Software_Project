"""Duplicate grouping v2 (S2-07, endpoint owner Zalak): wording similarity added to the rule candidates.

Unit tests need no database. The endpoint test checks the response shape, the ordering by score and
that nothing is ever linked or merged automatically.
"""

import pytest

from app.services.duplicate_similarity import (
    METHOD,
    WEIGHTS,
    combined_score,
    explain,
    score_candidates,
    text_similarity,
)

RADIUS, WINDOW = 300, 6


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_identical_text_scores_one_and_unrelated_text_scores_low():
    same = "Water entering homes near Ashram Road underpass"
    assert text_similarity(same, same) == 1.0
    assert text_similarity(same, "Chemical tanker fire at the GIDC estate gate") < 0.3


def test_similarity_ignores_case_and_punctuation():
    assert text_similarity("FLOOD at Vasna barrage!!", "flood at vasna barrage") == 1.0


def test_similarity_handles_gujarati_script():
    a = "વાસણા બેરેજ પાસે ઘરમાં પાણી ભરાયું"
    b = "વાસણા બેરેજ પાસે પાણી ભરાયું છે"
    assert text_similarity(a, b) > 0.6


def test_empty_text_has_no_similarity():
    assert text_similarity("", "anything") == 0.0
    assert text_similarity(None, None) == 0.0


def test_combined_score_rewards_close_recent_and_similar_reports():
    near = combined_score(text=0.9, distance_m=20, minutes_apart=10, same_address=False,
                          radius_m=RADIUS, window_hours=WINDOW)
    far = combined_score(text=0.1, distance_m=290, minutes_apart=340, same_address=False,
                         radius_m=RADIUS, window_hours=WINDOW)
    assert 0 <= far < near <= 1


def test_unknown_distance_moves_its_weight_to_the_address_signal():
    with_address = combined_score(text=0.0, distance_m=None, minutes_apart=0, same_address=True,
                                  radius_m=RADIUS, window_hours=WINDOW)
    assert with_address == pytest.approx(WEIGHTS["time"] + WEIGHTS["address"] + WEIGHTS["distance"])


def test_score_candidates_orders_best_first_and_drops_full_text():
    base = "Water entering homes near Ashram Road underpass, cars stuck"
    candidates = [
        {"incident_id": "far", "description": "Strong wind at the coast", "distance_m": 280,
         "minutes_apart": 300, "same_address": False},
        {"incident_id": "near", "description": "Water entering homes near Ashram Road underpass",
         "distance_m": 30, "minutes_apart": 15, "same_address": False},
    ]
    scored = score_candidates(base, candidates, radius_m=RADIUS, window_hours=WINDOW)
    assert [c["incident_id"] for c in scored] == ["near", "far"]
    assert all("description" not in c for c in scored)
    assert all(c["method"] == METHOD and 0 <= c["score"] <= 1 and c["explanation"] for c in scored)


def test_explanation_never_claims_a_decision():
    text = explain(0.9, 0.8)
    assert "strong match" in text and "a dispatcher decides" in text


@pytest.mark.db
def test_endpoint_returns_scored_candidates_and_never_merges(client, make, sql):
    staff = make.staff()
    a = make.incident(latitude=21.1702, longitude=72.8311, description="Water entering homes near the Adajan bridge")
    similar = make.incident(latitude=21.1705, longitude=72.8313, description="Water entering homes near Adajan bridge")
    other = make.incident(latitude=21.1703, longitude=72.8312, description="Strong wind broke a hoarding")

    body = client.get(f"/api/v1/dm/incidents/{a['incident_id']}/duplicates", headers=staff["headers"]).json()
    assert body["method"] == METHOD and body["advisory"] is True
    assert body["rules"]["weights"] == WEIGHTS
    ids = [c["incident_id"] for c in body["candidates"]]
    assert str(similar["incident_id"]) in ids and str(other["incident_id"]) in ids
    assert ids.index(str(similar["incident_id"])) < ids.index(str(other["incident_id"]))
    first = body["candidates"][0]
    assert {"score", "text_similarity", "explanation", "rationale", "description_excerpt"} <= set(first)
    assert "description" not in first
    assert "wording similarity" in first["rationale"]

    canonical = sql.execute(
        "SELECT canonical_incident_id FROM incidents WHERE incident_id = ANY(%s)",
        ([similar["incident_id"], other["incident_id"]],),
    ).fetchall()
    assert all(r["canonical_incident_id"] is None for r in canonical), "scoring must never link or merge"
