"""Warchief CLI — WoW-themed AI agent orchestration framework."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
import uuid
from pathlib import Path

__version__ = "0.1.0"

WARCHIEF_DIR = ".warchief"
DB_NAME = "warchief.db"
CONFIG_NAME = "config.toml"

DEFAULT_CONFIG = """\
[general]
project_name = ""
pipeline = "default"

[model]
default = "claude-sonnet-4-20250514"

[limits]
max_concurrent_agents = 8
max_total_spawns = 50

[paths]
pipelines_dir = "pipelines"
roles_dir = "warchief/roles"
prompts_dir = "prompts"

# Testing — configure your project's test commands.
# Tests run automatically after code review, before PR creation.
# Leave empty to skip automated testing.
[testing]
# test_command = "npm test"          # Unit/integration tests
# test_command = "pytest"            # Python projects
# e2e_command = "npx playwright test"  # E2E / browser tests (runs only if frontend files changed)
# test_timeout = 300                 # Max seconds per test command
# auto_run = true                    # false = manual approve/reject instead of auto-run
"""


def _warchief_root() -> Path:
    return Path.cwd() / WARCHIEF_DIR


def _db_path() -> Path:
    return _warchief_root() / DB_NAME


def _config_path() -> Path:
    return _warchief_root() / CONFIG_NAME


def _ensure_initialized() -> None:
    root = _warchief_root()
    if not root.exists() or not _db_path().exists():
        print(
            "Error: Warchief is not initialized in this directory.\n"
            "Run 'warchief init' first.",
            file=sys.stderr,
        )
        sys.exit(1)


def _generate_task_id() -> str:
    return f"wc-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Lazy imports for task_store / models to avoid hard failure when they don't
# exist yet but the user is only running e.g. ``warchief version``.
# ---------------------------------------------------------------------------

def _get_store():
    """Return an opened TaskStore pointing at the project DB."""
    from warchief.task_store import TaskStore  # noqa: WPS433
    return TaskStore(_db_path())


def _task_record(**kwargs):
    from warchief.models import TaskRecord  # noqa: WPS433
    return TaskRecord(**kwargs)


def _event_record(**kwargs):
    from warchief.models import EventRecord  # noqa: WPS433
    return EventRecord(**kwargs)


def _message_record(**kwargs):
    from warchief.models import MessageRecord  # noqa: WPS433
    return MessageRecord(**kwargs)


_GITIGNORE_ENTRIES = [".warchief", ".warchief-worktrees", ".claude", "debug/"]


def _ensure_gitignore(project_root: Path) -> None:
    """Append warchief/tool entries to the project's .gitignore if missing."""
    gitignore = project_root / ".gitignore"

    existing_lines: list[str] = []
    if gitignore.exists():
        existing_lines = gitignore.read_text().splitlines()

    existing_set = set(existing_lines)
    missing = [e for e in _GITIGNORE_ENTRIES if e not in existing_set]
    if not missing:
        return

    with open(gitignore, "a") as f:
        # Add a newline separator if file exists and doesn't end with one
        if existing_lines and existing_lines[-1] != "":
            f.write("\n")
        if existing_lines:
            f.write("# Warchief / tool artifacts\n")
        for entry in missing:
            f.write(entry + "\n")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_version(_args: argparse.Namespace) -> None:
    print(f"warchief {__version__}")


def cmd_init(_args: argparse.Namespace) -> None:
    root = _warchief_root()
    root.mkdir(parents=True, exist_ok=True)

    # Write default config
    cfg = _config_path()
    if not cfg.exists():
        cfg.write_text(DEFAULT_CONFIG)

    # Create SQLite DB via TaskStore (it will create tables on first open)
    from warchief.task_store import TaskStore  # noqa: WPS433
    store = TaskStore(_db_path())
    store.close()

    # Ensure .gitignore has warchief/tool entries
    _ensure_gitignore(Path.cwd())

    print(f"Warchief initialized in {root}")
    print(f"  Database : {_db_path()}")
    print(f"  Config   : {cfg}")


def cmd_create(args: argparse.Namespace) -> None:
    _ensure_initialized()
    task_id = _generate_task_id()
    now = time.time()

    labels_list: list[str] = []
    if args.labels:
        labels_list = [lbl.strip() for lbl in args.labels.split(",") if lbl.strip()]

    deps_list: list[str] = []
    if args.deps:
        deps_list = [d.strip() for d in args.deps.split(",") if d.strip()]

    tools_list: list[str] = []
    if args.tools:
        tools_list = [t.strip() for t in args.tools.split(",") if t.strip()]

    record = _task_record(
        id=task_id,
        title=args.title,
        description=args.description or "",
        status="open",
        stage=None,
        labels=labels_list,
        deps=deps_list,
        assigned_agent=None,
        base_branch="",
        rejection_count=0,
        spawn_count=0,
        crash_count=0,
        priority=args.priority,
        type=args.type,
        extra_tools=tools_list,
        created_at=now,
        updated_at=now,
        closed_at=None,
        version=0,
    )

    store = _get_store()
    created_id = store.create_task(record)
    store.close()
    print(created_id)


def cmd_show(args: argparse.Namespace) -> None:
    _ensure_initialized()
    store = _get_store()
    task = store.get_task(args.task_id)
    store.close()

    if task is None:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(dataclasses.asdict(task), indent=2, default=str))
    else:
        _print_task_detail(task)


def _print_task_detail(task) -> None:
    labels = ", ".join(task.labels) if task.labels else "\u2014"
    deps = ", ".join(task.deps) if task.deps else "\u2014"
    stage = task.stage if task.stage else "\u2014"
    agent = task.assigned_agent if task.assigned_agent else "\u2014"

    print(f"Task:        {task.id}")
    print(f"Title:       {task.title}")
    print(f"Description: {task.description or chr(0x2014)}")
    print(f"Type:        {task.type}")
    print(f"Status:      {task.status}")
    print(f"Stage:       {stage}")
    print(f"Priority:    {task.priority}")
    print(f"Labels:      {labels}")
    print(f"Deps:        {deps}")
    print(f"Agent:       {agent}")
    tools = ", ".join(task.extra_tools) if task.extra_tools else "\u2014"
    print(f"Extra Tools: {tools}")
    print(f"Branch:      {task.base_branch or chr(0x2014)}")
    print(f"Rejections:  {task.rejection_count}")
    print(f"Spawns:      {task.spawn_count}")
    print(f"Crashes:     {task.crash_count}")
    print(f"Version:     {task.version}")
    print(f"Created:     {task.created_at}")
    print(f"Updated:     {task.updated_at}")
    if task.closed_at:
        print(f"Closed:      {task.closed_at}")


