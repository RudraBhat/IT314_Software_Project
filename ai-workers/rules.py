"""Deterministic, explainable triage rules (model "drch-triage-v1-rules").

Pure functions with no I/O so they are trivial to test. The output follows the contract in
docs/api_contracts.md section 7 and is ADVISORY: the backend validates it again and a human decides.
"""

from __future__ import annotations

MODEL_NAME = "drch-triage-v1-rules"
SUPPORTED = ("CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING")

SCENARIO_KEYWORDS: dict[str, tuple[str, ...]] = {
    "URBAN_FLOODING": ("flood", "waterlog", "water level", "inundat", "submerged", "overflow", "rising water", "drain"),
    "INDUSTRIAL_FIRE": ("fire", "blaze", "explosion", "chemical", "gas leak", "smoke", "factory", "plant", "tank"),
    "CYCLONE": ("cyclone", "storm", "wind", "surge", "uprooted", "squall", "coastal", "hurricane"),
}
DISTRESS_KEYWORDS = ("trapped", "stranded", "rooftop", "unconscious", "drowning", "collapsed", "missing", "injured", "burn")
URGENCY_POINTS = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}


def _normalise(value: str | None) -> str:
    return (value or "").strip().upper().replace(" ", "_")


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if w in text]


def triage(payload: dict) -> dict:
    text = (payload.get("description") or "").lower()
    reported = _normalise(payload.get("reported_scenario"))
    people = payload.get("people_affected") or 0
    urgency = _normalise(payload.get("reported_urgency"))

    scores = {s: len(_hits(text, words)) for s, words in SCENARIO_KEYWORDS.items()}
    best = max(scores, key=lambda s: scores[s])
    factors: list[dict] = []
    notes: list[str] = []

    if reported in SUPPORTED:
        scenario = reported
        if scores[best] >= scores[reported] + 2 and best != reported:
            notes.append(f"The text reads more like {best.lower()} than the reported {reported.lower()}.")
    elif scores[best] >= 2:
        scenario = best
        notes.append("The reported scenario was not supported; inferred from the description.")
    else:
        scenario = "OTHER"  # outside the three supported scenarios: the backend flags it for manual triage
        notes.append("Could not match one of the three supported scenarios.")

    matched = _hits(text, SCENARIO_KEYWORDS.get(scenario, ()))
    if matched:
        factors.append({"name": "scenario_keywords", "detail": ", ".join(matched[:5]), "weight": round(min(0.15 * len(matched), 0.45), 2)})

    distress = _hits(text, DISTRESS_KEYWORDS)
    points = URGENCY_POINTS.get(urgency, 0)
    if urgency in URGENCY_POINTS:
        factors.append({"name": "reported_urgency", "detail": urgency, "weight": round(0.1 * points, 2)})
    if people >= 10:
        points += 1
        factors.append({"name": "people_affected", "detail": ">= 10 individuals involved", "weight": 0.4})
    if people >= 50:
        points += 1
    if distress:
        points += min(len(distress), 2)
        factors.append({"name": "stranded_trapped", "detail": "High risk distress keywords detected: " + ", ".join(distress[:4]), "weight": 0.5})

    priority = "CRITICAL" if points >= 4 else "HIGH" if points >= 2 else "MEDIUM" if points >= 1 else "LOW"

    confidence = 0.5 + 0.1 * min(len(matched), 3) + (0.1 if people else 0) + (0.05 if urgency in URGENCY_POINTS else 0)
    if notes:
        confidence -= 0.2
    if scenario == "OTHER":
        confidence = min(confidence, 0.4)

    return {
        "model": MODEL_NAME,
        "scenario": scenario,
        "priority": priority,
        "confidence": round(max(0.05, min(confidence, 0.95)), 3),
        "uncertainty": " ".join(notes) or None,
        "factors": factors,
    }
