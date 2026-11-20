"""Advisory related-signal matching for the dispatcher queue (heuristic; no trained model).

Finds PENDING ``source_signals`` that may describe the same event so a dispatcher can review them
together. Nothing here confirms a disaster, merges signals, creates incidents or dispatches teams:
callers only read. The ranking score is a sort hint, NOT a probability that two alerts are the same event.

Tuning: every threshold is a module constant below (documented in docs/architecture/signal-matching.md).
"""

from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------- thresholds
MATCH_RADIUS_M = 1000  # two signals are "nearby" when their points are within 1 km
MATCH_WINDOW_HOURS = 6  # ...and "recent" within 6 h by source time, falling back to receipt time
MIN_TEXT_JACCARD = 0.25  # wording counts as similar from this Jaccard overlap of content words...
MIN_SHARED_WORDS = 2  # ...and only with at least this many shared content words
CONFLICT_MIN_TEXT_JACCARD = 0.5  # when both labels are set and differ, wording must be much closer
MAX_GROUP_SIZE = 10  # cap on suggested group size
MAX_CANDIDATE_PAIRS = 5000  # SQL guard; the response reports truncated=true if it is hit
UNLOCATED_LIMIT = 50  # how many coordinate-less pending signals are listed

# Ranking weights (sum of the maxima = 100). Hint only; see score_pair().
WEIGHT_DISTANCE = 30
WEIGHT_TIME = 20
WEIGHT_TEXT = 30
WEIGHT_LABEL = 20
LABEL_CONFLICT_PENALTY = 10
TEXT_FULL_CREDIT_JACCARD = 0.5  # text weight is fully earned at this overlap

RULES: dict[str, Any] = {
    "radius_m": MATCH_RADIUS_M,
    "window_hours": MATCH_WINDOW_HOURS,
    "time_basis": "source_created_at when present; otherwise received_at (source_signals.created_at)",
    "min_text_jaccard": MIN_TEXT_JACCARD,
    "min_shared_words": MIN_SHARED_WORDS,
    "conflict_min_text_jaccard": CONFLICT_MIN_TEXT_JACCARD,
    "max_group_size": MAX_GROUP_SIZE,
    "weights": {
        "distance": WEIGHT_DISTANCE,
        "time": WEIGHT_TIME,
        "text": WEIGHT_TEXT,
        "label": WEIGHT_LABEL,
        "label_conflict_penalty": LABEL_CONFLICT_PENALTY,
    },
    "grouping": (
        "complete linkage: a signal joins a group only if it is a suggested match of EVERY member, so the "
        "group's largest pairwise distance is <= radius_m and its time span is <= window_hours"
    ),
    "group_location": "centre = mean of member coordinates; spread = largest pairwise distance between members",
    "group_time_range": "earliest to latest matching timestamp among members",
}
NOTE = (
    "Advisory only. ranking_score (0-100) orders suggestions by shared evidence; it is not a probability "
    "and not proof that the alerts describe the same event. A dispatcher must review every suggestion."
)

_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "were", "with", "this", "that", "from", "have", "has", "had", "not",
    "but", "you", "your", "our", "their", "its", "near", "into", "over", "out", "all", "any", "can", "will",
    "just", "very", "there", "here", "been", "being", "than", "then", "they", "them", "she", "him", "her",
    "his", "who", "what", "when", "where", "which", "about", "after", "before", "again", "also", "more",
    "some", "such", "only", "same", "too",
    "synthetic", "sample", "simulated",  # markers on test/demo data, not evidence about an event
})
# \w alone splits Gujarati/Hindi words at vowel signs, so the Devanagari and Gujarati blocks are added explicitly.
_TOKEN_RE = re.compile(r"[\w\u0900-\u097f\u0a80-\u0aff]+")
_INDIC_STOPWORDS = frozenset({
    "છે", "હતું", "હતા", "અને", "માં", "ની", "નો", "નું", "ના", "થી", "પર", "આ", "એક",
    "है", "हैं", "और", "में", "का", "की", "के", "से", "पर", "को", "ने", "यह",
})


