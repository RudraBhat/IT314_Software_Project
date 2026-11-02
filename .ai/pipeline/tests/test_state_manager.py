"""Tests for StateManager and TaskState lifecycle in .ai/pipeline/state_manager.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.state_manager import (
    COMPLETED,
    HUMAN_PLAN_APPROVAL,
    IMPLEMENTING,
    INITIALIZED,
    PLAN_READY,
    PLANNING,
    READY_FOR_HUMAN_REVIEW,
    REVIEWING,
    VALIDATING,
    VALIDATION_FAILED,
    InvalidTransition,
    StaleStateError,
    StateManager,
    TaskCorruptedError,
    TaskLock,
    TaskLockError,
    TaskState,
)


def test_create_and_load_task(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)

    state = mgr.create_task("Test feature implementation")
    assert state.task_id.startswith("task_")
    assert state.status == INITIALIZED
    assert state.task_description == "Test feature implementation"
    assert len(state.history) == 1

    loaded = mgr.load_task(state.task_id)
    assert loaded is not None
    assert loaded.task_id == state.task_id
    assert loaded.status == INITIALIZED
    assert loaded.task_description == state.task_description


def test_valid_lifecycle_transitions(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Full lifecycle task")

    mgr.transition(state, PLANNING)
    assert state.status == PLANNING

    mgr.transition(state, PLAN_READY)
    assert state.status == PLAN_READY

    mgr.transition(state, HUMAN_PLAN_APPROVAL)
    assert state.status == HUMAN_PLAN_APPROVAL

    mgr.transition(state, IMPLEMENTING)
    assert state.status == IMPLEMENTING

    mgr.transition(state, VALIDATING)
    assert state.status == VALIDATING

    mgr.transition(state, REVIEWING)
    assert state.status == REVIEWING

    mgr.transition(state, READY_FOR_HUMAN_REVIEW)
    assert state.status == READY_FOR_HUMAN_REVIEW

    # Complete with required metadata
    mgr.transition(
        state,
        COMPLETED,
        metadata={
            "phrase_verified": True,
            "acknowledged_at": "2026-11-02T12:00:00Z",
            "acknowledged_by": "test_dev",
        },
    )
    assert state.status == COMPLETED
    assert len(state.history) == 9


def test_invalid_transition_rejected(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Direct completion attempt")

    with pytest.raises(InvalidTransition) as exc_info:
        mgr.transition(state, COMPLETED)
    assert "Invalid state transition from 'INITIALIZED' to 'COMPLETED'" in str(exc_info.value)


def test_completed_requires_ready_for_human_review(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Skip stages attempt")
    mgr.transition(state, PLANNING)
    mgr.transition(state, IMPLEMENTING)
    mgr.transition(state, VALIDATING)

    with pytest.raises(InvalidTransition):
        mgr.transition(
            state,
            COMPLETED,
            metadata={"phrase_verified": True, "acknowledged_at": "now", "acknowledged_by": "dev"},
        )


def test_completed_requires_phrase_and_metadata(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Ack validation test")
    mgr.transition(state, PLANNING)
    mgr.transition(state, PLAN_READY)
    mgr.transition(state, IMPLEMENTING)
    mgr.transition(state, VALIDATING)
    mgr.transition(state, REVIEWING)
    mgr.transition(state, READY_FOR_HUMAN_REVIEW)

    # Missing phrase_verified
    with pytest.raises(InvalidTransition) as exc1:
        mgr.transition(state, COMPLETED, metadata={"acknowledged_at": "now", "acknowledged_by": "dev"})
    assert "phrase_verified" in str(exc1.value)

    # Missing acknowledged_by
    with pytest.raises(InvalidTransition) as exc2:
        mgr.transition(state, COMPLETED, metadata={"phrase_verified": True, "acknowledged_at": "now"})
    assert "acknowledged_by" in str(exc2.value)


def test_stale_state_detection(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Concurrency test")

    # Simulate another process changing on-disk status to HALTED_BY_USER
    disk_file = tasks_dir / f"{state.task_id}.json"
    data = json.loads(disk_file.read_text(encoding="utf-8"))
    data["status"] = "HALTED_BY_USER"
    disk_file.write_text(json.dumps(data), encoding="utf-8")

    # Attempting to transition in-memory state (which is INITIALIZED) should detect mismatch
    with pytest.raises(StaleStateError):
        mgr.transition(state, PLANNING)


def test_task_locking_prevents_concurrent_runs(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Lock test")

    lock1 = mgr.lock_task(state.task_id)
    lock1.acquire()

    # Second lock acquisition must raise TaskLockError
    lock2 = mgr.lock_task(state.task_id)
    with pytest.raises(TaskLockError):
        lock2.acquire()

    lock1.release()

    # After release, lock2 can acquire successfully
    lock2.acquire()
    lock2.release()


def test_task_lock_context_manager(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("CM Lock test")

    with mgr.lock_task(state.task_id):
        # Lock exists inside block
        assert (tasks_dir / f"{state.task_id}.lock").exists()

    # Lock removed after block
    assert not (tasks_dir / f"{state.task_id}.lock").exists()


def test_record_stage_preserves_task_status(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Stage test")
    mgr.transition(state, PLANNING)

    mgr.record_stage(state, "plan", "COMPLETED", {"plan_file": "plan.md"})
    assert state.status == PLANNING  # Task status NOT mutated
    assert "plan" in state.stages
    assert state.stages["plan"]["status"] == "COMPLETED"


def test_record_execution(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    mgr = StateManager(tasks_dir)
    state = mgr.create_task("Exec record test")
    mgr.transition(state, PLANNING)
    mgr.transition(state, IMPLEMENTING)

    rec_path = mgr.record_execution(
        state,
        {
            "selected_execution_agent": "antigravity",
            "files_modified": ["backend/routers/alert.py"],
            "test_results": "All tests passed.",
        },
    )
    assert rec_path.exists()
    assert state.stages["implementation"]["status"] == "COMPLETED"
    content = json.loads(rec_path.read_text(encoding="utf-8"))
    assert content["task_id"] == state.task_id
    assert content["selected_execution_agent"] == "antigravity"


def test_corrupted_task_raises_error(tmp_path: Path):
    tasks_dir = tmp_path / ".ai" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    corrupt_file = tasks_dir / "task_corrupt.json"
    corrupt_file.write_text("{not valid json", encoding="utf-8")

    mgr = StateManager(tasks_dir)
    with pytest.raises(TaskCorruptedError):
        mgr.load_task("task_corrupt")

