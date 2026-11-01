"""DRCH Master AI Pipeline Orchestrator.

Coordinates the multi-stage engineering lifecycle between Google Antigravity (primary)
and Claude Code (optional independent reviewer), with fail-closed validation,
atomic checkpoints, and human-in-the-loop review gating.
"""

from __future__ import annotations

import datetime
import getpass
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .claude_runner import (
    ClaudeFailureKind,
    ClaudeResult,
    detect_claude_cli,
    invoke_claude_detailed,
    resolve_model,
    validate_model_identifier,
)
from .planner import DRCH_CONSTRAINTS, generate_plan
from .reviewer import parse_verdict, run_code_review
from .state_manager import (
    COMPLETED,
    FAILED_AUTH,
    FAILED_CLI_MISSING,
    FAILED_IMPLEMENTATION,
    FAILED_MODEL_UNAVAILABLE,
    FAILED_PLANNING,
    FAILED_REVIEW,
    HANDED_OFF_TO_ANTIGRAVITY,
    HALTED_BY_USER,
    HUMAN_PLAN_APPROVAL,
    IMPLEMENTATION_FAILED,
    IMPLEMENTING,
    INITIALIZED,
    PAUSED,
    PAUSED_QUOTA_EXHAUSTED,
    PLAN_FAILED,
    PLAN_READY,
    PLANNING,
    READY_FOR_HUMAN_REVIEW,
    REVIEW_FAILED,
    REVIEW_REJECTED,
    REVIEWING,
    VALIDATING,
    VALIDATION_FAILED,
    StateManager,
    TaskLockError,
    TaskState,
)
from .validator import execute_validation_checks, get_last_validation_summary

logger = logging.getLogger("drch.ai.orchestrator")


