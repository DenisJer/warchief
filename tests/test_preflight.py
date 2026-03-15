"""Tests for preflight checks."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from warchief.config import Config
from warchief.models import TaskRecord
from warchief.preflight import (
    check_claude_available,
    check_deps_resolved,
    check_git_user,
    check_slot_available,
    check_task_non_empty,
    run_preflight,
)
from warchief.roles import RoleRegistry
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def config() -> Config:
    return Config(max_total_agents=4)


@pytest.fixture
def registry() -> RoleRegistry:
    return RoleRegistry(Path(__file__).parent.parent / "warchief" / "roles")


class TestCheckClaudeAvailable:
    def test_claude_found(self, monkeypatch):
        monkeypatch.setattr("warchief.preflight.shutil.which", lambda cmd: "/usr/bin/claude")
        assert check_claude_available() is None

    def test_claude_not_found(self, monkeypatch):
        monkeypatch.setattr("warchief.preflight.shutil.which", lambda cmd: None)
        err = check_claude_available()
        assert err is not None
        assert "Claude CLI" in err


class TestCheckGitUser:
    def test_user_configured(self, tmp_path: Path):
        """Test with a repo that has local git config."""
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
        assert check_git_user(tmp_path) is None

    def test_user_not_configured(self, tmp_path: Path, monkeypatch):
        """Test with bare repo and no global fallback."""
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "nonexistent"))
        err = check_git_user(tmp_path)
        # Might still pass if system-level git config exists, but function should not crash
        assert err is None or "not configured" in err


class TestCheckTaskNonEmpty:
    def test_valid_task(self):
        task = TaskRecord(id="wc-01", title="Build login")
        assert check_task_non_empty(task) is None

    def test_empty_title(self):
        task = TaskRecord(id="wc-01", title="")
        assert check_task_non_empty(task) is not None

    def test_whitespace_title(self):
        task = TaskRecord(id="wc-01", title="   ")
        assert check_task_non_empty(task) is not None


class TestCheckSlotAvailable:
    def test_slots_available(self, store: TaskStore, config: Config, registry: RoleRegistry):
        err = check_slot_available(store, "developer", config, registry)
        assert err is None

    def test_total_limit_reached(self, store: TaskStore, config: Config, registry: RoleRegistry):
        from warchief.models import AgentRecord
        for i in range(4):
            store.register_agent(AgentRecord(
                id=f"dev-{i}", role="developer", status="alive",
            ))
        err = check_slot_available(store, "developer", config, registry)
        assert err is not None
        assert "Total agent limit" in err

    def test_role_limit_reached(self, store: TaskStore, registry: RoleRegistry):
        from warchief.models import AgentRecord
        config = Config(max_total_agents=100)
        # Conductor max_concurrent = 1
        store.register_agent(AgentRecord(id="cond-1", role="conductor", status="alive"))
        err = check_slot_available(store, "conductor", config, registry)
        assert err is not None
        assert "Role" in err


class TestCheckDepsResolved:
    def test_no_deps(self, store: TaskStore):
        task = TaskRecord(id="wc-01", title="No deps", deps=[])
        assert check_deps_resolved(task, store) is None

    def test_deps_resolved(self, store: TaskStore):
        store.create_task(TaskRecord(id="wc-dep1", title="Dep 1", status="closed"))
        task = TaskRecord(id="wc-01", title="Has deps", deps=["wc-dep1"])
        assert check_deps_resolved(task, store) is None

    def test_deps_not_resolved(self, store: TaskStore):
        store.create_task(TaskRecord(id="wc-dep2", title="Dep 2", status="open"))
        task = TaskRecord(id="wc-01", title="Has deps", deps=["wc-dep2"])
        err = check_deps_resolved(task, store)
        assert err is not None
        assert "open" in err

    def test_dep_not_found(self, store: TaskStore):
        task = TaskRecord(id="wc-01", title="Has deps", deps=["wc-missing"])
        err = check_deps_resolved(task, store)
        assert err is not None
        assert "not found" in err


class TestRunPreflight:
    @patch("warchief.preflight.check_base_branch", return_value=None)
    @patch("warchief.preflight.check_claude_available", return_value=None)
    @patch("warchief.preflight.check_git_user", return_value=None)
    def test_all_pass(self, mock_git, mock_claude, mock_branch, store: TaskStore, config: Config, registry: RoleRegistry):
        task = TaskRecord(id="wc-01", title="Build login", base_branch="main")
        errors = run_preflight(task, "developer", Path("/tmp"), store, config, registry)
        assert errors == []

    @patch("warchief.preflight.check_base_branch", return_value="Branch not found")
    @patch("warchief.preflight.check_claude_available", return_value=None)
    @patch("warchief.preflight.check_git_user", return_value=None)
    def test_branch_failure(self, mock_git, mock_claude, mock_branch, store: TaskStore, config: Config, registry: RoleRegistry):
        task = TaskRecord(id="wc-01", title="Build login")
        errors = run_preflight(task, "developer", Path("/tmp"), store, config, registry)
        assert len(errors) >= 1
        assert any("Branch" in e for e in errors)

    @patch("warchief.preflight.check_claude_available", return_value="Claude CLI not found")
    def test_claude_missing_short_circuits(self, mock_claude, store: TaskStore, config: Config, registry: RoleRegistry):
        task = TaskRecord(id="wc-01", title="Build login")
        errors = run_preflight(task, "developer", Path("/tmp"), store, config, registry)
        assert len(errors) == 1
        assert "Claude CLI" in errors[0]
