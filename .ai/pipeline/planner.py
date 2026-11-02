"""DRCH Implementation Planner.

Scans the repository structure and context, generates an architecture-compliant
implementation plan using Claude Code or generates an Antigravity handoff prompt,
and saves the plan to `.ai/reports/<task_id>_plan.md`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .claude_runner import invoke_claude_detailed

logger = logging.getLogger("drch.ai.planner")

# Directories and patterns to exclude during context scans
EXCLUDE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
    ".tasks",
    ".reports",
    ".handoffs",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyd",
    ".so",
    ".dll",
    ".exe",
    ".iso",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
}

# Baseline DRCH Constraints shared across planner, reviewer, and orchestrator
DRCH_CONSTRAINTS = """1. Neon PostgreSQL 16 + PostGIS: Strictly no Supabase Auth, auth.users, or Supabase SQL.
2. Application-Managed Auth: Argon2id password hashing, TOTP MFA, and session revocation.
3. Audit Logging: SHA-256 hash-chained append-only logs with immutable triggers.
4. AI Boundaries: Advisory triage only; human dispatch approval strictly required.
5. Privacy: Reporter PII protected, public incident coordinates truncated to 4 decimals.
6. Disaster Scope: Exactly 3 disaster scenarios (cyclone, industrial_fire, urban_flooding).
7. Git Safety: NEVER suggest automated git commit, push, or history rewriting.
8. Reuse Existing Code: Do not duplicate existing services, models, schemas, or UI components."""


def scan_repository_context(repo_root: Path, max_files: int = 120) -> List[str]:
    """Scan key repository files for context while filtering binaries and noise."""
    discovered: List[str] = []
    for path in repo_root.rglob("*"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.is_file():
            if path.suffix.lower() in EXCLUDE_EXTENSIONS:
                continue
            if path.name.startswith(".env"):
                continue
            rel = str(path.relative_to(repo_root)).replace("\\", "/")
            discovered.append(rel)
            if len(discovered) >= max_files:
                break
    return sorted(discovered)


def build_planning_prompt(task_description: str, context_files: List[str]) -> str:
    """Build a comprehensive, constraint-aware prompt for generating an implementation plan."""
    key_files_sample = "\n".join(f"- {f}" for f in context_files[:50])

    return f"""You are the Lead Architect for the Disaster Response Coordination Hub (DRCH).
Produce a detailed, production-grade Implementation Plan for the following task:

TASK:
{task_description}

TECHNICAL CONSTRAINTS & REPOSITORY RULES:
{DRCH_CONSTRAINTS}

REPOSITORY STRUCTURE OVERVIEW:
{key_files_sample}

OUTPUT STRUCTURE REQUIRED:
# Implementation Plan: {task_description}

## 1. Summary & Scope
High-level summary of the required change and expected behavior.

## 2. Affected Modules & Existing Code to Reuse
Identify existing FastAPI routers, SQLAlchemy models, Pydantic schemas, or React components to reuse.

## 3. Step-by-Step Implementation Steps
Precise, sequential steps for implementing the changes without breaking existing contracts.

## 4. Verification & Testing Strategy
List relevant pytest suites, ruff lint checks, or manual API verification steps.

## 5. Security & Risk Analysis
Potential regressions, concurrency considerations, or RBAC implications.
"""


def generate_plan(
    task_id: str,
    task_description: str,
    repo_root: Path,
    reports_dir: Path,
    config: Dict[str, Any],
    dry_run: bool = False,
    role: str = "planner",
) -> Tuple[Optional[str], Optional[Path]]:
    """Generate an implementation plan and write it to `.ai/reports/<task_id>_plan.md`."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    plan_file = reports_dir / f"{task_id}_plan.md"

    context_files = scan_repository_context(repo_root)
    prompt = build_planning_prompt(task_description, context_files)

    print(f"  🔍 Scanning repo context ({len(context_files)} files identified)...")
    print("  📋 Generating architecture-compliant implementation plan...")

    result = invoke_claude_detailed(
        prompt=prompt,
        config=config,
        label=f"Plan Generation for {task_id}",
        cwd=repo_root,
        role=role,
        dry_run=dry_run,
    )

    if not result.ok or not result.text:
        return None, None

    plan_file.write_text(result.text, encoding="utf-8")
    print(f"  ✅ Plan saved to: {plan_file.relative_to(repo_root)}")
    return result.text, plan_file
