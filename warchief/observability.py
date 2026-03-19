"""Observability — metrics export for monitoring systems.

Provides a Prometheus/OpenMetrics-compatible text format endpoint
that can be scraped or dumped to file. No external dependencies required.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from warchief.config import STAGES
from warchief.metrics import compute_pipeline_metrics
from warchief.task_store import TaskStore


@dataclass
class GaugeMetric:
    name: str
    help_text: str
    value: float
    labels: dict[str, str] | None = None


@dataclass
class CounterMetric:
    name: str
    help_text: str
    value: float
    labels: dict[str, str] | None = None


def collect_metrics(store: TaskStore) -> list[GaugeMetric | CounterMetric]:
    """Collect all pipeline metrics as Prometheus-style metric objects."""
    pm = compute_pipeline_metrics(store)
    tasks = store.list_tasks()
    running_agents = store.get_running_agents()

    metrics: list[GaugeMetric | CounterMetric] = []

    # Task counts by status
    metrics.append(
        GaugeMetric(
            "warchief_tasks_total",
            "Total number of tasks",
            pm.total_tasks,
        )
    )
    metrics.append(
        GaugeMetric(
            "warchief_tasks_open",
            "Number of open tasks",
            pm.open_tasks,
        )
    )
    metrics.append(
        GaugeMetric(
            "warchief_tasks_in_progress",
            "Number of in-progress tasks",
            pm.in_progress_tasks,
        )
    )
    metrics.append(
        GaugeMetric(
            "warchief_tasks_blocked",
            "Number of blocked tasks",
            pm.blocked_tasks,
        )
    )
    metrics.append(
        GaugeMetric(
            "warchief_tasks_closed",
            "Number of closed tasks",
            pm.closed_tasks,
        )
    )

    # Task counts by stage
    for stage in STAGES:
        count = sum(1 for t in tasks if t.stage == stage)
        metrics.append(
            GaugeMetric(
                "warchief_tasks_by_stage",
                f"Tasks in {stage} stage",
                count,
                labels={"stage": stage},
            )
        )

    # Agent counts
    metrics.append(
        GaugeMetric(
            "warchief_agents_running",
            "Number of running agents",
            len(running_agents),
        )
    )

    # Agent counts by role
    role_counts: dict[str, int] = {}
    for agent in running_agents:
        role_counts[agent.role] = role_counts.get(agent.role, 0) + 1
    for role, count in role_counts.items():
        metrics.append(
            GaugeMetric(
                "warchief_agents_by_role",
                f"Running agents with role {role}",
                count,
                labels={"role": role},
            )
        )

    # Cumulative counters
    metrics.append(
        CounterMetric(
            "warchief_agents_spawned_total",
            "Total agents spawned",
            pm.total_agents_spawned,
        )
    )
    metrics.append(
        CounterMetric(
            "warchief_rejections_total",
            "Total rejections across all tasks",
            pm.total_rejections,
        )
    )
    metrics.append(
        CounterMetric(
            "warchief_crashes_total",
            "Total crashes across all tasks",
            pm.total_crashes,
        )
    )

    # Avg completion time
    if pm.avg_completion_time > 0:
        metrics.append(
            GaugeMetric(
                "warchief_avg_completion_seconds",
                "Average task completion time in seconds",
                pm.avg_completion_time,
            )
        )

    return metrics


def format_openmetrics(metrics: list[GaugeMetric | CounterMetric]) -> str:
    """Format metrics as OpenMetrics/Prometheus text format."""
    lines: list[str] = []
    seen_help: set[str] = set()

    for m in metrics:
        if m.name not in seen_help:
            metric_type = "gauge" if isinstance(m, GaugeMetric) else "counter"
            lines.append(f"# HELP {m.name} {m.help_text}")
            lines.append(f"# TYPE {m.name} {metric_type}")
            seen_help.add(m.name)

        if m.labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in m.labels.items())
            lines.append(f"{m.name}{{{label_str}}} {m.value}")
        else:
            lines.append(f"{m.name} {m.value}")

    lines.append("")
    return "\n".join(lines)


def export_metrics_file(store: TaskStore, project_root: Path) -> Path:
    """Export current metrics to a file for scraping."""
    metrics = collect_metrics(store)
    text = format_openmetrics(metrics)

    metrics_path = project_root / ".warchief" / "metrics.prom"
    metrics_path.write_text(text)
    return metrics_path


def format_metrics_summary(store: TaskStore) -> str:
    """Human-readable metrics summary for CLI display."""
    metrics = collect_metrics(store)

    lines: list[str] = []
    lines.append("Pipeline Observability Metrics")
    lines.append("=" * 55)

    for m in metrics:
        label_str = ""
        if m.labels:
            label_str = " (" + ", ".join(f"{k}={v}" for k, v in m.labels.items()) + ")"
        value_str = f"{m.value:.0f}" if m.value == int(m.value) else f"{m.value:.2f}"
        lines.append(f"  {m.name}{label_str}: {value_str}")

    return "\n".join(lines)
