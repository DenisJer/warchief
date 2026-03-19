"""Event feed — real-time display of pipeline activity."""

from __future__ import annotations

import time

from warchief.metrics import format_duration
from warchief.task_store import TaskStore


def render_feed(store: TaskStore, limit: int = 30) -> str:
    """Render recent events as a plain-text feed."""
    events = store.get_events(limit=limit)

    if not events:
        return "No events yet."

    lines: list[str] = []
    lines.append("Activity Feed")
    lines.append("=" * 70)

    now = time.time()
    for event in events:
        age = format_duration(now - event.created_at) if event.created_at else ""
        icon = _event_icon(event.event_type)
        task_str = event.task_id or ""
        agent_str = f" ({event.agent_id})" if event.agent_id else ""
        detail_str = ""

        if event.details:
            if "from_stage" in event.details and "to_stage" in event.details:
                detail_str = f" {event.details['from_stage']} -> {event.details['to_stage']}"
            elif "reason" in event.details:
                detail_str = f" {event.details['reason'][:40]}"
            elif "failure_reason" in event.details and event.details["failure_reason"]:
                detail_str = f" {event.details['failure_reason'][:40]}"

        lines.append(f"  {icon} {age:>6}  {event.event_type:<18} {task_str}{agent_str}{detail_str}")

    lines.append("")
    return "\n".join(lines)


def render_rich_feed(store: TaskStore, limit: int = 30) -> str:
    """Render feed using rich formatting (if available)."""
    try:
        from rich.console import Console
        from rich.table import Table
        from io import StringIO

        events = store.get_events(limit=limit)
        if not events:
            return "No events yet."

        table = Table(title="Warchief Activity Feed")
        table.add_column("Age", style="dim", width=8)
        table.add_column("Event", style="cyan")
        table.add_column("Task", style="green")
        table.add_column("Agent", style="yellow")
        table.add_column("Details")

        now = time.time()
        for event in events:
            age = format_duration(now - event.created_at) if event.created_at else ""
            detail = ""
            if event.details:
                if "to_stage" in event.details:
                    detail = f"-> {event.details['to_stage']}"
                elif "failure_reason" in event.details and event.details["failure_reason"]:
                    detail = event.details["failure_reason"][:40]

            color = _event_color(event.event_type)
            table.add_row(
                age,
                f"[{color}]{event.event_type}[/]",
                event.task_id or "",
                event.agent_id or "",
                detail,
            )

        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        console.print(table)
        return buf.getvalue()
    except ImportError:
        return render_feed(store, limit)


def _event_icon(event_type: str) -> str:
    icons = {
        "spawn": "+",
        "advance": ">",
        "transition": "~",
        "reject": "x",
        "block": "!",
        "crash": "*",
        "zombie": "z",
        "orphan_reset": "o",
        "orphan_recovery": "o",
        "zombie_recovery": "z",
        "mass_death": "!!",
        "comment": "#",
        "heartbeat": ".",
    }
    return icons.get(event_type, "?")


def _event_color(event_type: str) -> str:
    colors = {
        "spawn": "green",
        "advance": "cyan",
        "reject": "yellow",
        "block": "red",
        "crash": "red bold",
        "zombie": "red",
        "mass_death": "red bold",
    }
    return colors.get(event_type, "white")
