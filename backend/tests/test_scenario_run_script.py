"""Unit tests for scripts/scenario_run.py (S3-01, owner Dhruv). No network: only the helpers are checked."""

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scenario_run import REQUIRED_ENV, ScenarioError, expect, missing_env, timeline_matches


def test_every_credential_comes_from_the_environment():
    assert missing_env({}) == list(REQUIRED_ENV)
    full = {name: "x" for name in REQUIRED_ENV}
    assert missing_env(full) == []
    assert "SCENARIO_FIELD_TOTP_SECRET" in REQUIRED_ENV and "SMOKE_STAFF_TOTP_SECRET" in REQUIRED_ENV


def test_timeline_must_follow_the_full_lifecycle_in_order():
    assert timeline_matches(["SUBMITTED", "VERIFIED", "DISPATCHED", "RESOLVED", "CLOSED"])
    assert timeline_matches(["SUBMITTED", "VERIFIED", "DISPATCHED", "DISPATCHED", "RESOLVED", "CLOSED"])
    assert not timeline_matches(["SUBMITTED", "VERIFIED", "CLOSED"])
    assert not timeline_matches(["SUBMITTED", "DISPATCHED", "VERIFIED", "RESOLVED", "CLOSED"])


def test_expect_raises_with_the_step_name_on_a_wrong_status():
    ok = httpx.Response(200, json={"a": 1})
    assert expect(ok, 200, "step") == {"a": 1}
    with pytest.raises(ScenarioError, match="verify: expected HTTP 200, got 409"):
        expect(httpx.Response(409, json={"error": {"code": "STALE_VERSION"}}), 200, "verify")