def cmd_list(args: argparse.Namespace) -> None:
    _ensure_initialized()
    store = _get_store()
    tasks = store.list_tasks(
        status=args.status,
        stage=args.stage,
        has_label=args.label,
    )
    store.close()

    if not tasks:
        print("No tasks found.")
        return

    # Table header
    id_w, status_w, stage_w = 12, 10, 18
    header = (
        f"{'ID':<{id_w}}"
        f"{'Status':<{status_w}}"
        f"{'Stage':<{stage_w}}"
        f"Title"
    )
    print(header)
    for task in tasks:
        stage = task.stage if task.stage else "\u2014"
        row = (
            f"{task.id:<{id_w}}"
            f"{task.status:<{status_w}}"
            f"{stage:<{stage_w}}"
            f"{task.title}"
        )
        print(row)


def cmd_update(args: argparse.Namespace) -> None:
    _ensure_initialized()
    store = _get_store()
    task = store.get_task(args.task_id)
    if task is None:
        store.close()
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    updates: dict = {}
    if args.status:
        updates["status"] = args.status
    if args.add_label:
        current = list(task.labels) if task.labels else []
        if args.add_label not in current:
            current.append(args.add_label)
        updates["labels"] = current
    if args.remove_label:
        current = updates.get("labels", list(task.labels) if task.labels else [])
        if args.remove_label in current:
            current.remove(args.remove_label)
        updates["labels"] = current

    if updates:
        store.update_task(args.task_id, **updates)

    if args.comment:
        event = _event_record(
            event_type="comment",
            task_id=args.task_id,
            agent_id=None,
            details={"text": args.comment},
            actor="cli",
            created_at=time.time(),
        )
        store.log_event(event)

    store.close()
    print(f"Task {args.task_id} updated.")


def cmd_tell(args: argparse.Namespace) -> None:
    """Send a message to a task. The next agent spawned will see it."""
    _ensure_initialized()
    from warchief.control import _do_tell
    _do_tell(Path.cwd(), args.task_id, args.message)


