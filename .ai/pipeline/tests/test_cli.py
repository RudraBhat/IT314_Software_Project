"""Tests for scripts/ai-dev.py CLI entry point and argument parsing."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CLI_PATH = _REPO_ROOT / "scripts" / "ai-dev.py"


def test_cli_doctor_runs_cleanly():
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), "--doctor"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert proc.returncode == 0
    assert "DRCH AI Orchestration Doctor" in proc.stdout
    assert "All core systems operational" in proc.stdout


def test_cli_check_models_spends_zero_quota():
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), "--check-models"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    assert proc.returncode == 0
    assert "DRCH AI Model Configuration" in proc.stdout
    assert "No API quota was spent" in proc.stdout
    assert "strict reviewer policy" in proc.stdout


def test_cli_config_outputs_json():
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), "--config"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    assert proc.returncode == 0
    assert '"role_models"' in proc.stdout
    assert '"validation_commands"' in proc.stdout


def test_cli_list_tasks():
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), "--list-tasks"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    assert proc.returncode == 0


def test_cli_ack_review_exclusivity():
    # --ack-review cannot be combined with --task
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), "--ack-review", "task_123", "--task", "Some task"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    assert proc.returncode == 2
    assert "cannot be combined" in (proc.stderr + proc.stdout)


def test_cli_handoff_requires_resume():
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), "--handoff"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    assert proc.returncode == 2
    assert "--handoff requires --resume" in (proc.stderr + proc.stdout)

