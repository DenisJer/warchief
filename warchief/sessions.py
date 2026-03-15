"""Sessions — multi-project session management."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

SESSIONS_DIR = Path.home() / ".warchief-sessions"
SESSIONS_FILE = SESSIONS_DIR / "sessions.json"


@dataclass
class Session:
    project_root: str
    project_name: str
    started_at: float = 0.0
    last_active: float = 0.0
    pid: int | None = None
    status: str = "active"  # active, stopped


def _load_sessions() -> list[Session]:
    """Load all sessions from the global sessions file."""
    if not SESSIONS_FILE.exists():
        return []
    try:
        data = json.loads(SESSIONS_FILE.read_text())
        return [Session(**s) for s in data]
    except (json.JSONDecodeError, TypeError, KeyError):
        return []


def _save_sessions(sessions: list[Session]) -> None:
    """Save sessions to the global sessions file."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    data = [asdict(s) for s in sessions]
    SESSIONS_FILE.write_text(json.dumps(data, indent=2))


def register_session(project_root: Path, project_name: str = "") -> Session:
    """Register or update a session for the given project."""
    sessions = _load_sessions()
    root_str = str(project_root.resolve())

    # Update if exists
    for s in sessions:
        if s.project_root == root_str:
            s.last_active = time.time()
            s.pid = os.getpid()
            s.status = "active"
            if project_name:
                s.project_name = project_name
            _save_sessions(sessions)
            return s

    # Create new
    name = project_name or project_root.name
    session = Session(
        project_root=root_str,
        project_name=name,
        started_at=time.time(),
        last_active=time.time(),
        pid=os.getpid(),
        status="active",
    )
    sessions.append(session)
    _save_sessions(sessions)
    return session


def deregister_session(project_root: Path) -> None:
    """Mark a session as stopped."""
    sessions = _load_sessions()
    root_str = str(project_root.resolve())
    for s in sessions:
        if s.project_root == root_str:
            s.status = "stopped"
            s.pid = None
    _save_sessions(sessions)


def list_sessions() -> list[Session]:
    """List all known sessions."""
    return _load_sessions()


def get_active_sessions() -> list[Session]:
    """Return only sessions with live processes."""
    sessions = _load_sessions()
    active: list[Session] = []
    changed = False

    for s in sessions:
        if s.status == "active" and s.pid:
            try:
                os.kill(s.pid, 0)
                active.append(s)
            except (ProcessLookupError, PermissionError):
                s.status = "stopped"
                s.pid = None
                changed = True
        elif s.status == "active" and not s.pid:
            s.status = "stopped"
            changed = True

    if changed:
        _save_sessions(sessions)
    return active


def get_session(project_root: Path) -> Session | None:
    """Get session for a specific project."""
    sessions = _load_sessions()
    root_str = str(project_root.resolve())
    for s in sessions:
        if s.project_root == root_str:
            return s
    return None


def cleanup_stale_sessions() -> int:
    """Remove sessions for projects that no longer exist. Returns count removed."""
    sessions = _load_sessions()
    valid: list[Session] = []
    removed = 0

    for s in sessions:
        if Path(s.project_root).exists():
            valid.append(s)
        else:
            removed += 1

    if removed:
        _save_sessions(valid)
    return removed
