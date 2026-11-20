"""Related-signal suggestions (docs/architecture/signal-matching.md): heuristic, advisory, read-only.

Covers:
- Pure rules (no database): wording, label agreement, thresholds, ranking order, no-chaining groups.
- GET /api/v1/dm/signals/related: nearby+recent pairs, distance/time limits, missing coordinates,
  missing/conflicting labels, unrelated alerts, searching beyond the first screen of signals.
- Human review: the endpoint changes nothing, and promote/dismiss rules are unchanged.

DB tests use their own coordinates (the test database is shared and persistent) and look only at their own
signal ids.
"""

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.geo import is_in_gujarat
from app.services import signal_matching as sm

BASE = "/api/v1/dm"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
FLOOD_A = "Water is rising fast on the service road near Adajan underpass; two-wheelers are stuck."
FLOOD_B = "Heavy waterlogging at Adajan, vehicles stuck in the underpass, road looks flooded."
FIRE = "Smoke rising from a godown behind the textile market, fire brigade not yet seen."


def sig(text, lat=21.2000, lon=72.7900, label="URBAN_FLOODING", minutes=0, simulated=True):
    return {
        "signal_id": uuid4(), "source": "REPLAY", "content_text": text,
        "received_at": NOW + timedelta(minutes=minutes), "latitude": lat, "longitude": lon,
        "location_text": None, "ai_label": label, "is_simulated": simulated,
    }


# ------------------------------------------------------------------ pure rules (no database)


def test_tokenize_ignores_stopwords_and_keeps_gujarati():
    words = sm.tokenize("The flooded roads near the Adajan underpass; પાણી ભરાયું")
    assert {"flood", "road", "adajan", "underpass", "પાણી", "ભરાયું"} <= words
    assert "the" not in words and "near" not in words


def test_nearby_recent_signals_with_different_wording_are_suggested():
    result = sm.evaluate_pair(sig(FLOOD_A), sig(FLOOD_B, minutes=30), distance_m=430)
    assert result is not None
    assert result["label_agreement"] == "match"
    assert "same disaster label (URBAN_FLOODING)" in result["reasons"]
    assert any("similar wording" in r for r in result["reasons"])
    assert "includes simulated data" in result["warnings"]
    assert 0 <= result["ranking_score"] <= 100


def test_distance_and_time_limits_are_enforced_even_for_identical_alerts():
    a = sig(FLOOD_A)
    assert sm.evaluate_pair(a, sig(FLOOD_A), distance_m=sm.MATCH_RADIUS_M + 1) is None
    assert sm.evaluate_pair(a, sig(FLOOD_A, minutes=sm.MATCH_WINDOW_HOURS * 60 + 1), distance_m=10) is None
    # exactly on the limits is still allowed
    assert sm.evaluate_pair(a, sig(FLOOD_A, minutes=sm.MATCH_WINDOW_HOURS * 60), distance_m=sm.MATCH_RADIUS_M)


def test_missing_coordinates_are_never_matched():
    located = sig(FLOOD_A)
    for missing in ({"latitude": None}, {"longitude": None}):
        assert sm.evaluate_pair(located, {**sig(FLOOD_A), **missing}, distance_m=0) is None


def test_missing_label_needs_similar_wording_and_is_flagged():
    unlabeled = sig(FLOOD_B, label=None)
    suggested = sm.evaluate_pair(sig(FLOOD_A), unlabeled, distance_m=300)
    assert suggested and suggested["label_agreement"] == "unknown"
    assert "one or both signals have no disaster label" in suggested["warnings"]
    assert sm.evaluate_pair(sig(FLOOD_A), sig(FIRE, label=None), distance_m=300) is None


def test_conflicting_labels_need_much_closer_wording():
    assert sm.evaluate_pair(sig(FLOOD_A), sig(FIRE, label="INDUSTRIAL_FIRE"), distance_m=300) is None
    # moderately similar wording is not enough once labels disagree...
    assert sm.evaluate_pair(sig(FLOOD_A), sig(FLOOD_B, label="CYCLONE"), distance_m=300) is None
    # ...but near-identical wording is still shown, with an explicit warning
    near_copy = sm.evaluate_pair(sig(FLOOD_A), sig(FLOOD_A, label="CYCLONE"), distance_m=300)
    assert near_copy and near_copy["label_agreement"] == "conflict"
    assert any("labels differ" in w for w in near_copy["warnings"])


def test_unrelated_alerts_nearby_are_not_suggested():
    assert sm.evaluate_pair(sig(FLOOD_A), sig(FIRE, label=None), distance_m=50) is None


