"""Scratchpad — per-task shared context that persists across agent spawns.

Each task gets a scratchpad file in .warchief/scratchpads/{task_id}.md.
Agents append structured handoff notes; the next agent reads them.
This replaces raw agent log injection with focused, curated context.
"""

from __future__ import annotations

import re
import time
from pathlib import Path


def _scratchpad_dir(project_root: Path) -> Path:
    d = project_root / ".warchief" / "scratchpads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scratchpad_path(project_root: Path, task_id: str) -> Path:
    if not re.match(r"^[a-zA-Z0-9_-]+$", task_id):
        raise ValueError(f"Invalid task_id format: {task_id!r}")
    return _scratchpad_dir(project_root) / f"{task_id}.md"


def append_scratchpad(
    project_root: Path,
    task_id: str,
    role: str,
    agent_id: str,
    notes: str,
) -> None:
    """Append handoff notes to a task's scratchpad."""
    path = _scratchpad_path(project_root, task_id)
    timestamp = time.strftime("%H:%M:%S")
    entry = f"\n### [{timestamp}] {role} ({agent_id})\n{notes.strip()}\n"
    with open(path, "a") as f:
        f.write(entry)


def read_scratchpad(project_root: Path, task_id: str) -> str:
    """Read the full scratchpad for a task. Returns empty string if none."""
    path = _scratchpad_path(project_root, task_id)
    if not path.exists():
        return ""
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def read_scratchpad_for_role(
    project_root: Path,
    task_id: str,
    role: str,
) -> str:
    """Read scratchpad with role-aware filtering.

    Different roles need different context:
    - developer: needs rejection feedback, user Q&A, previous decisions
    - reviewer: needs what was done, WHY decisions were made, known issues
    - security_reviewer: needs what was done, security-relevant decisions
    - pr_creator: needs summary only (what + branch info)
    - tester: needs what was done, what to test
    """
    full = read_scratchpad(project_root, task_id)
    if not full:
        return ""

    # For now, all roles get the full scratchpad (it's already concise).
    # As scratchpads grow, we can filter by role here.
    # The key constraint: keep it under 2KB.
    _MAX_SCRATCHPAD_CHARS = 2048
    if len(full) > _MAX_SCRATCHPAD_CHARS:
        # Keep the header (first entry) + tail (most recent entries)
        lines = full.split("\n")
        # Find first ### boundary after the start
        first_entry_end = 0
        for i, line in enumerate(lines[1:], 1):
            if line.startswith("### ["):
                first_entry_end = i
                break
        if first_entry_end:
            header = "\n".join(lines[:first_entry_end])
            tail = full[-(_MAX_SCRATCHPAD_CHARS - len(header) - 20) :]
            # Find clean boundary in tail
            idx = tail.find("\n### [")
            if idx >= 0:
                tail = tail[idx:]
            return header + "\n...\n" + tail
        else:
            return "...\n" + full[-_MAX_SCRATCHPAD_CHARS:]

    return full


def clear_scratchpad(project_root: Path, task_id: str) -> None:
    """Remove a task's scratchpad (e.g. when task is dropped)."""
    path = _scratchpad_path(project_root, task_id)
    if path.exists():
        path.unlink()
