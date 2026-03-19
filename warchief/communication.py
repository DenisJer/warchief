"""Communication layer — nudge (ephemeral) and mail (persistent) channels."""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from warchief.models import MessageRecord
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.communication")

NUDGE_DIR = "nudges"

# Only these 5 message types are permitted as persistent mail.
MAIL_TYPES = {"DONE", "BLOCKED", "HANDOFF", "HELP", "ESCALATE"}


def nudge_dir(project_root: Path) -> Path:
    return project_root / ".warchief" / NUDGE_DIR


def send_nudge(
    project_root: Path,
    agent_id: str,
    message: str,
    agent_pid: int | None = None,
) -> bool:
    """Send an ephemeral nudge to an agent via file + SIGUSR1.

    Zero DB cost. Lost if the agent is dead.
    Returns True if the nudge was delivered.
    """
    ndir = nudge_dir(project_root) / agent_id
    ndir.mkdir(parents=True, exist_ok=True)

    nudge_file = ndir / f"{time.time():.6f}"
    nudge_file.write_text(message)

    if agent_pid:
        try:
            os.kill(agent_pid, signal.SIGUSR1)
            log.debug("Nudge sent to %s (PID %d): %s", agent_id, agent_pid, message[:50])
            return True
        except (ProcessLookupError, PermissionError):
            log.debug("Nudge signal failed for %s (PID %d)", agent_id, agent_pid)
            return False

    log.debug("Nudge file written for %s (no PID to signal)", agent_id)
    return True


def read_nudges(project_root: Path, agent_id: str) -> list[str]:
    """Read and consume all pending nudges for an agent."""
    ndir = nudge_dir(project_root) / agent_id
    if not ndir.exists():
        return []

    messages: list[str] = []
    for f in sorted(ndir.iterdir()):
        if f.is_file():
            try:
                messages.append(f.read_text())
                f.unlink()
            except OSError:
                pass

    return messages


def cleanup_nudges(project_root: Path, agent_id: str) -> None:
    """Remove all nudge files for an agent."""
    ndir = nudge_dir(project_root) / agent_id
    if not ndir.exists():
        return
    for f in ndir.iterdir():
        if f.is_file():
            f.unlink(missing_ok=True)
    try:
        ndir.rmdir()
    except OSError:
        pass


def send_mail(
    store: TaskStore,
    to_agent: str,
    body: str,
    message_type: str,
    from_agent: str | None = None,
) -> None:
    """Send persistent mail via the SQLite messages table.

    Only the 5 permitted message types are allowed: DONE, BLOCKED, HANDOFF, HELP, ESCALATE.
    """
    if message_type not in MAIL_TYPES:
        log.warning("Invalid mail type '%s'. Allowed: %s", message_type, MAIL_TYPES)
        return

    msg = MessageRecord(
        id=f"mail-{time.time():.6f}",
        to_agent=to_agent,
        body=body,
        from_agent=from_agent,
        message_type=message_type,
        persistent=True,
    )
    store.create_message(msg)
    log.info("Mail sent: %s -> %s (%s)", from_agent or "system", to_agent, message_type)


def get_unread_mail(store: TaskStore, agent_id: str) -> list[MessageRecord]:
    """Retrieve unread persistent mail for an agent."""
    return store.get_unread_mail(agent_id)


def mark_mail_read(store: TaskStore, message_id: str) -> None:
    """Mark a mail message as read."""
    store.mark_read(message_id)
