"""Dashboard — interactive terminal dashboard for pipeline monitoring.

Two backends:
1. Rich Live dashboard (requires `rich`) — auto-refreshing terminal display
2. Plain text snapshot — no dependencies

The TUI uses `rich.live` for auto-refreshing rather than `textual`
to keep dependencies minimal while still providing a live-updating view.
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

from warchief.config import STAGES, read_config
from warchief.cost_tracker import compute_cost_summary
from warchief.metrics import compute_pipeline_metrics, format_duration
from warchief.task_store import TaskStore


def run_dashboard(project_root: Path, refresh_interval: float = 2.0) -> None:
    """Launch the live dashboard. Falls back to snapshot if rich unavailable."""
    try:
        _run_rich_dashboard(project_root, refresh_interval)
    except ImportError:
        _run_plain_dashboard(project_root)


def render_dashboard_snapshot(project_root: Path) -> str:
    """Render a single snapshot of the dashboard as plain text."""
    db_path = project_root / ".warchief" / "warchief.db"
    store = TaskStore(db_path)
    try:
        return _build_plain_snapshot(store, project_root)
    finally:
        store.close()


def _build_plain_snapshot(store: TaskStore, project_root: Path) -> str:
    """Build a plain-text dashboard snapshot."""
    tasks = store.list_tasks()
    agents = store.get_running_agents()
    metrics = compute_pipeline_metrics(store)
    config = read_config(project_root)
    events = store.get_events(limit=10)

    agent_map = {a.current_task: a for a in agents if a.current_task}
    now = time.time()

    lines: list[str] = []

    # Header
    lines.append("")
    lines.append("  WARCHIEF DASHBOARD")
    lines.append("  " + "=" * 70)

    # Pipeline overview
    paused_str = " [PAUSED]" if config.paused else ""
    lines.append(f"  Status: {'Active' if not config.paused else 'Paused'}{paused_str}")
    lines.append(
        f"  Tasks: {metrics.total_tasks} total | "
        f"{metrics.open_tasks} open | {metrics.in_progress_tasks} active | "
        f"{metrics.blocked_tasks} blocked | {metrics.closed_tasks} done"
    )
    lines.append(f"  Agents: {len(agents)} running / {config.max_total_agents} max")
    if metrics.avg_completion_time > 0:
        lines.append(f"  Avg completion: {format_duration(metrics.avg_completion_time)}")

    # Stage columns
    lines.append("")
    lines.append("  PIPELINE")
    lines.append("  " + "-" * 70)

    for stage in STAGES:
        stage_tasks = [t for t in tasks if t.stage == stage]
        count = len(stage_tasks)
        active_count = sum(1 for t in stage_tasks if t.status == "in_progress")
        stage_header = f"  {stage.upper()} ({count})"
        if active_count:
            stage_header += f" [{active_count} active]"
        lines.append(stage_header)

        for t in stage_tasks:
            agent = agent_map.get(t.id)
            agent_str = f" -> {agent.id}" if agent else ""
            age = format_duration(now - t.updated_at) if t.updated_at else ""
            icon = _status_icon(t.status)
            lines.append(f"    {icon} {t.id} {t.title[:35]:<35} [{t.status}]{agent_str} {age}")

        if not stage_tasks:
            lines.append("    (empty)")

    # Agent tree
    lines.append("")
    lines.append("  AGENTS")
    lines.append("  " + "-" * 70)
    if agents:
        for a in agents:
            task_str = f"-> {a.current_task}" if a.current_task else "idle"
            age = format_duration(now - a.spawned_at) if a.spawned_at else ""
            lines.append(f"    {a.id:<30} {a.role:<15} {task_str:<18} {age}")
    else:
        lines.append("    (no active agents)")

    # Problems
    blocked = [t for t in tasks if t.status == "blocked"]
    if blocked:
        lines.append("")
        lines.append("  PROBLEMS")
        lines.append("  " + "-" * 70)
        for t in blocked:
            lines.append(f"    ! {t.id} {t.title[:40]} [BLOCKED]")

    # Testing
    testing_tasks = store.list_tasks(has_label="needs-testing")
    if testing_tasks:
        lines.append("")
        lines.append("  TESTING (waiting for Playwright verification)")
        lines.append("  " + "-" * 70)
        for tt in testing_tasks:
            lines.append(f'    > {tt.id} "{tt.title}"')
            lines.append(f'      approve {tt.id}  |  reject {tt.id} "feedback"')

    # Questions
    question_tasks = store.list_tasks(has_label="question")
    if question_tasks:
        lines.append("")
        lines.append("  QUESTIONS (waiting for user)")
        lines.append("  " + "-" * 70)
        for qt in question_tasks:
            qa_messages = store.get_task_messages(qt.id)
            questions = [m for m in qa_messages if m.message_type == "question"]
            latest_q = questions[-1].body if questions else "(no question text)"
            lines.append(f'    ? {qt.id} "{qt.title}"')
            lines.append(f"      \u2192 {latest_q}")
            lines.append(f'      Answer: warchief answer {qt.id} "your answer"')

    # Costs
    cost_summary = compute_cost_summary(project_root)
    lines.append("")
    lines.append("  TOKENS")
    lines.append("  " + "-" * 70)
    if cost_summary.entries:
        lines.append(f"    In:          {cost_summary.total_input_tokens:,}")
        lines.append(f"    Cache Read:  {cost_summary.total_cache_read_tokens:,}")
        lines.append(f"    Cache Write: {cost_summary.total_cache_write_tokens:,}")
        lines.append(f"    Out:         {cost_summary.total_output_tokens:,}")
        lines.append(f"    Cost:        ${cost_summary.total_cost_usd:.2f}")
        if config.budget.session_limit > 0:
            pct = cost_summary.total_cost_usd / config.budget.session_limit * 100
            bar_len = 30
            filled = int(bar_len * min(pct, 100) / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            warn = " !! OVER" if pct >= 100 else ""
            lines.append(
                f"    Budget:      [{bar}] {pct:.0f}% of ${config.budget.session_limit:.2f}{warn}"
            )
        if config.budget.per_task_default > 0:
            lines.append(f"    Per-task:    ${config.budget.per_task_default:.2f} default")
    else:
        lines.append("    (no token data yet)")

    # Recent events — only show last 10 minutes
    max_age = 600  # 10 minutes
    recent = [e for e in events if e.created_at and (now - e.created_at) < max_age]
    lines.append("")
    lines.append("  RECENT EVENTS (last 10 min)")
    lines.append("  " + "-" * 70)
    for event in recent[:8]:
        age = format_duration(now - event.created_at) if event.created_at else ""
        icon = _event_icon(event.event_type)
        task_str = event.task_id or ""
        agent_str = event.agent_id or ""
        lines.append(f"    {icon} {age:>5}  {event.event_type:<16} {task_str:<14} {agent_str}")

    if not recent:
        lines.append("    (no recent activity)")

    lines.append("")
    lines.append(f"  Last updated: {time.strftime('%H:%M:%S')}")
    lines.append("")

    return "\n".join(lines)


def _run_plain_dashboard(project_root: Path) -> None:
    """Print a single snapshot (no live update)."""
    print(render_dashboard_snapshot(project_root))
    print("  (Install 'rich' for live dashboard: pip install rich)")


def _run_rich_dashboard(project_root: Path, refresh_interval: float) -> None:
    """Run live-updating dashboard using rich.live."""
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()
    running = True

    def handle_signal(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    def build_layout() -> Layout:
        db_path = project_root / ".warchief" / "warchief.db"
        store = TaskStore(db_path)
        try:
            tasks = store.list_tasks()
            agents = store.get_running_agents()
            metrics = compute_pipeline_metrics(store)
            config = read_config(project_root)
            events = store.get_events(limit=8)
            question_tasks = store.list_tasks(has_label="question")
            # Pre-fetch question messages while store is open
            question_messages: dict[str, list] = {}
            for qt in question_tasks:
                question_messages[qt.id] = store.get_task_messages(qt.id)
        finally:
            store.close()

        now = time.time()
        agent_map = {a.current_task: a for a in agents if a.current_task}

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )

        # Header
        paused = " [PAUSED]" if config.paused else ""
        header_text = Text(f" WARCHIEF DASHBOARD{paused}", style="bold white on blue")
        header_text.append(
            f"  |  {metrics.total_tasks} tasks  |  {len(agents)} agents  |  "
            f"{metrics.closed_tasks} done  |  {metrics.blocked_tasks} blocked",
            style="white on blue",
        )
        layout["header"].update(Panel(header_text, style="blue"))

        # Body: pipeline + agents + events
        layout["body"].split_row(
            Layout(name="pipeline", ratio=3),
            Layout(name="sidebar", ratio=2),
        )

        # Pipeline table
        pipeline_table = Table(title="Pipeline", show_lines=True, expand=True)
        pipeline_table.add_column("Stage", style="cyan", min_width=12)
        pipeline_table.add_column("Tasks", min_width=30)
        pipeline_table.add_column("#", width=3, justify="right")

        for stage in STAGES:
            stage_tasks = [t for t in tasks if t.stage == stage]
            task_lines = []
            for t in stage_tasks:
                agent = agent_map.get(t.id)
                color = _rich_status_color(t.status)
                agent_str = f" [{agent.id}]" if agent else ""
                task_lines.append(f"[{color}]{t.id}[/] {t.title[:25]}{agent_str}")
            task_text = "\n".join(task_lines) if task_lines else "[dim](empty)[/]"
            pipeline_table.add_row(stage.upper(), task_text, str(len(stage_tasks)))

        layout["pipeline"].update(Panel(pipeline_table))

        # Check for pending questions (already fetched above)

        # Sidebar: agents + costs + questions (if any) + events
        if question_tasks:
            layout["sidebar"].split_column(
                Layout(name="agents"),
                Layout(name="costs", size=5),
                Layout(name="questions", size=6),
                Layout(name="events"),
            )
        else:
            layout["sidebar"].split_column(
                Layout(name="agents"),
                Layout(name="costs", size=5),
                Layout(name="events"),
            )

        # Agent table
        agent_table = Table(title="Agents", expand=True)
        agent_table.add_column("Agent", style="yellow")
        agent_table.add_column("Role")
        agent_table.add_column("Task")
        agent_table.add_column("Age", width=6)

        alive_agents = [a for a in agents if a.status == "alive"]
        for a in alive_agents:
            age = format_duration(now - a.spawned_at) if a.spawned_at else ""
            agent_table.add_row(a.id, a.role, a.current_task or "-", age)

        if not alive_agents:
            agent_table.add_row("[dim]no active agents[/]", "", "", "")

        layout["agents"].update(Panel(agent_table))

        # Token summary
        cost_summary = compute_cost_summary(project_root)
        if cost_summary.entries:
            token_text = Text()
            token_text.append(f"  In:    {cost_summary.total_input_tokens:,}\n", style="cyan")
            token_text.append(
                f"  Cache: {cost_summary.total_cache_read_tokens:,}r / {cost_summary.total_cache_write_tokens:,}w\n",
                style="dim cyan",
            )
            token_text.append(f"  Out:   {cost_summary.total_output_tokens:,}", style="green")
        else:
            token_text = Text("  (no data yet)", style="dim")
        layout["costs"].update(Panel(token_text, title="Tokens"))

        # Questions panel (if any)
        if question_tasks:
            q_table = Table(title="Questions", expand=True)
            q_table.add_column("Task", style="yellow")
            q_table.add_column("Question")
            for qt in question_tasks[:3]:
                qa_msgs = question_messages.get(qt.id, [])
                q_msgs = [m for m in qa_msgs if m.message_type == "question"]
                latest = q_msgs[-1].body[:50] if q_msgs else "?"
                q_table.add_row(qt.id, f"[bold red]{latest}[/]")
            layout["questions"].update(Panel(q_table))

        # Events table — only last 10 minutes
        max_age = 600
        recent = [e for e in events if e.created_at and (now - e.created_at) < max_age]
        event_table = Table(title="Recent Events (10 min)", expand=True)
        event_table.add_column("Age", width=6, style="dim")
        event_table.add_column("Event")
        event_table.add_column("Task")

        for event in recent[:6]:
            age = format_duration(now - event.created_at) if event.created_at else ""
            color = _rich_event_color(event.event_type)
            event_table.add_row(age, f"[{color}]{event.event_type}[/]", event.task_id or "")

        if not recent:
            event_table.add_row("[dim]-[/]", "[dim]no recent activity[/]", "")

        layout["events"].update(Panel(event_table))

        # Footer
        footer = Text(
            f" Press Ctrl+C to exit  |  Refresh: {refresh_interval}s  |  {time.strftime('%H:%M:%S')}"
        )
        layout["footer"].update(Panel(footer, style="dim"))

        return layout

    with Live(build_layout(), console=console, refresh_per_second=1, screen=True) as live:
        while running:
            time.sleep(refresh_interval)
            if running:
                try:
                    live.update(build_layout())
                except Exception:
                    pass


def _status_icon(status: str) -> str:
    return {"open": "o", "in_progress": ">", "blocked": "!", "closed": "x"}.get(status, "?")


def _event_icon(event_type: str) -> str:
    return {
        "spawn": "+",
        "advance": ">",
        "crash": "*",
        "block": "!",
        "reject": "x",
        "zombie": "z",
        "mass_death": "!!",
        "comment": "#",
    }.get(event_type, ".")


def _rich_status_color(status: str) -> str:
    return {"open": "white", "in_progress": "green", "blocked": "red", "closed": "dim"}.get(
        status, "white"
    )


def _rich_event_color(event_type: str) -> str:
    return {
        "spawn": "green",
        "advance": "cyan",
        "crash": "red bold",
        "block": "red",
        "reject": "yellow",
        "mass_death": "red bold",
    }.get(event_type, "white")
