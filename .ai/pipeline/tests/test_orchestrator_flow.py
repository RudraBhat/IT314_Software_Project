"""Tests for end-to-end orchestrator flow, state progression, and safety gating."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.claude_runner import ClaudeResult
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.state_manager import (
    COMPLETED,
    HANDED_OFF_TO_ANTIGRAVITY,
    IMPLEMENTING,
    PLAN_READY,
    PLANNING,
    READY_FOR_HUMAN_REVIEW,
    REVIEW_REJECTED,
    REVIEWING,
    VALIDATING,
    VALIDATION_FAILED,
)


def test_antigravity_primary_mode_flow(tmp_repo: Path, fake_claude):
    fake_claude.set_result(
        ok=True,
        text="## 1. Summary & Scope\nPlan content.\n## 4. Verification\nRun tests.",
    )

    orch = PipelineOrchestrator(tmp_repo)
    success = orch.run(
        task_description="Implement cyclone shelter router",
        dry_run=False,
        agent="antigravity",
    )

    # In antigravity mode, stage 5 generates a handoff and pauses in HANDED_OFF_TO_ANTIGRAVITY
    assert success is True
    tasks = orch.state_mgr.list_tasks()
    assert len(tasks) == 1
    task_id = tasks[0]["task_id"]

    state = orch.state_mgr.load_task(task_id)
    assert state is not None
    assert state.status == HANDED_OFF_TO_ANTIGRAVITY

    handoff_file = tmp_repo / ".ai" / "handoffs" / f"{task_id}_antigravity_handoff.md"
    assert handoff_file.exists()
    content = handoff_file.read_text(encoding="utf-8")
    assert "Disaster Response Coordination Hub" in content or "DRCH" in content
    assert "Neon PostgreSQL 16 + PostGIS" in content


def test_validation_failure_halts_pipeline_and_skips_review(tmp_repo: Path, fake_claude):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Validation test task")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)

    # Mock execute_validation_checks to fail
    with patch("pipeline.orchestrator.execute_validation_checks", return_value=(False, tmp_repo / "val.md")), \
         patch("pipeline.orchestrator.run_code_review") as mock_review:
        success = orch.run(
            task_description="",
            resume_task_id=state.task_id,
            target_step="validate",
            agent="antigravity",
        )
        assert success is False
        mock_review.assert_not_called()

    reloaded = orch.state_mgr.load_task(state.task_id)
    assert reloaded is not None
    assert reloaded.status == VALIDATION_FAILED


def test_review_step_refused_if_validation_not_passed(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Review prerequisite test")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    # Note: validation was NOT run

    with patch("pipeline.orchestrator.run_code_review") as mock_review:
        success = orch.run(
            task_description="",
            resume_task_id=state.task_id,
            target_step="review",
            agent="antigravity",
        )
        assert success is False
        mock_review.assert_not_called()

    reloaded = orch.state_mgr.load_task(state.task_id)
    assert reloaded is not None
    # State remained in IMPLEMENTING since validation prerequisite was missing
    assert reloaded.status == IMPLEMENTING


def test_code_review_rejected_transitions_to_review_rejected(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Reject review task")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    orch.state_mgr.transition(state, VALIDATING)

    # Record validation passed
    report_file = tmp_repo / ".ai" / "reports" / f"{state.task_id}_validation.md"
    report_file.write_text("# Validation Passed", encoding="utf-8")
    orch.state_mgr.record_stage(
        state,
        "validation",
        "PASSED",
        {"report_file": str(report_file), "passed": True, "diff_fingerprint": "abc"},
    )

    rev_file = tmp_repo / ".ai" / "reports" / f"{state.task_id}_review.md"
    rev_file.write_text("# Review\n**Verdict:** REJECTED\nViolation of Supabase rule.", encoding="utf-8")

    with patch("pipeline.orchestrator.run_code_review", return_value=("**Verdict:** REJECTED", rev_file)):
        success = orch.run(
            task_description="",
            resume_task_id=state.task_id,
            target_step="review",
            agent="antigravity",
        )
        assert success is False

    reloaded = orch.state_mgr.load_task(state.task_id)
    assert reloaded is not None
    assert reloaded.status == REVIEW_REJECTED


def test_code_review_approved_transitions_to_ready_for_human_review(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    state = orch.state_mgr.create_task("Approve review task")
    orch.state_mgr.transition(state, PLANNING)
    orch.state_mgr.transition(state, PLAN_READY)
    orch.state_mgr.transition(state, IMPLEMENTING)
    orch.state_mgr.transition(state, VALIDATING)

    # Record validation passed
    report_file = tmp_repo / ".ai" / "reports" / f"{state.task_id}_validation.md"
    report_file.write_text("# Validation Passed", encoding="utf-8")
    orch.state_mgr.record_stage(
        state,
        "validation",
        "PASSED",
        {"report_file": str(report_file), "passed": True, "diff_fingerprint": "abc"},
    )

    rev_file = tmp_repo / ".ai" / "reports" / f"{state.task_id}_review.md"
    rev_file.write_text("# Review\n**Verdict:** APPROVED\nAll rules respected.", encoding="utf-8")

    with patch("pipeline.orchestrator.run_code_review", return_value=("**Verdict:** APPROVED", rev_file)):
        success = orch.run(
            task_description="",
            resume_task_id=state.task_id,
            target_step="review",
            agent="antigravity",
        )
        assert success is True

    reloaded = orch.state_mgr.load_task(state.task_id)
    assert reloaded is not None
    # CRITICAL INVARIANT: Never becomes COMPLETED automatically!
    assert reloaded.status == READY_FOR_HUMAN_REVIEW
    assert reloaded.status != COMPLETED

    reloaded = orch.state_mgr.load_task(state.task_id)
    assert reloaded is not None
    # CRITICAL INVARIANT: Never becomes COMPLETED automatically!
    assert reloaded.status == READY_FOR_HUMAN_REVIEW
    assert reloaded.status != COMPLETED
