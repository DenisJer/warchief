"""Metrics — compute pipeline statistics from events."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from warchief.models import EventRecord
from warchief.task_store import TaskStore


@dataclass
class StageMetrics:
    stage: str
    total_tasks: int = 0
    avg_duration: float = 0.0
    min_duration: float = 0.0
    max_duration: float = 0.0
    rejection_count: int = 0
    crash_count: int = 0


@dataclass
class TaskTrace:
    task_id: str
    stages: list[dict] = field(default_factory=list)
    total_duration: float = 0.0
    rejections: int = 0
    crashes: int = 0


@dataclass
class PipelineMetrics:
    total_tasks: int = 0
    open_tasks: int = 0
    in_progress_tasks: int = 0
    blocked_tasks: int = 0
    closed_tasks: int = 0
    total_agents_spawned: int = 0
    total_rejections: int = 0
    total_crashes: int = 0
    stage_metrics: list[StageMetrics] = field(default_factory=list)
    avg_completion_time: float = 0.0


def compute_pipeline_metrics(store: TaskStore) -> PipelineMetrics:
    """Compute overall pipeline metrics from the task store."""
    tasks = store.list_tasks()
    metrics = PipelineMetrics(total_tasks=len(tasks))

    completion_times: list[float] = []

    for task in tasks:
        if task.status == "open":
            metrics.open_tasks += 1
        elif task.status == "in_progress":
            metrics.in_progress_tasks += 1
        elif task.status == "blocked":
            metrics.blocked_tasks += 1
        elif task.status == "closed":
            metrics.closed_tasks += 1

        metrics.total_agents_spawned += task.spawn_count
        metrics.total_rejections += task.rejection_count
        metrics.total_crashes += task.crash_count

        if task.closed_at and task.created_at:
            completion_times.append(task.closed_at - task.created_at)

    if completion_times:
        metrics.avg_completion_time = sum(completion_times) / len(completion_times)

    # Compute per-stage metrics from events
    metrics.stage_metrics = _compute_stage_metrics(store)

    return metrics


def compute_task_trace(store: TaskStore, task_id: str) -> TaskTrace | None:
    """Build a detailed trace of a task's journey through the pipeline."""
    task = store.get_task(task_id)
    if task is None:
        return None

    events = store.get_events(task_id=task_id, limit=500)
    events.reverse()  # Chronological order

    trace = TaskTrace(task_id=task_id)

    current_stage_start: float | None = None
    current_stage: str | None = None

    for event in events:
        if event.event_type == "advance":
            from_stage = event.details.get("from_stage")
            to_stage = event.details.get("to_stage")

            if from_stage and current_stage_start:
                trace.stages.append(
                    {
                        "stage": from_stage,
                        "duration": event.created_at - current_stage_start,
                        "entered_at": current_stage_start,
                        "exited_at": event.created_at,
                    }
                )

            current_stage = to_stage
            current_stage_start = event.created_at

        elif event.event_type == "spawn" and not current_stage_start:
            current_stage = event.details.get("stage", task.stage)
            current_stage_start = event.created_at

        elif event.event_type == "reject":
            trace.rejections += 1

        elif event.event_type == "crash":
            trace.crashes += 1

    # Include current stage if still in progress
    if current_stage and current_stage_start:
        end_time = task.closed_at or time.time()
        trace.stages.append(
            {
                "stage": current_stage,
                "duration": end_time - current_stage_start,
                "entered_at": current_stage_start,
                "exited_at": end_time,
            }
        )

    trace.total_duration = sum(s["duration"] for s in trace.stages)
    return trace


def _compute_stage_metrics(store: TaskStore) -> list[StageMetrics]:
    """Compute per-stage metrics from events."""
    events = store.get_events(limit=10000)

    # Group advance events by stage
    stage_durations: dict[str, list[float]] = defaultdict(list)
    stage_rejections: dict[str, int] = defaultdict(int)
    stage_crashes: dict[str, int] = defaultdict(int)
    stage_tasks: dict[str, set] = defaultdict(set)

    for event in events:
        if event.event_type == "advance":
            from_stage = event.details.get("from_stage")
            to_stage = event.details.get("to_stage")
            if from_stage and event.task_id:
                stage_tasks[from_stage].add(event.task_id)

        elif event.event_type == "reject":
            stage = event.details.get("from_stage", "unknown")
            stage_rejections[stage] += 1

        elif event.event_type == "crash":
            stage = event.details.get("from_stage", "unknown")
            stage_crashes[stage] += 1

    result: list[StageMetrics] = []
    for stage_name in sorted(set(stage_tasks.keys()) | set(stage_rejections.keys())):
        durations = stage_durations.get(stage_name, [])
        sm = StageMetrics(
            stage=stage_name,
            total_tasks=len(stage_tasks.get(stage_name, set())),
            avg_duration=sum(durations) / len(durations) if durations else 0,
            min_duration=min(durations) if durations else 0,
            max_duration=max(durations) if durations else 0,
            rejection_count=stage_rejections.get(stage_name, 0),
            crash_count=stage_crashes.get(stage_name, 0),
        )
        result.append(sm)

    return result


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"
