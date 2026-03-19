"""Conductor — decomposes high-level requirements into pipeline tasks."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

from warchief.config import Config
from warchief.models import TaskRecord
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.conductor")

DECOMPOSITION_PROMPT = """\
You are the Warchief Conductor — a senior software architect who decomposes feature \
requirements into small, parallelizable development tasks.

## Project Context

You are working in: {project_root}

Here is the project structure (top-level files/dirs):
{tree}

## Requirement

{requirement}

## Rules

1. Each task must be completable by a SINGLE developer agent in ONE session (30-60 min)
2. Tasks should be as parallel as possible — minimize dependency chains
3. Database/schema changes are always their own task
4. Frontend and backend are separate tasks
5. Include a test task only if the feature is complex enough to warrant dedicated testing
6. Label tasks with: "security" (if auth/crypto/input-validation), "frontend" (if UI)
7. Dependencies form a DAG — no cycles
8. Priority 1-10: infrastructure/schema=9, core logic=7, UI=5, polish=3

## Output Format

Return ONLY a JSON array. No markdown, no explanation. Each element:

```json
[
  {{
    "title": "Short imperative title (e.g. Create users table migration)",
    "description": "Detailed description with acceptance criteria. Be specific about what to implement, which files to create/modify, and expected behavior.",
    "type": "feature",
    "priority": 8,
    "labels": ["backend"],
    "deps": []
  }},
  {{
    "title": "Build login form component",
    "description": "...",
    "type": "feature",
    "priority": 5,
    "labels": ["frontend"],
    "deps": ["$0"]
  }}
]
```

Use `"$0"`, `"$1"`, etc. to reference earlier tasks by their position (0-indexed). \
These will be resolved to actual task IDs.

Return ONLY the JSON array.
"""


def _get_project_tree(project_root: Path, max_depth: int = 2) -> str:
    """Get a brief project tree for context."""
    try:
        result = subprocess.run(
            [
                "find",
                ".",
                "-maxdepth",
                str(max_depth),
                "-not",
                "-path",
                "./.git/*",
                "-not",
                "-path",
                "./node_modules/*",
                "-not",
                "-path",
                "./.warchief/*",
                "-not",
                "-path",
                "./.warchief-worktrees/*",
                "-not",
                "-path",
                "./.venv/*",
                "-not",
                "-name",
                "__pycache__",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().split("\n")
        # Limit output size
        if len(lines) > 80:
            lines = lines[:80] + [f"... ({len(lines) - 80} more entries)"]
        return "\n".join(lines)
    except (subprocess.TimeoutExpired, OSError):
        return "(could not read project tree)"


def run_conductor(
    requirement: str,
    project_root: Path,
    store: TaskStore,
    config: Config,
    base_branch: str = "main",
    on_status: callable = None,
) -> list[TaskRecord]:
    """Run the conductor to decompose a requirement into tasks.

    Args:
        requirement: The high-level feature description
        project_root: Path to the project
        store: Task store to create tasks in
        config: Warchief config
        base_branch: Git base branch
        on_status: Optional callback for status messages

    Returns:
        List of created TaskRecord objects
    """

    def emit(msg: str) -> None:
        if on_status:
            on_status(msg)
        log.info(msg)

    emit("Conductor analyzing requirement...")

    tree = _get_project_tree(project_root)
    prompt = DECOMPOSITION_PROMPT.format(
        project_root=project_root,
        tree=tree,
        requirement=requirement,
    )

    # Determine conductor model
    model = config.role_models.get("conductor", "claude-sonnet-4-20250514")

    cmd = [
        "claude",
        "--print",
        "--output-format",
        "text",
        "--model",
        model,
        prompt,
    ]

    emit(f"Running conductor (model: {model})...")

    # Remove Claude Code nesting detection so conductor can run
    env = os.environ.copy()
    for key in ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]:
        env.pop(key, None)

    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max
            env=env,
        )
    except subprocess.TimeoutExpired:
        emit("Conductor timed out after 5 minutes")
        return []
    except FileNotFoundError:
        emit("Claude CLI not found — cannot run conductor")
        return []

    if result.returncode != 0:
        emit(f"Conductor failed (exit {result.returncode})")
        log.error("Conductor stderr: %s", result.stderr[:500])
        return []

    # Parse the output
    raw_output = result.stdout.strip()
    tasks = _parse_conductor_output(raw_output, emit)
    if not tasks:
        return []

    # Create task records with real IDs, resolving $N references.
    # All subtasks share a group_id so they work on one branch and produce one PR.
    group_id = f"wc-grp-{uuid.uuid4().hex[:6]}" if len(tasks) > 1 else None
    created = _create_tasks_from_plan(
        tasks,
        store,
        base_branch,
        emit,
        group_id=group_id,
    )
    if group_id:
        emit(f"Group: {group_id} (shared branch: feature/{group_id})")

    emit(f"Conductor created {len(created)} task(s)")
    return created


def _parse_conductor_output(
    raw: str,
    emit: callable,
) -> list[dict] | None:
    """Parse conductor JSON output, handling markdown wrappers."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        # Remove first line (```json or ```) and last line (```)
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        emit(f"Conductor returned invalid JSON: {e}")
        log.error("Raw conductor output:\n%s", raw[:1000])
        return None

    if not isinstance(data, list):
        emit("Conductor output is not a JSON array")
        return None

    if len(data) == 0:
        emit("Conductor returned empty task list")
        return None

    # Validate each task
    for i, task in enumerate(data):
        if not isinstance(task, dict):
            emit(f"Task {i} is not a dict")
            return None
        if "title" not in task:
            emit(f"Task {i} missing 'title'")
            return None

    return data


def _create_tasks_from_plan(
    plan: list[dict],
    store: TaskStore,
    base_branch: str,
    emit: callable,
    group_id: str | None = None,
) -> list[TaskRecord]:
    """Create TaskRecords from the conductor's plan, resolving $N deps."""
    now = time.time()
    id_map: dict[str, str] = {}  # "$0" -> "wc-abc123"
    created: list[TaskRecord] = []

    for i, spec in enumerate(plan):
        task_id = f"wc-{uuid.uuid4().hex[:6]}"
        id_map[f"${i}"] = task_id

        # Resolve dependencies
        raw_deps = spec.get("deps", [])
        resolved_deps = []
        for dep in raw_deps:
            if dep.startswith("$") and dep in id_map:
                resolved_deps.append(id_map[dep])
            elif dep.startswith("wc-"):
                resolved_deps.append(dep)
            else:
                log.warning("Unresolved dep reference: %s", dep)

        labels = spec.get("labels", [])
        if resolved_deps:
            labels = labels + ["waiting"]

        record = TaskRecord(
            id=task_id,
            title=spec["title"],
            description=spec.get("description", spec["title"]),
            type=spec.get("type", "feature"),
            status="open",
            stage=None,  # Will be set by release_ready
            priority=spec.get("priority", 5),
            labels=labels,
            deps=resolved_deps,
            base_branch=base_branch,
            group_id=group_id,
            created_at=now,
            updated_at=now,
        )
        store.create_task(record)
        created.append(record)

        dep_str = f" (deps: {', '.join(resolved_deps)})" if resolved_deps else ""
        emit(f"  [{i + 1}/{len(plan)}] {task_id}: {spec['title']}{dep_str}")

    return created
