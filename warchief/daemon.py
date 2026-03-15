"""Daemon — background process that supervises the watcher and manages health."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from warchief.config import (
    Config, DAEMON_HEARTBEAT, MASS_DEATH_THRESHOLD, MASS_DEATH_WINDOW,
    read_config, setup_logging,
)
from warchief.models import EventRecord
from warchief.recovery import run_full_recovery
from warchief.roles import RoleRegistry
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.daemon")


class Daemon:
    """Background daemon that:

    1. Monitors the watcher and restarts it on crash
    2. Performs periodic health checks
    3. Detects mass agent death and pauses dispatch
    4. Triggers periodic backups
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._running = False
        self._watcher_pid: int | None = None
        self._recent_deaths: list[float] = []

    def start(self, foreground: bool = False) -> None:
        """Start the daemon. If not foreground, daemonize."""
        if not foreground:
            self._daemonize()

        self._running = True
        self._write_pid_file()
        self._install_signal_handlers()

        setup_logging(self.project_root)
        log.info("Daemon started (PID %d)", os.getpid())

        try:
            self._run_loop()
        finally:
            self._cleanup()

    def stop(self) -> None:
        self._running = False

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                log.exception("Error in daemon tick")
            time.sleep(DAEMON_HEARTBEAT)

    def _tick(self) -> None:
        config = read_config(self.project_root)

        # Write daemon heartbeat
        self._write_heartbeat()

        # Check watcher health and restart if needed
        self._ensure_watcher(config)

        # Check for mass death
        self._check_mass_death(config)

        # Periodic recovery
        self._periodic_recovery()

    # ── Watcher management ──────────────────────────────────────

    def _ensure_watcher(self, config: Config) -> None:
        """Ensure the watcher is running. Restart if dead."""
        lock_path = self.project_root / ".warchief" / "watcher.lock"

        if lock_path.exists():
            try:
                pid = int(lock_path.read_text().strip())
                if _is_process_alive(pid):
                    return  # Watcher is alive
            except (ValueError, OSError):
                pass

        if config.paused:
            return

        log.info("Watcher not running, starting it")
        self._start_watcher()

    def _start_watcher(self) -> None:
        """Spawn the watcher as a subprocess."""
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "warchief", "watch"],
                cwd=self.project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._watcher_pid = proc.pid
            log.info("Started watcher (PID %d)", proc.pid)
        except OSError as e:
            log.error("Failed to start watcher: %s", e)

    # ── Mass death detection ────────────────────────────────────

    def _check_mass_death(self, config: Config) -> None:
        """Detect mass agent death and pause dispatch."""
        store = self._open_store()
        try:
            running = store.get_running_agents()
            # Count recently dead agents
            events = store.get_events(limit=50)
            now = time.time()

            recent_crashes = [
                e for e in events
                if e.event_type in ("crash", "zombie_recovery", "orphan_recovery")
                and (now - e.created_at) < MASS_DEATH_WINDOW
            ]

            if len(recent_crashes) >= MASS_DEATH_THRESHOLD:
                if not config.paused:
                    log.critical(
                        "MASS DEATH DETECTED: %d agent failures in %ds. Pausing pipeline.",
                        len(recent_crashes), MASS_DEATH_WINDOW,
                    )
                    config.paused = True
                    from warchief.config import write_config
                    write_config(self.project_root, config)

                    store.log_event(EventRecord(
                        event_type="mass_death",
                        details={
                            "crash_count": len(recent_crashes),
                            "window_seconds": MASS_DEATH_WINDOW,
                        },
                        actor="daemon",
                    ))
        finally:
            store.close()

    # ── Periodic recovery ───────────────────────────────────────

    def _periodic_recovery(self) -> None:
        """Run recovery procedures periodically."""
        store = self._open_store()
        try:
            summary = run_full_recovery(store, self.project_root)
            if any(summary.values()):
                log.info("Recovery summary: %s", summary)
        finally:
            store.close()

    # ── Helpers ─────────────────────────────────────────────────

    def _open_store(self) -> TaskStore:
        return TaskStore(self.project_root / ".warchief" / "warchief.db")

    def _write_pid_file(self) -> None:
        pid_path = self.project_root / ".warchief" / "daemon.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

    def _write_heartbeat(self) -> None:
        hb_path = self.project_root / ".warchief" / "daemon_heartbeat"
        hb_path.write_text(str(time.time()))

    def _cleanup(self) -> None:
        pid_path = self.project_root / ".warchief" / "daemon.pid"
        pid_path.unlink(missing_ok=True)
        log.info("Daemon stopped")

    def _install_signal_handlers(self) -> None:
        def handle_stop(signum, frame):
            log.info("Received signal %d, stopping daemon", signum)
            self.stop()

        signal.signal(signal.SIGTERM, handle_stop)
        signal.signal(signal.SIGINT, handle_stop)

    def _daemonize(self) -> None:
        """Double-fork to detach from terminal."""
        if os.fork() > 0:
            sys.exit(0)
        os.setsid()
        if os.fork() > 0:
            sys.exit(0)
        # Redirect stdio
        sys.stdin = open(os.devnull, "r")
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")


def stop_daemon(project_root: Path) -> bool:
    """Stop a running daemon by reading its PID file."""
    pid_path = project_root / ".warchief" / "daemon.pid"
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False


def daemon_status(project_root: Path) -> dict:
    """Check daemon status."""
    pid_path = project_root / ".warchief" / "daemon.pid"
    hb_path = project_root / ".warchief" / "daemon_heartbeat"

    status: dict = {"running": False, "pid": None, "last_heartbeat": None}

    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            status["pid"] = pid
            status["running"] = _is_process_alive(pid)
        except (ValueError, OSError):
            pass

    if hb_path.exists():
        try:
            status["last_heartbeat"] = float(hb_path.read_text().strip())
        except (ValueError, OSError):
            pass

    return status


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