def tokenize(text: str | None) -> set[str]:
    """Lower-cased content words: drops stop-words, short ASCII tokens and simple English suffixes."""
    words: set[str] = set()
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if raw.isascii():
            if len(raw) < 3 or raw in _STOPWORDS:
                continue
            for suffix in ("ing", "ed", "es", "s"):
                if suffix == "s" and raw.endswith("ss"):
                    break  # "underpass" must stay "underpass"
                if raw.endswith(suffix) and len(raw) - len(suffix) >= 4:
                    raw = raw[: -len(suffix)]
                    break
            words.add(raw)
        elif len(raw) >= 2 and raw not in _INDIC_STOPWORDS:  # Gujarati / Hindi tokens are kept as-is
            words.add(raw)
    return words


def text_similarity(text_a: str | None, text_b: str | None) -> tuple[float, list[str]]:
    """Jaccard overlap of content words plus the sorted shared words."""
    a, b = tokenize(text_a), tokenize(text_b)
    shared = a & b
    union = a | b
    return (len(shared) / len(union) if union else 0.0), sorted(shared)


def label_agreement(label_a: str | None, label_b: str | None) -> str:
    """'match', 'conflict' (both set and different) or 'unknown' (one or both missing)."""
    a = (label_a or "").strip().upper()
    b = (label_b or "").strip().upper()
    if not a or not b:
        return "unknown"
    return "match" if a == b else "conflict"


def score_pair(distance_m: float, minutes_apart: float, jaccard: float, agreement: str) -> float:
    """0-100 ranking hint from distance, time gap, wording overlap and label agreement."""
    score = WEIGHT_DISTANCE * max(0.0, 1 - distance_m / MATCH_RADIUS_M)
    score += WEIGHT_TIME * max(0.0, 1 - minutes_apart / (MATCH_WINDOW_HOURS * 60))
    score += WEIGHT_TEXT * min(1.0, jaccard / TEXT_FULL_CREDIT_JACCARD)
    if agreement == "match":
        score += WEIGHT_LABEL
    elif agreement == "conflict":
        score -= LABEL_CONFLICT_PENALTY
    return round(max(0.0, min(100.0, score)), 1)


