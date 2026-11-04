#!/usr/bin/env python3
"""ResQ AI Development Orchestrator CLI.

Unified entry point for managing the AI-assisted software engineering lifecycle:
- Mode A: Independent Google Antigravity (Primary Development Agent)
- Mode B: Independent Claude Code CLI (Optional Independent Reviewer)
- Mode C: Coordinated Local Pipeline

Usage:
    python scripts/ai-dev.py --doctor
    python scripts/ai-dev.py --check-models
    python scripts/ai-dev.py --task "Implement cyclone alert endpoint" --agent antigravity
    python scripts/ai-dev.py --resume task_20261102_123456_a1b2c3 --step validate
    python scripts/ai-dev.py --resume task_20261102_123456_a1b2c3 --handoff
    python scripts/ai-dev.py --ack-review task_20261102_123456_a1b2c3
    python scripts/ai-dev.py --list-tasks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Fix Windows console encoding issues with emojis (type-safe for Pylance/MyPy)
for _stream in (sys.stdout, sys.stderr):
    _reconfig = getattr(_stream, "reconfigure", None)
    if callable(_reconfig):
        try:
            _reconfig(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Ensure .ai is on the Python path for pipeline imports
_REPO_ROOT = Path(__file__).resolve().parent.parent
_AI_PATH = _REPO_ROOT / ".ai"
if str(_AI_PATH) not in sys.path:
    sys.path.insert(0, str(_AI_PATH))

try:
    from pipeline.orchestrator import PipelineOrchestrator  # type: ignore[import-untyped, import-not-found]
except ImportError:
    try:
        import importlib.util

        _orch_file = _AI_PATH / "pipeline" / "orchestrator.py"
        _spec = importlib.util.spec_from_file_location("pipeline.orchestrator", _orch_file)
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules["pipeline.orchestrator"] = _mod
            _spec.loader.exec_module(_mod)
            PipelineOrchestrator = _mod.PipelineOrchestrator
        else:
            raise ImportError(f"Cannot load orchestrator from {_orch_file}")
    except Exception as err:
        print(f"❌ Failed to import orchestrator pipeline: {err}")
        print(f"   Looked in: {_AI_PATH}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ResQ AI Development Orchestrator (Antigravity Primary + Optional Claude Reviewer)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check environment health (Python, Git, Node, Claude CLI, repo rules)",
    )
    parser.add_argument(
        "--check-models",
        action="store_true",
        help="Display model configuration and alias table without spending API quota",
    )
    parser.add_argument(
        "--task",
        type=str,
        help="Description of the task to plan, implement, validate, and review",
    )
    parser.add_argument(
        "--agent",
        choices=["antigravity", "claude"],
        default="antigravity",
        help="Primary execution agent (default: antigravity)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without modifying files or invoking external APIs",
    )
    parser.add_argument(
        "--resume",
        type=str,
        metavar="TASK_ID",
        help="Resume an existing task by its ID or filename prefix",
    )
    parser.add_argument(
        "--step",
        choices=["plan", "implement", "validate", "review", "all"],
        default="all",
        help="Target a specific stage when executing or resuming a task (default: all)",
    )
    parser.add_argument(
        "--handoff",
        action="store_true",
        help="Create Google Antigravity handoff prompt for resumed task (used with --resume)",
    )
    parser.add_argument(
        "--ack-review",
        type=str,
        metavar="TASK_ID",
        help="Acknowledge code review and finalize task (requires interactive TTY and exact phrase)",
    )
    parser.add_argument(
        "--record-impl",
        type=str,
        metavar="TASK_ID",
        help="Record a structured implementation execution record for Antigravity",
    )
    parser.add_argument(
        "--list-tasks",
        action="store_true",
        help="List all previous tasks and their statuses",
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Display the current orchestrator pipeline configuration",
    )

    args = parser.parse_args()

    # Exclusivity and precondition validation
    if args.ack_review:
        if args.task or args.resume or args.dry_run or args.handoff:
            parser.error("--ack-review cannot be combined with --task, --resume, --handoff, or --dry-run.")

    if args.handoff and not args.resume:
        parser.error("--handoff requires --resume <TASK_ID>.")

    orchestrator = PipelineOrchestrator(repo_root=_REPO_ROOT)

    # Dispatch commands
    if args.doctor:
        ok = orchestrator.doctor()
        sys.exit(0 if ok else 1)

    if args.check_models:
        orchestrator.check_models()
        sys.exit(0)

    if args.list_tasks:
        orchestrator.list_tasks()
        sys.exit(0)

    if args.config:
        import json

        print(f"\nConfiguration ({orchestrator.config_path}):")
        print(json.dumps(orchestrator.config, indent=2))
        sys.exit(0)

    if args.ack_review:
        ok = orchestrator.acknowledge_review(args.ack_review)
        sys.exit(0 if ok else 1)

    if args.record_impl:
        task = orchestrator.state_mgr.load_task(args.record_impl)
        if not task:
            print(f"❌ Error: Task {args.record_impl} not found.")
            sys.exit(1)
        rec_path = orchestrator.state_mgr.record_execution(
            task,
            {
                "selected_execution_agent": "antigravity",
                "execution_stage": "implementation",
                "implementation_summary": "Antigravity applied verified code changes to workspace.",
            },
        )
        print(f"✅ Implementation record saved to: {rec_path.relative_to(_REPO_ROOT)}")
        sys.exit(0)

    if args.resume and args.handoff:
        task = orchestrator.state_mgr.load_task(args.resume)
        if not task:
            print(f"❌ Error: Task {args.resume} not found.")
            sys.exit(1)
        plan_f = orchestrator.reports_dir / f"{task.task_id}_plan.md"
        handoff_p = orchestrator.generate_antigravity_handoff(task, plan_f)
        orchestrator.state_mgr.transition(
            task,
            "HANDED_OFF_TO_ANTIGRAVITY",
            {"handoff_file": str(handoff_p), "reason": "human_requested"},
        )
        sys.exit(0)

    if args.resume:
        success = orchestrator.run(
            task_description="",
            dry_run=args.dry_run,
            resume_task_id=args.resume,
            target_step=args.step,
            agent=args.agent,
        )
        sys.exit(0 if success else 1)

    if args.task:
        success = orchestrator.run(
            task_description=args.task,
            dry_run=args.dry_run,
            target_step=args.step,
            agent=args.agent,
        )
        sys.exit(0 if success else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
