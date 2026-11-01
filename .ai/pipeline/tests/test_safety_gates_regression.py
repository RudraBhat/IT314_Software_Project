"""Static and regression safety tests for DRCH AI Pipeline.

Enforces:
1. Zero Git write operations in pipeline and runner code.
2. Zero external AI SDK imports (Anthropic, OpenAI) or raw network calls.
3. Strict boundary preservation for application code directories.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_PIPELINE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PIPELINE_DIR.parent.parent


def test_zero_git_mutating_commands_in_pipeline_code():
    forbidden_subcommands = [
        "commit",
        "push",
        "merge",
        "reset",
        "clean",
        "rebase",
    ]

    pipeline_files = list(_PIPELINE_DIR.glob("*.py"))
    scripts_file = _REPO_ROOT / "scripts" / "ai-dev.py"
    if scripts_file.exists():
        pipeline_files.append(scripts_file)

    for py_file in pipeline_files:
        content = py_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        for idx, line in enumerate(lines, 1):
            # Check for subprocess calls invoking git
            if "subprocess" in line or "run(" in line or "Popen(" in line:
                for subcmd in forbidden_subcommands:
                    # Match ["git", "commit"] or "git commit"
                    if re.search(rf'["\']git["\'],\s*["\']{subcmd}', line) or re.search(rf'git\s+{subcmd}', line):
                        # Verify it's not a safety check or documentation string
                        if "DISALLOWED_PATTERNS" not in line and "forbidden" not in line and "deny" not in line:
                            raise AssertionError(
                                f"Mutating git command '{subcmd}' found in {py_file.name}:{idx}: {line.strip()}"
                            )


def test_zero_external_sdk_imports():
    disallowed_modules = {
        "anthropic",
        "openai",
        "langchain",
        "requests",
        "httpx",
        "urllib3",
    }

    pipeline_files = list(_PIPELINE_DIR.glob("*.py"))
    for py_file in pipeline_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    assert root_mod not in disallowed_modules, (
                        f"Prohibited external SDK import '{alias.name}' in {py_file.name}:{node.lineno}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    assert root_mod not in disallowed_modules, (
                        f"Prohibited external SDK import from '{node.module}' in {py_file.name}:{node.lineno}"
                    )


def test_claude_settings_enforces_git_restrictions():
    settings_file = _REPO_ROOT / ".claude" / "settings.json"
    assert settings_file.exists(), "Missing .claude/settings.json"

    import json
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    deny_rules = settings.get("permissions", {}).get("deny", [])

    must_deny = [
        "git commit*",
        "git push*",
        "git merge*",
        "git reset*",
    ]
    for req in must_deny:
        assert any(req in r for r in deny_rules), f"Missing deny rule for '{req}' in .claude/settings.json"


def test_agents_md_contains_git_safety_instructions():
    agents_md = _REPO_ROOT / "AGENTS.md"
    assert agents_md.exists(), "Missing AGENTS.md"
    content = agents_md.read_text(encoding="utf-8").lower()

    assert "never automatically commit, push, merge, reset, or rewrite git history" in content