def test_closer_and_more_similar_pairs_rank_higher_and_conflict_is_penalised():
    near = sm.evaluate_pair(sig(FLOOD_A), sig(FLOOD_B, minutes=5), distance_m=100)
    far = sm.evaluate_pair(sig(FLOOD_A), sig(FLOOD_B, minutes=300), distance_m=900)
    assert near["ranking_score"] > far["ranking_score"]
    assert sm.score_pair(100, 5, 0.5, "match") > sm.score_pair(100, 5, 0.5, "unknown") > sm.score_pair(100, 5, 0.5, "conflict")


def test_groups_do_not_chain_signals_that_are_not_close_to_each_other():
    a, b, c = sig(FLOOD_A), sig(FLOOD_B, minutes=10), sig(FLOOD_A, minutes=20)
    # a-b and b-c are each within 1 km but a-c is not, so no single group may hold all three
    pairs = [sm.evaluate_pair(a, b, 800), sm.evaluate_pair(b, c, 800)]
    assert all(pairs)
    groups = sm.build_groups(pairs)
    assert len(groups) == 1 and groups[0]["size"] == 2
    assert groups[0]["max_pairwise_distance_m"] <= sm.MATCH_RADIUS_M
    assert groups[0]["time_range"]["span_minutes"] <= sm.MATCH_WINDOW_HOURS * 60


def test_mutually_close_signals_form_one_group_with_centre_and_time_range():
    a, b, c = sig(FLOOD_A), sig(FLOOD_B, minutes=10, lat=21.2010), sig(FLOOD_A, minutes=40, lon=72.7910)
    pairs = [sm.evaluate_pair(a, b, 120), sm.evaluate_pair(b, c, 150), sm.evaluate_pair(a, c, 100)]
    (group,) = sm.build_groups(pairs)
    assert group["size"] == 3
    assert group["time_range"]["span_minutes"] == 40
    assert 21.2 <= group["centre"]["latitude"] <= 21.201


# ------------------------------------------------------------------ endpoint (database)


def _spot():
    """A random point in Gujarat: the shared test database keeps rows between runs, so tests never reuse places."""
    while True:
        lat, lon = round(random.uniform(20.2, 23.8), 4), round(random.uniform(69.5, 73.8), 4)
        # keep a margin so the +/- 0.02 degree offsets used below stay inside Gujarat (promotion enforces it)
        if all(is_in_gujarat(lat + dy, lon + dx) for dy in (-0.02, 0, 0.02) for dx in (-0.02, 0, 0.02)):
            return lat, lon


def _related(client, headers):
    res = client.get(f"{BASE}/signals/related", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _pair_ids(data, wanted):
    wanted = {str(w) for w in wanted}
    return [
        {p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]}
        for p in data["pairs"]
        if {p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]} <= wanted
    ]


def test_related_requires_staff_session(client, make, citizen_user, field_user):
    assert client.get(f"{BASE}/signals/related").status_code == 401
    assert client.get(f"{BASE}/signals/related", headers=citizen_user["headers"]).status_code == 403
    assert client.get(f"{BASE}/signals/related", headers=field_user["headers"]).status_code == 403
    assert client.get(f"{BASE}/signals/related", headers=make.staff()["headers"]).status_code == 200


def test_nearby_recent_pair_is_suggested_with_reasons_and_flags(client, make):
    staff = make.staff()
    now = datetime.now(UTC)
    lat, lon = _spot()
    a = make.signal(content_text=FLOOD_A, latitude=lat, longitude=lon, created_at=now - timedelta(minutes=50))
    b = make.signal(content_text=FLOOD_B, latitude=lat + 0.0035, longitude=lon + 0.0020,
                    created_at=now - timedelta(minutes=20))

    data = _related(client, staff["headers"])
    assert data["method"] == "heuristic"
    assert data["advisory"] is True and data["requires_human_review"] is True
    assert data["rules"]["radius_m"] == 1000 and data["rules"]["window_hours"] == 6
    (pair,) = [p for p in data["pairs"] if {p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]}
               == {str(a["signal_id"]), str(b["signal_id"])}]
    assert pair["signal_a"]["content_text"] == FLOOD_A and pair["signal_b"]["content_text"] == FLOOD_B
    assert pair["signal_a"]["source"] == "REPLAY" and pair["signal_a"]["received_at"]
    assert pair["signal_a"]["ai_label"] == "URBAN_FLOODING"
    assert pair["signal_a"]["is_simulated"] is True and pair["signal_b"]["is_simulated"] is True
    assert 0 < pair["distance_m"] <= 1000 and pair["minutes_apart"] == 30
    assert pair["label_agreement"] == "match" and pair["reasons"] and 0 <= pair["ranking_score"] <= 100
    assert any(str(a["signal_id"]) in g["signal_ids"] and str(b["signal_id"]) in g["signal_ids"] for g in data["groups"])
    assert "raw_payload" not in str(pair)


