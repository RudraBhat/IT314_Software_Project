"""Text similarity for incident duplicate candidates (S2-07). Owner: Zalak (endpoint); weights: Dhruvil.

The rule query in GET /dm/incidents/{id}/duplicates already finds candidates by scenario, time window
and distance or address. This module adds a wording score and combines it with those signals into one
ranking score with a plain-language explanation. It is advisory only: it never links, merges or
dismisses anything; a dispatcher decides every pair.

* Wording: cosine similarity of character trigram counts (after lower-casing and stripping
  punctuation). Character n-grams cope with spelling variants and work for Gujarati and Hindi script
  as well as English, without a model or external service.
* Combination: a weighted sum of wording, distance, time gap and same address. The default weights
  are a reasoned starting point, **not tuned**: Dhruvil tunes them and the threshold on the labelled
  duplicate pairs (S2-07) and changes the constants here.
"""

from __future__ import annotations

import math
import re
from collections import Counter

METHOD = "rules+text"

# Default weights (sum to 1). Untuned until S2-07's labelled pairs are available.
WEIGHTS = {"text": 0.40, "distance": 0.30, "time": 0.20, "address": 0.10}
# A candidate at or above this score is described as a "strong" match in the explanation. It is a
# display hint only; nothing is decided automatically.
STRONG_MATCH = 0.70

_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise(text: str | None) -> str:
    cleaned = _NON_WORD.sub(" ", (text or "").lower())
    return _SPACE.sub(" ", cleaned).strip()


def trigrams(text: str | None) -> Counter:
    """Character trigram counts of the normalised text, padded so short words still produce grams."""
    norm = normalise(text)
    if not norm:
        return Counter()
    padded = f"  {norm}  "
    return Counter(padded[i:i + 3] for i in range(len(padded) - 2))


def text_similarity(a: str | None, b: str | None) -> float:
    """Cosine similarity (0-1) of the two texts' character trigram profiles; 0 when either is empty."""
    ga, gb = trigrams(a), trigrams(b)
    if not ga or not gb:
        return 0.0
    dot = sum(count * gb[gram] for gram, count in ga.items() if gram in gb)
    norm = math.sqrt(sum(c * c for c in ga.values())) * math.sqrt(sum(c * c for c in gb.values()))
    return round(dot / norm, 3) if norm else 0.0


def _closeness(value: float | None, limit: float) -> float | None:
    """1 when value is 0, falling linearly to 0 at the limit; None when the value is unknown."""
    if value is None or limit <= 0:
        return None
    return max(0.0, 1.0 - float(value) / limit)


def combined_score(
    *,
    text: float,
    distance_m: float | None,
    minutes_apart: float | None,
    same_address: bool,
    radius_m: float,
    window_hours: float,
) -> float:
    """Weighted 0-1 score. An unknown distance gives its weight to the address signal instead."""
    distance = _closeness(distance_m, radius_m)
    time_gap = _closeness(minutes_apart, window_hours * 60)
    address = 1.0 if same_address else 0.0
    weights = dict(WEIGHTS)
    if distance is None:
        weights["address"] += weights.pop("distance")
        distance = 0.0
    score = (
        weights["text"] * text
        + weights.get("distance", 0.0) * distance
        + weights["time"] * (time_gap or 0.0)
        + weights["address"] * address
    )
    return round(min(1.0, max(0.0, score)), 3)


def explain(score: float, text: float) -> str:
    """Short plain-language summary for the dispatcher; never a verdict."""
    strength = "strong" if score >= STRONG_MATCH else "possible" if score >= 0.4 else "weak"
    wording = "very similar" if text >= 0.6 else "partly similar" if text >= 0.3 else "different"
    return f"{strength} match (score {score:.2f}): wording {wording} ({text:.2f}); a dispatcher decides"


def score_candidates(
    base_description: str | None,
    candidates: list[dict],
    *,
    radius_m: float,
    window_hours: float,
) -> list[dict]:
    """Add text_similarity, score, method and explanation to each candidate, best first.

    Each candidate needs ``description`` (full text, removed from the output), ``distance_m``,
    ``minutes_apart`` and ``same_address``.
    """
    scored = []
    for c in candidates:
        description = c.pop("description", None)
        text = text_similarity(base_description, description)
        score = combined_score(
            text=text,
            distance_m=c.get("distance_m"),
            minutes_apart=c.get("minutes_apart"),
            same_address=bool(c.get("same_address")),
            radius_m=radius_m,
            window_hours=window_hours,
        )
        scored.append({**c, "text_similarity": text, "score": score, "method": METHOD,
                       "explanation": explain(score, text)})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored
