"""Pipeline checker — scans tasks, determines what's ready, respects budgets."""
from __future__ import annotations

import logging
import time

from warchief.config import Config, MAX_SPAWNS_PER_CYCLE, REJECTION_COOLDOWN
from warchief.models import TaskRecord
from warchief.pipeline_template import PipelineTemplate
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.pipeline_checker")


def check_pipeline(
    store: TaskStore,
    pipeline: PipelineTemplate,
    config: Config,
    max_spawns: int = MAX_SPAWNS_PER_CYCLE,
) -> list[tuple[TaskRecord, str]]:
    """Scan the pipeline and return tasks ready for spawning with their roles.

    Returns a list of (task, role) tuples, sorted by priority and capped
    at ``max_spawns``.
    """
    ready: list[tuple[TaskRecord, str, int]] = []

    for stage_name in pipeline.stage_names:
        required_label = pipeline.requires_label(stage_name)
        role = pipeline.stage_to_role.get(stage_name)
        if not role:
            continue

        tasks = store.get_ready_tasks(stage_name)
        for task in tasks:
            # Skip if stage requires a label the task doesn't have
            if required_label and required_label not in task.labels:
                continue

            # Skip if in rejection cooldown
            if not _past_rejection_cooldown(task, store):
                continue

            priority = pipeline.get_stage_priority(stage_name) + task.priority
            ready.append((task, role, priority))

    # Sort by combined priority (descending)
    ready.sort(key=lambda x: x[2], reverse=True)

    # Enforce PR creator serialization: only one pr-creation task at a time
    result = _serialize_pr_creator(ready, store)

    return result[:max_spawns]


def release_ready(
    store: TaskStore,
    pipeline: PipelineTemplate,
) -> list[TaskRecord]:
    """Find tasks that are open with no stage and release them into the pipeline.

    These are newly created tasks that haven't been assigned a stage yet.
    """
    tasks = store.list_tasks(status="open")
    released: list[TaskRecord] = []

    for task in tasks:
        if task.stage:
            continue
        # Has any stage label already?
        if any(l.startswith("stage:") for l in task.labels):
            continue

        first_stage = pipeline.active_stages(task.labels)[0] if pipeline.active_stages(task.labels) else None
        if not first_stage:
            continue

        store.update_task(
            task.id,
            stage=first_stage,
            labels=task.labels + [f"stage:{first_stage}"],
        )
        released.append(task)
        log.info("Released task %s into stage %s", task.id, first_stage)

    return released


def _past_rejection_cooldown(task: TaskRecord, store: TaskStore) -> bool:
    """Check if enough time has passed since the last rejection."""
    if task.rejection_count == 0:
        return True

    events = store.get_events(task_id=task.id, limit=5)
    rejection_events = [e for e in events if e.event_type in ("reject", "advance")]
    if not rejection_events:
        return True

    last_event_time = rejection_events[0].created_at
    return (time.time() - last_event_time) > REJECTION_COOLDOWN


def _serialize_pr_creator(
    ready: list[tuple[TaskRecord, str, int]],
    store: TaskStore,
) -> list[tuple[TaskRecord, str]]:
    """Ensure only one pr_creator task runs at a time."""
    result: list[tuple[TaskRecord, str]] = []
    pr_creator_included = False

    # Check if a pr_creator is already running
    running = store.get_running_agents()
    pr_creator_running = any(a.role == "pr_creator" for a in running)

    for task, role, _priority in ready:
        if role == "pr_creator":
            if pr_creator_running or pr_creator_included:
                continue
            pr_creator_included = True
        result.append((task, role))

    return result


# Keep backward-compatible alias
_serialize_integrator = _serialize_pr_creator