def test_signal_outside_distance_or_time_limit_is_not_suggested(client, make):
    staff = make.staff()
    now = datetime.now(UTC)
    lat, lon = _spot()
    base = make.signal(content_text=FLOOD_A, latitude=lat, longitude=lon, created_at=now)
    too_far = make.signal(content_text=FLOOD_A, latitude=lat + 0.018, longitude=lon, created_at=now)  # ~2 km
    too_old = make.signal(content_text=FLOOD_A, latitude=lat, longitude=lon, created_at=now - timedelta(hours=7))

    data = _related(client, staff["headers"])
    assert _pair_ids(data, [base["signal_id"], too_far["signal_id"]]) == []
    assert _pair_ids(data, [base["signal_id"], too_old["signal_id"]]) == []
    assert _pair_ids(data, [too_far["signal_id"], too_old["signal_id"]]) == []


def test_signal_without_coordinates_is_listed_as_location_missing_and_not_matched(client, make):
    staff = make.staff()
    now = datetime.now(UTC)
    lat, lon = _spot()
    located = make.signal(content_text=FLOOD_A, latitude=lat, longitude=lon, created_at=now)
    unlocated = make.signal(content_text=FLOOD_A, latitude=None, longitude=None, location_text=None, created_at=now)

    data = _related(client, staff["headers"])
    assert _pair_ids(data, [located["signal_id"], unlocated["signal_id"]]) == []
    entry = next(u for u in data["unlocated"] if u["signal_id"] == str(unlocated["signal_id"]))
    assert entry["location_missing"] is True and entry["latitude"] is None
    assert data["unlocated_total"] >= 1


def test_missing_and_conflicting_labels_via_endpoint(client, make):
    staff = make.staff()
    now = datetime.now(UTC)
    lat, lon = _spot()
    kw = {"latitude": lat, "longitude": lon, "created_at": now}
    base = make.signal(content_text=FLOOD_A, **kw)
    no_label_similar = make.signal(content_text=FLOOD_B, ai_label=None, **kw)
    no_label_other = make.signal(content_text=FIRE, ai_label=None, **kw)
    conflict_other = make.signal(content_text=FIRE, ai_label="INDUSTRIAL_FIRE", **kw)

    data = _related(client, staff["headers"])
    (similar,) = [p for p in data["pairs"] if {p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]}
                  == {str(base["signal_id"]), str(no_label_similar["signal_id"])}]
    assert similar["label_agreement"] == "unknown"
    assert any("no disaster label" in w for w in similar["warnings"])
    assert _pair_ids(data, [base["signal_id"], no_label_other["signal_id"]]) == []
    assert _pair_ids(data, [base["signal_id"], conflict_other["signal_id"]]) == []


def test_promoted_and_dismissed_signals_are_not_suggested(client, make):
    staff = make.staff()
    lat, lon = _spot()
    kw = {"latitude": lat, "longitude": lon, "content_text": FLOOD_A}
    pending = make.signal(**kw)
    dismissed = make.signal(status="DISMISSED", dismiss_rationale="test", **kw)
    promoted = make.signal(status="PROMOTED", **kw)
    data = _related(client, staff["headers"])
    assert _pair_ids(data, [pending["signal_id"], dismissed["signal_id"], promoted["signal_id"]]) == []


def test_searches_all_pending_signals_not_only_the_first_screen(client, make, sql):
    staff = make.staff()
    old = datetime.now(UTC) - timedelta(hours=3)
    lat, lon = _spot()
    a = make.signal(content_text=FLOOD_A, latitude=lat, longitude=lon, created_at=old)
    b = make.signal(content_text=FLOOD_B, latitude=lat + 0.003, longitude=lon + 0.001, created_at=old)
    fillers = [make.signal(content_text=f"Filler {i} unrelated chatter", latitude=22.5 + i * 0.05, longitude=70.0,
                           created_at=datetime.now(UTC) - timedelta(seconds=i)) for i in range(55)]
    try:
        page = client.get(f"{BASE}/signals?status=PENDING&limit=50", headers=staff["headers"]).json()
        shown = {s["signal_id"] for s in page}
        assert str(a["signal_id"]) not in shown and str(b["signal_id"]) not in shown  # off the visible page
        data = _related(client, staff["headers"])
        assert len(_pair_ids(data, [a["signal_id"], b["signal_id"]])) == 1  # still found
    finally:
        sql.execute("UPDATE source_signals SET status = 'DISMISSED' WHERE signal_id = ANY(%s)",
                    ([f["signal_id"] for f in fillers],))


