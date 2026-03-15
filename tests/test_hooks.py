"""Tests for hook installation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from warchief.hooks import install_agent_hooks


class TestHookInstallation:
    def test_creates_hook_script(self, tmp_path: Path):
        install_agent_hooks(tmp_path, "dev-thrall", "wc-001", "developer", "/tmp/db")

        hooks_dir = tmp_path / ".claude" / "hooks"
        assert (hooks_dir / "verify_task_updated.py").exists()

    def test_script_is_executable(self, tmp_path: Path):
        import os
        install_agent_hooks(tmp_path, "dev-thrall", "wc-001", "developer", "/tmp/db")

        hook = tmp_path / ".claude" / "hooks" / "verify_task_updated.py"
        assert os.access(hook, os.X_OK)

    def test_creates_settings_json(self, tmp_path: Path):
        install_agent_hooks(tmp_path, "dev-thrall", "wc-001", "developer", "/tmp/db")

        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()

        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]

    def test_preserves_existing_settings(self, tmp_path: Path):
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"existing_key": "value"}))

        install_agent_hooks(tmp_path, "dev-thrall", "wc-001", "developer", "/tmp/db")

        settings = json.loads(settings_path.read_text())
        assert settings["existing_key"] == "value"
        assert "hooks" in settings

    def test_idempotent(self, tmp_path: Path):
        install_agent_hooks(tmp_path, "dev-thrall", "wc-001", "developer", "/tmp/db")
        install_agent_hooks(tmp_path, "dev-thrall", "wc-001", "developer", "/tmp/db")

        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert len(settings["hooks"]["Stop"]) == 1


class TestVerifyTaskScript:
    def test_script_is_valid_python(self, tmp_path: Path):
        install_agent_hooks(tmp_path, "dev-thrall", "wc-001", "developer", "/tmp/db")
        script = (tmp_path / ".claude" / "hooks" / "verify_task_updated.py").read_text()
        compile(script, "<test>", "exec")  # Raises SyntaxError if invalid
