"""Diagnostics — log extraction and failure formatting."""

from __future__ import annotations

import logging
from pathlib import Path

from warchief.models import EventRecord
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.diagnostics")


def get_recent_failures(store: TaskStore, limit: int = 20) -> list[dict]:
    """Extract recent failure events with formatted context."""
    events = store.get_events(limit=limit * 3)
    failures: list[dict] = []

    for event in events:
        if event.event_type in (
            "block",
            "crash",
            "zombie",
            "zombie_recovery",
            "orphan_recovery",
            "mass_death",
            "reject",
        ):
            task = store.get_task(event.task_id) if event.task_id else None
            failures.append(
                {
                    "event_type": event.event_type,
                    "task_id": event.task_id,
                    "task_title": task.title if task else None,
                    "agent_id": event.agent_id,
                    "details": event.details,
                    "timestamp": event.created_at,
                    "actor": event.actor,
                }
            )

        if len(failures) >= limit:
            break

    return failures


def format_failure_report(failures: list[dict]) -> str:
    """Format failure events into a human-readable report."""
    if not failures:
        return "No recent failures."

    lines: list[str] = []
    lines.append("Recent Failures")
    lines.append("=" * 60)

    for f in failures:
        task_str = (
            f"{f['task_id']} ({f['task_title']})" if f["task_title"] else f["task_id"] or "n/a"
        )
        lines.append(f"\n  [{f['event_type'].upper()}] Task: {task_str}")
        if f["agent_id"]:
            lines.append(f"    Agent: {f['agent_id']}")
        if f["details"]:
            for k, v in f["details"].items():
                if v:
                    lines.append(f"    {k}: {v}")

    lines.append("")
    return "\n".join(lines)


def tail_log(project_root: Path, lines: int = 50) -> str:
    """Read the last N lines from the warchief log file."""
    log_path = project_root / ".warchief" / "warchief.log"
    if not log_path.exists():
        return "No log file found."

    all_lines = log_path.read_text().splitlines()
    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return "\n".join(tail)


def get_agent_log(
    store: TaskStore,
    agent_id: str,
    limit: int = 50,
) -> list[dict]:
    """Get event log entries for a specific agent."""
    events = store.get_events(limit=limit * 5)
    return [
        {
            "event_type": e.event_type,
            "task_id": e.task_id,
            "details": e.details,
            "timestamp": e.created_at,
        }
        for e in events
        if e.agent_id == agent_id
    ][:limit]
