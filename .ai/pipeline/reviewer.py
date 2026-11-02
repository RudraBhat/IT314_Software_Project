"""DRCH Automated Code Reviewer.

Extracts the current git diff, verifies changes against DRCH architecture
and security constraints using Claude Code, and writes a structured review
report to `.ai/reports/<task_id>_review.md`.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .claude_runner import invoke_claude_detailed
from .planner import DRCH_CONSTRAINTS

logger = logging.getLogger("drch.ai.reviewer")


def extract_git_diff(repo_root: Path, max_lines: int = 1200) -> str:
    """Extract both working tree and staged diffs from git."""
    try:
        proc_unstaged = subprocess.run(
            ["git", "diff"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        proc_staged = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )

        staged_out = (proc_staged.stdout or "").strip()
        unstaged_out = (proc_unstaged.stdout or "").strip()

        diff = ""
        if staged_out:
            diff += "=== STAGED CHANGES ===\n" + staged_out + "\n\n"
        if unstaged_out:
            diff += "=== UNSTAGED CHANGES ===\n" + unstaged_out + "\n"

        if not diff.strip():
            # Check untracked files
            proc_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            untracked = (proc_status.stdout or "").strip()
            if untracked:
                diff = f"=== UNTRACKED FILES ONLY ===\n{untracked}\n"

        lines = diff.splitlines()
        if len(lines) > max_lines:
            truncated = "\n".join(lines[:max_lines])
            return f"{truncated}\n\n... [Diff truncated: {len(lines) - max_lines} more lines]"
        return diff
    except Exception as e:
        logger.error(f"Failed to capture git diff: {e}")
        return f"[Error retrieving git diff: {e}]"


def parse_verdict(review_text: str) -> Optional[str]:
    """Parse verdict from code review markdown text."""
    if not review_text:
        return None
    # Search for '**Verdict:** APPROVED' or 'Verdict: REJECTED'
    match = re.search(
        r"\*{0,2}Verdict:\*{0,2}\s*(APPROVED_WITH_COMMENTS|APPROVED|REJECTED)",
        review_text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()
    return None


def build_review_prompt(task_description: str, diff_text: str) -> str:
    """Build the code review prompt evaluating changes against DRCH constraints."""
    return f"""You are the Principal Security & Architecture Reviewer for DRCH.
Review the following code diff for compliance with repository standards.

TASK UNDER REVIEW:
{task_description}

GIT DIFF:
```diff
{diff_text or "No git changes detected."}
```

CORE ARCHITECTURE & SECURITY CONSTRAINTS:
{DRCH_CONSTRAINTS}

ADDITIONAL REVIEW INVARIANTS:
1. Neon PostgreSQL 16 + PostGIS Compliance: Strictly zero Supabase references (no `auth.users`, `auth.uid()`, Supabase SDK).
2. Authentication & Authorization: Preserves Argon2id password hashing, TOTP MFA, and session revocation.
3. Append-Only Audit Trail: Verifies SHA-256 hash chaining is preserved with trigger-enforced immutability.
4. AI Advisory Boundary: Ensures AI outputs are strictly advisory (`triage_results`); human dispatcher approval required for state transitions.
5. Privacy & PII: Reporter PII protected; public incident coordinates truncated to 4 decimal places.
6. Scenario Scope: Exactly three supported disaster scenarios (`cyclone`, `industrial_fire`, `urban_flooding`).
7. Code Cleanliness: Zero redundant or duplicate files; minimal targeted modifications.
8. Concurrency & Safety: Atomic transactions, proper locking, no race conditions.
9. Git Restrictions: Strictly NO automated `git commit`, `git push`, `git merge`, `git reset`, `git clean`, or `git rebase`.

OUTPUT FORMAT REQUIRED:
# Code Review: {task_description}

## 1. Executive Summary & Verdict
- **Verdict:** [APPROVED | APPROVED_WITH_COMMENTS | REJECTED]
- **Summary:** Concise summary of the changes and quality.

## 2. DRCH Architecture & Security Compliance
- **Neon PostGIS:** [COMPLIANT / VIOLATION]
- **Auth & RBAC:** [COMPLIANT / VIOLATION]
- **Audit Immutability:** [COMPLIANT / VIOLATION]
- **PII & Privacy:** [COMPLIANT / VIOLATION]
- **Scenario Scope:** [COMPLIANT / VIOLATION]
- **AI Advisory Boundary:** [COMPLIANT / VIOLATION]

## 3. Specific Findings
Categorize findings by severity:
- **Critical:** Blocking bugs or security holes.
- **Major:** Deviations from architecture or error handling flaws.
- **Minor / Suggestions:** Code cleanliness or documentation improvements.

## 4. Verification Recommendations
What tests or manual checks should be run before merging?
"""


def run_code_review(
    task_id: str,
    task_description: str,
    repo_root: Path,
    reports_dir: Path,
    config: Dict[str, Any],
    dry_run: bool = False,
    role: str = "reviewer",
) -> Tuple[Optional[str], Optional[Path]]:
    """Execute code review on current diff and write `.ai/reports/<task_id>_review.md`."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    review_file = reports_dir / f"{task_id}_review.md"

    diff_text = extract_git_diff(repo_root)
    prompt = build_review_prompt(task_description, diff_text)

    print("  🧐 Extracting git diff and initiating automated code review...")

    # Role reviewer has NO fallback by hard policy
    result = invoke_claude_detailed(
        prompt=prompt,
        config=config,
        label=f"Code Review for {task_id}",
        cwd=repo_root,
        role=role,
        dry_run=dry_run,
    )

    if not result.ok or not result.text:
        # Hard rule: If review call fails, no review file is written
        return None, None

    review_file.write_text(result.text, encoding="utf-8")
    print(f"  ✅ Code review saved to: {review_file.relative_to(repo_root)}")
    return result.text, review_file
