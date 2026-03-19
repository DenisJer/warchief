"""Tmux UI — interactive terminal layout for Warchief pipeline.

Creates a tmux session with:
- Dashboard pane (live pipeline view with costs/questions)
- Orchestrator pane (watcher verbose output)
- Agent log viewer (tail -f selected agent's log)
- Control pane (answer questions, select agents)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


SESSION_NAME = "warchief"


def is_tmux_available() -> bool:
    """Check if tmux is installed."""
    return shutil.which("tmux") is not None


def is_in_tmux() -> bool:
    """Check if we're already inside a tmux session."""
    return os.environ.get("TMUX", "") != ""


def session_exists() -> bool:
    """Check if the warchief tmux session already exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", SESSION_NAME],
        capture_output=True,
    )
    return result.returncode == 0


def kill_session() -> None:
    """Kill the warchief tmux session."""
    subprocess.run(
        ["tmux", "kill-session", "-t", SESSION_NAME],
        capture_output=True,
    )


def launch_ui(
    project_root: Path, requirement: str | None = None, no_conductor: bool = False
) -> None:
    """Launch the tmux-based Warchief UI.

    Layout:
    ┌──────────────────────────┬─────────────────────────┐
    │                          │                         │
    │      DASHBOARD           │    AGENT LOG VIEWER     │
    │                          │                         │
    ├──────────────────────────┤                         │
    │   ORCHESTRATOR           │                         │
    │   (watcher output)       │                         │
    ├──────────────────────────┴─────────────────────────┤
    │  CONTROL (answer questions, select agents)         │
    └────────────────────────────────────────────────────┘
    """
    if not is_tmux_available():
        print("Error: tmux is not installed. Install it with: brew install tmux", file=sys.stderr)
        sys.exit(1)

    if session_exists():
        print(f"Warchief session already running. Attaching...")
        attach_session()
        return

    warchief_bin = shutil.which("warchief") or "warchief"
    project_dir = str(project_root)

    # Build the start command with original args
    start_cmd = f"cd {project_dir} && {warchief_bin} watch"

    # If there's a requirement, we need to run start (which does conductor + watch)
    # But for tmux, we split: run conductor first, then watch in the pane
    if requirement:
        conductor_flag = " --no-conductor" if no_conductor else ""
        # Pre-run: create tasks from requirement before launching tmux
        pre_cmd = f'{warchief_bin} start "{requirement}"{conductor_flag} --tmux-pre'
        start_cmd = f"cd {project_dir} && {warchief_bin} watch"

    # Create the tmux session with the dashboard in the first pane
    dashboard_cmd = f"cd {project_dir} && {warchief_bin} dashboard"
    subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            SESSION_NAME,
            "-x",
            "200",
            "-y",
            "50",
            dashboard_cmd,
        ],
        check=True,
    )

    # Name the first window
    subprocess.run(
        [
            "tmux",
            "rename-window",
            "-t",
            f"{SESSION_NAME}:0",
            "warchief",
        ]
    )

    # Split bottom-left: orchestrator (watcher)
    subprocess.run(
        [
            "tmux",
            "split-window",
            "-t",
            f"{SESSION_NAME}:0",
            "-v",
            "-p",
            "40",
            start_cmd,
        ]
    )

    # Split right side: agent log viewer
    subprocess.run(
        [
            "tmux",
            "split-window",
            "-t",
            f"{SESSION_NAME}:0.0",
            "-h",
            "-p",
            "45",
            f"cd {project_dir} && {warchief_bin} agent-monitor",
        ]
    )

    # Split bottom: control pane
    subprocess.run(
        [
            "tmux",
            "split-window",
            "-t",
            f"{SESSION_NAME}:0.1",
            "-v",
            "-p",
            "30",
            f"cd {project_dir} && {warchief_bin} control",
        ]
    )

    # Set pane titles
    for pane_idx, title in [
        (0, "Dashboard"),
        (2, "Agent Logs"),
        (1, "Orchestrator"),
        (3, "Control"),
    ]:
        subprocess.run(
            [
                "tmux",
                "select-pane",
                "-t",
                f"{SESSION_NAME}:0.{pane_idx}",
                "-T",
                title,
            ]
        )

    # Enable pane borders with titles
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "pane-border-status",
            "top",
        ]
    )
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "pane-border-format",
            " #{pane_title} ",
        ]
    )

    # Enable mouse support (click panes, scroll logs, resize panes)
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "mouse",
            "on",
        ]
    )

    # Increase scrollback buffer for all panes
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "history-limit",
            "10000",
        ]
    )

    # Set status bar with help hints
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "status-style",
            "bg=colour235,fg=colour208",
        ]
    )
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "status-left",
            " WARCHIEF ",
        ]
    )
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "status-right-length",
            "80",
        ]
    )
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            SESSION_NAME,
            "status-right",
            " Mouse: scroll/click | Ctrl-B [ scroll | Ctrl-B x kill pane ",
        ]
    )

    # Select the control pane as active
    subprocess.run(
        [
            "tmux",
            "select-pane",
            "-t",
            f"{SESSION_NAME}:0.3",
        ]
    )

    # Attach to the session
    attach_session()


def attach_session() -> None:
    """Attach to the warchief tmux session."""
    os.execvp("tmux", ["tmux", "attach-session", "-t", SESSION_NAME])
