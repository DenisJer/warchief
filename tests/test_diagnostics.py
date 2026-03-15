"""Tests for diagnostics."""
from __future__ import annotations

from pathlib import Path

import pytest

from warchief.diagnostics import (
    format_failure_report,
    get_agent_log,
    get_recent_failures,
    tail_log,
)
from warchief.models import EventRecord, TaskRecord
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestRecentFailures:
    def test_no_failures(self, store: TaskStore):
        failures = get_recent_failures(store)
        assert failures == []

    def test_finds_crashes(self, store: TaskStore):
        store.create_task(TaskRecord(id="wc-f1", title="Crashed task"))
        store.log_event(EventRecord(
            event_type="crash", task_id="wc-f1", agent_id="dev-thrall",
            details={"exit_code": 1},
        ))

        failures = get_recent_failures(store)
        assert len(failures) == 1
        assert failures[0]["event_type"] == "crash"
        assert failures[0]["task_title"] == "Crashed task"

    def test_finds_blocks(self, store: TaskStore):
        store.create_task(TaskRecord(id="wc-f2", title="Blocked"))
        store.log_event(EventRecord(
            event_type="block", task_id="wc-f2",
            details={"failure_reason": "Too many rejections"},
        ))

        failures = get_recent_failures(store)
        assert len(failures) == 1

    def test_limit(self, store: TaskStore):
        for i in range(10):
            store.log_event(EventRecord(
                event_type="crash", task_id=f"wc-{i}",
            ))

        failures = get_recent_failures(store, limit=3)
        assert len(failures) == 3


class TestFormatReport:
    def test_empty(self):
        assert "No recent failures" in format_failure_report([])

    def test_formatted(self):
        failures = [{
            "event_type": "crash",
            "task_id": "wc-f1",
            "task_title": "Login page",
            "agent_id": "dev-thrall",
            "details": {"exit_code": 1},
            "timestamp": 1234567890,
            "actor": "watcher",
        }]
        report = format_failure_report(failures)
        assert "CRASH" in report
        assert "wc-f1" in report
        assert "dev-thrall" in report


class TestTailLog:
    def test_no_log(self, tmp_path: Path):
        result = tail_log(tmp_path)
        assert "No log file" in result

    def test_reads_tail(self, tmp_path: Path):
        log_dir = tmp_path / ".warchief"
        log_dir.mkdir()
        log_file = log_dir / "warchief.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(100)))

        result = tail_log(tmp_path, lines=10)
        lines = result.splitlines()
        assert len(lines) == 10
        assert "line 99" in lines[-1]


class TestAgentLog:
    def test_empty(self, store: TaskStore):
        entries = get_agent_log(store, "dev-nobody")
        assert entries == []

    def test_filters_by_agent(self, store: TaskStore):
        store.log_event(EventRecord(event_type="spawn", agent_id="dev-a", task_id="wc-1"))
        store.log_event(EventRecord(event_type="spawn", agent_id="dev-b", task_id="wc-2"))

        entries = get_agent_log(store, "dev-a")
        assert len(entries) == 1
        assert entries[0]["task_id"] == "wc-1"
