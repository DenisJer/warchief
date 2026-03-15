"""Tests for prime context generation."""
from __future__ import annotations

from pathlib import Path

import pytest

from warchief.models import EventRecord, TaskRecord
from warchief.prime import build_prime_context
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestBuildPrimeContext:
    def test_empty_for_fresh_task(self, store: TaskStore, tmp_path: Path):
        task = TaskRecord(
            id="wc-t01", title="Build login",
            description="Add OAuth login flow",
            status="open", stage="development",
        )
        store.create_task(task)

        ctx = build_prime_context(task, "developer", store, tmp_path)
        assert ctx == ""  # No history, no deps, no events

    def test_includes_previous_attempts(self, store: TaskStore, tmp_path: Path):
        task = TaskRecord(
            id="wc-t01", title="Build login",
            status="open", spawn_count=2, crash_count=1,
        )
        store.create_task(task)

        ctx = build_prime_context(task, "developer", store, tmp_path)
        assert "2 time(s)" in ctx
        assert "Crashes: 1" in ctx

    def test_includes_deps(self, store: TaskStore, tmp_path: Path):
        store.create_task(TaskRecord(id="wc-dep1", title="Auth module", status="closed"))
        task = TaskRecord(
            id="wc-t01", title="Login page",
            deps=["wc-dep1"], status="open",
        )
        store.create_task(task)

        ctx = build_prime_context(task, "developer", store, tmp_path)
        assert "wc-dep1" in ctx
        assert "Auth module" in ctx
        assert "closed" in ctx

    def test_includes_rejection_events(self, store: TaskStore, tmp_path: Path):
        task = TaskRecord(
            id="wc-t01", title="Login", rejection_count=2, spawn_count=2,
        )
        store.create_task(task)

        store.log_event(EventRecord(
            event_type="block", task_id="wc-t01",
            details={"failure_reason": "Missing error handling"},
        ))

        ctx = build_prime_context(task, "developer", store, tmp_path)
        assert "Missing error handling" in ctx

    def test_includes_previous_agent_logs(self, store: TaskStore, tmp_path: Path):
        task = TaskRecord(id="wc-t01", title="Build login", spawn_count=1)
        store.create_task(task)

        # Create fake agent log and prompt
        logs_dir = tmp_path / ".warchief" / "agent-logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "dev-thrall.log").write_text("Implemented login form\nAll tests pass")
        (logs_dir / "dev-thrall.prompt").write_text("Task wc-t01: Build login")

        ctx = build_prime_context(task, "developer", store, tmp_path)
        assert "dev-thrall" in ctx
        assert "All tests pass" in ctx