def cmd_nudge(args: argparse.Namespace) -> None:
    """Send a message and restart the agent so it sees it immediately."""
    _ensure_initialized()
    from warchief.control import _do_nudge
    _do_nudge(Path.cwd(), args.task_id, args.message)


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve a task after manual Playwright testing."""
    _ensure_initialized()
    from warchief.control import _do_approve
    _do_approve(Path.cwd(), args.task_id)


def cmd_reject(args: argparse.Namespace) -> None:
    """Reject a task after manual testing — sends back to development."""
    _ensure_initialized()
    from warchief.control import _do_reject
    _do_reject(Path.cwd(), args.task_id, args.feedback)


def cmd_retry(args: argparse.Namespace) -> None:
    """Reopen a closed/blocked task with feedback and send it back to development."""
    _ensure_initialized()
    store = _get_store()
    task = store.get_task(args.task_id)
    if task is None:
        store.close()
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    # Reset task to development with clean counters
    new_labels = [l for l in task.labels
                  if not l.startswith("stage:") and l not in ("rejected", "question")]
    new_labels.append("stage:development")

    store.update_task(
        args.task_id,
        status="open",
        stage="development",
        labels=new_labels,
        assigned_agent=None,
        spawn_count=0,
        crash_count=0,
    )

    # Store feedback as a message so the next agent sees it
    feedback = args.feedback
    if feedback:
        import uuid as _uuid
        msg = _message_record(
            id=f"msg-{_uuid.uuid4().hex[:8]}",
            from_agent="user",
            to_agent=args.task_id,
            message_type="feedback",
            body=feedback,
            persistent=True,
            created_at=time.time(),
        )
        store.create_message(msg)

    # Log the retry event
    store.log_event(_event_record(
        event_type="retry",
        task_id=args.task_id,
        details={"feedback": feedback or "", "previous_stage": task.stage or ""},
        actor="cli",
        created_at=time.time(),
    ))

    store.close()
    print(f"Task {args.task_id} reopened in development.")
    if feedback:
        print(f"Feedback: {feedback}")
    print("The agent will see your feedback when it re-spawns.")


def cmd_release(args: argparse.Namespace) -> None:
    _ensure_initialized()
    store = _get_store()
    task = store.get_task(args.task_id)
    if task is None:
        store.close()
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    store.update_task(args.task_id, stage=args.stage)
    store.close()
    print(f"Task {args.task_id} released to stage '{args.stage}'.")


def cmd_config(args: argparse.Namespace) -> None:
    _ensure_initialized()
    import tomllib  # noqa: WPS433

    cfg_path = _config_path()

    if args.key is None:
        # Show all config
        print(cfg_path.read_text())
        return

    data = tomllib.loads(cfg_path.read_text())

    if args.value is None:
        # Get a single value -- support dotted keys like "model.default"
        parts = args.key.split(".")
        node = data
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                print(f"Error: Key '{args.key}' not found.", file=sys.stderr)
                sys.exit(1)
        print(node)
        return

    # Set a value -- rewrite the TOML naively (line-level replacement).
    parts = args.key.split(".")
    if len(parts) != 2:
        print(
            "Error: Config key must be in 'section.key' format (e.g. model.default).",
            file=sys.stderr,
        )
        sys.exit(1)

    section, key = parts
    lines = cfg_path.read_text().splitlines(keepends=True)
    in_section = False
    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
        if in_section and (stripped.startswith(f"{key} =") or stripped.startswith(f"{key}=")):
            new_lines.append(f'{key} = "{args.value}"\n')
            found = True
        else:
            new_lines.append(line)

    if not found:
        print(f"Error: Key '{args.key}' not found in config.", file=sys.stderr)
        sys.exit(1)

    cfg_path.write_text("".join(new_lines))
    print(f"Set {args.key} = {args.value}")


def cmd_watch(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.config import read_config, setup_logging
    from warchief.roles import RoleRegistry
    from warchief.watcher import Watcher

    project_root = Path.cwd()
    setup_logging(project_root)
    config = read_config(project_root)
    registry = RoleRegistry(Path(__file__).parent / "roles")
    store = _get_store()

    watcher = Watcher(project_root, store, config, registry, verbose=True)
    print("Watcher started. Press Ctrl+C to stop.")
    try:
        watcher.start()
    finally:
        store.close()


def cmd_stop(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    import signal
    lock_path = _warchief_root() / "watcher.lock"
    if not lock_path.exists():
        print("No watcher running.")
        return
    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to watcher (PID {pid})")
    except (ValueError, ProcessLookupError, PermissionError) as e:
        print(f"Could not stop watcher: {e}")


def cmd_pause(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.config import Config, read_config, write_config
    project_root = Path.cwd()
    config = read_config(project_root)
    config.paused = True
    write_config(project_root, config)
    print("Pipeline paused. The watcher will skip ticks until resumed.")


def cmd_resume(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.config import Config, read_config, write_config
    project_root = Path.cwd()
    config = read_config(project_root)
    config.paused = False
    write_config(project_root, config)
    print("Pipeline resumed.")


def cmd_status(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    store = _get_store()
    running = store.get_running_agents()
    tasks = store.list_tasks()
    store.close()

    open_count = sum(1 for t in tasks if t.status == "open")
    in_progress = sum(1 for t in tasks if t.status == "in_progress")
    blocked = sum(1 for t in tasks if t.status == "blocked")
    closed = sum(1 for t in tasks if t.status == "closed")

    print(f"Tasks:  {len(tasks)} total | {open_count} open | {in_progress} in progress | {blocked} blocked | {closed} closed")
    print(f"Agents: {len(running)} running")
    if running:
        for a in running:
            print(f"  {a.id} ({a.role}) -> {a.current_task or 'idle'} [{a.status}]")

    lock_path = _warchief_root() / "watcher.lock"
    if lock_path.exists():
        print(f"Watcher: running (PID {lock_path.read_text().strip()})")
    else:
        print("Watcher: not running")


def cmd_kill_agent(args: argparse.Namespace) -> None:
    _ensure_initialized()
    import signal as sig
    store = _get_store()
    agent = store.get_agent(args.name)
    if agent is None:
        store.close()
        print(f"Agent '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)
    if agent.pid:
        try:
            os.kill(agent.pid, sig.SIGTERM)
            print(f"Sent SIGTERM to {args.name} (PID {agent.pid})")
        except (ProcessLookupError, PermissionError) as e:
            print(f"Could not kill: {e}")
    store.update_agent(args.name, status="dead")
    # Reset the task so it can be picked up again
    if agent.current_task:
        task = store.get_task(agent.current_task)
        if task and task.status in ("in_progress", "open"):
            store.update_task(task.id, status="open", assigned_agent=None)
            print(f"Reset task {task.id} to open")
    store.close()


def cmd_start(args: argparse.Namespace) -> None:
    _ensure_initialized()

    # Launch tmux UI if available and not opted out
    no_tmux = getattr(args, "no_tmux", False)
    if not no_tmux:
        from warchief.tmux_ui import is_tmux_available, is_in_tmux
        if is_tmux_available() and not is_in_tmux():
            from warchief.tmux_ui import launch_ui
            # Do the conductor/task setup first, then launch tmux with just the watcher
            _start_setup_tasks(args)
            launch_ui(Path.cwd())
            return

    # Non-tmux path: setup tasks + run watcher inline
    _start_setup_tasks(args)

    from warchief.config import read_config, setup_logging
    from warchief.roles import RoleRegistry
    from warchief.watcher import Watcher

    project_root = Path.cwd()
    setup_logging(project_root)
    config = read_config(project_root)
    registry = RoleRegistry(Path(__file__).parent / "roles")
    store = _get_store()

    watcher = Watcher(project_root, store, config, registry, verbose=True)
    print("Warchief started. Pipeline is running. Press Ctrl+C to stop.")
    try:
        watcher.start()
    finally:
        store.close()


def _start_setup_tasks(args: argparse.Namespace) -> None:
    """Create tasks from requirement and release into pipeline.

    Shared by both tmux and non-tmux start paths.
    """
    from warchief.config import read_config, setup_logging
    from warchief.hooks import install_hooks
    from warchief.pipeline_checker import release_ready
    from warchief.pipeline_template import load_pipeline

    project_root = Path.cwd()
    setup_logging(project_root)
    config = read_config(project_root)
    store = _get_store()

    install_hooks(project_root)
    base = config.base_branch or "main"

    # If a requirement is given, run conductor to decompose it
    requirement = getattr(args, "requirement", None)
    if requirement:
        existing = store.list_tasks()
        dupes = [t for t in existing if t.title == requirement and t.status != "closed"]
        if dupes:
            print(f"Task already exists: {dupes[0].id} ({dupes[0].status})")
            print("Use 'warchief start' (no argument) to resume the pipeline.")
            store.close()
            return

        no_conductor = getattr(args, "no_conductor", False)

        if no_conductor:
            task_id = _generate_task_id()
            now = time.time()
            record = _task_record(
                id=task_id, title=requirement,
                description=requirement,
                status="open", stage=None, labels=[],
                deps=[], assigned_agent=None, base_branch=base,
                rejection_count=0, spawn_count=0, crash_count=0,
                priority=5, type="feature",
                created_at=now, updated_at=now, closed_at=None, version=0,
            )
            store.create_task(record)
            print(f"Created task {task_id}: {requirement}")
        else:
            from warchief.conductor import run_conductor
            print(f"Requirement: {requirement}")
            print()
            created = run_conductor(
                requirement=requirement,
                project_root=project_root,
                store=store,
                config=config,
                base_branch=base,
                on_status=lambda msg: print(f"  {msg}"),
            )
            if not created:
                print("Conductor failed to decompose. Falling back to single task.")
                task_id = _generate_task_id()
                now = time.time()
                record = _task_record(
                    id=task_id, title=requirement,
                    description=requirement,
                    status="open", stage=None, labels=[],
                    deps=[], assigned_agent=None, base_branch=base,
                    rejection_count=0, spawn_count=0, crash_count=0,
                    priority=5, type="feature",
                    created_at=now, updated_at=now, closed_at=None, version=0,
                )
                store.create_task(record)
                print(f"Created task {task_id}: {requirement}")
            print()

    # Load default pipeline and release unstaged tasks
    pipeline_path = project_root / "pipelines" / "default.toml"
    if not pipeline_path.exists():
        pipeline_path = Path(__file__).parent.parent / "pipelines" / "default.toml"
    pipeline = load_pipeline(pipeline_path)
    released = release_ready(store, pipeline)
    for t in released:
        print(f"Released {t.id} into pipeline")

    store.close()


def cmd_board(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.board import render_board
    store = _get_store()
    output = render_board(store)
    store.close()
    print(output)


def cmd_metrics(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.metrics import compute_pipeline_metrics, format_duration
    store = _get_store()
    m = compute_pipeline_metrics(store)
    store.close()

    print(f"Pipeline Metrics")
    print(f"{'=' * 50}")
    print(f"Total tasks:       {m.total_tasks}")
    print(f"  Open:            {m.open_tasks}")
    print(f"  In progress:     {m.in_progress_tasks}")
    print(f"  Blocked:         {m.blocked_tasks}")
    print(f"  Closed:          {m.closed_tasks}")
    print(f"Agents spawned:    {m.total_agents_spawned}")
    print(f"Total rejections:  {m.total_rejections}")
    print(f"Total crashes:     {m.total_crashes}")
    if m.avg_completion_time > 0:
        print(f"Avg completion:    {format_duration(m.avg_completion_time)}")

    if m.stage_metrics:
        print(f"\nPer-Stage Breakdown")
        print(f"{'-' * 50}")
        for sm in m.stage_metrics:
            print(f"  {sm.stage}: {sm.total_tasks} tasks, "
                  f"{sm.rejection_count} rejections, {sm.crash_count} crashes")


def cmd_logs(args: argparse.Namespace) -> None:
    _ensure_initialized()
    agent_name = args.agent
    log_path = _warchief_root() / "agent-logs" / f"{agent_name}.log"

    if args.events:
        # Show event-based logs (old behavior)
        from warchief.diagnostics import get_agent_log
        store = _get_store()
        entries = get_agent_log(store, agent_name, limit=50)
        store.close()
        if not entries:
            print(f"No event entries for agent '{agent_name}'.")
            return
        for e in entries:
            print(f"  {e['event_type']:<18} {e['task_id'] or '':<14} {e['details']}")
        return

    if not log_path.exists():
        # List available logs
        logs_dir = _warchief_root() / "agent-logs"
        if logs_dir.exists():
            available = [f.stem for f in sorted(logs_dir.glob("*.log"))]
            if available:
                print(f"Agent '{agent_name}' has no log. Available logs:")
                for name in available:
                    size = (logs_dir / f"{name}.log").stat().st_size
                    print(f"  {name} ({size / 1024:.1f} KB)")
                return
        print(f"No logs found for agent '{agent_name}'.")
        return

    if args.follow:
        # Live tail with follow
        import subprocess
        try:
            subprocess.run(["tail", "-f", str(log_path)])
        except KeyboardInterrupt:
            pass
        return

    # Show last N lines
    lines = args.lines or 50
    content = log_path.read_text()
    output_lines = content.split("\n")
    if len(output_lines) > lines:
        output_lines = output_lines[-lines:]
        print(f"... (showing last {lines} lines, use --lines N for more)\n")
    print("\n".join(output_lines))


def cmd_attach(_args: argparse.Namespace) -> None:
    """Open a tmux session with panes tailing each active agent's output."""
    _ensure_initialized()
    import shutil
    import subprocess

    if not shutil.which("tmux"):
        print("tmux is not installed. Install it with: brew install tmux")
        print("\nAlternatively, use 'warchief logs <agent> -f' to tail a single agent.")
        return

    store = _get_store()
    agents = store.get_running_agents()
    alive = [a for a in agents if a.status == "alive"]
    store.close()

    logs_dir = _warchief_root() / "agent-logs"

    if not alive:
        # Show any recent logs instead
        if logs_dir.exists():
            available = sorted(logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
            if available:
                print("No active agents. Recent logs:")
                for f in available[:10]:
                    size = f.stat().st_size
                    print(f"  warchief logs {f.stem} -f   ({size / 1024:.1f} KB)")
                return
        print("No active agents and no logs found.")
        return

    session_name = "warchief"

    # Kill existing warchief tmux session if any
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True)

    # Create new session with first agent
    first = alive[0]
    first_log = logs_dir / f"{first.id}.log"
    first_cmd = f"tail -f {first_log}" if first_log.exists() else f"echo 'Waiting for {first.id} output...' && sleep 3 && tail -f {first_log}"

    subprocess.run([
        "tmux", "new-session", "-d", "-s", session_name,
        "-n", first.id, first_cmd,
    ])

    # Add panes for remaining agents
    for agent in alive[1:]:
        agent_log = logs_dir / f"{agent.id}.log"
        tail_cmd = f"tail -f {agent_log}" if agent_log.exists() else f"echo 'Waiting for {agent.id}...' && sleep 3 && tail -f {agent_log}"
        subprocess.run([
            "tmux", "split-window", "-t", session_name, "-v", tail_cmd,
        ])

    # Add a status pane at the bottom
    wc_cmd = shutil.which("warchief") or "warchief"
    subprocess.run([
        "tmux", "split-window", "-t", session_name, "-v",
        "-l", "8",  # 8 lines tall
        f"watch -n 5 '{wc_cmd} board'",
    ])

    # Even out the panes
    subprocess.run(["tmux", "select-layout", "-t", session_name, "tiled"])

    # Attach
    print(f"Attaching to tmux session '{session_name}' with {len(alive)} agent(s)...")
    print("Tip: Ctrl+B then D to detach, Ctrl+B then arrow keys to switch panes")
    os.execvp("tmux", ["tmux", "attach-session", "-t", session_name])


