"""DRCH Validation and Test Runner.

Executes automated checks (ruff, pytest, frontend type checks) with fail-closed safety filtering,
captures logs, and generates a structured verification report at
`.ai/reports/<task_id>_validation.md`.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("drch.ai.validator")

# Commands strictly forbidden in the automated validation runner
DISALLOWED_PATTERNS = [
    "commit",
    "push",
    "reset",
    "clean -f",
    "rebase",
    "merge",
    "drop table",
    "truncate",
    "rm -rf",
    "sudo",
]


@dataclass
class ValidationSummary:
    passed: bool
    total_checks: int
    passed_count: int = 0
    failed_count: int = 0
    skipped_unsafe_count: int = 0
    skipped_by_user_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    blocking_reasons: List[str] = field(default_factory=list)


_last_validation_summary: Optional[ValidationSummary] = None


def get_last_validation_summary() -> Optional[ValidationSummary]:
    """Return the summary of the most recently executed validation suite."""
    return _last_validation_summary


def is_safe_command(cmd: str) -> bool:
    """Ensure command contains no mutating or destructive operations."""
    lowered = cmd.lower()
    return not any(disallowed in lowered for disallowed in DISALLOWED_PATTERNS)


def discover_default_checks(repo_root: Path) -> List[Dict[str, str]]:
    """Discover available test and lint commands based on repository contents."""
    checks: List[Dict[str, str]] = []

    # Backend checks
    backend_dir = repo_root / "backend"
    if backend_dir.exists():
        checks.append({
            "name": "Backend Ruff Linter",
            "command": "python -m ruff check backend/",
            "category": "lint",
        })
        # Check if tests directory exists
        if (backend_dir / "tests").exists() or (repo_root / "tests").exists():
            checks.append({
                "name": "Backend Unit Tests",
                "command": "python -m pytest backend/tests/test_units.py -q --disable-warnings",
                "category": "test",
            })

    # Frontend checks
    frontend_dir = repo_root / "frontend"
    if frontend_dir.exists() and (frontend_dir / "package.json").exists():
        checks.append({
            "name": "Frontend Lint",
            "command": "npm run lint --prefix frontend",
            "category": "lint",
        })

    return checks


def execute_validation_checks(
    task_id: str,
    repo_root: Path,
    reports_dir: Path,
    custom_checks: Optional[List[Dict[str, str]]] = None,
    dry_run: bool = False,
    prompt_approval: bool = False,
) -> Tuple[bool, Path]:
    """Run validation checks with strict fail-closed enforcement.

    Any skipped, unsafe, timed out, or failed check immediately invalidates the run.
    """
    global _last_validation_summary
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"{task_id}_validation.md"

    checks_to_run = custom_checks if custom_checks is not None else discover_default_checks(repo_root)

    print(f"\n🧪 Running Validation Suite for {task_id} ({len(checks_to_run)} checks)...")

    results: List[Dict[str, Any]] = []
    blocking_reasons: List[str] = []

    passed_count = 0
    failed_count = 0
    skipped_unsafe_count = 0
    skipped_by_user_count = 0
    timeout_count = 0
    error_count = 0

    if not checks_to_run:
        blocking_reasons.append("no_checks_executed")

    for item in checks_to_run:
        name = item["name"]
        cmd = item["command"]

        # 1. Unsafe Command Check
        if not is_safe_command(cmd):
            print(f"  ⚠️ Skipping unsafe validation command: {cmd}")
            skipped_unsafe_count += 1
            blocking_reasons.append(f"unsafe_command_skipped: {cmd}")
            results.append({
                "name": name,
                "command": cmd,
                "status": "SKIPPED_UNSAFE",
                "returncode": -1,
                "output": "Command blocked by security filter.",
                "duration_seconds": 0.0,
            })
            continue

        # 2. Interactive Approval Prompt
        if prompt_approval:
            try:
                confirm = input(f"  Execute check '{name}' (`{cmd}`)? [Y/n]: ").strip().lower()
                if confirm not in ("y", "yes", ""):
                    print(f"  ⏭️ Skipped '{name}' by user.")
                    skipped_by_user_count += 1
                    blocking_reasons.append(f"check_skipped_by_user: {name}")
                    results.append({
                        "name": name,
                        "command": cmd,
                        "status": "SKIPPED_BY_USER",
                        "returncode": 0,
                        "output": "User skipped check.",
                        "duration_seconds": 0.0,
                    })
                    continue
            except (EOFError, KeyboardInterrupt):
                print(f"\n  ⏭️ Skipped '{name}' (input stream closed).")
                skipped_by_user_count += 1
                blocking_reasons.append(f"check_skipped_by_user: {name}")
                results.append({
                    "name": name,
                    "command": cmd,
                    "status": "SKIPPED_BY_USER",
                    "returncode": 0,
                    "output": "Input stream closed or interrupted.",
                    "duration_seconds": 0.0,
                })
                continue

        # 3. Dry-Run Simulation
        if dry_run:
            print(f"  [DRY RUN] Simulating check: {name} (`{cmd}`)")
            passed_count += 1
            results.append({
                "name": name,
                "command": cmd,
                "status": "PASSED (SIMULATED)",
                "returncode": 0,
                "output": "[Simulated output: 0 errors detected]",
                "duration_seconds": 0.01,
            })
            continue

        # 4. Live Command Execution
        print(f"  ⏳ Running: {name}...")
        start_time = time.time()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
            duration = round(time.time() - start_time, 2)
            passed = proc.returncode == 0
            output = (proc.stdout + "\n" + proc.stderr).strip()

            if passed:
                passed_count += 1
                status_str = "PASSED"
                icon = "✅"
            else:
                failed_count += 1
                blocking_reasons.append(f"check_failed: {name}")
                status_str = "FAILED"
                icon = "❌"

            print(f"  {icon} {name}: {status_str} (code {proc.returncode}, {duration}s)")
            results.append({
                "name": name,
                "command": cmd,
                "status": status_str,
                "returncode": proc.returncode,
                "output": output[:3000],
                "duration_seconds": duration,
            })

        except subprocess.TimeoutExpired:
            timeout_count += 1
            blocking_reasons.append(f"check_timed_out: {name}")
            print(f"  ❌ {name}: TIMED OUT (>180s)")
            results.append({
                "name": name,
                "command": cmd,
                "status": "TIMEOUT",
                "returncode": -1,
                "output": "Command execution timed out after 180 seconds.",
                "duration_seconds": 180.0,
            })

        except Exception as e:
            error_count += 1
            blocking_reasons.append(f"check_error: {name} ({e})")
            print(f"  ❌ {name}: ERROR ({e})")
            results.append({
                "name": name,
                "command": cmd,
                "status": "ERROR",
                "returncode": -1,
                "output": str(e),
                "duration_seconds": 0.0,
            })

    # Fail-closed decision: passed ONLY if blocking_reasons is empty and at least 1 check passed
    all_passed = (len(blocking_reasons) == 0) and (passed_count > 0)

    summary = ValidationSummary(
        passed=all_passed,
        total_checks=len(checks_to_run),
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_unsafe_count=skipped_unsafe_count,
        skipped_by_user_count=skipped_by_user_count,
        timeout_count=timeout_count,
        error_count=error_count,
        blocking_reasons=blocking_reasons,
    )
    _last_validation_summary = summary

    # Generate Markdown Report
    summary_lines = [
        f"# Validation Report: {task_id}",
        "",
        f"- **Overall Result:** {'PASSED ✅' if all_passed else 'FAILED ❌'}",
        f"- **Total Checks:** {len(checks_to_run)}",
        f"- **Execution Mode:** {'Dry Run (Simulated)' if dry_run else 'Live Execution'}",
    ]

    if blocking_reasons:
        summary_lines.append("")
        summary_lines.append("### ⚠️ Blocking Reasons (Fail-Closed Enforcement)")
        for reason in blocking_reasons:
            summary_lines.append(f"- {reason}")

    summary_lines.extend([
        "",
        "## Summary of Checks",
        "",
        "| Check | Command | Status | Duration |",
        "| :--- | :--- | :--- | :--- |",
    ])

    for r in results:
        summary_lines.append(
            f"| {r['name']} | `{r['command']}` | {r['status']} | {r['duration_seconds']}s |"
        )

    summary_lines.append("\n## Detailed Outputs\n")
    for r in results:
        summary_lines.append(f"### {r['name']}\n")
        summary_lines.append(f"- **Command:** `{r['command']}`")
        summary_lines.append(f"- **Exit Code:** {r['returncode']}")
        summary_lines.append("```text")
        summary_lines.append(r["output"] or "(No output)")
        summary_lines.append("```\n")

    report_content = "\n".join(summary_lines)
    report_file.write_text(report_content, encoding="utf-8")
    print(f"  📄 Validation report saved to: {report_file.relative_to(repo_root)}")

    return all_passed, report_file
