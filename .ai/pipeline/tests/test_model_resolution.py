"""Tests for model resolution, fallback execution, and static model inspection."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.claude_runner import (
    ClaudeFailureKind,
    ClaudeResult,
    invoke_claude_detailed,
)
from pipeline.orchestrator import PipelineOrchestrator


def test_fallback_hops_on_model_unavailable(tmp_path: Path):
    config = {
        "claude_command": ["claude", "-p"],
        "role_models": {"implementer": "primary-model"},
        "model_fallbacks": {"implementer": ["backup-model"]},
        "permission_mode": "default",
    }

    # Simulate primary model failing with MODEL_UNAVAILABLE, backup succeeding
    calls = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if "--model" in cmd and "primary-model" in cmd:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr="Error: model not found: primary-model",
            )
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="Success with backup model",
            stderr="",
        )

    with patch("shutil.which", return_value="claude"), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        res = invoke_claude_detailed(
            prompt="Do task",
            config=config,
            label="Fallback test",
            cwd=tmp_path,
            role="implementer",
            dry_run=False,
        )

    assert res.ok is True
    assert res.model_used == "backup-model"
    assert len(res.fallback_hops) == 1
    assert res.fallback_hops[0]["from"] == "primary-model"
    assert res.fallback_hops[0]["to"] == "backup-model"
    exec_calls = [c for c in calls if "-p" in c]
    assert len(exec_calls) == 2


def test_reviewer_role_never_falls_back(tmp_path: Path):
    config = {
        "claude_command": ["claude", "-p"],
        "role_models": {"reviewer": "strict-review-model"},
        "model_fallbacks": {"reviewer": ["weaker-model"]},
        "permission_mode": "default",
    }

    calls = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="Error: model not found: strict-review-model",
        )

    with patch("shutil.which", return_value="claude"), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        res = invoke_claude_detailed(
            prompt="Review diff",
            config=config,
            label="Reviewer fallback test",
            cwd=tmp_path,
            role="reviewer",
            dry_run=False,
        )

    assert res.ok is False
    assert res.kind == ClaudeFailureKind.MODEL_UNAVAILABLE
    exec_calls = [c for c in calls if "-p" in c]
    assert len(exec_calls) == 1  # Only 1 attempt, zero fallback hops
    assert len(res.fallback_hops) == 0


def test_quota_exhausted_stops_immediately_without_fallback(tmp_path: Path):
    config = {
        "claude_command": ["claude", "-p"],
        "role_models": {"implementer": "primary-model"},
        "model_fallbacks": {"implementer": ["backup-model"]},
        "permission_mode": "default",
    }

    calls = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="Error: Credit balance is too low.",
        )

    with patch("shutil.which", return_value="claude"), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        res = invoke_claude_detailed(
            prompt="Do task",
            config=config,
            label="Quota stop test",
            cwd=tmp_path,
            role="implementer",
            dry_run=False,
        )

    assert res.ok is False
    assert res.kind == ClaudeFailureKind.QUOTA_EXHAUSTED
    exec_calls = [c for c in calls if "-p" in c]
    assert len(exec_calls) == 1  # Absolutely NO fallbacks or retries on quota
    assert len(res.fallback_hops) == 0


def test_dry_run_invokes_zero_subprocesses(tmp_path: Path):
    config = {"role_models": {"implementer": "sonnet"}}

    with patch("subprocess.run") as mock_subproc:
        res = invoke_claude_detailed(
            prompt="Do task",
            config=config,
            label="Dry run test",
            cwd=tmp_path,
            role="implementer",
            dry_run=True,
        )
        assert res.ok is True
        mock_subproc.assert_not_called()


def test_check_models_invokes_zero_subprocesses(tmp_repo: Path, capsys):
    orch = PipelineOrchestrator(tmp_repo)

    with patch("subprocess.run") as mock_subproc:
        orch.check_models()
        mock_subproc.assert_not_called()

    captured = capsys.readouterr()
    assert "DRCH AI Model Configuration" in captured.out
    assert "No API quota was spent" in captured.out
