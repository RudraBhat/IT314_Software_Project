"""Tests for human review acknowledgment gate in .ai/pipeline/orchestrator.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.orchestrator import PipelineOrchestrator
from pipeline.state_manager import (
    COMPLETED,
    IMPLEMENTING,
    PLAN_READY,
    PLANNING,
    READY_FOR_HUMAN_REVIEW,
    VALIDATING,
)


def test_ack_review_rejected_without_tty(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("TTY test task")

    with patch("sys.stdin.isatty", return_value=False), \
         patch("sys.stdout.isatty", return_value=False):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is False


def test_ack_review_rejected_for_dry_run(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Dry run ack test", dry_run=True)

    with patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdout.isatty", return_value=True):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is False


def test_ack_review_rejected_when_not_ready_for_review(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Premature ack test")
    orch.state_mgr.transition(state, PLANNING)

    with patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdout.isatty", return_value=True):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is False


def test_ack_review_rejected_if_validation_failed(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Failed val ack test")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    orch.state_mgr.transition(state, VALIDATING)
    orch.state_mgr.transition(state, READY_FOR_HUMAN_REVIEW)

    # validation stage marked passed: False
    orch.state_mgr.record_stage(state, "validation", "FAILED", {"passed": False})

    with patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdout.isatty", return_value=True):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is False


def test_ack_review_rejected_if_review_verdict_rejected(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Review rejected ack test")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    orch.state_mgr.transition(state, VALIDATING)
    orch.state_mgr.transition(state, READY_FOR_HUMAN_REVIEW)

    orch.state_mgr.record_stage(state, "validation", "PASSED", {"passed": True})
    orch.state_mgr.record_stage(state, "review", "COMPLETED", {"verdict": "REJECTED"})

    with patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdout.isatty", return_value=True):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is False


def test_ack_review_rejected_on_diff_drift(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Diff drift test")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    orch.state_mgr.transition(state, VALIDATING)
    orch.state_mgr.transition(state, READY_FOR_HUMAN_REVIEW)

    orch.state_mgr.record_stage(state, "validation", "PASSED", {"passed": True})
    orch.state_mgr.record_stage(
        state,
        "review",
        "COMPLETED",
        {"verdict": "APPROVED", "diff_fingerprint": "original_fingerprint_123"},
    )

    # Current working tree diff returns different fingerprint
    with patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdout.isatty", return_value=True), \
         patch("pipeline.orchestrator.compute_git_diff_fingerprint", return_value="modified_fingerprint_456"):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is False


def test_ack_review_rejected_on_wrong_phrase(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Wrong phrase test")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    orch.state_mgr.transition(state, VALIDATING)
    orch.state_mgr.transition(state, READY_FOR_HUMAN_REVIEW)

    orch.state_mgr.record_stage(state, "validation", "PASSED", {"passed": True})
    orch.state_mgr.record_stage(
        state,
        "review",
        "COMPLETED",
        {"verdict": "APPROVED", "diff_fingerprint": "match_fp"},
    )

    with patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdout.isatty", return_value=True), \
         patch("pipeline.orchestrator.compute_git_diff_fingerprint", return_value="match_fp"), \
         patch("builtins.input", side_effect=["yes", "ok", "wrong phrase"]):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is False

    reloaded = orch.state_mgr.load_task(state.task_id)
    assert reloaded is not None
    assert reloaded.status == READY_FOR_HUMAN_REVIEW


def test_ack_review_succeeds_with_exact_phrase(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Successful ack test")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    orch.state_mgr.transition(state, VALIDATING)
    orch.state_mgr.transition(state, READY_FOR_HUMAN_REVIEW)

    orch.state_mgr.record_stage(state, "validation", "PASSED", {"passed": True})
    orch.state_mgr.record_stage(
        state,
        "review",
        "COMPLETED",
        {"verdict": "APPROVED", "diff_fingerprint": "exact_fp"},
    )

    expected_phrase = f"I have reviewed the diff and reports for {state.task_id}"

    with patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdout.isatty", return_value=True), \
         patch("pipeline.orchestrator.compute_git_diff_fingerprint", return_value="exact_fp"), \
         patch("builtins.input", return_value=expected_phrase), \
         patch("getpass.getuser", return_value="lead_architect"):
        ok = orch.acknowledge_review(state.task_id)
        assert ok is True

    reloaded = orch.state_mgr.load_task(state.task_id)
    assert reloaded is not None
    assert reloaded.status == COMPLETED
    last_event = reloaded.history[-1]
    assert last_event["status"] == COMPLETED
    meta = last_event["metadata"]
    assert meta["phrase_verified"] is True
    assert meta["acknowledged_by"] == "lead_architect"
    assert "acknowledged_at" in meta

