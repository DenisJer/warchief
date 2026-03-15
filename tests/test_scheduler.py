"""Tests for the scheduler."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.config import Config
from warchief.models import AgentRecord, TaskRecord
from warchief.roles import RoleRegistry
from warchief.scheduler import Scheduler
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


@pytest.fixture
def config() -> Config:
    return Config(max_total_agents=8, base_branch="main")


@pytest.fixture
def registry() -> RoleRegistry:
    return RoleRegistry(Path(__file__).parent.parent / "warchief" / "roles")


@pytest.fixture
def scheduler(project_root, store, config, registry) -> Scheduler:
    return Scheduler(project_root, store, config, registry)


class TestScheduler:
    def test_create_context(self, scheduler, store):
        store.create_task(TaskRecord(id="wc-s01", title="Sched task"))
        ctx_id = scheduler.create_context("wc-s01", "developer")
        assert ctx_id.startswith("sched-")

    def test_no_pending_returns_zero(self, scheduler):
        assert scheduler.dispatch_pending() == 0

    @patch("warchief.scheduler.spawn_agent")
    @patch("warchief.scheduler.run_preflight", return_value=[])
    def test_dispatch_spawns_agent(self, mock_pf, mock_spawn, scheduler, store):
        mock_spawn.return_value = AgentRecord(
            id="dev-test", role="developer", status="alive",
        )
        store.create_task(TaskRecord(
            id="wc-s02", title="Task", status="open",
        ))
        scheduler.create_context("wc-s02", "developer")

        spawned = scheduler.dispatch_pending()
        assert spawned == 1
        mock_spawn.assert_called_once()

    @patch("warchief.scheduler.spawn_agent")
    @patch("warchief.scheduler.run_preflight", return_value=["error"])
    def test_preflight_fail_skips(self, mock_pf, mock_spawn, scheduler, store):
        store.create_task(TaskRecord(
            id="wc-s03", title="Task", status="open",
        ))
        scheduler.create_context("wc-s03", "developer")

        spawned = scheduler.dispatch_pending()
        assert spawned == 0
        mock_spawn.assert_not_called()

    def test_respects_capacity(self, scheduler, store, config):
        config.max_total_agents = 0  # No slots
        scheduler.config = config

        store.create_task(TaskRecord(id="wc-s04", title="Task", status="open"))
        scheduler.create_context("wc-s04", "developer")

        spawned = scheduler.dispatch_pending()
        assert spawned == 0

    def test_skips_assigned_task(self, scheduler, store):
        store.create_task(TaskRecord(
            id="wc-s05", title="Task", status="open",
            assigned_agent="someone",
        ))
        scheduler.create_context("wc-s05", "developer")

        spawned = scheduler.dispatch_pending()
        assert spawned == 0
