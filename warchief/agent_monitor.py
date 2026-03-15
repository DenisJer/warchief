"""Agent Monitor — live agent log viewer for the tmux UI.

Shows a list of agents and tails the selected agent's log file.
Automatically picks up new agents as they spawn.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def run_monitor(project_root: Path) -> None:
    """Run the interactive agent log monitor."""
    logs_dir = project_root / ".warchief" / "agent-logs"
    db_path = project_root / ".warchief" / "warchief.db"

    selected_agent: str | None = None
    last_agents: list[str] = []
    follow_position: int = 0  # Track position in file for follow mode

    print("Agent Log Viewer")
    print("=" * 50)
    print("Waiting for agents to spawn...")
    print()

    try:
        while True:
            # Discover agents from log files
            agents = _discover_agents(logs_dir)

            # If new agents appeared, auto-switch to the newest one
            if agents != last_agents:
                new_agents = [a for a in agents if a not in last_agents]
                last_agents = agents[:]

                if new_agents:
                    # Always follow the newest agent
                    selected_agent = new_agents[-1]
                    follow_position = 0
                    _print_agent_list(agents, selected_agent)
                    print(f"\n>>> Following: {selected_agent}")
                    print("-" * 50)
                elif selected_agent and selected_agent not in agents:
                    # Selected agent was removed, pick latest
                    selected_agent = agents[-1] if agents else None
                    follow_position = 0
                    _print_agent_list(agents, selected_agent)

            # Tail the selected agent's log
            if selected_agent:
                log_path = logs_dir / f"{selected_agent}.log"
                if log_path.exists():
                    new_content = _read_new_content(log_path, follow_position)
                    if new_content:
                        sys.stdout.write(new_content)
                        sys.stdout.flush()
                        follow_position += len(new_content.encode())

            # Check for user input (non-blocking)
            if _check_stdin():
                line = sys.stdin.readline().strip()
                if line == "q":
                    break
                elif line == "l" or line == "list":
                    _print_agent_list(agents, selected_agent)
                elif line.isdigit():
                    idx = int(line) - 1
                    if 0 <= idx < len(agents):
                        selected_agent = agents[idx]
                        follow_position = 0
                        print(f"\n>>> Switched to: {selected_agent}")
                        print("-" * 50)
                elif line.startswith("f ") or line.startswith("follow "):
                    name = line.split(None, 1)[1] if " " in line else ""
                    matches = [a for a in agents if name in a]
                    if matches:
                        selected_agent = matches[0]
                        follow_position = 0
                        print(f"\n>>> Following: {selected_agent}")
                        print("-" * 50)

            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _discover_agents(logs_dir: Path) -> list[str]:
    """Find all agent IDs from log files, sorted by modification time."""
    if not logs_dir.exists():
        return []
    log_files = sorted(logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime)
    return [f.stem for f in log_files]


def _print_agent_list(agents: list[str], selected: str | None) -> None:
    """Print the agent list with selection indicator."""
    if not agents:
        return
    print("\nAgents:")
    for i, agent in enumerate(agents, 1):
        marker = " >>>" if agent == selected else "    "
        print(f"  {marker} [{i}] {agent}")
    print("  Type a number to switch, 'l' to list, 'q' to quit")
    print()


def _read_new_content(path: Path, offset: int) -> str:
    """Read new content from a file starting at offset."""
    try:
        size = path.stat().st_size
        if size <= offset:
            return ""
        with open(path, "r") as f:
            f.seek(offset)
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _check_stdin() -> bool:
    """Non-blocking check if there's input available on stdin."""
    import select
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        return bool(ready)
    except (ValueError, OSError):
        return False
