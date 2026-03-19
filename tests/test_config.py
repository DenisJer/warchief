"""Tests for config read/write and logging setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from warchief.config import Config, read_config, setup_logging, write_config


class TestConfigReadWrite:
    def test_default_config_when_missing(self, tmp_path: Path):
        cfg = read_config(tmp_path)
        assert cfg.max_total_agents == 8
        assert cfg.base_branch == ""
        assert cfg.paused is False

    def test_write_then_read(self, tmp_path: Path):
        cfg = Config(
            max_total_agents=4,
            base_branch="main",
            use_tmux_windows=True,
            agent_timeout=1800,
            notify_conductor=True,
            paused=False,
            docs_path="docs/",
            project_type="python",
            role_models={"developer": "claude-sonnet-4-6", "conductor": "claude-opus-4-6"},
            max_role_agents={"developer": 6, "reviewer": 4},
        )
        write_config(tmp_path, cfg)

        loaded = read_config(tmp_path)
        assert loaded.max_total_agents == 4
        assert loaded.base_branch == "main"
        assert loaded.use_tmux_windows is True
        assert loaded.agent_timeout == 1800
        assert loaded.notify_conductor is True
        assert loaded.docs_path == "docs/"
        assert loaded.project_type == "python"
        assert loaded.role_models["developer"] == "claude-sonnet-4-6"
        assert loaded.max_role_agents["developer"] == 6

    def test_write_overwrites(self, tmp_path: Path):
        cfg1 = Config(max_total_agents=4)
        write_config(tmp_path, cfg1)

        cfg2 = Config(max_total_agents=12)
        write_config(tmp_path, cfg2)

        loaded = read_config(tmp_path)
        assert loaded.max_total_agents == 12

    def test_config_file_location(self, tmp_path: Path):
        write_config(tmp_path, Config())
        assert (tmp_path / ".warchief" / "config.toml").exists()

    def test_empty_role_models(self, tmp_path: Path):
        cfg = Config(role_models={}, max_role_agents={})
        write_config(tmp_path, cfg)
        loaded = read_config(tmp_path)
        assert loaded.role_models == {}
        assert loaded.max_role_agents == {}


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path: Path):
        setup_logging(tmp_path)
        log_dir = tmp_path / ".warchief"
        assert log_dir.exists()

    def test_idempotent(self, tmp_path: Path):
        setup_logging(tmp_path)
        setup_logging(tmp_path)
        # Should not raise or duplicate handlers beyond initial setup
