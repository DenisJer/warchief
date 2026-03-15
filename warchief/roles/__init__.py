"""Role registry — loads and queries role definitions from TOML files."""

from __future__ import annotations

import tomllib
from pathlib import Path


class RoleRegistry:
    """Loads all ``.toml`` role definitions from a directory and provides
    convenient accessors for role metadata.

    Usage::

        registry = RoleRegistry(Path("warchief/roles"))
        print(registry.list_roles())
        print(registry.get_model("developer"))
    """

    def __init__(self, roles_dir: Path) -> None:
        self._roles: dict[str, dict] = {}
        self._roles_dir = roles_dir
        self._load(roles_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_role(self, name: str) -> dict:
        """Return the full parsed TOML dict for *name*.

        Raises ``KeyError`` if the role is not found.
        """
        if name not in self._roles:
            raise KeyError(f"Role '{name}' not found. Available: {self.list_roles()}")
        return self._roles[name]

    def list_roles(self) -> list[str]:
        """Return a sorted list of all loaded role names."""
        return sorted(self._roles)

    def get_allowed_tools(self, role_name: str) -> list[str]:
        """Return the list of allowed tools for *role_name*."""
        role = self.get_role(role_name)
        return list(role.get("permissions", {}).get("allowed_tools", []))

    def get_model(self, role_name: str) -> str:
        """Return the default model identifier for *role_name*."""
        role = self.get_role(role_name)
        return str(role.get("model", {}).get("default", ""))

    def get_max_concurrent(self, role_name: str) -> int:
        """Return the maximum number of concurrent agents for *role_name*."""
        role = self.get_role(role_name)
        return int(role.get("identity", {}).get("max_concurrent", 1))

    def get_max_turns(self, role_name: str) -> int | None:
        """Return the max_turns limit for *role_name*, or None if unset."""
        role = self.get_role(role_name)
        val = role.get("model", {}).get("max_turns")
        return int(val) if val is not None else None

    def get_timeout(self, role_name: str) -> int:
        """Return the health-check timeout (seconds) for *role_name*."""
        role = self.get_role(role_name)
        return int(role.get("health", {}).get("timeout_seconds", 3600))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self, roles_dir: Path) -> None:
        if not roles_dir.is_dir():
            return
        for toml_path in sorted(roles_dir.glob("*.toml")):
            with toml_path.open("rb") as fh:
                data = tomllib.load(fh)
            name = data.get("identity", {}).get("name", toml_path.stem)
            self._roles[name] = data
