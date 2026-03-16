"""Preflight checks before spawning an agent for a task."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from warchief.config import Config
from warchief.models import TaskRecord
from warchief.roles import RoleRegistry
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.preflight")


def check_base_branch(project_root: Path, base_branch: str) -> str | None:
    """Verify the base branch exists. Returns error message or None."""
    try:
        subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{base_branch}"],
            cwd=project_root, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        # Also check remotes
        try:
            subprocess.run(
                ["git", "show-ref", "--verify", f"refs/remotes/origin/{base_branch}"],
                cwd=project_root, check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            return f"Base branch '{base_branch}' not found locally or on origin"
    return None


def check_task_non_empty(task: TaskRecord) -> str | None:
    """Verify the task has a title and description."""
    if not task.title.strip():
        return f"Task {task.id} has no title"
    return None


def check_slot_available(
    store: TaskStore,
    role: str,
    config: Config,
    registry: RoleRegistry,
) -> str | None:
    """Verify there's a slot available for this role."""
    running = store.get_running_agents()
    total_running = len(running)

    if total_running >= config.max_total_agents:
        return f"Total agent limit reached ({total_running}/{config.max_total_agents})"

    role_count = sum(1 for a in running if a.role == role)
    max_for_role = config.max_role_agents.get(role) or registry.get_max_concurrent(role)
    if role_count >= max_for_role:
        return f"Role '{role}' limit reached ({role_count}/{max_for_role})"

    return None


def check_claude_available() -> str | None:
    """Verify the Claude CLI is on PATH."""
    if not shutil.which("claude"):
        return "Claude CLI not found on PATH — install from https://claude.ai/download"
    return None


def check_git_user(project_root: Path) -> str | None:
    """Verify git user.name and user.email are set so agents can commit."""
    for key in ("user.name", "user.email"):
        try:
            result = subprocess.run(
                ["git", "config", key],
                cwd=project_root, capture_output=True, text=True, timeout=5,
            )
            if not result.stdout.strip():
                return f"Git {key} not configured — run: git config {key} \"value\""
        except (subprocess.TimeoutExpired, OSError):
            return f"Could not check git {key}"
    return None


def check_deps_resolved(task: TaskRecord, store: TaskStore) -> str | None:
    """Verify all dependencies are closed."""
    if not task.deps:
        return None
    for dep_id in task.deps:
        dep = store.get_task(dep_id)
        if dep is None:
            return f"Dependency {dep_id} not found"
        if dep.status != "closed":
            return f"Dependency {dep_id} is {dep.status}, not closed"
    return None


def run_preflight(
    task: TaskRecord,
    role: str,
    project_root: Path,
    store: TaskStore,
    config: Config,
    registry: RoleRegistry,
) -> list[str]:
    """Run all preflight checks. Returns list of error messages (empty = all clear)."""
    errors: list[str] = []

    # Environment checks — fail fast before anything else
    err = check_claude_available()
    if err:
        errors.append(err)
        return errors  # No point continuing without claude

    err = check_git_user(project_root)
    if err:
        errors.append(err)

    from warchief.config import detect_default_branch
    base = task.base_branch or config.base_branch or detect_default_branch(project_root)
    err = check_base_branch(project_root, base)
    if err:
        errors.append(err)

    err = check_task_non_empty(task)
    if err:
        errors.append(err)

    err = check_slot_available(store, role, config, registry)
    if err:
        errors.append(err)

    err = check_deps_resolved(task, store)
    if err:
        errors.append(err)

    if errors:
        # Dependency and slot-limit failures are expected during normal operation
        # (tasks waiting on deps, role limits) — log at DEBUG to avoid spam
        is_routine = all(
            "Dependency" in e or "limit reached" in e
            for e in errors
        )
        if is_routine:
            log.debug("Preflight skipped for task %s: %s", task.id, errors)
        else:
            log.warning("Preflight failed for task %s: %s", task.id, errors)
    else:
        log.debug("Preflight passed for task %s", task.id)

    return errors
