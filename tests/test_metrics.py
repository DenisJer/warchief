"""Tests for metrics computation."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from warchief.metrics import (
    compute_pipeline_metrics,
    compute_task_trace,
    format_duration,
)
from warchief.models import EventRecord, TaskRecord
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestFormatDuration:
    def test_seconds(self):
        assert format_duration(30) == "30s"

    def test_minutes(self):
        assert format_duration(150) == "2.5m"

    def test_hours(self):
        assert format_duration(7200) == "2.0h"


class TestPipelineMetrics:
    def test_empty_pipeline(self, store):
        m = compute_pipeline_metrics(store)
        assert m.total_tasks == 0
        assert m.open_tasks == 0

    def test_counts(self, store):
        store.create_task(TaskRecord(id="wc-1", title="T1", status="open"))
        store.create_task(TaskRecord(id="wc-2", title="T2", status="in_progress", spawn_count=2))
        store.create_task(TaskRecord(id="wc-3", title="T3", status="blocked", rejection_count=1))
        store.create_task(TaskRecord(id="wc-4", title="T4", status="closed"))

        m = compute_pipeline_metrics(store)
        assert m.total_tasks == 4
        assert m.open_tasks == 1
        assert m.in_progress_tasks == 1
        assert m.blocked_tasks == 1
        assert m.closed_tasks == 1
        assert m.total_agents_spawned == 2
        assert m.total_rejections == 1

    def test_avg_completion_time(self, store):
        now = time.time()
        store.create_task(
            TaskRecord(
                id="wc-fast",
                title="Fast",
                status="closed",
                created_at=now - 100,
                closed_at=now,
            )
        )
        # Need to manually set closed_at since create_task overrides created_at
        store._conn.execute(
            "UPDATE tasks SET closed_at = ?, created_at = ? WHERE id = ?",
            (now, now - 100, "wc-fast"),
        )
        store._conn.commit()

        m = compute_pipeline_metrics(store)
        assert m.avg_completion_time > 0


class TestTaskTrace:
    def test_nonexistent_task(self, store):
        assert compute_task_trace(store, "wc-nope") is None

    def test_simple_trace(self, store):
        store.create_task(TaskRecord(id="wc-t01", title="Traced"))

        now = time.time()
        store.log_event(
            EventRecord(
                event_type="spawn",
                task_id="wc-t01",
                details={"stage": "development"},
                created_at=now - 300,
            )
        )
        store.log_event(
            EventRecord(
                event_type="advance",
                task_id="wc-t01",
                details={"from_stage": "development", "to_stage": "reviewing"},
                created_at=now - 200,
            )
        )
        store.log_event(
            EventRecord(
                event_type="advance",
                task_id="wc-t01",
                details={"from_stage": "reviewing", "to_stage": "pr-creation"},
                created_at=now - 100,
            )
        )

        trace = compute_task_trace(store, "wc-t01")
        assert trace is not None
        assert trace.task_id == "wc-t01"
        assert len(trace.stages) >= 2
        assert trace.total_duration > 0

    def test_trace_with_rejections(self, store):
        store.create_task(TaskRecord(id="wc-t02", title="Rejected"))
        store.log_event(
            EventRecord(
                event_type="reject",
                task_id="wc-t02",
            )
        )
        store.log_event(
            EventRecord(
                event_type="reject",
                task_id="wc-t02",
            )
        )

        trace = compute_task_trace(store, "wc-t02")
        assert trace.rejections == 2
