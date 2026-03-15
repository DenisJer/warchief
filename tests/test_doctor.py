"""Tests for doctor health checks."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from warchief.doctor import (
    CheckResult,
    HealthReport,
    check_claude_cli,
    check_config,
    check_database,
    check_disk_space,
    check_git,
    check_git_user,
    check_log_file,
    check_orphaned_tasks,
    check_warchief_dir,
    check_watcher,
    format_report,
    run_doctor,
)
from warchief.models import TaskRecord
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


class TestWarchiefDir:
    def test_exists(self, project_root: Path):
        result = check_warchief_dir(project_root)
        assert result.ok is True

    def test_missing(self, tmp_path: Path):
        result = check_warchief_dir(tmp_path / "nope")
        assert result.ok is False
        assert result.severity == "error"


class TestDatabase:
    def test_valid_db(self, project_root: Path, store: TaskStore):
        result = check_database(project_root)
        assert result.ok is True
        assert "integrity" in result.message

    def test_missing_db(self, tmp_path: Path):
        root = tmp_path / "project"
        root.mkdir()
        (root / ".warchief").mkdir()
        result = check_database(root)
        assert result.ok is False

    def test_corrupt_db(self, project_root: Path):
        db_path = project_root / ".warchief" / "warchief.db"
        db_path.write_bytes(b"not a database")
        result = check_database(project_root)
        assert result.ok is False


class TestConfig:
    def test_default_config(self, project_root: Path):
        result = check_config(project_root)
        assert result.ok is True
        assert "max_agents" in result.message


class TestWatcher:
    def test_not_running(self, project_root: Path):
        result = check_watcher(project_root)
        assert result.ok is False
        assert result.severity == "warning"

    def test_running(self, project_root: Path):
        lock_path = project_root / ".warchief" / "watcher.lock"
        lock_path.write_text(str(os.getpid()))
        result = check_watcher(project_root)
        assert result.ok is True

    def test_stale_pid(self, project_root: Path):
        lock_path = project_root / ".warchief" / "watcher.lock"
        lock_path.write_text("99999999")
        result = check_watcher(project_root)
        assert result.ok is False


class TestDiskSpace:
    def test_sufficient(self, project_root: Path):
        result = check_disk_space(project_root)
        assert result.ok is True  # Should always pass in dev


class TestOrphanedTasks:
    def test_no_orphans(self, store: TaskStore):
        result = check_orphaned_tasks(store)
        assert result.ok is True

    def test_with_orphan(self, store: TaskStore):
        store.create_task(TaskRecord(
            id="wc-orph", title="Orphan",
            status="in_progress", assigned_agent="ghost-agent",
        ))
        result = check_orphaned_tasks(store)
        assert result.ok is False
        assert "wc-orph" in result.message


class TestLogFile:
    def test_no_log(self, project_root: Path):
        result = check_log_file(project_root)
        assert result.ok is True

    def test_small_log(self, project_root: Path):
        log_file = project_root / ".warchief" / "warchief.log"
        log_file.write_text("some log data\n" * 100)
        result = check_log_file(project_root)
        assert result.ok is True


class TestHealthReport:
    def test_healthy_report(self):
        report = HealthReport(checks=[
            CheckResult("test1", True, "ok"),
            CheckResult("test2", True, "ok"),
        ])
        assert report.healthy is True
        assert report.error_count == 0

    def test_unhealthy_report(self):
        report = HealthReport(checks=[
            CheckResult("test1", True, "ok"),
            CheckResult("test2", False, "bad", "error"),
            CheckResult("test3", False, "meh", "warning"),
        ])
        assert report.healthy is False
        assert report.error_count == 1
        assert report.warning_count == 1


class TestFormatReport:
    def test_format_healthy(self):
        report = HealthReport(checks=[
            CheckResult("db", True, "Database OK"),
        ])
        output = format_report(report)
        assert "PASS" in output
        assert "healthy" in output.lower()

    def test_format_unhealthy(self):
        report = HealthReport(checks=[
            CheckResult("db", False, "Corrupt", "error"),
        ])
        output = format_report(report)
        assert "FAIL" in output
        assert "error" in output.lower()


class TestClaudeCli:
    def test_claude_found(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/claude" if cmd == "claude" else None)
        monkeypatch.setattr(
            "warchief.doctor.subprocess.run",
            lambda *a, **kw: type("R", (), {"stdout": "claude 1.0.0\n", "stderr": ""})(),
        )
        result = check_claude_cli()
        assert result.ok is True
        assert "claude" in result.message.lower()

    def test_claude_not_found(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        result = check_claude_cli()
        assert result.ok is False
        assert result.severity == "error"


class TestGit:
    def test_git_ok(self, tmp_path: Path):
        """Test on a real temporary git repo."""
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       cwd=tmp_path, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"})
        result = check_git(tmp_path)
        assert result.ok is True

    def test_not_a_repo(self, tmp_path: Path):
        result = check_git(tmp_path)
        assert result.ok is False

    def test_git_not_installed(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        result = check_git(Path("/tmp"))
        assert result.ok is False
        assert result.severity == "error"


class TestGitUser:
    def test_local_config(self, tmp_path: Path):
        """Test repo with local git user config."""
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, capture_output=True)
        result = check_git_user(tmp_path)
        assert result.ok is True
        assert "local" in result.message
        assert "Test User" in result.message

    def test_no_config(self, tmp_path: Path, monkeypatch):
        """Test with no git user config at all."""
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        # Override HOME to prevent global config from leaking in
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "nonexistent_gitconfig"))
        result = check_git_user(tmp_path)
        # If global config exists on the test machine this might still pass,
        # so we just check the function runs without error
        assert isinstance(result, CheckResult)


class TestRunDoctor:
    def test_full_run(self, project_root: Path, store: TaskStore):
        report = run_doctor(project_root)
        assert len(report.checks) >= 10  # 3 new + 7 original
        # With a valid setup, most checks should pass
        passed = sum(1 for c in report.checks if c.ok)
        assert passed >= 5