def cmd_drop(args: argparse.Namespace) -> None:
    """Drop a task entirely — kill its agent, close the task, clean up."""
    _ensure_initialized()
    import signal as sig
    from warchief.worktree import remove_worktree

    store = _get_store()
    task = store.get_task(args.task_id)
    if task is None:
        store.close()
        print(f"Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    project_root = Path.cwd()

    # Kill assigned agent if alive
    if task.assigned_agent:
        agent = store.get_agent(task.assigned_agent)
        if agent:
            if agent.pid and agent.status == "alive":
                try:
                    os.kill(agent.pid, sig.SIGTERM)
                    print(f"  Killed agent {agent.id} (PID {agent.pid})")
                except (ProcessLookupError, PermissionError):
                    pass
            store.update_agent(agent.id, status="dead")
            # Clean up worktree
            if agent.worktree_path:
                try:
                    remove_worktree(project_root, agent.id)
                    print(f"  Removed worktree for {agent.id}")
                except Exception:
                    pass

    # Close the task
    store.update_task(task.id, status="closed", assigned_agent=None)

    # Clean up agent log files for this task
    logs_dir = _warchief_root() / "agent-logs"
    cleaned = 0
    if logs_dir.exists():
        for prompt_file in logs_dir.glob("*.prompt"):
            try:
                if task.id in prompt_file.read_text():
                    stem = prompt_file.stem
                    for ext in (".prompt", ".log", ".usage.json"):
                        f = logs_dir / f"{stem}{ext}"
                        if f.exists():
                            f.unlink()
                            cleaned += 1
            except (OSError, UnicodeDecodeError):
                continue

    # Remove messages for this task
    store._conn.execute(
        "DELETE FROM messages WHERE from_agent = ? OR to_agent = ?",
        (task.id, task.id),
    )
    store._conn.commit()
    store.close()

    print(f"Dropped task {task.id} \"{task.title}\" ({cleaned} log files cleaned)")


def cmd_grant(args: argparse.Namespace) -> None:
    """Grant MCP tools to a task using natural language or exact patterns."""
    _ensure_initialized()
    from warchief.mcp_discovery import get_mcp_servers, resolve_tool_grant

    store = _get_store()
    task = store.get_task(args.task_id)
    if task is None:
        store.close()
        print(f"Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    # If --list, show available MCP servers
    if args.list_servers:
        servers = get_mcp_servers()
        if not servers:
            print("No MCP servers configured in ~/.claude.json")
        else:
            print("Available MCP servers:")
            for name, pattern in sorted(servers.items()):
                print(f"  {name:<25} → {pattern}")
        store.close()
        return

    if not args.tools_text:
        print("Error: provide tools to grant (e.g. 'figma console' or 'mcp__figma__*')", file=sys.stderr)
        store.close()
        sys.exit(1)

    tools_text = " ".join(args.tools_text)

    # Try natural language resolution first
    resolved = resolve_tool_grant(tools_text)

    # If no match, treat as exact pattern(s)
    if not resolved:
        resolved = [t.strip() for t in tools_text.split(",") if t.strip()]

    existing = list(task.extra_tools)
    new_tools = [t for t in resolved if t not in existing]
    if new_tools:
        store.update_task(args.task_id, extra_tools=existing + new_tools)
        for t in new_tools:
            print(f"  + {t}")
        print(f"Granted {len(new_tools)} tool(s) to {args.task_id}")
    else:
        print("All requested tools already granted.")

    store.close()


def cmd_purge(args: argparse.Namespace) -> None:
    """Clean up old data: closed tasks, dead agents, stale events, orphan logs."""
    _ensure_initialized()
    store = _get_store()

    keep_events = args.keep_events
    removed_tasks = 0
    removed_agents = 0
    removed_events = 0
    removed_logs = 0

    # Remove closed tasks (unless --keep-closed)
    if not args.keep_closed:
        tasks = store.list_tasks()
        for t in tasks:
            if t.status == "closed":
                store._conn.execute("DELETE FROM tasks WHERE id = ?", (t.id,))
                removed_tasks += 1

    # Remove dead/zombie agents
    agents = store._conn.execute(
        "SELECT id FROM agents WHERE status IN ('dead', 'zombie')"
    ).fetchall()
    for (aid,) in agents:
        store._conn.execute("DELETE FROM agents WHERE id = ?", (aid,))
        removed_agents += 1

    # Trim events to last N
    total_events = store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    if total_events > keep_events:
        store._conn.execute(
            """DELETE FROM events WHERE id NOT IN (
                SELECT id FROM events ORDER BY created_at DESC LIMIT ?
            )""", (keep_events,),
        )
        removed_events = total_events - keep_events

    store._conn.commit()
    store.close()

    # Clean up agent log files for agents that no longer exist
    logs_dir = _warchief_root() / "agent-logs"
    if logs_dir.exists():
        active_store = _get_store()
        all_agents = {r[0] for r in active_store._conn.execute("SELECT id FROM agents").fetchall()}
        active_store.close()
        for log_file in logs_dir.glob("*.log"):
            if log_file.stem not in all_agents:
                log_file.unlink()
                removed_logs += 1
        # Also clean prompt files
        for prompt_file in logs_dir.glob("*.prompt"):
            if prompt_file.stem not in all_agents:
                prompt_file.unlink()

    print(f"Purged: {removed_tasks} closed task(s), {removed_agents} dead agent(s), "
          f"{removed_events} old event(s), {removed_logs} stale log file(s)")


def cmd_feed(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.feed import render_feed
    store = _get_store()
    print(render_feed(store))
    store.close()


def cmd_backup(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.backup import create_backup
    store = _get_store()
    path = create_backup(Path.cwd(), store)
    store.close()
    print(f"Backup created: {path}")


def cmd_restore(args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.backup import list_backups, restore_backup
    store = _get_store()

    if hasattr(args, "file") and args.file:
        backup_path = Path(args.file)
    else:
        backups = list_backups(Path.cwd())
        if not backups:
            print("No backups found.", file=sys.stderr)
            store.close()
            sys.exit(1)
        backup_path = backups[0]  # Most recent
        print(f"Restoring from: {backup_path}")

    counts = restore_backup(Path.cwd(), store, backup_path)
    store.close()
    print(f"Restored: {counts['tasks']} tasks, {counts['events']} events, {counts['agents']} agents")


def cmd_daemon(args: argparse.Namespace) -> None:
    _ensure_initialized()
    action = args.action if hasattr(args, "action") else "status"

    if action == "start":
        from warchief.daemon import Daemon
        daemon = Daemon(Path.cwd())
        fg = hasattr(args, "foreground") and args.foreground
        print("Starting daemon..." + (" (foreground)" if fg else ""))
        daemon.start(foreground=fg)
    elif action == "stop":
        from warchief.daemon import stop_daemon
        if stop_daemon(Path.cwd()):
            print("Daemon stopped.")
        else:
            print("No daemon running.")
    elif action == "status":
        from warchief.daemon import daemon_status
        from warchief.metrics import format_duration
        s = daemon_status(Path.cwd())
        if s["running"]:
            age = ""
            if s["last_heartbeat"]:
                import time
                age = f" (last heartbeat {format_duration(time.time() - s['last_heartbeat'])} ago)"
            print(f"Daemon running (PID {s['pid']}){age}")
        else:
            print("Daemon not running.")


def cmd_doctor(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.doctor import format_report, run_doctor
    report = run_doctor(Path.cwd())
    print(format_report(report))


def cmd_sessions(_args: argparse.Namespace) -> None:
    from warchief.sessions import get_active_sessions, list_sessions
    sessions = list_sessions()
    active = get_active_sessions()
    active_roots = {s.project_root for s in active}

    if not sessions:
        print("No known sessions.")
        return

    print(f"{'Project':<30} {'Status':<10} {'PID':<8} Root")
    for s in sessions:
        is_active = s.project_root in active_roots
        status = "active" if is_active else "stopped"
        pid = str(s.pid) if s.pid else "—"
        print(f"{s.project_name:<30} {status:<10} {pid:<8} {s.project_root}")


def cmd_connect(args: argparse.Namespace) -> None:
    from warchief.sessions import get_active_sessions
    active = get_active_sessions()
    if not active:
        print("No active sessions to connect to.")
        return

    target = args.session
    if target:
        matches = [s for s in active if target in s.project_name or target in s.project_root]
        if not matches:
            print(f"No active session matching '{target}'.")
            return
        session = matches[0]
    else:
        if len(active) == 1:
            session = active[0]
        else:
            print("Multiple active sessions — specify which one:")
            for i, s in enumerate(active, 1):
                print(f"  {i}. {s.project_name} ({s.project_root})")
            return

    print(f"Session: {session.project_name}")
    print(f"  Root: {session.project_root}")
    print(f"  PID:  {session.pid}")
    print(f"  Use: cd {session.project_root} && warchief status")


def cmd_dashboard(args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.dashboard import render_dashboard_snapshot, run_dashboard
    if args.snapshot:
        print(render_dashboard_snapshot(Path.cwd()))
    else:
        run_dashboard(Path.cwd(), refresh_interval=args.refresh)


def cmd_costs(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.cost_tracker import compute_cost_summary, format_cost_summary
    summary = compute_cost_summary(Path.cwd())
    print(format_cost_summary(summary))


def cmd_observe(_args: argparse.Namespace) -> None:
    _ensure_initialized()
    from warchief.observability import export_metrics_file, format_metrics_summary
    store = _get_store()
    print(format_metrics_summary(store))
    path = export_metrics_file(store, Path.cwd())
    store.close()
    print(f"\nMetrics exported to: {path}")


def _find_project_root() -> Path:
    """Walk up from cwd looking for a .warchief directory (or symlink)."""
    p = Path.cwd().resolve()
    while True:
        if (p / ".warchief").exists():
            return p
        parent = p.parent
        if parent == p:
            break
        p = parent
    # Fallback: assume cwd
    return Path.cwd()


def cmd_agent_update(args: argparse.Namespace) -> None:
    """Update task status (for use by agents)."""
    from warchief.task_store import TaskStore  # noqa: WPS433

    project_root = _find_project_root()
    db_path = project_root / ".warchief" / "warchief.db"
    store = TaskStore(db_path)
    try:
        task_id = args.task_id or os.environ.get("WARCHIEF_TASK")
        if not task_id:
            print("Error: No task ID. Set WARCHIEF_TASK or pass --task-id", file=sys.stderr)
            sys.exit(1)

        task = store.get_task(task_id)
        if not task:
            print(f"Error: Task {task_id} not found", file=sys.stderr)
            sys.exit(1)

        updates: dict = {}
        if args.status:
            # Base allowed statuses for all agents
            allowed = {"open", "blocked"}
            # Integrators, testers, and PR creators can also set "closed"
            role = os.environ.get("WARCHIEF_ROLE", "")
            if role in ("integrator", "tester", "pr_creator"):
                allowed.add("closed")
            if args.status not in allowed:
                print(f"Error: Agents can only set status to: {', '.join(sorted(allowed))}", file=sys.stderr)
                sys.exit(1)
            updates["status"] = args.status

        if args.comment:
            # Log the comment as an event
            from warchief.models import EventRecord  # noqa: WPS433
            agent_id = os.environ.get("WARCHIEF_AGENT", "unknown")
            store.log_event(EventRecord(
                event_type="comment",
                task_id=task_id,
                agent_id=agent_id,
                details={"comment": args.comment},
                actor=agent_id,
            ))
            print(f"Comment logged for {task_id}")

        if args.add_label:
            current = list(task.labels)
            # Agents can only add: rejected
            if args.add_label == "rejected":
                if "rejected" not in current:
                    current.append("rejected")
                updates["labels"] = current
                updates["rejection_count"] = task.rejection_count + 1
            else:
                print("Error: Agents can only add 'rejected' label", file=sys.stderr)
                sys.exit(1)

        if getattr(args, "question", None):
            from warchief.models import EventRecord, MessageRecord  # noqa: WPS433
            agent_id = os.environ.get("WARCHIEF_AGENT", task_id)
            # Force status to blocked
            updates["status"] = "blocked"
            # Add "question" label
            current = list(updates.get("labels", task.labels))
            if "question" not in current:
                current.append("question")
            updates["labels"] = current
            # Store question as a message
            store.create_message(MessageRecord(
                id="",
                from_agent=task_id,
                to_agent="user",
                message_type="question",
                body=args.question,
                persistent=True,
            ))
            # Log event
            store.log_event(EventRecord(
                event_type="question",
                task_id=task_id,
                agent_id=agent_id,
                details={"question": args.question},
                actor=agent_id,
            ))
            print(f"Question recorded for {task_id}: {args.question}")

        if updates:
            store.update_task(task_id, **updates)
            print(f"Updated {task_id}: {updates}")
    finally:
        store.close()


def cmd_answer(args: argparse.Namespace) -> None:
    """Answer a pending agent question."""
    _ensure_initialized()
    from warchief.models import EventRecord, MessageRecord  # noqa: WPS433
    store = _get_store()
    try:
        task = store.get_task(args.task_id)
        if not task:
            print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
            sys.exit(1)
        if "question" not in task.labels:
            print(f"Error: Task '{args.task_id}' has no pending question.", file=sys.stderr)
            sys.exit(1)

        # Store answer as a message
        store.create_message(MessageRecord(
            id="",
            from_agent="user",
            to_agent=args.task_id,
            message_type="answer",
            body=args.answer_text,
            persistent=True,
        ))

        # Check if the answer is granting MCP tool permissions
        from warchief.mcp_discovery import is_tool_grant, resolve_tool_grant
        granted_tools: list[str] = []
        if is_tool_grant(args.answer_text):
            granted_tools = resolve_tool_grant(args.answer_text)
            if granted_tools:
                existing = list(task.extra_tools)
                new_tools = [t for t in granted_tools if t not in existing]
                if new_tools:
                    store.update_task(args.task_id, extra_tools=existing + new_tools)
                    print(f"Granted tools: {', '.join(new_tools)}")

        # Remove "question" label and set status to open
        new_labels = [l for l in task.labels if l != "question"]
        store.update_task(args.task_id, status="open", labels=new_labels)

        # Log event
        store.log_event(EventRecord(
            event_type="answer",
            task_id=args.task_id,
            details={"answer": args.answer_text, "granted_tools": granted_tools},
            actor="user",
        ))
        print(f"Answer recorded for {args.task_id}. Task unblocked.")
    finally:
        store.close()


def cmd_questions(_args: argparse.Namespace) -> None:
    """List all pending agent questions."""
    _ensure_initialized()
    store = _get_store()
    try:
        tasks = store.list_tasks(has_label="question")
        if not tasks:
            print("No pending questions.")
            return

        print("Pending Questions:")
        for task in tasks:
            # Get the latest question message for this task
            messages = store.get_task_messages(task.id)
            questions = [m for m in messages if m.message_type == "question"]
            latest_q = questions[-1].body if questions else "(no question text)"
            print(f'  {task.id} "{task.title}"')
            print(f"    Q: {latest_q}")
            print(f'    \u2192 Answer with: warchief answer {task.id} "your answer"')
    finally:
        store.close()


def cmd_agent_monitor(_args: argparse.Namespace) -> None:
    """Run the live agent log viewer (used by tmux UI)."""
    _ensure_initialized()
    from warchief.agent_monitor import run_monitor
    run_monitor(Path.cwd())


def cmd_control(_args: argparse.Namespace) -> None:
    """Run the interactive control pane (used by tmux UI)."""
    _ensure_initialized()
    from warchief.control import run_control
    run_control(Path.cwd())


def _skeleton(phase: int):
    """Return a handler that prints a 'not yet implemented' message."""
    def handler(_args: argparse.Namespace) -> None:
        print(f"Not yet implemented \u2014 Phase {phase}")
    return handler


# ---------------------------------------------------------------------------
# Argument parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warchief",
        description="Warchief \u2014 WoW-themed AI agent orchestration framework",
    )
    sub = parser.add_subparsers(dest="command")

    # version
    sub.add_parser("version", help="Print version")

    # init
    sub.add_parser("init", help="Initialize Warchief in the current directory")

    # create
    p_create = sub.add_parser("create", help="Create a new task")
    p_create.add_argument("title", help="Task title")
    p_create.add_argument("--description", default="", help="Task description")
    p_create.add_argument(
        "--type",
        default="feature",
        choices=["feature", "bug", "investigation"],
        help="Task type (default: feature)",
    )
    p_create.add_argument("--labels", default="", help="Comma-separated labels")
    p_create.add_argument("--deps", default="", help="Comma-separated dependency task IDs")
    p_create.add_argument("--priority", type=int, default=5, help="Priority 1-10 (default: 5)")
    p_create.add_argument("--tools", default="", help="Extra tools for agents (comma-separated, e.g. 'mcp__figma-console__*,mcp__figma__*')")

    # show
    p_show = sub.add_parser("show", help="Show task details")
    p_show.add_argument("task_id", help="Task ID")
    p_show.add_argument("--json", action="store_true", help="Output as JSON")

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--status", default=None, help="Filter by status")
    p_list.add_argument("--stage", default=None, help="Filter by stage")
    p_list.add_argument("--label", default=None, help="Filter by label")

    # update
    p_update = sub.add_parser("update", help="Update a task")
    p_update.add_argument("task_id", help="Task ID")
    p_update.add_argument("--status", default=None, help="New status")
    p_update.add_argument("--add-label", default=None, help="Add a label")
    p_update.add_argument("--remove-label", default=None, help="Remove a label")
    p_update.add_argument("--comment", default=None, help="Log a comment event")

    # tell
    p_tell = sub.add_parser("tell", help="Send a message to a task (next agent sees it)")
    p_tell.add_argument("task_id", help="Task ID")
    p_tell.add_argument("message", help="Message for the agent")

    # nudge
    p_nudge = sub.add_parser("nudge", help="Send a message and restart the agent immediately")
    p_nudge.add_argument("task_id", help="Task ID")
    p_nudge.add_argument("message", help="Message for the agent")

    # retry
    p_retry = sub.add_parser("retry", help="Reopen a task with feedback and send back to development")
    p_retry.add_argument("task_id", help="Task ID")
    p_retry.add_argument("feedback", help="Feedback for the agent (what to do differently)")

    # approve (after manual testing)
    p_approve = sub.add_parser("approve", help="Approve a task after manual Playwright testing")
    p_approve.add_argument("task_id", help="Task ID")

    # reject (after manual testing)
    p_reject = sub.add_parser("reject", help="Reject a task after testing (back to development)")
    p_reject.add_argument("task_id", help="Task ID")
    p_reject.add_argument("feedback", help="Feedback for the developer")

    # release
    p_release = sub.add_parser("release", help="Release task into a pipeline stage")
    p_release.add_argument("task_id", help="Task ID")
    p_release.add_argument("--stage", required=True, help="Pipeline stage name")

    # config
    p_config = sub.add_parser("config", help="Get/set configuration values")
    p_config.add_argument("key", nargs="?", default=None, help="Config key (section.key)")
    p_config.add_argument("value", nargs="?", default=None, help="Value to set")

    # Skeleton commands
    p_start = sub.add_parser("start", help="Start processing a requirement")
    p_start.add_argument("requirement", nargs="?", default=None)
    p_start.add_argument("--no-conductor", action="store_true",
                         help="Skip conductor decomposition, create a single task")
    p_start.add_argument("--no-tmux", action="store_true",
                         help="Run without tmux UI (plain terminal mode)")

    sub.add_parser("watch", help="Watch the pipeline")
    sub.add_parser("board", help="Show task board")
    sub.add_parser("stop", help="Stop the pipeline")
    sub.add_parser("pause", help="Pause the pipeline")
    sub.add_parser("resume", help="Resume the pipeline")

    p_grant = sub.add_parser("grant", help="Grant MCP tools to a task (e.g. 'figma console')")
    p_grant.add_argument("task_id", help="Task ID")
    p_grant.add_argument("tools_text", nargs="*", help="Tools to grant (natural language or exact patterns)")
    p_grant.add_argument("--list", dest="list_servers", action="store_true", help="List available MCP servers")

    p_drop = sub.add_parser("drop", help="Drop a task — kill agent, close task, clean up")
    p_drop.add_argument("task_id", help="Task ID to drop")

    p_kill = sub.add_parser("kill-agent", help="Kill a running agent")
    p_kill.add_argument("name", help="Agent name")

    sub.add_parser("status", help="Show pipeline status")

    p_logs = sub.add_parser("logs", help="Show agent output")
    p_logs.add_argument("agent", help="Agent name (e.g. developer-thrall)")
    p_logs.add_argument("-f", "--follow", action="store_true",
                        help="Follow log output in real-time (like tail -f)")
    p_logs.add_argument("-n", "--lines", type=int, default=50,
                        help="Number of lines to show (default: 50)")
    p_logs.add_argument("--events", action="store_true",
                        help="Show pipeline events instead of agent output")

    sub.add_parser("attach", help="Open tmux with live agent output")

    p_purge = sub.add_parser("purge", help="Clean up old tasks, agents, events, logs")
    p_purge.add_argument("--keep-events", type=int, default=50,
                         help="Keep last N events (default: 50)")
    p_purge.add_argument("--keep-closed", action="store_true",
                         help="Don't delete closed tasks")
    sub.add_parser("feed", help="Show activity feed")
    sub.add_parser("metrics", help="Show metrics")
    sub.add_parser("backup", help="Backup project state")

    p_restore = sub.add_parser("restore", help="Restore project state")
    p_restore.add_argument("--file", default=None, help="Backup file path")

    p_daemon = sub.add_parser("daemon", help="Manage the background daemon")
    p_daemon.add_argument("action", nargs="?", default="status",
                          choices=["start", "stop", "status"],
                          help="Daemon action (default: status)")
    p_daemon.add_argument("--foreground", action="store_true",
                          help="Run daemon in foreground")

    sub.add_parser("doctor", help="Diagnose configuration issues")
    sub.add_parser("sessions", help="List active sessions")

    p_connect = sub.add_parser("connect", help="Connect to a running session")
    p_connect.add_argument("session", nargs="?", default=None)

    # Phase 6 commands
    p_dashboard = sub.add_parser("dashboard", help="Launch interactive dashboard")
    p_dashboard.add_argument("--refresh", type=float, default=2.0,
                              help="Refresh interval in seconds (default: 2)")
    p_dashboard.add_argument("--snapshot", action="store_true",
                              help="Print single snapshot instead of live view")

    sub.add_parser("costs", help="Show cost breakdown")
    sub.add_parser("observe", help="Export observability metrics")

    # Agent-facing commands
    p_agent_update = sub.add_parser("agent-update", help="Update task (for agents)")
    p_agent_update.add_argument("--task-id", help="Task ID (defaults to WARCHIEF_TASK env)")
    p_agent_update.add_argument("--status", choices=["open", "blocked", "closed"], help="New status")
    p_agent_update.add_argument("--comment", help="Add a comment")
    p_agent_update.add_argument("--add-label", help="Add a label (only 'rejected' allowed)")
    p_agent_update.add_argument("--question", help="Ask the user a question (sets status to blocked)")

    # answer
    p_answer = sub.add_parser("answer", help="Answer a pending agent question")
    p_answer.add_argument("task_id", help="Task ID")
    p_answer.add_argument("answer_text", help="Answer text")

    # questions
    sub.add_parser("questions", help="List pending agent questions")

    # tmux UI internal commands
    sub.add_parser("agent-monitor", help="Live agent log viewer (used by tmux UI)")
    sub.add_parser("control", help="Interactive control pane (used by tmux UI)")

    return parser


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

DISPATCH: dict[str, object] = {
    "version": cmd_version,
    "init": cmd_init,
    "create": cmd_create,
    "show": cmd_show,
    "list": cmd_list,
    "update": cmd_update,
    "tell": cmd_tell,
    "nudge": cmd_nudge,
    "retry": cmd_retry,
    "approve": cmd_approve,
    "reject": cmd_reject,
    "release": cmd_release,
    "config": cmd_config,
    # Phase 2 commands
    "watch": cmd_watch,
    "stop": cmd_stop,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "status": cmd_status,
    "grant": cmd_grant,
    "drop": cmd_drop,
    "kill-agent": cmd_kill_agent,
    # Phase 3 commands
    "start": cmd_start,
    "board": cmd_board,
    "metrics": cmd_metrics,
    # Phase 4 commands
    "logs": cmd_logs,
    "attach": cmd_attach,
    "purge": cmd_purge,
    "feed": cmd_feed,
    "backup": cmd_backup,
    "restore": cmd_restore,
    "daemon": cmd_daemon,
    # Phase 5 commands
    "doctor": cmd_doctor,
    "sessions": cmd_sessions,
    "connect": cmd_connect,
    # Phase 6 commands
    "dashboard": cmd_dashboard,
    "costs": cmd_costs,
    "observe": cmd_observe,
    # Agent-facing commands
    "agent-update": cmd_agent_update,
    "answer": cmd_answer,
    "questions": cmd_questions,
    # Tmux UI commands
    "agent-monitor": cmd_agent_monitor,
    "control": cmd_control,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handler = DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except ImportError as exc:
        print(
            f"Error: Missing dependency \u2014 {exc}\n"
            "Ensure warchief.task_store and warchief.models are available.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
