"""Tests for agent spawner."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.config import Config
from warchief.models import TaskRecord
from warchief.roles import RoleRegistry
from warchief.spawner import _next_agent_id, _WARCHIEFS, build_claude_command
from warchief.task_store import TaskStore


@pytest.fixture
def registry() -> RoleRegistry:
    return RoleRegistry(Path(__file__).parent.parent / "warchief" / "roles")


@pytest.fixture
def config() -> Config:
    return Config(max_total_agents=8, base_branch="main")


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestAgentNaming:
    def test_next_agent_id_format(self):
        agent_id = _next_agent_id("developer")
        assert agent_id.startswith("developer-")
        # Format: role-name-uuid4hex (e.g. developer-thrall-a1b2)
        parts = agent_id.split("-")
        assert len(parts) >= 3
        # The WoW name is between role and UUID suffix
        name_part = parts[1]
        assert name_part in _WARCHIEFS

    def test_sequential_names(self):
        # Reset for deterministic test
        import warchief.spawner as sp
        old_idx = sp._name_index
        sp._name_index = 0

        id1 = _next_agent_id("developer")
        id2 = _next_agent_id("reviewer")
        assert id1 != id2
        assert id1.startswith("developer-")
        assert id2.startswith("reviewer-")

        sp._name_index = old_idx

    def test_wraps_around(self):
        import warchief.spawner as sp
        old_idx = sp._name_index
        sp._name_index = len(_WARCHIEFS) - 1

        id1 = _next_agent_id("dev")
        id2 = _next_agent_id("dev")
        assert id1.startswith("dev-")
        assert id2.startswith("dev-")
        assert id1 != id2

        sp._name_index = old_idx


class TestBuildClaudeCommand:
    def test_basic_command(self, registry: RoleRegistry, config: Config):
        task = TaskRecord(
            id="wc-t01", title="Build login",
            description="Build it well",
            labels=["frontend"], base_branch="main",
        )
        cmd, cwd, _prompt = build_claude_command(
            "developer", registry, task, None, Path("/project"), config,
        )
        assert cmd[0] == "claude"
        assert "--print" in cmd
        assert "--model" in cmd
        assert "--output-format" in cmd

    def test_allowed_tools_included(self, registry: RoleRegistry, config: Config):
        task = TaskRecord(id="wc-t01", title="Test")
        cmd, cwd, _prompt = build_claude_command(
            "developer", registry, task, None, Path("/project"), config,
        )
        assert "--allowedTools" in cmd
        # Developer should have Bash in allowed tools
        idx = [i for i, x in enumerate(cmd) if x == "--allowedTools"]
        tools = [cmd[i + 1] for i in idx]
        assert "Bash" in tools

    def test_worktree_sets_cwd(self, registry: RoleRegistry, config: Config):
        task = TaskRecord(id="wc-t01", title="Test")
        wt = Path("/project/.warchief-worktrees/dev-thrall")
        cmd, cwd, _prompt = build_claude_command(
            "developer", registry, task, wt, Path("/project"), config,
        )
        assert cwd == str(wt)

    def test_config_model_override(self, registry: RoleRegistry):
        config = Config(role_models={"developer": "claude-opus-4-6"})
        task = TaskRecord(id="wc-t01", title="Test")
        cmd, cwd, _prompt = build_claude_command(
            "developer", registry, task, None, Path("/project"), config,
        )
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-opus-4-6"