def _summary(row: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    received_at = row[f"{prefix}created_at"]
    source_created_at = row.get(f"{prefix}source_created_at")
    return {
        "signal_id": row[f"{prefix}signal_id"],
        "source": row[f"{prefix}source"],
        "content_text": (row[f"{prefix}content_text"] or "")[:500],
        "received_at": received_at,
        "source_created_at": source_created_at,
        "match_time": source_created_at or received_at,
        "match_time_basis": "source" if source_created_at else "received_fallback",
        "latitude": row[f"{prefix}latitude"],
        "longitude": row[f"{prefix}longitude"],
        "location_text": row.get(f"{prefix}location_text"),
        "location_precision": row.get(f"{prefix}location_precision", "EXACT"),
        "ai_label": row[f"{prefix}ai_label"],
        "is_simulated": row[f"{prefix}is_simulated"],
    }


def evaluate_pair(a: dict[str, Any], b: dict[str, Any], distance_m: float) -> dict[str, Any] | None:
    """Return a suggestion for two signal summaries, or None when they should not be suggested.

    Rules are re-checked here (not only in SQL) so the same decision is testable without a database.
    """
    if any(s["latitude"] is None or s["longitude"] is None for s in (a, b)):
        return None  # never match automatically without coordinates
    if any(s.get("location_precision", "EXACT") != "EXACT" for s in (a, b)):
        return None  # candidate/approximate points remain visible but never drive grouping
    if distance_m > MATCH_RADIUS_M:
        return None
    a_time = a.get("match_time") or a["received_at"]
    b_time = b.get("match_time") or b["received_at"]
    minutes_apart = abs((b_time - a_time).total_seconds()) / 60
    if minutes_apart > MATCH_WINDOW_HOURS * 60:
        return None

    jaccard, shared = text_similarity(a["content_text"], b["content_text"])
    agreement = label_agreement(a["ai_label"], b["ai_label"])
    min_jaccard = CONFLICT_MIN_TEXT_JACCARD if agreement == "conflict" else MIN_TEXT_JACCARD
    wording_similar = jaccard >= min_jaccard and len(shared) >= MIN_SHARED_WORDS
    if agreement != "match" and not wording_similar:
        return None  # nearby and recent alone is not enough

    a_basis = a.get("match_time_basis") or ("source" if a.get("source_created_at") else "received_fallback")
    b_basis = b.get("match_time_basis") or ("source" if b.get("source_created_at") else "received_fallback")
    time_word = "posted" if a_basis == b_basis == "source" else "timestamped"
    reasons = [f"{round(distance_m)} m apart (limit {MATCH_RADIUS_M} m)",
               f"{time_word} {round(minutes_apart)} min apart (limit {MATCH_WINDOW_HOURS * 60} min)"]
    warnings: list[str] = []
    if "received_fallback" in {a_basis, b_basis}:
        warnings.append("one or both timestamps use platform receipt time because source time is unavailable")
    if agreement == "match":
        reasons.append(f"same disaster label ({a['ai_label']})")
    elif agreement == "unknown":
        warnings.append("one or both signals have no disaster label")
    else:
        warnings.append(f"disaster labels differ ({a['ai_label']} vs {b['ai_label']}); treat with extra caution")
    if wording_similar:
        reasons.append(f"similar wording: {len(shared)} shared words ({', '.join(shared[:6])})")
    elif shared:
        warnings.append("wording is not similar; suggested on location, time and label only")
    if a["is_simulated"] or b["is_simulated"]:
        warnings.append("includes simulated data")

    return {
        "signal_a": a,
        "signal_b": b,
        "distance_m": round(distance_m),
        "minutes_apart": round(minutes_apart),
        "shared_words": shared,
        "text_similarity": round(jaccard, 2),
        "label_agreement": agreement,
        "ranking_score": score_pair(distance_m, minutes_apart, jaccard, agreement),
        "reasons": reasons,
        "warnings": warnings,
    }


def build_groups(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group signals by complete linkage so edge members are never merely 'friends of friends'.

    Pairs are taken strongest first; a signal joins a group only if it is a suggested match of every
    existing member. Groups are suggestions for review, never merged records.
    """
    ordered = sorted(pairs, key=lambda p: (-p["ranking_score"], p["distance_m"],
                                           str(p["signal_a"]["signal_id"]), str(p["signal_b"]["signal_id"])))
    adjacency: dict[Any, set[Any]] = {}
    signals: dict[Any, dict[str, Any]] = {}
    best: dict[frozenset, float] = {}
    dist: dict[frozenset, int] = {}
    for p in ordered:
        ia, ib = p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]
        adjacency.setdefault(ia, set()).add(ib)
        adjacency.setdefault(ib, set()).add(ia)
        signals[ia], signals[ib] = p["signal_a"], p["signal_b"]
        best[frozenset((ia, ib))] = p["ranking_score"]
        dist[frozenset((ia, ib))] = p["distance_m"]

    groups: list[list[Any]] = []
    member_of: dict[Any, int] = {}
    for p in ordered:
        ia, ib = p["signal_a"]["signal_id"], p["signal_b"]["signal_id"]
        ga, gb = member_of.get(ia), member_of.get(ib)
        if ga is None and gb is None:
            member_of[ia] = member_of[ib] = len(groups)
            groups.append([ia, ib])
        elif (ga is None) != (gb is None):
            gi, new = (gb, ia) if ga is None else (ga, ib)
            if len(groups[gi]) < MAX_GROUP_SIZE and all(m in adjacency[new] for m in groups[gi]):
                groups[gi].append(new)
                member_of[new] = gi

    out = []
    for members in groups:
        member_set = set(members)
        rows = [signals[m] for m in members]
        times = sorted(r.get("match_time") or r["received_at"] for r in rows)
        lat = sum(r["latitude"] for r in rows) / len(rows)
        lon = sum(r["longitude"] for r in rows) / len(rows)
        out.append({
            "signal_ids": sorted(members, key=str),
            "size": len(members),
            "centre": {"latitude": round(lat, 6), "longitude": round(lon, 6)},
            "max_pairwise_distance_m": max(dist[k] for k in dist if k <= member_set),
            "time_range": {"start": times[0], "end": times[-1],
                           "span_minutes": round((times[-1] - times[0]).total_seconds() / 60)},
            "top_ranking_score": max(best[frozenset((x, y))] for x in members for y in members
                                     if x != y and frozenset((x, y)) in best),
        })
    out.sort(key=lambda g: (-g["top_ranking_score"], -g["size"]))
    for i, g in enumerate(out, 1):
        g["group_id"] = f"G{i}"
    return out


_PAIR_SQL = """
SELECT a.signal_id, a.source, a.content_text, a.created_at, a.source_created_at,
       a.latitude::float AS latitude, a.longitude::float AS longitude, a.location_text,
       a.location_precision, a.ai_label, a.is_simulated,
       b.signal_id AS b_signal_id, b.source AS b_source, b.content_text AS b_content_text,
       b.created_at AS b_created_at, b.source_created_at AS b_source_created_at,
       b.latitude::float AS b_latitude, b.longitude::float AS b_longitude,
       b.location_text AS b_location_text, b.location_precision AS b_location_precision,
       b.ai_label AS b_ai_label, b.is_simulated AS b_is_simulated,
       ST_Distance(a.geom, b.geom) AS distance_m
FROM source_signals a
JOIN source_signals b
  ON a.signal_id < b.signal_id
 AND b.status = 'PENDING'
 AND b.geom IS NOT NULL
 AND b.location_precision = 'EXACT'
 AND ST_DWithin(a.geom, b.geom, %(radius)s)
 AND COALESCE(b.source_created_at, b.created_at)
     BETWEEN COALESCE(a.source_created_at, a.created_at) - make_interval(hours => %(window)s)
         AND COALESCE(a.source_created_at, a.created_at) + make_interval(hours => %(window)s)
WHERE a.status = 'PENDING' AND a.geom IS NOT NULL AND a.location_precision = 'EXACT'
  AND (%(signal_id)s::uuid IS NULL OR a.signal_id = %(signal_id)s OR b.signal_id = %(signal_id)s)
ORDER BY ST_Distance(a.geom, b.geom), COALESCE(a.source_created_at, a.created_at)
LIMIT %(cap)s
"""

_UNLOCATED_SQL = """
SELECT signal_id, source, content_text, created_at, source_created_at,
       latitude::float AS latitude, longitude::float AS longitude, location_text,
       location_precision, ai_label, is_simulated, count(*) OVER () AS total
FROM source_signals
WHERE status = 'PENDING'
  AND (geom IS NULL OR latitude IS NULL OR longitude IS NULL OR location_precision <> 'EXACT')
  AND (%(signal_id)s::uuid IS NULL OR signal_id = %(signal_id)s)
ORDER BY COALESCE(source_created_at, created_at) DESC LIMIT %(limit)s
"""


def find_related_signals(conn, signal_id=None, limit: int = 100) -> dict[str, Any]:
    """One pair query over ALL pending signals (not just what a screen shows), then Python scoring."""
    rows = conn.execute(_PAIR_SQL, {"radius": MATCH_RADIUS_M, "window": MATCH_WINDOW_HOURS,
                                    "signal_id": signal_id, "cap": MAX_CANDIDATE_PAIRS + 1}).fetchall()
    truncated = len(rows) > MAX_CANDIDATE_PAIRS
    pairs = []
    for row in rows[:MAX_CANDIDATE_PAIRS]:
        first, second = _summary(row), _summary(row, "b_")
        # signal_a is the "original": the selected signal when signal_id is given, otherwise the earlier one
        if (signal_id is not None and second["signal_id"] == signal_id) or (
            signal_id is None and second["match_time"] < first["match_time"]
        ):
            first, second = second, first
        suggestion = evaluate_pair(first, second, float(row["distance_m"]))
        if suggestion:
            pairs.append(suggestion)
    pairs.sort(key=lambda p: (-p["ranking_score"], p["distance_m"]))

    unlocated = conn.execute(_UNLOCATED_SQL, {"signal_id": signal_id, "limit": UNLOCATED_LIMIT}).fetchall()
    unlocated_total = unlocated[0]["total"] if unlocated else 0
    return {
        "method": "heuristic",
        "advisory": True,
        "requires_human_review": True,
        "note": NOTE,
        "rules": RULES,
        "pairs": pairs[:limit],
        "pairs_total": len(pairs),
        "groups": build_groups(pairs),
        "unlocated": [{
            **_summary(r),
            "location_missing": r["latitude"] is None or r["longitude"] is None,
            "location_approximate": r["location_precision"] != "EXACT"
            and r["latitude"] is not None and r["longitude"] is not None,
            "note": (
                "Approximate or unverified coordinates are not used for grouping; review the location manually."
                if r["latitude"] is not None and r["longitude"] is not None
                else "No coordinates, so it is not matched automatically; review it manually."
            ),
        }
                      for r in unlocated],
        "unlocated_total": unlocated_total,
        "truncated": truncated,
    }
