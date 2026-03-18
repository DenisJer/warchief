"""Doctor — health checks for the Warchief system."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from warchief.config import ZOMBIE_THRESHOLD, read_config
from warchief.heartbeat import list_heartbeats
from warchief.task_store import TaskStore
from warchief.worktree import list_worktrees

log = logging.getLogger("warchief.doctor")


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    severity: str = "info"  # info, warning, error


@dataclass
class HealthReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(c.ok or c.severity == "info" for c in self.checks)

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.checks if not c.ok and c.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if not c.ok and c.severity == "warning")


def check_warchief_dir(project_root: Path) -> CheckResult:
    """Check that .warchief directory exists."""
    wc_dir = project_root / ".warchief"
    if wc_dir.exists() and wc_dir.is_dir():
        return CheckResult("warchief_dir", True, ".warchief directory exists")
    return CheckResult("warchief_dir", False, ".warchief directory missing — run 'warchief init'", "error")


def check_database(project_root: Path) -> CheckResult:
    """Check that SQLite database is accessible and not corrupted."""
    db_path = project_root / ".warchief" / "warchief.db"
    if not db_path.exists():
        return CheckResult("database", False, "Database file missing", "error")

    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        if result and result[0] == "ok":
            return CheckResult("database", True, "Database integrity check passed")
        return CheckResult("database", False, f"Database integrity check failed: {result}", "error")
    except sqlite3.Error as e:
        return CheckResult("database", False, f"Cannot open database: {e}", "error")


def check_config(project_root: Path) -> CheckResult:
    """Check that config is readable."""
    try:
        config = read_config(project_root)
        return CheckResult("config", True, f"Config loaded (max_agents={config.max_total_agents})")
    except Exception as e:
        return CheckResult("config", False, f"Config error: {e}", "error")


def check_watcher(project_root: Path) -> CheckResult:
    """Check if the watcher is running."""
    lock_path = project_root / ".warchief" / "watcher.lock"
    if not lock_path.exists():
        return CheckResult("watcher", False, "Watcher not running", "warning")

    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, 0)
        return CheckResult("watcher", True, f"Watcher running (PID {pid})")
    except (ValueError, ProcessLookupError, PermissionError):
        return CheckResult("watcher", False, "Watcher PID file stale", "warning")


def check_daemon(project_root: Path) -> CheckResult:
    """Check if the daemon is running."""
    pid_path = project_root / ".warchief" / "daemon.pid"
    if not pid_path.exists():
        return CheckResult("daemon", False, "Daemon not running", "info")

    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        hb_path = project_root / ".warchief" / "daemon_heartbeat"
        if hb_path.exists():
            last_hb = float(hb_path.read_text().strip())
            age = time.time() - last_hb
            if age > 120:
                return CheckResult("daemon", False, f"Daemon heartbeat stale ({age:.0f}s old)", "warning")
        return CheckResult("daemon", True, f"Daemon running (PID {pid})")
    except (ValueError, ProcessLookupError, PermissionError):
        return CheckResult("daemon", False, "Daemon PID file stale", "warning")


def check_disk_space(project_root: Path) -> CheckResult:
    """Check that there's enough disk space."""
    usage = shutil.disk_usage(project_root)
    free_gb = usage.free / (1024 ** 3)
    if free_gb < 1.0:
        return CheckResult("disk_space", False, f"Low disk space: {free_gb:.1f} GB free", "error")
    if free_gb < 5.0:
        return CheckResult("disk_space", False, f"Disk space warning: {free_gb:.1f} GB free", "warning")
    return CheckResult("disk_space", True, f"{free_gb:.1f} GB free")


def check_agents(project_root: Path, store: TaskStore) -> CheckResult:
    """Check agent health — look for zombies."""
    running = store.get_running_agents()
    if not running:
        return CheckResult("agents", True, "No running agents")

    heartbeats = list_heartbeats(project_root)
    now = time.time()
    zombies = []

    for agent in running:
        hb = heartbeats.get(agent.id)
        if hb is not None and (now - hb) > ZOMBIE_THRESHOLD:
            zombies.append(agent.id)
        elif agent.pid:
            try:
                os.kill(agent.pid, 0)
            except (ProcessLookupError, PermissionError):
                zombies.append(agent.id)

    if zombies:
        return CheckResult(
            "agents", False,
            f"{len(zombies)} zombie agent(s): {', '.join(zombies)}",
            "warning",
        )
    return CheckResult("agents", True, f"{len(running)} agent(s) healthy")


