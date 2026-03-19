"""Heartbeat system — agents write heartbeats, watcher detects zombies."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger("warchief.heartbeat")

HEARTBEAT_DIR = "heartbeats"
HEARTBEAT_INTERVAL = 60  # seconds between heartbeats


def heartbeat_dir(project_root: Path) -> Path:
    return project_root / ".warchief" / HEARTBEAT_DIR


def write_heartbeat(project_root: Path, agent_id: str) -> None:
    """Write a heartbeat file for this agent. Called by the agent periodically."""
    hb_dir = heartbeat_dir(project_root)
    hb_dir.mkdir(parents=True, exist_ok=True)
    hb_file = hb_dir / agent_id
    hb_file.write_text(str(time.time()))


def read_heartbeat(project_root: Path, agent_id: str) -> float | None:
    """Read the last heartbeat timestamp for an agent. Returns None if no heartbeat."""
    hb_file = heartbeat_dir(project_root) / agent_id
    if not hb_file.exists():
        return None
    try:
        return float(hb_file.read_text().strip())
    except (ValueError, OSError):
        return None


def is_zombie(project_root: Path, agent_id: str, threshold: float) -> bool:
    """Check if an agent is a zombie (heartbeat older than threshold seconds)."""
    last_hb = read_heartbeat(project_root, agent_id)
    if last_hb is None:
        return False  # No heartbeat file = hasn't started yet
    return (time.time() - last_hb) > threshold


def cleanup_heartbeat(project_root: Path, agent_id: str) -> None:
    """Remove the heartbeat file for a dead/retired agent."""
    hb_file = heartbeat_dir(project_root) / agent_id
    if hb_file.exists():
        hb_file.unlink()
        log.debug("Cleaned up heartbeat for %s", agent_id)


def list_heartbeats(project_root: Path) -> dict[str, float]:
    """Return a dict of agent_id -> last_heartbeat_timestamp."""
    hb_dir = heartbeat_dir(project_root)
    if not hb_dir.exists():
        return {}
    result: dict[str, float] = {}
    for f in hb_dir.iterdir():
        if f.is_file():
            try:
                result[f.name] = float(f.read_text().strip())
            except (ValueError, OSError):
                pass
    return result
