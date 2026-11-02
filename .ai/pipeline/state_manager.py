"""DRCH Task State Management.

Persists multi-stage task lifecycle state into `.ai/tasks/<task_id>.json`
with atomic persistence, concurrency task locking, state-machine transition
validation, and structured execution recording.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("drch.ai.state")

# ---------------------------------------------------------------------------
# Task Lifecycle Status Constants
# ---------------------------------------------------------------------------
INITIALIZED = "INITIALIZED"
PLANNING = "PLANNING"
PLAN_READY = "PLAN_READY"
HUMAN_PLAN_APPROVAL = "HUMAN_PLAN_APPROVAL"
IMPLEMENTING = "IMPLEMENTING"
VALIDATING = "VALIDATING"
REVIEWING = "REVIEWING"
READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
COMPLETED = "COMPLETED"

# Explicit failure and pause states
PLAN_FAILED = "PLAN_FAILED"
FAILED_PLANNING = "FAILED_PLANNING"  # Legacy alias
IMPLEMENTATION_FAILED = "IMPLEMENTATION_FAILED"
FAILED_IMPLEMENTATION = "FAILED_IMPLEMENTATION"  # Legacy alias
VALIDATION_FAILED = "VALIDATION_FAILED"
REVIEW_FAILED = "REVIEW_FAILED"
FAILED_REVIEW = "FAILED_REVIEW"  # Legacy alias
REVIEW_REJECTED = "REVIEW_REJECTED"
PAUSED = "PAUSED"
PAUSED_QUOTA_EXHAUSTED = "PAUSED_QUOTA_EXHAUSTED"
FAILED_MODEL_UNAVAILABLE = "FAILED_MODEL_UNAVAILABLE"
FAILED_AUTH = "FAILED_AUTH"
FAILED_CLI_MISSING = "FAILED_CLI_MISSING"
HANDED_OFF_TO_ANTIGRAVITY = "HANDED_OFF_TO_ANTIGRAVITY"
HALTED_BY_USER = "HALTED_BY_USER"

ALL_STATUSES = {
    INITIALIZED,
    PLANNING,
    PLAN_READY,
    HUMAN_PLAN_APPROVAL,
    IMPLEMENTING,
    VALIDATING,
    REVIEWING,
    READY_FOR_HUMAN_REVIEW,
    COMPLETED,
    PLAN_FAILED,
    FAILED_PLANNING,
    IMPLEMENTATION_FAILED,
    FAILED_IMPLEMENTATION,
    VALIDATION_FAILED,
    REVIEW_FAILED,
    FAILED_REVIEW,
    REVIEW_REJECTED,
    PAUSED,
    PAUSED_QUOTA_EXHAUSTED,
    FAILED_MODEL_UNAVAILABLE,
    FAILED_AUTH,
    FAILED_CLI_MISSING,
    HANDED_OFF_TO_ANTIGRAVITY,
    HALTED_BY_USER,
}

# ---------------------------------------------------------------------------
# Strict Transition Rules Matrix
# ---------------------------------------------------------------------------
ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    INITIALIZED: {PLANNING, PAUSED, HALTED_BY_USER},
    PLANNING: {
        PLAN_READY,
        IMPLEMENTING,
        PLAN_FAILED,
        FAILED_PLANNING,
        PAUSED_QUOTA_EXHAUSTED,
        FAILED_MODEL_UNAVAILABLE,
        FAILED_AUTH,
        FAILED_CLI_MISSING,
        HALTED_BY_USER,
        HANDED_OFF_TO_ANTIGRAVITY,
    },
    PLAN_READY: {
        HUMAN_PLAN_APPROVAL,
        IMPLEMENTING,
        HANDED_OFF_TO_ANTIGRAVITY,
        HALTED_BY_USER,
        PLANNING,
    },
    HUMAN_PLAN_APPROVAL: {
        IMPLEMENTING,
        HANDED_OFF_TO_ANTIGRAVITY,
        HALTED_BY_USER,
        PLANNING,
    },
    IMPLEMENTING: {
        VALIDATING,
        IMPLEMENTATION_FAILED,
        FAILED_IMPLEMENTATION,
        PAUSED_QUOTA_EXHAUSTED,
        FAILED_MODEL_UNAVAILABLE,
        FAILED_AUTH,
        FAILED_CLI_MISSING,
        HANDED_OFF_TO_ANTIGRAVITY,
        HALTED_BY_USER,
    },
    VALIDATING: {
        REVIEWING,
        VALIDATION_FAILED,
        READY_FOR_HUMAN_REVIEW,  # when review is skipped by configuration or Antigravity-only mode
    },
    VALIDATION_FAILED: {
        VALIDATING,
        IMPLEMENTING,
        HANDED_OFF_TO_ANTIGRAVITY,
        HALTED_BY_USER,
    },
    REVIEWING: {
        READY_FOR_HUMAN_REVIEW,
        REVIEW_REJECTED,
        REVIEW_FAILED,
        FAILED_REVIEW,
        PAUSED_QUOTA_EXHAUSTED,
        FAILED_MODEL_UNAVAILABLE,
        FAILED_AUTH,
        FAILED_CLI_MISSING,
        HALTED_BY_USER,
    },
    READY_FOR_HUMAN_REVIEW: {
        COMPLETED,
        REVIEWING,
        VALIDATING,
        IMPLEMENTING,
        HALTED_BY_USER,
    },
    REVIEW_REJECTED: {
        IMPLEMENTING,
        VALIDATING,
        HANDED_OFF_TO_ANTIGRAVITY,
        HALTED_BY_USER,
    },
    PAUSED_QUOTA_EXHAUSTED: {
        PLANNING,
        IMPLEMENTING,
        REVIEWING,
        HANDED_OFF_TO_ANTIGRAVITY,
        VALIDATING,
        HALTED_BY_USER,
    },
    HANDED_OFF_TO_ANTIGRAVITY: {
        IMPLEMENTING,
        VALIDATING,
        READY_FOR_HUMAN_REVIEW,
        HALTED_BY_USER,
    },
    HALTED_BY_USER: {
        PLANNING,
        IMPLEMENTING,
        VALIDATING,
        REVIEWING,
        HANDED_OFF_TO_ANTIGRAVITY,
    },
    # Recovery from failures
    PLAN_FAILED: {PLANNING, HALTED_BY_USER},
    FAILED_PLANNING: {PLANNING, HALTED_BY_USER},
    IMPLEMENTATION_FAILED: {IMPLEMENTING, HANDED_OFF_TO_ANTIGRAVITY, VALIDATING, HALTED_BY_USER},
    FAILED_IMPLEMENTATION: {IMPLEMENTING, HANDED_OFF_TO_ANTIGRAVITY, VALIDATING, HALTED_BY_USER},
    REVIEW_FAILED: {REVIEWING, HALTED_BY_USER, READY_FOR_HUMAN_REVIEW},
    FAILED_REVIEW: {REVIEWING, HALTED_BY_USER, READY_FOR_HUMAN_REVIEW},
    FAILED_MODEL_UNAVAILABLE: {PLANNING, IMPLEMENTING, REVIEWING, HANDED_OFF_TO_ANTIGRAVITY, HALTED_BY_USER},
    FAILED_AUTH: {PLANNING, IMPLEMENTING, REVIEWING, HANDED_OFF_TO_ANTIGRAVITY, HALTED_BY_USER},
    FAILED_CLI_MISSING: {PLANNING, IMPLEMENTING, REVIEWING, HANDED_OFF_TO_ANTIGRAVITY, HALTED_BY_USER},
    PAUSED: {PLANNING, IMPLEMENTING, VALIDATING, REVIEWING, HALTED_BY_USER},
    COMPLETED: set(),  # Terminal state
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class InvalidTransition(Exception):
    """Raised when an invalid state transition is attempted."""


class StaleStateError(Exception):
    """Raised when on-disk state does not match the in-memory state."""


class TaskLockError(Exception):
    """Raised when a task lock cannot be acquired."""


class TaskCorruptedError(Exception):
    """Raised when task state file cannot be parsed or is missing required keys."""


@dataclass
class TaskState:
    task_id: str
    task_description: str
    created_at: str
    updated_at: str
    status: str
    stages: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    lock_owner: Optional[str] = None
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskState:
        required = ["task_id", "task_description", "created_at", "updated_at", "status"]
        for req in required:
            if req not in data:
                raise TaskCorruptedError(f"Missing required key in task JSON: {req}")

        return cls(
            task_id=data["task_id"],
            task_description=data["task_description"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            status=data["status"],
            stages=data.get("stages", {}),
            history=data.get("history", []),
            lock_owner=data.get("lock_owner"),
            dry_run=data.get("dry_run", False),
        )


class TaskLock:
    """Exclusive filesystem lock for a task using O_CREAT | O_EXCL."""

    def __init__(self, lock_path: Path, task_id: str):
        self.lock_path = lock_path
        self.task_id = task_id
        self.fd: Optional[int] = None

    def acquire(self) -> None:
        try:
            # O_CREAT | O_EXCL is atomic on POSIX and Windows
            self.fd = os.open(
                str(self.lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            lock_info = {
                "task_id": self.task_id,
                "pid": os.getpid(),
                "acquired_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            os.write(self.fd, json.dumps(lock_info).encode("utf-8"))
        except FileExistsError:
            age_str = "unknown"
            info = {}
            try:
                raw = self.lock_path.read_text(encoding="utf-8")
                info = json.loads(raw)
                acq_time = datetime.datetime.fromisoformat(info["acquired_at"])
                age = (datetime.datetime.now(datetime.timezone.utc) - acq_time).total_seconds()
                age_str = f"{int(age)}s ago by PID {info.get('pid')}"
            except Exception:
                pass
            raise TaskLockError(
                f"Task {self.task_id} is locked ({age_str}). "
                f"If a previous process crashed, manually remove {self.lock_path.name}."
            )

    def release(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None
        if self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove lock file {self.lock_path}: {e}")

    def __enter__(self) -> TaskLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class StateManager:
    def __init__(self, tasks_dir: Path):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def lock_task(self, task_id: str) -> TaskLock:
        """Create a TaskLock context manager for the task."""
        lock_path = self.tasks_dir / f"{task_id}.lock"
        return TaskLock(lock_path=lock_path, task_id=task_id)

    def create_task(self, description: str, dry_run: bool = False) -> TaskState:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        short_id = uuid.uuid4().hex[:6]
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        task_id = f"task_{timestamp}_{short_id}"

        state = TaskState(
            task_id=task_id,
            task_description=description.strip(),
            created_at=now,
            updated_at=now,
            status=INITIALIZED,
            stages={},
            history=[{"timestamp": now, "status": INITIALIZED, "event": "Task created"}],
            dry_run=dry_run,
        )
        self.save_task(state)
        return state

    def save_task(self, state: TaskState) -> Path:
        """Atomically persist task state with fsync and Windows retry handling."""
        state.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        target_path = self.tasks_dir / f"{state.task_id}.json"
        tmp_path = self.tasks_dir / f"{state.task_id}.json.tmp"

        payload = json.dumps(state.to_dict(), indent=2).encode("utf-8")

        try:
            with open(tmp_path, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace with retry for Windows / OneDrive file-locking quirks
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    os.replace(tmp_path, target_path)
                    break
                except PermissionError:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(0.05 * (2**attempt))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

        return target_path

    def load_task(self, task_id: str) -> Optional[TaskState]:
        """Load task state from disk, supporting partial ID matches for convenience."""
        path = self.tasks_dir / f"{task_id}.json"
        if not path.exists():
            candidates = list(self.tasks_dir.glob(f"*{task_id}*.json"))
            if candidates:
                path = candidates[0]
            else:
                return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskState.from_dict(data)
        except json.JSONDecodeError as err:
            raise TaskCorruptedError(f"Task file {path.name} is corrupted JSON: {err}")

    def list_tasks(self) -> List[Dict[str, Any]]:
        tasks = []
        for p in sorted(self.tasks_dir.glob("task_*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                tasks.append({
                    "task_id": data.get("task_id", p.stem),
                    "status": data.get("status", "UNKNOWN"),
                    "created_at": data.get("created_at", ""),
                    "description": data.get("task_description", "")[:60],
                    "dry_run": data.get("dry_run", False),
                })
            except Exception:
                continue
        return tasks

    def transition(
        self, state: TaskState, new_status: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Validate and execute a state machine transition with concurrency checking."""
        meta = metadata or {}
        current = state.status

        # Concurrency safety: Verify on-disk status matches in-memory status
        target_path = self.tasks_dir / f"{state.task_id}.json"
        if target_path.exists():
            try:
                on_disk_data = json.loads(target_path.read_text(encoding="utf-8"))
                on_disk_status = on_disk_data.get("status")
                if on_disk_status and on_disk_status != current:
                    raise StaleStateError(
                        f"Task {state.task_id} was modified externally: on-disk status is "
                        f"'{on_disk_status}', but in-memory state was '{current}'."
                    )
            except (json.JSONDecodeError, KeyError):
                pass

        # Validate transition against rules
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise InvalidTransition(
                f"Invalid state transition from '{current}' to '{new_status}'. "
                f"Allowed transitions from '{current}' are: {sorted(list(allowed))}"
            )

        # Special enforcement for COMPLETED:
        if new_status == COMPLETED:
            if current != READY_FOR_HUMAN_REVIEW:
                raise InvalidTransition(
                    f"A task can only be completed from '{READY_FOR_HUMAN_REVIEW}', got '{current}'."
                )
            if not meta.get("phrase_verified"):
                raise InvalidTransition(
                    "Transition to COMPLETED requires verified human acknowledgment metadata (phrase_verified)."
                )
            if not meta.get("acknowledged_at") or not meta.get("acknowledged_by"):
                raise InvalidTransition(
                    "Transition to COMPLETED requires acknowledged_at and acknowledged_by metadata."
                )

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state.status = new_status
        state.history.append({
            "timestamp": now,
            "status": new_status,
            "metadata": meta,
        })
        self.save_task(state)

    def record_stage(
        self, state: TaskState, stage_name: str, status: str, payload: Dict[str, Any]
    ) -> None:
        """Record stage execution results without mutating task-level status."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state.stages[stage_name] = {
            "completed_at": now,
            "status": status,
            **payload,
        }
        state.history.append({
            "timestamp": now,
            "stage": stage_name,
            "status": status,
        })
        self.save_task(state)

    def record_execution(
        self, state: TaskState, execution_data: Dict[str, Any]
    ) -> Path:
        """Record a structured execution record for Antigravity or Claude implementation."""
        agent = execution_data.get("selected_execution_agent", "antigravity")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "task_id": state.task_id,
            "task_description": state.task_description,
            "completion_timestamp": now,
            **execution_data,
        }

        # Save record in stages and write to reports
        reports_dir = self.tasks_dir.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        record_path = reports_dir / f"{state.task_id}_execution_{agent}.json"
        record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

        self.record_stage(
            state=state,
            stage_name="implementation",
            status="COMPLETED",
            payload={"execution_record_file": str(record_path), "agent": agent},
        )
        return record_path