def check_orphaned_tasks(store: TaskStore) -> CheckResult:
    """Check for tasks stuck in_progress with no live agent."""
    orphans = store.get_orphaned_tasks()
    if orphans:
        ids = [t.id for t in orphans]
        return CheckResult(
            "orphaned_tasks", False,
            f"{len(orphans)} orphaned task(s): {', '.join(ids)}",
            "warning",
        )
    return CheckResult("orphaned_tasks", True, "No orphaned tasks")


def check_worktrees(project_root: Path, store: TaskStore) -> CheckResult:
    """Check for orphaned worktrees."""
    worktrees = set(list_worktrees(project_root))
    if not worktrees:
        return CheckResult("worktrees", True, "No worktrees")

    running = store.get_running_agents()
    active = {a.id for a in running}
    orphaned = worktrees - active

    if orphaned:
        return CheckResult(
            "worktrees", False,
            f"{len(orphaned)} orphaned worktree(s): {', '.join(orphaned)}",
            "warning",
        )
    return CheckResult("worktrees", True, f"{len(worktrees)} worktree(s) consistent")


def check_claude_cli() -> CheckResult:
    """Check that Claude Code CLI is installed and accessible."""
    claude_path = shutil.which("claude")
    if not claude_path:
        return CheckResult(
            "claude_cli", False,
            "Claude CLI not found on PATH — install from https://claude.ai/download",
            "error",
        )
    # Try to get version
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()
        version_short = version.split("\n")[0][:80] if version else "unknown version"
        return CheckResult("claude_cli", True, f"Claude CLI found: {version_short}")
    except (subprocess.TimeoutExpired, OSError):
        return CheckResult("claude_cli", True, f"Claude CLI found at {claude_path} (version check timed out)")


def check_tmux() -> CheckResult:
    """Check that tmux is installed (optional but recommended)."""
    tmux_path = shutil.which("tmux")
    if not tmux_path:
        return CheckResult(
            "tmux", False,
            "tmux not found — install with 'brew install tmux' for the interactive UI",
            "warning",
        )
    try:
        result = subprocess.run(
            ["tmux", "-V"], capture_output=True, text=True, timeout=5,
        )
        version = result.stdout.strip()
        return CheckResult("tmux", True, f"tmux found: {version}")
    except (subprocess.TimeoutExpired, OSError):
        return CheckResult("tmux", True, f"tmux found at {tmux_path}")


def check_gh_cli() -> CheckResult:
    """Check that GitHub CLI (gh) is installed and authenticated."""
    gh_path = shutil.which("gh")
    if not gh_path:
        return CheckResult(
            "gh_cli", False,
            "GitHub CLI (gh) not found on PATH — install from https://cli.github.com/ "
            "(required for PR creation)",
            "error",
        )
    # Check authentication
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return CheckResult(
                "gh_cli", False,
                "GitHub CLI not authenticated — run 'gh auth login'",
                "error",
            )
        # Extract account info from stderr (gh auth status prints to stderr)
        status_text = result.stderr.strip() or result.stdout.strip()
        account_line = ""
        for line in status_text.splitlines():
            if "Logged in" in line or "account" in line.lower():
                account_line = line.strip()
                break
        msg = f"GitHub CLI OK: {account_line}" if account_line else "GitHub CLI authenticated"
        return CheckResult("gh_cli", True, msg)
    except (subprocess.TimeoutExpired, OSError):
        return CheckResult("gh_cli", True, f"GitHub CLI found at {gh_path} (auth check timed out)")


def check_git(project_root: Path) -> CheckResult:
    """Check that git is available and project is a valid repo."""
    git_path = shutil.which("git")
    if not git_path:
        return CheckResult("git", False, "Git not found on PATH", "error")

    # Check if project is a git repo
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_root, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return CheckResult("git", False, f"{project_root} is not a git repository", "error")
    except (subprocess.TimeoutExpired, OSError) as e:
        return CheckResult("git", False, f"Git check failed: {e}", "error")

    # Check for at least one commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return CheckResult("git", False, "Git repo has no commits", "warning")
    except (subprocess.TimeoutExpired, OSError):
        pass

    return CheckResult("git", True, "Git repository OK")


