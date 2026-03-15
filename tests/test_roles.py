"""Tests for RoleRegistry."""
from __future__ import annotations

from pathlib import Path

import pytest

from warchief.roles import RoleRegistry


@pytest.fixture
def registry() -> RoleRegistry:
    roles_dir = Path(__file__).parent.parent / "warchief" / "roles"
    return RoleRegistry(roles_dir)


class TestRoleRegistry:
    def test_loads_all_roles(self, registry: RoleRegistry):
        roles = registry.list_roles()
        assert "conductor" in roles
        assert "developer" in roles
        assert "reviewer" in roles
        assert "integrator" in roles
        assert "tester" in roles
        assert "security_reviewer" in roles
        assert "pr_creator" in roles
        assert "investigator" in roles
        assert "challenger" in roles

    def test_get_role(self, registry: RoleRegistry):
        role = registry.get_role("conductor")
        assert role["identity"]["name"] == "conductor"

    def test_get_model(self, registry: RoleRegistry):
        model = registry.get_model("conductor")
        assert "opus" in model.lower() or "claude" in model.lower()

    def test_get_allowed_tools(self, registry: RoleRegistry):
        tools = registry.get_allowed_tools("conductor")
        assert "Bash" in tools
        assert "Read" in tools

    def test_get_max_concurrent(self, registry: RoleRegistry):
        assert registry.get_max_concurrent("conductor") == 1
        assert registry.get_max_concurrent("developer") >= 1

    def test_get_timeout(self, registry: RoleRegistry):
        timeout = registry.get_timeout("conductor")
        assert timeout > 0

    def test_unknown_role_raises(self, registry: RoleRegistry):
        with pytest.raises(KeyError, match="not found"):
            registry.get_role("warlock")

    def test_empty_dir(self, tmp_path: Path):
        registry = RoleRegistry(tmp_path)
        assert registry.list_roles() == []

    def test_nonexistent_dir(self, tmp_path: Path):
        registry = RoleRegistry(tmp_path / "nope")
        assert registry.list_roles() == []
