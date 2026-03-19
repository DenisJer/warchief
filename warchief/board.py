"""Kanban board — terminal display of pipeline state."""

from __future__ import annotations

import time

from warchief.config import STAGES
from warchief.metrics import format_duration
from warchief.task_store import TaskStore


def render_board(store: TaskStore, use_rich: bool = True) -> str:
    """Render a kanban board showing tasks by stage.

    If ``use_rich`` is True and rich is available, returns a rich-formatted table.
    Otherwise returns plain text.
    """
    if use_rich:
        try:
            return _render_rich_board(store)
        except ImportError:
            pass
    return _render_plain_board(store)


def _render_plain_board(store: TaskStore) -> str:
    """Plain text kanban board."""
    tasks = store.list_tasks()
    running_agents = store.get_running_agents()
    agent_map = {a.current_task: a for a in running_agents if a.current_task}

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  WARCHIEF PIPELINE BOARD")
    lines.append("=" * 80)

    # Unassigned tasks (no stage)
    unstaged = [t for t in tasks if not t.stage and t.status != "closed"]
    if unstaged:
        lines.append("")
        lines.append(f"  BACKLOG ({len(unstaged)})")
        lines.append("  " + "-" * 40)
        for t in unstaged:
            lines.append(f"    {t.id}  {t.title[:40]}  [{t.status}]  P{t.priority}")

    # Each stage column
    for stage in STAGES:
        stage_tasks = [t for t in tasks if t.stage == stage]
        if not stage_tasks:
            lines.append("")
            lines.append(f"  {stage.upper()} (0)")
            lines.append("  " + "-" * 40)
            lines.append("    (empty)")
            continue

        lines.append("")
        lines.append(f"  {stage.upper()} ({len(stage_tasks)})")
        lines.append("  " + "-" * 40)

        for t in stage_tasks:
            agent = agent_map.get(t.id)
            agent_str = f" -> {agent.id}" if agent else ""
            age = format_duration(time.time() - t.updated_at) if t.updated_at else ""
            status_icon = _status_icon(t.status)
            lines.append(
                f"    {status_icon} {t.id}  {t.title[:30]}  [{t.status}]{agent_str}  {age}"
            )

    # Completed
    closed = [t for t in tasks if t.status == "closed"]
    if closed:
        lines.append("")
        lines.append(f"  DONE ({len(closed)})")
        lines.append("  " + "-" * 40)
        for t in closed[-5:]:  # Last 5
            lines.append(f"    {t.id}  {t.title[:40]}")

    # Blocked
    blocked = [t for t in tasks if t.status == "blocked"]
    if blocked:
        lines.append("")
        lines.append(f"  BLOCKED ({len(blocked)})")
        lines.append("  " + "-" * 40)
        for t in blocked:
            lines.append(f"    {t.id}  {t.title[:40]}")

    lines.append("")
    lines.append("=" * 80)

    # Summary line
    total = len(tasks)
    active = sum(1 for t in tasks if t.status == "in_progress")
    lines.append(f"  {total} tasks | {active} active | {len(closed)} done | {len(blocked)} blocked")
    lines.append("")

    return "\n".join(lines)


def _render_rich_board(store: TaskStore) -> str:
    """Rich-formatted kanban board."""
    from rich.console import Console
    from rich.table import Table
    from io import StringIO

    tasks = store.list_tasks()
    running_agents = store.get_running_agents()
    agent_map = {a.current_task: a for a in running_agents if a.current_task}

    table = Table(title="Warchief Pipeline Board", show_lines=True)

    for stage in STAGES:
        table.add_column(stage.upper(), style="cyan", min_width=20)

    # Build columns
    columns: dict[str, list[str]] = {s: [] for s in STAGES}
    for task in tasks:
        if task.stage and task.stage in columns:
            agent = agent_map.get(task.id)
            agent_str = f"\n  -> {agent.id}" if agent else ""
            status_color = _status_color(task.status)
            entry = f"[{status_color}]{task.id}[/]\n{task.title[:25]}{agent_str}"
            columns[task.stage].append(entry)

    # Pad columns to same length
    max_rows = max((len(v) for v in columns.values()), default=0)
    for stage in STAGES:
        while len(columns[stage]) < max_rows:
            columns[stage].append("")

    for i in range(max_rows):
        row = [columns[stage][i] for stage in STAGES]
        table.add_row(*row)

    buf = StringIO()
    console = Console(file=buf, force_terminal=True)
    console.print(table)
    return buf.getvalue()


def _status_icon(status: str) -> str:
    icons = {
        "open": "o",
        "in_progress": ">",
        "blocked": "!",
        "closed": "x",
    }
    return icons.get(status, "?")


def _status_color(status: str) -> str:
    colors = {
        "open": "white",
        "in_progress": "green",
        "blocked": "red",
        "closed": "dim",
    }
    return colors.get(status, "white")