def compute_git_diff_fingerprint(repo_root: Path) -> str:
    """Compute SHA-256 fingerprint of current staged and unstaged git diffs."""
    try:
        p1 = subprocess.run(
            ["git", "diff"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        p2 = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        content = (p1.stdout or "") + "\n---STAGED---\n" + (p2.stdout or "")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    except Exception as e:
        logger.warning(f"Failed to compute git diff fingerprint: {e}")
        return "diff_unavailable"


class PipelineOrchestrator:
    def __init__(self, repo_root: Path, config_path: Optional[Path] = None):
        self.repo_root = repo_root.resolve()
        self.ai_dir = self.repo_root / ".ai"
        self.tasks_dir = self.ai_dir / "tasks"
        self.reports_dir = self.ai_dir / "reports"
        self.handoffs_dir = self.ai_dir / "handoffs"

        self.config_path = config_path or (self.ai_dir / "pipeline" / "config.json")
        self.config = self._load_config()

        self.state_mgr = StateManager(self.tasks_dir)

    def _load_config(self) -> Dict[str, Any]:
        """Load and validate pipeline configuration with hard safety rules."""
        default_config: Dict[str, Any] = {
            "claude_command": ["claude", "-p"],
            "model_aliases": {"opus": "opus", "sonnet": "sonnet"},
            "role_models": {"planner": None, "implementer": None, "reviewer": None},
            "model_fallbacks": {"planner": [], "implementer": []},
            "permission_mode": "default",
            "auto_approve_plan": False,
            "auto_approve_checks": False,
            "max_diff_chars": 50000,
        }

        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                default_config.update(loaded)
            except Exception as e:
                logger.warning(f"Failed to parse config file: {e}")

        # Legacy model mapping
        if "model" in default_config and default_config["model"] is not None:
            legacy_val = default_config["model"]
            if not any(default_config.get("role_models", {}).values()):
                logger.info(f"Mapping legacy 'model' key ({legacy_val}) to all role_models")
                default_config["role_models"] = {
                    "planner": legacy_val,
                    "implementer": legacy_val,
                    "reviewer": legacy_val,
                }

        # Hard safety: Reviewer role NEVER allows fallbacks
        fallbacks = default_config.get("model_fallbacks", {})
        if "reviewer" in fallbacks and fallbacks["reviewer"]:
            logger.warning("Ignoring configured 'reviewer' model fallback: Reviewer fallback is prohibited.")
            fallbacks["reviewer"] = []

        # Validate model identifiers in aliases
        aliases = default_config.get("model_aliases", {})
        for alias_name, model_id in aliases.items():
            if model_id and not validate_model_identifier(model_id):
                logger.warning(f"Invalid model identifier in alias '{alias_name}': {model_id}")

        return default_config

    def check_models(self) -> None:
        """Display model configuration table without performing any network or API calls."""
        print("\n🤖 DRCH AI Model Configuration (Safe Static Analysis)")
        print("=" * 65)
        print(f"{'Role':<15} {'Configured Alias':<20} {'Resolved Identifier':<20} {'Fallback Chain'}")
        print("-" * 65)

        roles = ["planner", "implementer", "reviewer"]
        for role in roles:
            alias_or_raw = (self.config.get("role_models") or {}).get(role) or "(default CLI)"
            resolved = resolve_model(self.config, role) or "(CLI default)"
            fb_chain = (self.config.get("model_fallbacks") or {}).get(role, [])
            fb_str = " -> ".join(fb_chain) if fb_chain else "None"
            if role == "reviewer":
                fb_str = "Disabled (strict reviewer policy)"
            print(f"{role:<15} {str(alias_or_raw):<20} {str(resolved):<20} {fb_str}")

        print("=" * 65)
        print("ℹ️ Note: Availability is confirmed during execution. No API quota was spent.\n")

    def doctor(self) -> bool:
        """Run comprehensive diagnostic checks on the development environment."""
        print("\n🏥 DRCH AI Orchestration Doctor")
        print("=" * 50)
        all_ok = True

        # Python Version
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info >= (3, 11):
            print(f"✅ Python: {py_ver} (>= 3.11)")
        else:
            print(f"❌ Python: {py_ver} (Requires 3.11+)")
            all_ok = False

        # Git
        git_path = shutil.which("git")
        if git_path:
            try:
                proc = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
                print(f"✅ Git: {proc.stdout.strip()}")
            except Exception:
                print(f"✅ Git: {git_path}")
        else:
            print("❌ Git: Not found in PATH")
            all_ok = False

        # Node / npm
        node_path = shutil.which("node")
        if node_path:
            try:
                proc = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
                print(f"✅ Node.js: {proc.stdout.strip()}")
            except Exception:
                print(f"✅ Node.js: {node_path}")
        else:
            print("⚠️ Node.js: Not found in PATH (Frontend checks may be limited)")

        # Claude Code CLI (Optional independent reviewer)
        claude_info = detect_claude_cli()
        if claude_info["installed"]:
            print(f"✅ Claude Code CLI: {claude_info['version']} ({claude_info['path']}) [Optional Reviewer]")
        else:
            print("ℹ️ Claude Code CLI: Not installed (Antigravity operates independently)")

        # Repository Rules
        agents_md = self.repo_root / "AGENTS.md"
        claude_md = self.repo_root / "CLAUDE.md"
        arch_doc = self.repo_root / "docs" / "ARCHITECTURE.md"

        if agents_md.exists():
            print("✅ AGENTS.md: Found")
        else:
            print("❌ AGENTS.md: Missing")
            all_ok = False

        if claude_md.exists():
            print("✅ CLAUDE.md: Found")
        else:
            print("❌ CLAUDE.md: Missing")
            all_ok = False

        if arch_doc.exists():
            print("✅ docs/ARCHITECTURE.md: Found")
        else:
            print("❌ docs/ARCHITECTURE.md: Missing")
            all_ok = False

        # Claude Settings & Git Deny Rules
        claude_settings = self.repo_root / ".claude" / "settings.json"
        if claude_settings.exists():
            try:
                st = json.loads(claude_settings.read_text(encoding="utf-8"))
                deny_rules = st.get("permissions", {}).get("deny", [])
                if any("git commit" in r for r in deny_rules):
                    print(f"✅ Claude Deny Rules: Active ({len(deny_rules)} rules configured)")
                else:
                    print("⚠️ Claude Deny Rules: Missing explicit git deny permissions")
            except Exception:
                print("❌ Claude settings: Invalid JSON")
        else:
            print("❌ .claude/settings.json: Missing")
            all_ok = False

        # Antigravity Rules
        rules_dir = self.repo_root / ".agents" / "rules"
        if rules_dir.exists() and len(list(rules_dir.glob("*.md"))) >= 4:
            print(f"✅ Antigravity Rules: Found {len(list(rules_dir.glob('*.md')))} rules")
        else:
            print("⚠️ Antigravity Rules: Incomplete in .agents/rules/")

        print("=" * 50)
        status_msg = "All core systems operational! 🚀" if all_ok else "Some checks require attention."
        print(f"Status: {status_msg}\n")
        return all_ok

    def list_tasks(self) -> None:
        """Display previous orchestrator tasks and their statuses."""
        tasks = self.state_mgr.list_tasks()
        if not tasks:
            print("No tasks found in `.ai/tasks/`.")
            return

        print(f"\n📋 Registered Tasks ({len(tasks)}):")
        print(f"{'Task ID':<30} {'Status':<25} {'Created At':<22} {'Description'}")
        print("-" * 105)
        for t in tasks:
            print(f"{t['task_id']:<30} {t['status']:<25} {t['created_at'][:19]:<22} {t['description']}")
        print()

    def generate_antigravity_handoff(self, state: TaskState, plan_file: Optional[Path]) -> Path:
        """Generate a handoff document for continuing implementation in Antigravity."""
        self.handoffs_dir.mkdir(parents=True, exist_ok=True)
        handoff_file = self.handoffs_dir / f"{state.task_id}_antigravity_handoff.md"

        plan_ref = plan_file.name if plan_file else f"{state.task_id}_plan.md"
        content = f"""# Antigravity Handoff: {state.task_description}

- **Task ID:** `{state.task_id}`
- **Current Status:** `{state.status}`
- **Implementation Plan:** `.ai/reports/{plan_ref}`

## Instructions for Google Antigravity:
1. Open this repository in Google Antigravity.
2. Review the plan at `.ai/reports/{plan_ref}`.
3. Review `docs/ARCHITECTURE.md` and `AGENTS.md`.
4. Apply the required code changes with minimal, targeted modifications.
5. Respect all DRCH constraints:
   - Neon PostgreSQL 16 + PostGIS only (no Supabase Auth)
   - Application auth, Argon2id & TOTP MFA
   - Append-only SHA-256 hash-chained audit logs
   - Public coordinates rounded to 4 decimals, reporter PII protected
   - Exactly three scenarios: cyclone, industrial_fire, urban_flooding
   - NEVER run git commit or git push
6. After implementation, run:
   ```powershell
   python scripts/ai-dev.py --resume {state.task_id} --step validate
   ```
"""
        handoff_file.write_text(content, encoding="utf-8")
        print(f"  📝 Antigravity handoff instruction created: {handoff_file.relative_to(self.repo_root)}")
        return handoff_file

    def acknowledge_review(self, task_id: str) -> bool:
        """Interactive final human review acknowledgment gate."""
        # Check real interactive terminal
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("❌ Error: Review acknowledgment requires an interactive terminal (TTY).")
            return False

        state = self.state_mgr.load_task(task_id)
        if not state:
            print(f"❌ Error: Task {task_id} not found.")
            return False

        if state.dry_run:
            print("❌ Error: Dry-run simulation tasks cannot be acknowledged as completed.")
            return False

        if state.status != READY_FOR_HUMAN_REVIEW:
            print(f"❌ Error: Task is in state '{state.status}', not '{READY_FOR_HUMAN_REVIEW}'.")
            return False

        # Verify validation record exists and passed with 0 skipped checks
        val_stage = state.stages.get("validation", {})
        if not val_stage.get("passed"):
            print("❌ Error: Validation did not pass completely.")
            return False

        # Verify review stage exists and was not rejected
        rev_stage = state.stages.get("review", {})
        verdict = rev_stage.get("verdict", "").upper()
        if verdict == "REJECTED":
            print("❌ Error: Code review verdict was REJECTED. Fix issues before acknowledging.")
            return False

        # Verify diff fingerprint has not drifted since review
        reviewed_fp = rev_stage.get("diff_fingerprint")
        current_fp = compute_git_diff_fingerprint(self.repo_root)
        if reviewed_fp and current_fp != reviewed_fp:
            print("❌ Error: Working tree has changed since the code review was conducted.")
            print("   Please re-run validation and review before acknowledging.")
            return False

        expected_phrase = f"I have reviewed the diff and reports for {state.task_id}"

        print("\n" + "=" * 65)
        print(f"📋 HUMAN REVIEW ACKNOWLEDGMENT: {state.task_id}")
        print("=" * 65)
        print(f"Task Description: {state.task_description}")
        print(f"Validation Report: .ai/reports/{state.task_id}_validation.md")
        print(f"Review Report:     .ai/reports/{state.task_id}_review.md")
        print(f"Review Verdict:    {verdict or 'APPROVED (VERIFIED)'}")
        print("-" * 65)
        print("To confirm completion and finalize this task, type the exact phrase:")
        print(f"  {expected_phrase}")
        print("-" * 65)

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = input(f"[{attempt + 1}/{max_attempts}] Enter phrase: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n⏹️ Acknowledgment canceled by user.")
                return False

            if response == expected_phrase:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                user = getpass.getuser()
                self.state_mgr.transition(
                    state,
                    COMPLETED,
                    {
                        "acknowledged_at": now,
                        "acknowledged_by": user,
                        "phrase_verified": True,
                    },
                )
                print("\n" + "=" * 65)
                print(f"🎉 Task {state.task_id} successfully COMPLETED!")
                print("=" * 65)
                print("Next Steps:")
                print("1. Review git status and git diff manually.")
                print("2. Commit and push using your standard Git workflow.")
                print("=" * 65 + "\n")
                return True
            else:
                print("  ❌ Phrase did not match. Please try again.")

        print(f"⏹️ Failed {max_attempts} attempts. Task remains in '{READY_FOR_HUMAN_REVIEW}'.")
        return False

    def run(
        self,
        task_description: str,
        dry_run: bool = False,
        resume_task_id: Optional[str] = None,
        target_step: Optional[str] = None,
        agent: str = "antigravity",
    ) -> bool:
        """Execute the end-to-end orchestration workflow."""
        print("\n🚀 DRCH AI Orchestration Pipeline")
        print("=" * 65)
        print(f"Repository: {self.repo_root}")
        print(f"Execution Agent: {agent.upper()}")
        print(f"Mode: {'DRY RUN (Simulation)' if dry_run else 'LIVE EXECUTION'}")

        # Stage 1: Task Initialization / Resumption
        if resume_task_id:
            state = self.state_mgr.load_task(resume_task_id)
            if not state:
                print(f"❌ Error: Task {resume_task_id} not found.")
                return False
            print(f"🔄 Resuming Task: {state.task_id} (Status: {state.status})")
        else:
            state = self.state_mgr.create_task(task_description, dry_run=dry_run)
            print(f"✨ Initialized Task: {state.task_id}")
            print(f"📝 Description: {state.task_description}")

        # Acquire per-task filesystem lock
        try:
            lock = self.state_mgr.lock_task(state.task_id)
            lock.acquire()
        except TaskLockError as err:
            print(f"❌ {err}")
            return False

        try:
            return self._run_lifecycle(state, dry_run, target_step, agent)
        finally:
            lock.release()

    def _run_lifecycle(
        self,
        state: TaskState,
        dry_run: bool,
        target_step: Optional[str],
        agent: str,
    ) -> bool:
        plan_file: Optional[Path] = self.reports_dir / f"{state.task_id}_plan.md"
        planning_already_done = (
            state.stages.get("planning", {}).get("status") == "COMPLETED"
            and plan_file.exists()
        )

        # Stage 2 & 3: Planning
        if not target_step or target_step in ["plan", "all"]:
            if (planning_already_done or state.status != INITIALIZED) and target_step != "plan":
                if plan_file and plan_file.exists():
                    print(f"  ℹ️ Using existing approved plan: {plan_file.relative_to(self.repo_root)}")
            else:
                self.state_mgr.transition(state, PLANNING)
                plan_text, plan_file = generate_plan(
                    task_id=state.task_id,
                    task_description=state.task_description,
                    repo_root=self.repo_root,
                    reports_dir=self.reports_dir,
                    config=self.config,
                    dry_run=dry_run,
                )
                if not plan_file:
                    print("❌ Planning failed.")
                    self.state_mgr.transition(state, PLAN_FAILED)
                    return False

                self.state_mgr.transition(state, PLAN_READY)
                self.state_mgr.record_stage(
                    state=state,
                    stage_name="planning",
                    status="COMPLETED",
                    payload={"plan_file": str(plan_file)},
                )

        # Stage 4: Human Plan Approval Gate
        if state.status == PLAN_READY:
            if not self.config.get("auto_approve_plan", False) and not dry_run:
                self.state_mgr.transition(state, HUMAN_PLAN_APPROVAL)
                print("\n" + "=" * 65)
                print(f"🛑 HUMAN APPROVAL REQUIRED: Implementation Plan ({state.task_id})")
                print(f"   Review the plan at: {self.reports_dir / f'{state.task_id}_plan.md'}")
                print("=" * 65)
                choice = input("Proceed with implementation? [Y/n/handoff]: ").strip().lower()

                if choice == "handoff":
                    handoff_path = self.generate_antigravity_handoff(state, plan_file)
                    self.state_mgr.transition(
                        state, HANDED_OFF_TO_ANTIGRAVITY, {"handoff_file": str(handoff_path)}
                    )
                    print("✅ Handed off to Google Antigravity. Complete code in Antigravity, then run:")
                    print(f"   python scripts/ai-dev.py --resume {state.task_id} --step validate")
                    return True
                elif choice not in ("y", "yes", ""):
                    print("⏹️ Task halted by user.")
                    self.state_mgr.transition(state, HALTED_BY_USER)
                    return False

        # Stage 5: Implementation Execution
        if not target_step or target_step in ["implement", "all"]:
            # Precondition check
            if not planning_already_done and state.status not in (PLAN_READY, HUMAN_PLAN_APPROVAL):
                print(f"❌ Error: Cannot implement task {state.task_id} without an approved plan.")
                return False

            self.state_mgr.transition(state, IMPLEMENTING)

            if agent == "antigravity":
                print(f"\n🛠️ Stage 5: Antigravity Implementation ({state.task_id})")
                print("  ℹ️ Antigravity operates directly in the workspace.")
                handoff_path = self.generate_antigravity_handoff(state, plan_file)
                self.state_mgr.transition(
                    state,
                    HANDED_OFF_TO_ANTIGRAVITY,
                    {"handoff_file": str(handoff_path), "agent": "antigravity"},
                )
                print("  ✅ Workspace prepared for Antigravity.")
                print(f"     Apply code changes according to .ai/reports/{state.task_id}_plan.md")
                print("     When ready, resume the pipeline with:")
                print(f"     python scripts/ai-dev.py --resume {state.task_id} --step validate\n")
                return True

            else:
                # Claude Code execution path
                print(f"\n🛠️ Stage 5: Executing Implementation via Claude Code ({state.task_id})...")
                impl_prompt = f"""You are implementing the approved plan for DRCH.
Task: {state.task_description}
Plan location: .ai/reports/{state.task_id}_plan.md

FULL DRCH REPOSITORY & SECURITY CONSTRAINTS:
{DRCH_CONSTRAINTS}

ADDITIONAL CONSTRAINTS:
- Neon PostgreSQL 16 + PostGIS only (no Supabase Auth or dependencies)
- Application-managed authentication, Argon2id & TOTP MFA
- Append-only SHA-256 hash-chained audit logs with immutable triggers
- Reporter PII protected, public incident coordinates truncated to 4 decimals
- AI triage advisory only; human dispatcher approval required for state changes
- Exactly three supported scenarios: cyclone, industrial_fire, urban_flooding
- Never run git commit, git push, git merge, or git reset

Implement the required code changes now."""

                res = invoke_claude_detailed(
                    prompt=impl_prompt,
                    config=self.config,
                    label=f"Implementation for {state.task_id}",
                    cwd=self.repo_root,
                    role="implementer",
                    dry_run=dry_run,
                )

                if not res.ok:
                    print(f"\n❌ Implementation failed: {res.kind.value if res.kind else 'UNKNOWN'}")
                    if res.kind == ClaudeFailureKind.QUOTA_EXHAUSTED:
                        self.state_mgr.transition(
                            state,
                            PAUSED_QUOTA_EXHAUSTED,
                            {"stage": "implement", "detail": res.detail},
                        )
                        print("  ⏸️ Pipeline PAUSED: Claude subscription quota exhausted.")
                        print("  👉 Option 1: Switch to Antigravity: python scripts/ai-dev.py --resume <id> --handoff")
                        print("  👉 Option 2: Resume later after quota resets.")
                    elif res.kind == ClaudeFailureKind.MODEL_UNAVAILABLE:
                        self.state_mgr.transition(state, FAILED_MODEL_UNAVAILABLE, {"hops": res.fallback_hops})
                    elif res.kind == ClaudeFailureKind.AUTH_REQUIRED:
                        self.state_mgr.transition(state, FAILED_AUTH)
                    elif res.kind == ClaudeFailureKind.CLI_NOT_INSTALLED:
                        self.state_mgr.transition(state, FAILED_CLI_MISSING)
                    else:
                        self.state_mgr.transition(state, IMPLEMENTATION_FAILED, {"detail": res.detail})
                    return False

                self.state_mgr.record_stage(
                    state=state,
                    stage_name="implementation",
                    status="COMPLETED",
                    payload={"result_preview": (res.text or "")[:500], "agent": "claude"},
                )

        # Stage 6: Automated Verification & Validation (Fail-Closed)
        if not target_step or target_step in ["validate", "all"]:
            self.state_mgr.transition(state, VALIDATING)
            passed, val_report = execute_validation_checks(
                task_id=state.task_id,
                repo_root=self.repo_root,
                reports_dir=self.reports_dir,
                dry_run=dry_run,
                prompt_approval=not self.config.get("auto_approve_checks", False) and not dry_run,
            )

            summary = get_last_validation_summary()
            diff_fp = compute_git_diff_fingerprint(self.repo_root)

            if not passed:
                blocking = summary.blocking_reasons if summary else ["validation_failed"]
                print(f"\n❌ Validation failed: {len(blocking)} blocking issue(s).")
                for b in blocking:
                    print(f"   - {b}")
                self.state_mgr.transition(
                    state,
                    VALIDATION_FAILED,
                    {"report_file": str(val_report), "blocking_reasons": blocking},
                )
                print("⏹️ Pipeline stopped. Review stage cannot proceed until validation passes.")
                print(f"   Fix issues, then run: python scripts/ai-dev.py --resume {state.task_id} --step validate\n")
                return False

            self.state_mgr.record_stage(
                state=state,
                stage_name="validation",
                status="PASSED",
                payload={"report_file": str(val_report), "passed": True, "diff_fingerprint": diff_fp},
            )

        # Stage 7: Independent Code Review
        if not target_step or target_step in ["review", "all"]:
            # Precondition: Validation must have passed
            val_stage = state.stages.get("validation", {})
            if not val_stage.get("passed"):
                print("❌ Error: Cannot run code review before validation passes.")
                return False

            self.state_mgr.transition(state, REVIEWING)
            rev_text, rev_file = run_code_review(
                task_id=state.task_id,
                task_description=state.task_description,
                repo_root=self.repo_root,
                reports_dir=self.reports_dir,
                config=self.config,
                dry_run=dry_run,
                role="reviewer",
            )

            if not rev_file or not rev_text:
                print("❌ Code review failed.")
                self.state_mgr.transition(state, REVIEW_FAILED)
                return False

            verdict = parse_verdict(rev_text)
            diff_fp = compute_git_diff_fingerprint(self.repo_root)

            self.state_mgr.record_stage(
                state=state,
                stage_name="review",
                status="COMPLETED",
                payload={
                    "review_file": str(rev_file),
                    "verdict": verdict or "UNKNOWN",
                    "diff_fingerprint": diff_fp,
                },
            )

            if verdict == "REJECTED":
                print("\n❌ Code Review VERDICT: REJECTED")
                print(f"   Inspect findings at: {rev_file.relative_to(self.repo_root)}")
                self.state_mgr.transition(state, REVIEW_REJECTED, {"verdict": "REJECTED"})
                return False

            self.state_mgr.transition(state, READY_FOR_HUMAN_REVIEW, {"verdict": verdict or "APPROVED"})

        # Stage 8: Ready for Human Review
        if state.status == READY_FOR_HUMAN_REVIEW:
            print("\n" + "=" * 65)
            print(f"🏁 Stage 8: READY FOR HUMAN REVIEW ({state.task_id})")
            print("=" * 65)
            print(f"Validation: PASSED ✅ (.ai/reports/{state.task_id}_validation.md)")
            print(f"Review:     COMPLETED ✅ (.ai/reports/{state.task_id}_review.md)")
            print(f"Diff Fingerprint: {compute_git_diff_fingerprint(self.repo_root)}")
            print("-" * 65)
            print("Next Step to Finalize & Complete:")
            print(f"  python scripts/ai-dev.py --ack-review {state.task_id}")
            print("=" * 65 + "\n")
            return True

        return True
