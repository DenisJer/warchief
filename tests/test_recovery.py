"""Tests for recovery procedures."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from warchief.models import AgentRecord, TaskRecord
from warchief.recovery import (
    recover_orphans,
    recover_zombie_agents,
    recover_worktrees,
    run_full_recovery,
)
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


class TestRecoverOrphans:
    def test_recover_orphaned_task(self, store: TaskStore):
        store.create_task(TaskRecord(
            id="wc-orph", title="Orphan", status="in_progress",
            assigned_agent="dev-ghost",
        ))
        recovered = recover_orphans(store)
        assert "wc-orph" in recovered

        task = store.get_task("wc-orph")
        assert task.status == "open"
        assert task.assigned_agent is None

    def test_no_orphans(self, store: TaskStore):
        store.create_task(TaskRecord(id="wc-ok", title="OK", status="open"))
        recovered = recover_orphans(store)
        assert recovered == []


class TestRecoverZombies:
    @patch("warchief.recovery._is_process_alive", return_value=False)
    def test_recover_dead_agent(self, mock_alive, store: TaskStore, project_root: Path):
        store.register_agent(AgentRecord(
            id="dev-dead", role="developer", status="alive",
            current_task="wc-t01", pid=99999,
        ))
        store.create_task(TaskRecord(
            id="wc-t01", title="Task", status="in_progress",
            assigned_agent="dev-dead",
        ))

        zombies = recover_zombie_agents(store, project_root, threshold=0)
        assert "dev-dead" in zombies

        agent = store.get_agent("dev-dead")
        assert agent.status == "dead"

        task = store.get_task("wc-t01")
        assert task.status == "open"

    @patch("warchief.recovery._is_process_alive", return_value=True)
    @patch("warchief.recovery.is_zombie", return_value=False)
    def test_alive_agent_not_recovered(self, mock_zombie, mock_alive, store, project_root):
        store.register_agent(AgentRecord(
            id="dev-alive", role="developer", status="alive", pid=12345,
        ))
        zombies = recover_zombie_agents(store, project_root)
        assert zombies == []


class TestRecoverWorktrees:
    def test_remove_orphaned_worktree(self, store: TaskStore, project_root: Path):
        wt_dir = project_root / ".warchief-worktrees" / "dev-old"
        wt_dir.mkdir(parents=True)

        # No agent registered for dev-old
        cleaned = recover_worktrees(store, project_root)
        assert "dev-old" in cleaned

    def test_keep_active_worktree(self, store: TaskStore, project_root: Path):
        wt_dir = project_root / ".warchief-worktrees" / "dev-active"
        wt_dir.mkdir(parents=True)

        store.register_agent(AgentRecord(
            id="dev-active", role="developer", status="alive",
        ))

        cleaned = recover_worktrees(store, project_root)
        assert "dev-active" not in cleaned


class TestFullRecovery:
    @patch("warchief.recovery._is_process_alive", return_value=False)
    def test_runs_all(self, mock_alive, store: TaskStore, project_root: Path):
        store.create_task(TaskRecord(
            id="wc-orph2", title="Orphan", status="in_progress",
            assigned_agent="dev-ghost2",
        ))

        summary = run_full_recovery(store, project_root)
        assert "orphaned_tasks" in summary
        assert "zombie_agents" in summary
        assert "cleaned_worktrees" in summary
