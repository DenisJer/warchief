"""Tests for handoff and conductor context."""
from __future__ import annotations

from pathlib import Path

import pytest

from warchief.handoff import (
    create_handoff,
    load_conductor_context,
    save_conductor_context,
)
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestHandoff:
    def test_create_handoff(self, store: TaskStore):
        create_handoff(
            store, from_agent="dev-thrall-1", to_agent="dev-thrall-2",
            task_id="wc-t01",
            context="Working on login. Tests pass. Need to add error handling.",
        )

        mail = store.get_unread_mail("dev-thrall-2")
        assert len(mail) == 1
        assert "HANDOFF" in mail[0].body
        assert "login" in mail[0].body
        assert mail[0].message_type == "HANDOFF"


class TestConductorContext:
    def test_save_and_load(self, tmp_path: Path):
        save_conductor_context(tmp_path, "Planning: 3 tasks remain. Priority: auth.")
        ctx = load_conductor_context(tmp_path)
        assert ctx is not None
        assert "3 tasks remain" in ctx

    def test_overwrite(self, tmp_path: Path):
        save_conductor_context(tmp_path, "v1")
        save_conductor_context(tmp_path, "v2")
        ctx = load_conductor_context(tmp_path)
        assert ctx == "v2"

    def test_history_append(self, tmp_path: Path):
        save_conductor_context(tmp_path, "first")
        save_conductor_context(tmp_path, "second")

        history_path = tmp_path / ".warchief" / "conductor-history.md"
        assert history_path.exists()
        content = history_path.read_text()
        assert "first" in content
        assert "second" in content

    def test_load_nonexistent(self, tmp_path: Path):
        assert load_conductor_context(tmp_path) is None
