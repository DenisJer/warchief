"""Tests for event feed."""
from __future__ import annotations

from pathlib import Path

import pytest

from warchief.feed import render_feed
from warchief.models import EventRecord
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestFeed:
    def test_empty_feed(self, store: TaskStore):
        output = render_feed(store)
        assert "No events" in output

    def test_feed_with_events(self, store: TaskStore):
        store.log_event(EventRecord(
            event_type="spawn", task_id="wc-01", agent_id="dev-thrall",
        ))
        store.log_event(EventRecord(
            event_type="advance", task_id="wc-01",
            details={"from_stage": "development", "to_stage": "reviewing"},
        ))

        output = render_feed(store)
        assert "Activity Feed" in output
        assert "spawn" in output
        assert "advance" in output
        assert "wc-01" in output

    def test_feed_limit(self, store: TaskStore):
        for i in range(20):
            store.log_event(EventRecord(event_type="heartbeat", task_id=f"wc-{i}"))

        output = render_feed(store, limit=5)
        # Should still render (limit applies to events queried)
        assert "Activity Feed" in output
