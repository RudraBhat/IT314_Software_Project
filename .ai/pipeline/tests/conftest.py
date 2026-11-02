"""Pytest fixtures for DRCH AI Pipeline test suite.

Ensures that:
1. No real Claude Code CLI commands or external network API calls run.
2. Git commands are strictly monitored and any mutating git commands raise an error.
3. Isolated temporary workspace directories are provided for file-based tests.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# Ensure .ai and repo root are in sys.path
_TESTS_DIR = Path(__file__).resolve().parent
_PIPELINE_DIR = _TESTS_DIR.parent
_AI_DIR = _PIPELINE_DIR.parent
_REPO_ROOT = _AI_DIR.parent

for p in (str(_REPO_ROOT), str(_AI_DIR), str(_PIPELINE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline.claude_runner import ClaudeResult, ClaudeFailureKind


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a fully-structured mock DRCH repository in tmp_path."""
    # Create directories
    (tmp_path / ".ai" / "tasks").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "handoffs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "pipeline").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agents" / "rules").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)

    # Core repo files
    (tmp_path / "AGENTS.md").write_text("# AGENTS\nInspect first.", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE\n@AGENTS.md", encoding="utf-8")
    (tmp_path / "docs" / "ARCHITECTURE.md").write_text("# DRCH Architecture\nNeon PostGIS.", encoding="utf-8")
    (tmp_path / "docs" / "AI_WORKFLOW.md").write_text("# AI Workflow", encoding="utf-8")

    # Antigravity rules
    for rule_name in ("architecture.md", "backend-database.md", "frontend.md", "security.md"):
        (tmp_path / ".agents" / "rules" / rule_name).write_text(f"# Rule {rule_name}", encoding="utf-8")

    # Claude settings
    claude_settings = {
        "permissions": {
            "deny": [
                "git commit*",
                "git push*",
                "git merge*",
                "git reset*",
                "gh pr merge*",
            ]
        }
    }
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(claude_settings), encoding="utf-8")

    # Pipeline config
    config = {
        "claude_command": ["claude", "-p"],
        "model_aliases": {"opus": "opus", "sonnet": "sonnet"},
        "role_models": {"planner": None, "implementer": None, "reviewer": None},
        "model_fallbacks": {"planner": [], "implementer": []},
        "permission_mode": "default",
        "validation_commands": ["python -m pytest backend/tests/test_units.py -v"],
        "max_diff_chars": 50000,
        "auto_approve_plan": True,
        "auto_approve_checks": True,
    }
    (tmp_path / ".ai" / "pipeline" / "config.json").write_text(json.dumps(config), encoding="utf-8")

    # Backend test dummy
    (tmp_path / "backend" / "tests" / "test_units.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    return tmp_path


@pytest.fixture
def git_spy():
    """Spy on subprocess calls to verify NO mutating git commands run."""
    invocations: List[List[str]] = []
    forbidden_subcommands = {"commit", "push", "merge", "reset", "rebase", "clean"}

    real_run = subprocess.run

    def safe_subprocess_run(cmd, *args, **kwargs):
        cmd_list = cmd if isinstance(cmd, list) else cmd.split()
        invocations.append(cmd_list)

        if cmd_list and cmd_list[0] == "git":
            for token in cmd_list[1:]:
                if token in forbidden_subcommands:
                    raise AssertionError(f"Mutating git command attempted in test: {' '.join(cmd_list)}")

        return real_run(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=safe_subprocess_run):
        yield invocations


@pytest.fixture
def fake_claude():
    """Fixture to mock invoke_claude_detailed with scripted responses."""
    class FakeClaudeManager:
        def __init__(self):
            self.calls: List[Dict[str, Any]] = []
            self.next_result: Optional[ClaudeResult] = None
            self.side_effect: Optional[Callable[..., ClaudeResult]] = None

        def set_result(self, ok: bool, text: str = "", kind: Optional[ClaudeFailureKind] = None, returncode: int = 0):
            self.next_result = ClaudeResult(
                ok=ok,
                text=text,
                kind=kind,
                returncode=returncode,
            )

        def __call__(self, *args, **kwargs):
            self.calls.append({"args": args, "kwargs": kwargs})
            if self.side_effect:
                return self.side_effect(*args, **kwargs)
            if self.next_result:
                return self.next_result
            # Default success response
            role = kwargs.get("role", "implementer")
            label = kwargs.get("label", "")
            if "review" in label.lower() or role == "reviewer":
                text = "**Verdict:** APPROVED\n\nAll constraints compliant."
            elif "plan" in label.lower() or role == "planner":
                text = "## 1. Summary & Scope\nPlan content.\n## 4. Verification\nRun tests."
            else:
                text = "Implementation completed successfully."
            return ClaudeResult(ok=True, text=text, returncode=0)

    manager = FakeClaudeManager()
    with patch("pipeline.orchestrator.invoke_claude_detailed", side_effect=manager), \
         patch("pipeline.claude_runner.invoke_claude_detailed", side_effect=manager), \
         patch("pipeline.planner.invoke_claude_detailed", side_effect=manager), \
         patch("pipeline.reviewer.invoke_claude_detailed", side_effect=manager):
        yield manager