def test_signal_id_filter_returns_only_pairs_with_that_signal(client, make):
    staff = make.staff()
    now = datetime.now(UTC)
    lat, lon = _spot()
    kw = {"latitude": lat, "longitude": lon, "created_at": now}
    a = make.signal(content_text=FLOOD_A, **kw)
    b = make.signal(content_text=FLOOD_B, **kw)
    res = client.get(f"{BASE}/signals/related?signal_id={a['signal_id']}", headers=staff["headers"])
    assert res.status_code == 200
    pairs = res.json()["pairs"]
    assert pairs and all(str(a["signal_id"]) in (p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]) for p in pairs)
    assert any(str(b["signal_id"]) in (p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]) for p in pairs)


def test_geom_is_kept_in_sync_with_coordinates(make, sql):
    s = make.signal(latitude=21.3, longitude=72.3)
    row = sql.execute("SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM source_signals "
                      "WHERE signal_id = %s", (s["signal_id"],)).fetchone()
    assert (round(row["lat"], 3), round(row["lon"], 3)) == (21.3, 72.3)
    sql.execute("UPDATE source_signals SET latitude = NULL, longitude = NULL WHERE signal_id = %s", (s["signal_id"],))
    assert sql.execute("SELECT geom IS NULL AS n FROM source_signals WHERE signal_id = %s", (s["signal_id"],)).fetchone()["n"]


# ------------------------------------------------------------------ human review & unchanged rules


def test_suggestions_change_nothing_and_every_action_still_needs_a_human(client, make, sql):
    staff = make.staff()
    now = datetime.now(UTC)
    lat, lon = _spot()
    kw = {"latitude": lat, "longitude": lon, "created_at": now}
    a = make.signal(content_text=FLOOD_A, **kw)
    b = make.signal(content_text=FLOOD_B, **kw)

    def counts():
        incidents = sql.execute("SELECT count(*) AS n FROM incidents").fetchone()["n"]
        audit_logs = sql.execute("SELECT count(*) AS n FROM audit_logs").fetchone()["n"]
        dispatch_orders = sql.execute("SELECT count(*) AS n FROM dispatch_orders").fetchone()["n"]
        return incidents, audit_logs, dispatch_orders

    before = counts()

    data = _related(client, staff["headers"])
    assert data["requires_human_review"] is True and "not a probability" in data["note"]
    assert counts() == before
    states = sql.execute("SELECT status FROM source_signals WHERE signal_id = ANY(%s)",
                         ([a["signal_id"], b["signal_id"]],)).fetchall()
    assert {s["status"] for s in states} == {"PENDING"}

    # promote rules are unchanged: DISPATCH-only staff are refused, and nothing happens to the related signal
    refused = client.post(f"{BASE}/signals/{a['signal_id']}/promote", headers=make.staff("DISPATCH")["headers"])
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "PERMISSION_REQUIRED"
    assert counts()[0] == before[0]

    ok = client.post(f"{BASE}/signals/{a['signal_id']}/promote", headers=make.staff("PUBLISHER")["headers"])
    assert ok.status_code == 201 and ok.json()["incident_status"] == "SUBMITTED"
    assert counts()[0] == before[0] + 1  # exactly one incident; the related signal was not merged or promoted
    assert sql.execute("SELECT status FROM source_signals WHERE signal_id = %s", (b["signal_id"],)).fetchone()["status"] == "PENDING"
    assert sql.execute("SELECT status FROM incidents WHERE incident_ref = %s",
                       (ok.json()["incident_ref"],)).fetchone()["status"] == "SUBMITTED"
    assert counts()[2] == before[2]  # nothing dispatched

    # the promoted signal now disappears from suggestions
    assert _pair_ids(_related(client, staff["headers"]), [a["signal_id"], b["signal_id"]]) == []


def test_related_endpoint_accepts_no_write_methods(client, make):
    headers = make.staff("PUBLISHER", "SUPERVISOR", "DISPATCH")["headers"]
    for method in (client.post, client.put, client.patch, client.delete):
        assert method(f"{BASE}/signals/related", headers=headers).status_code in (404, 405, 422)


@pytest.mark.parametrize("bad", ["0", "501", "x"])
def test_limit_validation(client, make, bad):
    res = client.get(f"{BASE}/signals/related?limit={bad}", headers=make.staff()["headers"])
    assert res.status_code == 422
