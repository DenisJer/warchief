"""Tests for the kanban board."""
from __future__ import annotations

from pathlib import Path

import pytest

from warchief.board import render_board
from warchief.models import AgentRecord, TaskRecord
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestBoard:
    def test_empty_board(self, store):
        output = render_board(store, use_rich=False)
        assert "WARCHIEF PIPELINE BOARD" in output

    def test_board_with_tasks(self, store):
        store.create_task(TaskRecord(
            id="wc-b01", title="Build login", status="open",
            stage="development", labels=["stage:development"], priority=5,
        ))
        store.create_task(TaskRecord(
            id="wc-b02", title="Review auth", status="in_progress",
            stage="reviewing", labels=["stage:reviewing"],
        ))
        store.create_task(TaskRecord(
            id="wc-b03", title="Done task", status="closed",
        ))

        output = render_board(store, use_rich=False)
        assert "DEVELOPMENT" in output
        assert "REVIEWING" in output
        assert "wc-b01" in output
        assert "wc-b02" in output
        assert "DONE" in output

    def test_board_with_agents(self, store):
        store.create_task(TaskRecord(
            id="wc-b04", title="Active task", status="in_progress",
            stage="development", assigned_agent="dev-thrall",
        ))
        store.register_agent(AgentRecord(
            id="dev-thrall", role="developer", status="alive",
            current_task="wc-b04",
        ))

        output = render_board(store, use_rich=False)
        assert "dev-thrall" in output

    def test_board_blocked_section(self, store):
        store.create_task(TaskRecord(
            id="wc-b05", title="Blocked task", status="blocked",
        ))

        output = render_board(store, use_rich=False)
        assert "BLOCKED" in output
        assert "wc-b05" in output

    def test_board_backlog(self, store):
        store.create_task(TaskRecord(
            id="wc-b06", title="Backlog task", status="open",
        ))

        output = render_board(store, use_rich=False)
        assert "BACKLOG" in output
