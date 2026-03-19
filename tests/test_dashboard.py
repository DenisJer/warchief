"""Tests for dashboard rendering."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from warchief.dashboard import render_dashboard_snapshot, _build_plain_snapshot
from warchief.models import AgentRecord, EventRecord, TaskRecord
from warchief.task_store import TaskStore


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".warchief").mkdir()
    return root


@pytest.fixture
def store(project_root: Path) -> TaskStore:
    s = TaskStore(project_root / ".warchief" / "warchief.db")
    yield s
    s.close()


class TestDashboardSnapshot:
    def test_empty_dashboard(self, project_root: Path, store: TaskStore):
        output = render_dashboard_snapshot(project_root)
        assert "WARCHIEF DASHBOARD" in output
        assert "PIPELINE" in output
        assert "AGENTS" in output

    def test_dashboard_with_tasks(self, project_root: Path, store: TaskStore):
        store.create_task(
            TaskRecord(
                id="wc-d1",
                title="Login page",
                status="in_progress",
                stage="development",
            )
        )
        store.create_task(
            TaskRecord(
                id="wc-d2",
                title="Review auth",
                status="open",
                stage="reviewing",
            )
        )

        output = render_dashboard_snapshot(project_root)
        assert "wc-d1" in output
        assert "wc-d2" in output
        assert "DEVELOPMENT" in output
        assert "REVIEWING" in output

    def test_dashboard_with_agents(self, project_root: Path, store: TaskStore):
        store.register_agent(
            AgentRecord(
                id="developer-thrall",
                role="developer",
                status="alive",
                current_task="wc-a1",
                pid=12345,
                spawned_at=time.time(),
            )
        )

        output = render_dashboard_snapshot(project_root)
        assert "developer-thrall" in output
        assert "developer" in output

    def test_dashboard_with_events(self, project_root: Path, store: TaskStore):
        store.log_event(
            EventRecord(
                event_type="spawn",
                task_id="wc-e1",
                agent_id="developer-thrall",
            )
        )

        output = render_dashboard_snapshot(project_root)
        assert "spawn" in output
        assert "RECENT EVENTS" in output

    def test_dashboard_with_blocked(self, project_root: Path, store: TaskStore):
        store.create_task(
            TaskRecord(
                id="wc-b1",
                title="Stuck task",
                status="blocked",
            )
        )

        output = render_dashboard_snapshot(project_root)
        assert "PROBLEMS" in output
        assert "wc-b1" in output

    def test_dashboard_summary_line(self, project_root: Path, store: TaskStore):
        store.create_task(TaskRecord(id="wc-s1", title="T1", status="open"))
        store.create_task(TaskRecord(id="wc-s2", title="T2", status="closed"))

        output = render_dashboard_snapshot(project_root)
        assert "2 total" in output
        assert "1 open" in output
        assert "1 done" in output


class TestBuildPlainSnapshot:
    def test_internal_builder(self, project_root: Path, store: TaskStore):
        output = _build_plain_snapshot(store, project_root)
        assert isinstance(output, str)
        assert "WARCHIEF DASHBOARD" in output
