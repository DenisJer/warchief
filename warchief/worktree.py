"""Git worktree management for agent sandboxes."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("warchief.worktree")

WORKTREE_DIR = ".warchief-worktrees"


def _worktrees_root(project_root: Path) -> Path:
    return project_root / WORKTREE_DIR


def create_branch_worktree(
    project_root: Path,
    agent_id: str,
    branch_name: str,
    base_branch: str = "main",
) -> Path:
    """Create a git worktree on a new feature branch for a developer agent.

    Returns the worktree path.
    """
    root = _worktrees_root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    wt_path = root / agent_id

    if wt_path.exists():
        # Only reuse if it's a real git worktree (has .git file)
        if (wt_path / ".git").exists():
            log.warning("Worktree already exists at %s, reusing", wt_path)
            return wt_path
        else:
            # Broken directory from previous failed attempt — remove it
            log.warning("Removing broken worktree directory at %s", wt_path)
            import shutil
            shutil.rmtree(wt_path, ignore_errors=True)

    # Ensure main repo is not on the feature branch (would block worktree creation)
    try:
        current = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_root, capture_output=True, text=True, timeout=5,
        )
        if current.stdout.strip() == branch_name:
            log.warning("Main repo is on %s — switching to %s", branch_name, base_branch)
            subprocess.run(
                ["git", "checkout", base_branch],
                cwd=project_root, capture_output=True, timeout=10,
            )
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Create the branch if it doesn't exist
    try:
        subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{branch_name}"],
            cwd=project_root, check=True, capture_output=True,
        )
        branch_exists = True
    except subprocess.CalledProcessError:
        branch_exists = False

    def _run_git_worktree(cmd):
        """Run git worktree command with error logging."""
        result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
        if result.returncode != 0:
            log.error("git worktree failed: %s\nstderr: %s", " ".join(cmd), result.stderr.strip())
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
        return result

    if branch_exists:
        # Check if branch is already checked out in another worktree
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=project_root, capture_output=True, text=True,
        )
        branch_in_use = f"branch refs/heads/{branch_name}" in result.stdout

        if branch_in_use:
            log.warning("Branch %s checked out elsewhere, cleaning up stale worktree", branch_name)
            _remove_stale_worktree_for_branch(project_root, branch_name, result.stdout)
            _run_git_worktree(["git", "worktree", "add", str(wt_path), branch_name])
        else:
            _run_git_worktree(["git", "worktree", "add", str(wt_path), branch_name])
    else:
        _run_git_worktree(["git", "worktree", "add", "-b", branch_name, str(wt_path), base_branch])

    _symlink_warchief_dir(project_root, wt_path)
    log.info("Created branch worktree: %s on %s", wt_path, branch_name)
    return wt_path


def create_detached_worktree(
    project_root: Path,
    agent_id: str,
    commit_ref: str,
) -> Path:
    """Create a detached worktree for read-only agents (reviewers, integrators).

    Returns the worktree path.
    """
    root = _worktrees_root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    wt_path = root / agent_id

    if wt_path.exists():
        # Only reuse if it's a real git worktree (has .git file)
        if (wt_path / ".git").exists():
            log.warning("Worktree already exists at %s, reusing", wt_path)
            return wt_path
        else:
            # Broken directory from previous failed attempt — remove it
            log.warning("Removing broken worktree directory at %s", wt_path)
            import shutil
            shutil.rmtree(wt_path, ignore_errors=True)

    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt_path), commit_ref],
        cwd=project_root, check=True, capture_output=True,
    )

    _symlink_warchief_dir(project_root, wt_path)
    log.info("Created detached worktree: %s at %s", wt_path, commit_ref)
    return wt_path


def create_integrator_worktree(
    project_root: Path,
    agent_id: str,
    base_branch: str = "main",
    feature_branch: str = "",
) -> Path:
    """Create a worktree for an integrator to merge a feature branch into base.

    Uses a temporary integration branch so it doesn't conflict with `main`
    being checked out in the project root. After the merge, the real base
    branch ref is updated to match.
    """
    root = _worktrees_root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    wt_path = root / agent_id

    if wt_path.exists():
        # Only reuse if it's a real git worktree (has .git file)
        if (wt_path / ".git").exists():
            log.warning("Worktree already exists at %s, reusing", wt_path)
            return wt_path
        else:
            # Broken directory from previous failed attempt — remove it
            log.warning("Removing broken worktree directory at %s", wt_path)
            import shutil
            shutil.rmtree(wt_path, ignore_errors=True)

    # Create a temporary integration branch at the same commit as base
    integration_branch = f"integrate/{agent_id}"

    # Delete stale integration branch if it exists
    subprocess.run(
        ["git", "branch", "-D", integration_branch],
        cwd=project_root, capture_output=True,
    )

    # Create worktree on a new branch starting from base
    subprocess.run(
        ["git", "worktree", "add", "-b", integration_branch, str(wt_path), base_branch],
        cwd=project_root, check=True, capture_output=True,
    )

    _symlink_warchief_dir(project_root, wt_path)
    log.info("Created integrator worktree: %s on %s (for merging into %s)",
             wt_path, integration_branch, base_branch)
    return wt_path


def finalize_integration(
    project_root: Path,
    agent_id: str,
    base_branch: str = "main",
) -> bool:
    """After integrator merges in their worktree, fast-forward base branch to match.

    Returns True if base branch was updated.
    """
    integration_branch = f"integrate/{agent_id}"
    try:
        # Fast-forward the real base branch to the integration branch
        subprocess.run(
            ["git", "branch", "-f", base_branch, integration_branch],
            cwd=project_root, check=True, capture_output=True,
        )
        log.info("Updated %s to match %s", base_branch, integration_branch)
        return True
    except subprocess.CalledProcessError as e:
        log.error("Failed to update %s: %s", base_branch, e)
        return False
    finally:
        # Clean up the integration branch
        subprocess.run(
            ["git", "branch", "-D", integration_branch],
            cwd=project_root, capture_output=True,
        )


def remove_worktree(project_root: Path, agent_id: str) -> bool:
    """Remove a worktree and prune. Returns True if actually removed."""
    import shutil
    wt_path = _worktrees_root(project_root) / agent_id
    if not wt_path.exists():
        log.debug("Worktree %s already removed", wt_path)
        return True

    result = subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt_path)],
        cwd=project_root, capture_output=True, text=True,
    )

    # If git worktree remove failed, force-delete the directory
    if wt_path.exists():
        if result.returncode != 0:
            log.warning("git worktree remove failed for %s: %s", wt_path, result.stderr.strip())
        shutil.rmtree(wt_path, ignore_errors=True)

    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=project_root, capture_output=True,
    )

    removed = not wt_path.exists()
    if removed:
        log.info("Removed worktree: %s", wt_path)
    else:
        log.error("Failed to remove worktree: %s", wt_path)
    return removed


def repair_worktree(project_root: Path, agent_id: str) -> bool:
    """Attempt to repair a broken worktree. Returns True if repaired."""
    wt_path = _worktrees_root(project_root) / agent_id
    if not wt_path.exists():
        return False

    subprocess.run(
        ["git", "worktree", "repair", str(wt_path)],
        cwd=project_root, capture_output=True,
    )

    _symlink_warchief_dir(project_root, wt_path)
    log.info("Repaired worktree: %s", wt_path)
    return True


def list_worktrees(project_root: Path) -> list[str]:
    """Return agent IDs that have worktrees."""
    root = _worktrees_root(project_root)
    if not root.exists():
        return []
    return [d.name for d in root.iterdir() if d.is_dir()]


def _remove_stale_worktree_for_branch(
    project_root: Path, branch_name: str, porcelain_output: str,
) -> None:
    """Find and remove the worktree that has branch_name checked out."""
    # Parse porcelain output to find the worktree path
    # Format: "worktree /path\nHEAD ...\nbranch refs/heads/name\n\n"
    current_path = None
    for line in porcelain_output.split("\n"):
        if line.startswith("worktree "):
            current_path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch_name}" and current_path:
            # Don't remove the main worktree
            if current_path == str(project_root):
                log.warning("Branch %s is checked out in main worktree, cannot remove", branch_name)
                return
            log.info("Removing stale worktree at %s (has branch %s)", current_path, branch_name)
            subprocess.run(
                ["git", "worktree", "remove", "--force", current_path],
                cwd=project_root, capture_output=True,
            )
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=project_root, capture_output=True,
            )
            return


def _symlink_warchief_dir(project_root: Path, wt_path: Path) -> None:
    """Ensure the worktree has a .warchief symlink pointing to the main project's .warchief."""
    src = project_root / ".warchief"
    dst = wt_path / ".warchief"
    if dst.exists() or dst.is_symlink():
        return
    # Safety: never create a symlink that points to itself
    if src.resolve() == dst.resolve():
        log.warning("Refusing to create circular symlink: %s -> %s", dst, src)
        return
    if src.exists() and src.is_dir():
        os.symlink(src, dst)
        log.debug("Symlinked %s -> %s", dst, src)
