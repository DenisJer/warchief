"""Tests for session management."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from warchief.sessions import (
    Session,
    cleanup_stale_sessions,
    deregister_session,
    get_active_sessions,
    get_session,
    list_sessions,
    register_session,
)


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path: Path, monkeypatch):
    """Redirect sessions storage to tmp_path."""
    sessions_dir = tmp_path / "sessions"
    sessions_file = sessions_dir / "sessions.json"
    monkeypatch.setattr("warchief.sessions.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("warchief.sessions.SESSIONS_FILE", sessions_file)


class TestRegister:
    def test_register_new(self, tmp_path: Path):
        project = tmp_path / "myproject"
        project.mkdir()
        session = register_session(project, "My Project")
        assert session.project_name == "My Project"
        assert session.status == "active"
        assert session.pid == os.getpid()

    def test_register_updates_existing(self, tmp_path: Path):
        project = tmp_path / "myproject"
        project.mkdir()
        register_session(project, "v1")
        session = register_session(project, "v2")
        assert session.project_name == "v2"

        # Should not duplicate
        sessions = list_sessions()
        assert len(sessions) == 1

    def test_default_name(self, tmp_path: Path):
        project = tmp_path / "coolproject"
        project.mkdir()
        session = register_session(project)
        assert session.project_name == "coolproject"


class TestDeregister:
    def test_deregister(self, tmp_path: Path):
        project = tmp_path / "myproject"
        project.mkdir()
        register_session(project)
        deregister_session(project)

        session = get_session(project)
        assert session is not None
        assert session.status == "stopped"
        assert session.pid is None


class TestListSessions:
    def test_empty(self):
        assert list_sessions() == []

    def test_multiple(self, tmp_path: Path):
        p1 = tmp_path / "proj1"
        p2 = tmp_path / "proj2"
        p1.mkdir()
        p2.mkdir()
        register_session(p1, "Project 1")
        register_session(p2, "Project 2")
        sessions = list_sessions()
        assert len(sessions) == 2


class TestActiveSessions:
    def test_current_process(self, tmp_path: Path):
        project = tmp_path / "active"
        project.mkdir()
        register_session(project)
        active = get_active_sessions()
        assert len(active) == 1

    def test_dead_process_cleaned(self, tmp_path: Path):
        project = tmp_path / "dead"
        project.mkdir()
        register_session(project)

        # Manually set a dead PID
        sessions = list_sessions()
        sessions[0].pid = 99999999
        from warchief.sessions import _save_sessions
        _save_sessions(sessions)

        active = get_active_sessions()
        assert len(active) == 0

        # Should be marked stopped
        session = get_session(project)
        assert session.status == "stopped"


class TestGetSession:
    def test_found(self, tmp_path: Path):
        project = tmp_path / "found"
        project.mkdir()
        register_session(project, "Found")
        assert get_session(project) is not None

    def test_not_found(self, tmp_path: Path):
        assert get_session(tmp_path / "nope") is None


class TestCleanup:
    def test_removes_stale(self, tmp_path: Path):
        project = tmp_path / "exists"
        project.mkdir()
        register_session(project, "Exists")

        # Manually add a session for nonexistent path
        sessions = list_sessions()
        sessions.append(Session(
            project_root="/nonexistent/path/gone",
            project_name="Gone",
            status="stopped",
        ))
        from warchief.sessions import _save_sessions
        _save_sessions(sessions)

        removed = cleanup_stale_sessions()
        assert removed == 1
        assert len(list_sessions()) == 1
