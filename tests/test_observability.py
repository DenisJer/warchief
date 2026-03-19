"""Tests for observability metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from warchief.models import TaskRecord
from warchief.observability import (
    CounterMetric,
    GaugeMetric,
    collect_metrics,
    export_metrics_file,
    format_metrics_summary,
    format_openmetrics,
)
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


class TestCollectMetrics:
    def test_empty_store(self, store: TaskStore):
        metrics = collect_metrics(store)
        assert len(metrics) > 0
        # Should have basic task gauges
        names = [m.name for m in metrics]
        assert "warchief_tasks_total" in names
        assert "warchief_agents_running" in names

    def test_with_tasks(self, store: TaskStore):
        store.create_task(TaskRecord(id="wc-o1", title="Open", status="open"))
        store.create_task(TaskRecord(id="wc-o2", title="Blocked", status="blocked"))
        store.create_task(TaskRecord(id="wc-o3", title="Closed", status="closed"))

        metrics = collect_metrics(store)
        metric_map = {m.name: m for m in metrics if not m.labels}
        assert metric_map["warchief_tasks_total"].value == 3
        assert metric_map["warchief_tasks_open"].value == 1
        assert metric_map["warchief_tasks_blocked"].value == 1
        assert metric_map["warchief_tasks_closed"].value == 1

    def test_stage_metrics(self, store: TaskStore):
        store.create_task(
            TaskRecord(
                id="wc-s1",
                title="In dev",
                status="in_progress",
                stage="development",
            )
        )
        metrics = collect_metrics(store)
        stage_metrics = [
            m
            for m in metrics
            if m.name == "warchief_tasks_by_stage"
            and m.labels
            and m.labels.get("stage") == "development"
        ]
        assert len(stage_metrics) == 1
        assert stage_metrics[0].value == 1


class TestFormatOpenMetrics:
    def test_gauge(self):
        metrics = [GaugeMetric("test_gauge", "A test gauge", 42)]
        text = format_openmetrics(metrics)
        assert "# HELP test_gauge A test gauge" in text
        assert "# TYPE test_gauge gauge" in text
        assert "test_gauge 42" in text

    def test_counter(self):
        metrics = [CounterMetric("test_counter", "A counter", 100)]
        text = format_openmetrics(metrics)
        assert "# TYPE test_counter counter" in text
        assert "test_counter 100" in text

    def test_labels(self):
        metrics = [GaugeMetric("m", "desc", 5, labels={"role": "dev", "stage": "review"})]
        text = format_openmetrics(metrics)
        assert 'role="dev"' in text
        assert 'stage="review"' in text

    def test_deduplicates_help(self):
        metrics = [
            GaugeMetric("same_name", "desc", 1, labels={"a": "1"}),
            GaugeMetric("same_name", "desc", 2, labels={"a": "2"}),
        ]
        text = format_openmetrics(metrics)
        assert text.count("# HELP same_name") == 1


class TestExportMetrics:
    def test_export_file(self, project_root: Path, store: TaskStore):
        store.create_task(TaskRecord(id="wc-x1", title="Test"))
        path = export_metrics_file(store, project_root)
        assert path.exists()
        content = path.read_text()
        assert "warchief_tasks_total" in content
        assert str(path).endswith(".prom")


class TestFormatSummary:
    def test_summary(self, store: TaskStore):
        store.create_task(TaskRecord(id="wc-m1", title="Metric test"))
        text = format_metrics_summary(store)
        assert "Observability Metrics" in text
        assert "warchief_tasks_total" in text
