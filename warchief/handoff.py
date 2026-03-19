"""Handoff — session cycling with context preservation (from Gastown)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from warchief.communication import send_mail
from warchief.models import MessageRecord
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.handoff")


def create_handoff(
    store: TaskStore,
    from_agent: str,
    to_agent: str,
    task_id: str,
    context: str,
) -> None:
    """Create a handoff message from one agent session to the next.

    Used when an agent's session is about to die (timeout, context compaction)
    and needs to transfer state to a fresh session.
    """
    body = f"HANDOFF from {from_agent}\nTask: {task_id}\n---\n{context}"

    send_mail(
        store=store,
        to_agent=to_agent,
        body=body,
        message_type="HANDOFF",
        from_agent=from_agent,
    )

    log.info("Handoff created: %s -> %s for task %s", from_agent, to_agent, task_id)


def save_conductor_context(project_root: Path, context: str) -> None:
    """Save conductor context to a file for crash recovery.

    Written by the conductor before context compaction.
    Append-only history is also maintained.
    """
    wc_dir = project_root / ".warchief"
    wc_dir.mkdir(parents=True, exist_ok=True)

    # Volatile context (overwritten each time)
    ctx_path = wc_dir / "conductor-context.md"
    ctx_path.write_text(context)

    # Append-only history
    history_path = wc_dir / "conductor-history.md"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with history_path.open("a") as f:
        f.write(f"\n---\n## {timestamp}\n{context}\n")

    log.info("Conductor context saved (%d chars)", len(context))


def load_conductor_context(project_root: Path) -> str | None:
    """Load the latest conductor context. Returns None if not found."""
    ctx_path = project_root / ".warchief" / "conductor-context.md"
    if ctx_path.exists():
        return ctx_path.read_text()
    return None