def check_git_user(project_root: Path) -> CheckResult:
    """Check git user.name and user.email configuration.

    Detects local (repo-level) vs global config so users with
    multiple identities (work/personal) can see which one agents will use.
    """
    def _git_config(scope: str, key: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "config", f"--{scope}", key],
                cwd=project_root, capture_output=True, text=True, timeout=5,
            )
            val = result.stdout.strip()
            return val if val else None
        except (subprocess.TimeoutExpired, OSError):
            return None

    local_name = _git_config("local", "user.name")
    local_email = _git_config("local", "user.email")
    global_name = _git_config("global", "user.name")
    global_email = _git_config("global", "user.email")

    # Effective values (local overrides global)
    eff_name = local_name or global_name
    eff_email = local_email or global_email

    if not eff_name or not eff_email:
        missing = []
        if not eff_name:
            missing.append("user.name")
        if not eff_email:
            missing.append("user.email")
        return CheckResult(
            "git_user", False,
            f"Git {', '.join(missing)} not configured — agents will fail to commit. "
            f"Run: git config user.name \"Your Name\" && git config user.email \"you@example.com\"",
            "error",
        )

    # Build info message showing source
    parts = []
    if local_name:
        parts.append(f"name=\"{local_name}\" (local)")
    elif global_name:
        parts.append(f"name=\"{global_name}\" (global)")

    if local_email:
        parts.append(f"email=\"{local_email}\" (local)")
    elif global_email:
        parts.append(f"email=\"{global_email}\" (global)")

    # Warn if using global config in a repo (might be wrong identity)
    if (not local_name or not local_email) and (global_name or global_email):
        hint = " — set local config if this is a work project: git config user.email \"work@company.com\""
        return CheckResult(
            "git_user", True,
            f"Git user: {', '.join(parts)}{hint}",
        )

    return CheckResult("git_user", True, f"Git user: {', '.join(parts)}")


def check_log_file(project_root: Path) -> CheckResult:
    """Check log file exists and isn't too large."""
    log_file = project_root / ".warchief" / "warchief.log"
    if not log_file.exists():
        return CheckResult("log_file", True, "No log file yet")

    size_mb = log_file.stat().st_size / (1024 * 1024)
    if size_mb > 100:
        return CheckResult("log_file", False, f"Log file too large: {size_mb:.1f} MB", "warning")
    return CheckResult("log_file", True, f"Log file: {size_mb:.1f} MB")


