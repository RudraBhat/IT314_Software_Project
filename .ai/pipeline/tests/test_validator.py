"""Tests for automated verification and fail-closed validation in .ai/pipeline/validator.py."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from pipeline.validator import (
    discover_default_checks,
    execute_validation_checks,
    get_last_validation_summary,
    is_safe_command,
)


def test_is_safe_command():
    safe_commands = [
        "python -m pytest backend/tests/test_units.py -v",
        "python -m ruff check backend/",
        "npm run lint --prefix frontend",
        "python -m pytest tests/ -q --disable-warnings",
    ]
    for cmd in safe_commands:
        assert is_safe_command(cmd) is True, f"Expected safe for: {cmd}"

    unsafe_commands = [
        "git commit -m 'danger'",
        "git push origin main",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git rebase origin/main",
        "git merge feature",
        "psql -c 'DROP TABLE incidents;'",
        "psql -c 'TRUNCATE TABLE audit_log;'",
        "rm -rf /var/data",
        "sudo rm something",
    ]
    for cmd in unsafe_commands:
        assert is_safe_command(cmd) is False, f"Expected unsafe for: {cmd}"


def test_discover_default_checks(tmp_repo: Path):
    checks = discover_default_checks(tmp_repo)
    names = [c["name"] for c in checks]
    assert "Backend Ruff Linter" in names
    assert "Backend Unit Tests" in names


def test_execute_validation_all_pass(tmp_repo: Path):
    reports_dir = tmp_repo / ".ai" / "reports"
    custom_checks = [
        {"name": "Check 1", "command": 'python -c "import sys; sys.exit(0)"'},
        {"name": "Check 2", "command": 'python -c "import sys; sys.exit(0)"'},
    ]

    passed, report_path = execute_validation_checks(
        task_id="task_test_val_pass",
        repo_root=tmp_repo,
        reports_dir=reports_dir,
        custom_checks=custom_checks,
        dry_run=False,
    )
    assert passed is True
    assert report_path.exists()
    summary = get_last_validation_summary()
    assert summary is not None
    assert summary.passed is True
    assert summary.passed_count == 2
    assert summary.failed_count == 0
    assert len(summary.blocking_reasons) == 0


def test_execute_validation_fail_closed_on_test_failure(tmp_repo: Path):
    reports_dir = tmp_repo / ".ai" / "reports"
    custom_checks = [
        {"name": "Passing Check", "command": 'python -c "import sys; sys.exit(0)"'},
        {"name": "Failing Check", "command": 'python -c "import sys; sys.exit(1)"'},
    ]

    passed, report_path = execute_validation_checks(
        task_id="task_test_val_fail",
        repo_root=tmp_repo,
        reports_dir=reports_dir,
        custom_checks=custom_checks,
        dry_run=False,
    )
    assert passed is False
    summary = get_last_validation_summary()
    assert summary is not None
    assert summary.passed is False
    assert summary.failed_count == 1
    assert any("check_failed" in r for r in summary.blocking_reasons)


def test_execute_validation_fail_closed_on_unsafe_command(tmp_repo: Path):
    reports_dir = tmp_repo / ".ai" / "reports"
    custom_checks = [
        {"name": "Dangerous Check", "command": "git reset --hard HEAD"},
    ]

    passed, report_path = execute_validation_checks(
        task_id="task_test_val_unsafe",
        repo_root=tmp_repo,
        reports_dir=reports_dir,
        custom_checks=custom_checks,
        dry_run=False,
    )
    assert passed is False
    summary = get_last_validation_summary()
    assert summary is not None
    assert summary.passed is False
    assert summary.skipped_unsafe_count == 1
    assert any("unsafe_command_skipped" in r for r in summary.blocking_reasons)


def test_execute_validation_fail_closed_on_user_skip(tmp_repo: Path):
    reports_dir = tmp_repo / ".ai" / "reports"
    custom_checks = [
        {"name": "Prompted Check", "command": "python -c 'import sys; sys.exit(0)'"},
    ]

    # User answers 'n' to prompt
    with patch("builtins.input", return_value="n"):
        passed, report_path = execute_validation_checks(
            task_id="task_test_val_user_skip",
            repo_root=tmp_repo,
            reports_dir=reports_dir,
            custom_checks=custom_checks,
            dry_run=False,
            prompt_approval=True,
        )

    assert passed is False
    summary = get_last_validation_summary()
    assert summary is not None
    assert summary.passed is False
    assert summary.skipped_by_user_count == 1
    assert any("check_skipped_by_user" in r for r in summary.blocking_reasons)


def test_execute_validation_fail_closed_on_eof_input(tmp_repo: Path):
    reports_dir = tmp_repo / ".ai" / "reports"
    custom_checks = [
        {"name": "Prompted Check", "command": "python -c 'import sys; sys.exit(0)'"},
    ]

    # Input closed unexpectedly (non-interactive pipe)
    with patch("builtins.input", side_effect=EOFError):
        passed, report_path = execute_validation_checks(
            task_id="task_test_val_eof",
            repo_root=tmp_repo,
            reports_dir=reports_dir,
            custom_checks=custom_checks,
            dry_run=False,
            prompt_approval=True,
        )

    assert passed is False
    summary = get_last_validation_summary()
    assert summary is not None
    assert summary.passed is False
    assert summary.skipped_by_user_count == 1


def test_execute_validation_fail_closed_on_no_checks(tmp_repo: Path):
    reports_dir = tmp_repo / ".ai" / "reports"

    passed, report_path = execute_validation_checks(
        task_id="task_test_val_empty",
        repo_root=tmp_repo,
        reports_dir=reports_dir,
        custom_checks=[],
        dry_run=False,
    )
    assert passed is False
    summary = get_last_validation_summary()
    assert summary is not None
    assert summary.passed is False
    assert "no_checks_executed" in summary.blocking_reasons


def test_execute_validation_dry_run(tmp_repo: Path):
    reports_dir = tmp_repo / ".ai" / "reports"
    custom_checks = [
        {"name": "Dry Check", "command": "python -m pytest test.py"},
    ]

    with patch("subprocess.run") as mock_subproc:
        passed, report_path = execute_validation_checks(
            task_id="task_test_val_dry",
            repo_root=tmp_repo,
            reports_dir=reports_dir,
            custom_checks=custom_checks,
            dry_run=True,
        )
        assert passed is True
        mock_subproc.assert_not_called()
