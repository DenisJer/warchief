"""Tests for the daemon."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.daemon import Daemon, daemon_status, stop_daemon


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".warchief").mkdir()
    return root


class TestDaemonStatus:
    def test_not_running(self, project_root: Path):
        status = daemon_status(project_root)
        assert status["running"] is False
        assert status["pid"] is None

    def test_running_with_pid(self, project_root: Path):
        pid_path = project_root / ".warchief" / "daemon.pid"
        pid_path.write_text(str(os.getpid()))

        status = daemon_status(project_root)
        assert status["running"] is True
        assert status["pid"] == os.getpid()

    def test_stale_pid_file(self, project_root: Path):
        pid_path = project_root / ".warchief" / "daemon.pid"
        pid_path.write_text("99999999")

        status = daemon_status(project_root)
        assert status["running"] is False
        assert status["pid"] == 99999999

    def test_with_heartbeat(self, project_root: Path):
        import time
        hb_path = project_root / ".warchief" / "daemon_heartbeat"
        hb_path.write_text(str(time.time()))

        status = daemon_status(project_root)
        assert status["last_heartbeat"] is not None


class TestStopDaemon:
    def test_no_pid_file(self, project_root: Path):
        assert stop_daemon(project_root) is False

    def test_stale_pid(self, project_root: Path):
        pid_path = project_root / ".warchief" / "daemon.pid"
        pid_path.write_text("99999999")

        result = stop_daemon(project_root)
        assert result is False
        # PID file should be cleaned up
        assert not pid_path.exists()


class TestDaemonInit:
    def test_write_pid_file(self, project_root: Path):
        daemon = Daemon(project_root)
        daemon._write_pid_file()

        pid_path = project_root / ".warchief" / "daemon.pid"
        assert pid_path.exists()
        assert int(pid_path.read_text()) == os.getpid()

    def test_write_heartbeat(self, project_root: Path):
        daemon = Daemon(project_root)
        daemon._write_heartbeat()

        hb_path = project_root / ".warchief" / "daemon_heartbeat"
        assert hb_path.exists()

    def test_cleanup(self, project_root: Path):
        daemon = Daemon(project_root)
        daemon._write_pid_file()
        daemon._cleanup()

        pid_path = project_root / ".warchief" / "daemon.pid"
        assert not pid_path.exists()

    @patch("warchief.daemon._is_process_alive", return_value=True)
    def test_ensure_watcher_alive(self, mock_alive, project_root: Path):
        daemon = Daemon(project_root)
        lock_path = project_root / ".warchief" / "watcher.lock"
        lock_path.write_text(str(os.getpid()))

        from warchief.config import Config
        daemon._ensure_watcher(Config())
        # Should not try to start a new watcher

    @patch("warchief.daemon._is_process_alive", return_value=False)
    @patch.object(Daemon, "_start_watcher")
    def test_ensure_watcher_dead_restarts(self, mock_start, mock_alive, project_root):
        daemon = Daemon(project_root)
        lock_path = project_root / ".warchief" / "watcher.lock"
        lock_path.write_text("99999")

        from warchief.config import Config
        daemon._ensure_watcher(Config())
        mock_start.assert_called_once()
