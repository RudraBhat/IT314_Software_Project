"""Tests for planning and review prompt generation and verdict parsing."""

from __future__ import annotations

from pipeline.planner import DRCH_CONSTRAINTS, build_planning_prompt
from pipeline.reviewer import build_review_prompt, parse_verdict


def test_planning_prompt_contains_all_constraints():
    prompt = build_planning_prompt("Implement shelter capacity API", ["backend/routers/shelter.py"])
    assert "Disaster Response Coordination Hub (DRCH)" in prompt
    assert "Neon PostgreSQL 16 + PostGIS" in prompt
    assert "Argon2id" in prompt
    assert "TOTP MFA" in prompt
    assert "SHA-256" in prompt
    assert "cyclone, industrial_fire, urban_flooding" in prompt
    assert "NEVER suggest automated git commit, push" in prompt
    assert "backend/routers/shelter.py" in prompt
    assert "## 1. Summary & Scope" in prompt
    assert "## 2. Affected Modules & Existing Code to Reuse" in prompt
    assert "## 3. Step-by-Step Implementation Steps" in prompt
    assert "## 4. Verification & Testing Strategy" in prompt
    assert "## 5. Security & Risk Analysis" in prompt


def test_review_prompt_contains_all_invariants():
    diff_sample = "diff --git a/routers/shelter.py b/routers/shelter.py\n+new_code"
    prompt = build_review_prompt("Review shelter changes", diff_sample)

    assert "Principal Security & Architecture Reviewer for DRCH" in prompt
    assert "Neon PostgreSQL 16 + PostGIS Compliance" in prompt
    assert "Strictly zero Supabase references" in prompt
    assert "Authentication & Authorization" in prompt
    assert "Append-Only Audit Trail" in prompt
    assert "AI Advisory Boundary" in prompt
    assert "Privacy & PII" in prompt
    assert "Scenario Scope" in prompt
    assert "cyclone, industrial_fire, urban_flooding" in prompt
    assert "Code Cleanliness" in prompt
    assert "Concurrency & Safety" in prompt
    assert "Git Restrictions" in prompt
    assert "diff --git" in prompt
    assert "OUTPUT FORMAT REQUIRED:" in prompt


def test_parse_verdict_approved():
    samples = [
        "## 1. Summary\n- **Verdict:** APPROVED\nLooks good.",
        "- Verdict: APPROVED",
        "**Verdict:** approved",
        "verdict: APPROVED",
    ]
    for s in samples:
        assert parse_verdict(s) == "APPROVED"


def test_parse_verdict_approved_with_comments():
    samples = [
        "- **Verdict:** APPROVED_WITH_COMMENTS\nMinor typo.",
        "Verdict: approved_with_comments",
    ]
    for s in samples:
        assert parse_verdict(s) == "APPROVED_WITH_COMMENTS"


def test_parse_verdict_rejected():
    samples = [
        "## 1. Summary\n- **Verdict:** REJECTED\nViolates PostGIS rule.",
        "- Verdict: REJECTED",
        "**Verdict:** rejected",
    ]
    for s in samples:
        assert parse_verdict(s) == "REJECTED"


def test_parse_verdict_missing_or_invalid():
    assert parse_verdict("") is None
    assert parse_verdict(None) is None  # type: ignore[arg-type]
    assert parse_verdict("This review is pending discussion.") is None
    assert parse_verdict("Verdict: MAYBE") is None

