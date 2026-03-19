"""Recovery — self-healing for orphans, zombies, and broken worktrees."""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from warchief.config import ZOMBIE_THRESHOLD
from warchief.heartbeat import cleanup_heartbeat, is_zombie
from warchief.models import AgentRecord, EventRecord
from warchief.task_store import TaskStore
from warchief.worktree import list_worktrees, remove_worktree, repair_worktree

log = logging.getLogger("warchief.recovery")


def recover_orphans(store: TaskStore) -> list[str]:
    """Reset tasks that are in_progress but have no live agent.

    Returns list of recovered task IDs.
    """
    orphans = store.get_orphaned_tasks()
    recovered: list[str] = []

    for task in orphans:
        log.warning("Recovering orphaned task %s (was %s)", task.id, task.assigned_agent)
        store.update_task(task.id, status="open", assigned_agent=None)
        store.log_event(
            EventRecord(
                event_type="orphan_recovery",
                task_id=task.id,
                agent_id=task.assigned_agent,
                details={"previous_status": task.status},
                actor="recovery",
            )
        )
        recovered.append(task.id)

    if recovered:
        log.info("Recovered %d orphaned tasks", len(recovered))
    return recovered


def recover_zombie_agents(
    store: TaskStore,
    project_root: Path,
    threshold: float = ZOMBIE_THRESHOLD,
) -> list[str]:
    """Detect and terminate zombie agents.

    Returns list of zombie agent IDs.
    """
    running = store.get_running_agents()
    zombies: list[str] = []

    for agent in running:
        if agent.status not in ("alive", "zombie"):
            continue

        is_zomb = is_zombie(project_root, agent.id, threshold)
        process_dead = agent.pid and not _is_process_alive(agent.pid)

        if is_zomb or process_dead:
            log.warning("Zombie agent detected: %s (PID %s)", agent.id, agent.pid)

            # Try to kill if still running
            if agent.pid and not process_dead:
                try:
                    os.kill(agent.pid, signal.SIGTERM)
                    log.info("Sent SIGTERM to zombie %s (PID %d)", agent.id, agent.pid)
                except (ProcessLookupError, PermissionError):
                    pass

            store.update_agent(agent.id, status="dead")
            cleanup_heartbeat(project_root, agent.id)

            # Reset the task if still assigned
            if agent.current_task:
                task = store.get_task(agent.current_task)
                if task and task.status == "in_progress":
                    store.update_task(task.id, status="open", assigned_agent=None)

            store.log_event(
                EventRecord(
                    event_type="zombie_recovery",
                    agent_id=agent.id,
                    task_id=agent.current_task,
                    actor="recovery",
                )
            )
            zombies.append(agent.id)

    if zombies:
        log.info("Recovered %d zombie agents", len(zombies))
    return zombies


def recover_worktrees(store: TaskStore, project_root: Path) -> list[str]:
    """Find and repair broken worktrees. Remove orphaned ones.

    Returns list of agent IDs whose worktrees were cleaned up.
    """
    existing_worktrees = set(list_worktrees(project_root))
    running = store.get_running_agents()
    active_agents = {a.id for a in running}

    cleaned: list[str] = []

    for wt_agent_id in existing_worktrees:
        if wt_agent_id not in active_agents:
            # Worktree exists but agent is not running — check if agent is dead
            agent = store.get_agent(wt_agent_id)
            if agent is None or agent.status in ("dead", "retired"):
                log.info("Removing orphaned worktree for %s", wt_agent_id)
                remove_worktree(project_root, wt_agent_id)
                cleaned.append(wt_agent_id)
            else:
                # Agent exists but worktree may be broken — try repair
                repaired = repair_worktree(project_root, wt_agent_id)
                if repaired:
                    log.info("Repaired worktree for %s", wt_agent_id)

    if cleaned:
        log.info("Cleaned up %d orphaned worktrees", len(cleaned))
    return cleaned


def run_full_recovery(store: TaskStore, project_root: Path) -> dict:
    """Run all recovery procedures. Returns summary."""
    return {
        "orphaned_tasks": recover_orphans(store),
        "zombie_agents": recover_zombie_agents(store, project_root),
        "cleaned_worktrees": recover_worktrees(store, project_root),
    }


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
