"""Merge verification — confirms branches are properly merged."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("warchief.merge_verifier")


def verify_merge(
    project_root: Path,
    feature_branch: str,
    base_branch: str,
) -> bool:
    """Check if feature_branch is an ancestor of base_branch (i.e., merged).

    Uses ``git merge-base --is-ancestor``.
    """
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", feature_branch, base_branch],
            cwd=project_root,
            capture_output=True,
        )
        merged = result.returncode == 0
        log.debug("Merge check: %s into %s = %s", feature_branch, base_branch, merged)
        return merged
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.error("Merge verification failed: %s", e)
        return False


def get_merge_status(
    project_root: Path,
    feature_branch: str,
    base_branch: str,
) -> dict:
    """Get detailed merge status including ahead/behind counts."""
    status: dict = {
        "merged": False,
        "ahead": 0,
        "behind": 0,
        "conflicts": False,
    }

    # Check if merged
    status["merged"] = verify_merge(project_root, feature_branch, base_branch)

    # Get ahead/behind counts
    try:
        result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", f"{base_branch}...{feature_branch}"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) == 2:
                status["behind"] = int(parts[0])
                status["ahead"] = int(parts[1])
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass

    # Check for merge conflicts (dry-run)
    if not status["merged"] and status["ahead"] > 0:
        try:
            result = subprocess.run(
                [
                    "git",
                    "merge-tree",
                    f"$(git merge-base {base_branch} {feature_branch})",
                    base_branch,
                    feature_branch,
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                shell=True,
            )
            status["conflicts"] = "conflict" in result.stdout.lower()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    return status


def get_feature_branch_name(task_id: str, group_id: str | None = None) -> str:
    """Return the conventional feature branch name for a task.

    Grouped tasks share ``feature/{group_id}``.
    """
    return f"feature/{group_id}" if group_id else f"feature/{task_id}"