def check_node() -> CheckResult:
    """Check that Node.js and npm/npx are installed."""
    node_path = shutil.which("node")
    if not node_path:
        return CheckResult(
            "node", False,
            "Node.js not found on PATH — install from https://nodejs.org/ "
            "(required for frontend projects)",
            "warning",
        )
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        version = result.stdout.strip()

        # Check npm too
        npm_path = shutil.which("npm")
        npx_path = shutil.which("npx")
        extras = []
        if npm_path:
            npm_ver = subprocess.run(
                ["npm", "--version"], capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            extras.append(f"npm {npm_ver}")
        else:
            extras.append("npm NOT FOUND")
        if npx_path:
            extras.append("npx OK")
        else:
            extras.append("npx NOT FOUND")

        return CheckResult("node", True, f"Node {version} ({', '.join(extras)})")
    except (subprocess.TimeoutExpired, OSError):
        return CheckResult("node", True, f"Node found at {node_path} (version check timed out)")


def check_playwright(project_root: Path) -> CheckResult:
    """Check Playwright CLI availability and browser installation."""
    npx_path = shutil.which("npx")
    if not npx_path:
        return CheckResult("playwright", False, "npx not found — cannot run Playwright", "info")

    # Check if project uses Playwright (config file exists)
    pw_config_names = [
        "playwright.config.ts", "playwright.config.js",
        "playwright.config.mjs", "playwright.config.cjs",
    ]
    has_config = any((project_root / cfg).exists() for cfg in pw_config_names)

    # Check if playwright is in project dependencies
    has_dep = False
    pkg_json = project_root / "package.json"
    if pkg_json.exists():
        try:
            import json
            pkg = json.loads(pkg_json.read_text())
            all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            has_dep = "@playwright/test" in all_deps or "playwright" in all_deps
        except (json.JSONDecodeError, OSError):
            pass

    if not has_config and not has_dep:
        return CheckResult("playwright", True, "Not used in this project", )

    # Check if Playwright CLI works
    try:
        result = subprocess.run(
            ["npx", "playwright", "--version"],
            cwd=project_root, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return CheckResult(
                "playwright", False,
                "Playwright CLI failed — run 'npm install' in your project",
                "warning",
            )
        pw_version = result.stdout.strip().split("\n")[0]
    except (subprocess.TimeoutExpired, OSError):
        return CheckResult(
            "playwright", False,
            "Playwright CLI check timed out",
            "warning",
        )

    # Check if browsers are installed
    browsers_installed = False

    # Method 1: Check common browser cache locations
    cache_dirs = [
        Path.home() / ".cache" / "ms-playwright",           # Linux
        Path.home() / "Library" / "Caches" / "ms-playwright",  # macOS
        Path.home() / "AppData" / "Local" / "ms-playwright",   # Windows
    ]
    for cache_dir in cache_dirs:
        if cache_dir.exists() and any(cache_dir.iterdir()):
            browsers_installed = True
            break

    # Method 2: Check node_modules/.cache/ms-playwright (project-local)
    if not browsers_installed:
        local_cache = project_root / "node_modules" / ".cache" / "ms-playwright"
        if local_cache.exists() and any(local_cache.iterdir()):
            browsers_installed = True

    if not browsers_installed:
        return CheckResult(
            "playwright", False,
            f"Playwright {pw_version} found but browsers NOT installed — "
            f"run 'npx playwright install' to download browser binaries",
            "warning",
        )

    return CheckResult(
        "playwright", True,
        f"Playwright {pw_version} with browsers installed",
    )


def check_test_frameworks(project_root: Path) -> CheckResult:
    """Detect test frameworks configured in the project."""
    from warchief.test_runner import detect_test_commands
    detected = detect_test_commands(project_root)

    parts = []
    if detected.test_command:
        parts.append(f"unit: '{detected.test_command}'")
    if detected.e2e_command:
        parts.append(f"e2e: '{detected.e2e_command}'")

    if not parts:
        return CheckResult(
            "test_frameworks", False,
            "No test framework detected — tester agent will set one up",
            "info",
        )

    source = f" (from {detected.source})" if detected.source else ""
    return CheckResult(
        "test_frameworks", True,
        f"Detected: {', '.join(parts)}{source}",
    )


def run_doctor(project_root: Path) -> HealthReport:
    """Run all health checks and return a report."""
    report = HealthReport()

    # Environment checks (no DB needed)
    report.checks.append(check_claude_cli())
    report.checks.append(check_gh_cli())
    report.checks.append(check_git(project_root))
    report.checks.append(check_git_user(project_root))
    report.checks.append(check_node())
    report.checks.append(check_tmux())

    # Project-specific checks
    report.checks.append(check_playwright(project_root))
    report.checks.append(check_test_frameworks(project_root))

    # Warchief state checks
    report.checks.append(check_warchief_dir(project_root))
    report.checks.append(check_database(project_root))
    report.checks.append(check_config(project_root))
    report.checks.append(check_watcher(project_root))
    report.checks.append(check_daemon(project_root))
    report.checks.append(check_disk_space(project_root))
    report.checks.append(check_log_file(project_root))

    # Checks that need the DB
    db_path = project_root / ".warchief" / "warchief.db"
    if db_path.exists():
        try:
            store = TaskStore(db_path)
            report.checks.append(check_agents(project_root, store))
            report.checks.append(check_orphaned_tasks(store))
            report.checks.append(check_worktrees(project_root, store))
            store.close()
        except Exception as e:
            report.checks.append(CheckResult("store_checks", False, f"Could not run DB checks: {e}", "error"))

    return report


def format_report(report: HealthReport) -> str:
    """Format the health report for display."""
    lines: list[str] = []
    lines.append("Warchief Health Check")
    lines.append("=" * 50)

    for check in report.checks:
        if check.ok:
            icon = "PASS"
        elif check.severity == "info":
            icon = "INFO"
        elif check.severity == "warning":
            icon = "WARN"
        else:
            icon = "FAIL"
        lines.append(f"  [{icon}] {check.name}: {check.message}")

    lines.append("")
    if report.healthy:
        lines.append("All checks passed. System is healthy.")
    else:
        parts = []
        if report.error_count:
            parts.append(f"{report.error_count} error(s)")
        if report.warning_count:
            parts.append(f"{report.warning_count} warning(s)")
        lines.append(f"Issues found: {', '.join(parts)}")

    return "\n".join(lines)
