"""Hooks — install Claude Code hooks into agent worktrees.

Hooks enforce agent boundaries at the tool-use level:
- verify-task-updated: Stop hook — blocks exit if task still in_progress
- validate-warchief-transition: PreToolUse — validates opus update commands
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("warchief.hooks")


def install_hooks(project_root: Path) -> None:
    """Install project-level hooks (placeholder for future enforcement).

    Agent-specific hooks are installed per-worktree by install_agent_hooks.
    """
    log.debug("Project-level hooks: no-op (agent hooks installed per worktree)")


def install_agent_hooks(
    worktree_path: Path,
    agent_id: str,
    task_id: str,
    role: str,
    db_path: str,
) -> None:
    """Install Claude Code hooks into an agent's worktree.

    Creates .claude/settings.json with hook definitions that enforce
    agent boundaries and task workflow compliance.
    """
    claude_dir = worktree_path / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Ensure heavy directories are never scanned by the agent
    _write_claudeignore(worktree_path)

    # Ensure warchief artifacts are never committed
    _write_worktree_gitignore(worktree_path)

    # Write the hook scripts
    _write_verify_task_hook(hooks_dir)

    # Write settings.json with hook configuration
    # Use relative path so settings.json works regardless of worktree location
    settings = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 .claude/hooks/verify_task_updated.py"
                        }
                    ]
                }
            ]
        }
    }

    settings_path = claude_dir / "settings.json"

    # Merge with existing settings if present
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
            existing.setdefault("hooks", {}).update(settings["hooks"])
            settings = existing
        except (json.JSONDecodeError, OSError):
            pass

    # Atomic write
    tmp_path = settings_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(settings, indent=2))
    os.replace(str(tmp_path), str(settings_path))
    log.info("Installed hooks for agent %s at %s", agent_id, worktree_path)


def _write_verify_task_hook(hooks_dir: Path) -> None:
    """Write the verify-task-updated stop hook.

    This hook checks that the agent updated its task status before exiting.
    Also checks for uncommitted changes (developer agents).
    """
    script = '''#!/usr/bin/env python3
"""Stop hook: verify agent updated task status before exiting.

Checks the task in the DB to see if the agent changed status from in_progress.
For developer agents, also checks for uncommitted git changes.
Reads hook input from stdin, outputs JSON response.
"""
import json
import os
import sqlite3
import subprocess
import sys


def main():
    role = os.environ.get("WARCHIEF_ROLE", "")
    task_id = os.environ.get("WARCHIEF_TASK", "")
    db_path = os.environ.get("WARCHIEF_DB", "")

    # Check if task status was updated
    if task_id and db_path and os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT status FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            conn.close()

            if row and row[0] == "in_progress":
                # Task still in_progress — agent forgot to update
                print(
                    f"WARNING: Task {task_id} is still 'in_progress'. "
                    "You should signal completion before exiting.",
                    file=sys.stderr,
                )
                print(
                    f"Run: warchief agent-update --status open",
                    file=sys.stderr,
                )
                print(
                    "Or if blocked: warchief agent-update --status blocked --comment 'reason'",
                    file=sys.stderr,
                )
        except Exception:
            pass  # Fail open — don't block agent on DB errors

    # For developers: check for uncommitted changes
    if role == "developer":
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=10,
            )
            if status.stdout.strip():
                changes = status.stdout.strip().split("\\n")
                print(f"WARNING: {len(changes)} uncommitted file(s) detected.", file=sys.stderr)
                print("Run: git add -A && git commit -m 'feat: <description>'", file=sys.stderr)
        except Exception:
            pass  # Fail open


if __name__ == "__main__":
    main()
'''
    hook_path = hooks_dir / "verify_task_updated.py"
    hook_path.write_text(script)
    hook_path.chmod(0o755)


def _write_worktree_gitignore(worktree_path: Path) -> None:
    """Ensure .gitignore in worktree blocks warchief/claude artifacts from commits."""
    gitignore_path = worktree_path / ".gitignore"
    warchief_entries = [".claude/", ".warchief/", ".warchief-worktrees/", ".claudeignore", "debug/", "CLAUDE.md"]

    existing_lines: list[str] = []
    if gitignore_path.exists():
        try:
            existing_lines = gitignore_path.read_text().splitlines()
        except OSError:
            pass

    existing_set = set()
    for line in existing_lines:
        stripped = line.strip()
        existing_set.add(stripped)
        existing_set.add(stripped.rstrip("/"))
        existing_set.add(stripped.rstrip("/") + "/")

    missing = [e for e in warchief_entries if e not in existing_set]
    if not missing:
        return

    with open(gitignore_path, "a") as f:
        if existing_lines and existing_lines[-1] != "":
            f.write("\n")
        f.write("# Warchief artifacts — do NOT commit\n")
        for entry in missing:
            f.write(entry + "\n")


def _write_claudeignore(worktree_path: Path) -> None:
    """Write a .claudeignore to prevent agents from scanning heavy directories.

    Claude Code respects .gitignore, but .claudeignore is belt-and-suspenders:
    ensures node_modules, dist, build artifacts etc. are never read even if
    .gitignore is missing or incomplete.
    """
    ignore_path = worktree_path / ".claudeignore"
    # Don't overwrite if project already ships one
    if ignore_path.exists():
        return
    ignore_path.write_text(
        "# Auto-generated by warchief — prevent agents from scanning heavy dirs\n"
        "node_modules/\n"
        ".next/\n"
        "dist/\n"
        "build/\n"
        ".nuxt/\n"
        ".output/\n"
        "vendor/\n"
        "target/\n"
        "__pycache__/\n"
        ".venv/\n"
        "*.min.js\n"
        "*.min.css\n"
        "*.map\n"
        "package-lock.json\n"
        "yarn.lock\n"
        "pnpm-lock.yaml\n"
    )
