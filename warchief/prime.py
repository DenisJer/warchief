"""Prime — context injection for agent startup.

Before an agent begins work, this module gathers relevant context:
- Previous attempt history (how many times this task has been tried)
- Rejection reasons from prior review cycles
- Crash/failure information
- Related task status (dependencies)
"""
from __future__ import annotations

import logging
from pathlib import Path

from warchief.models import TaskRecord
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.prime")


def build_prime_context(
    task: TaskRecord,
    role: str,
    store: TaskStore,
    project_root: Path,
) -> str:
    """Build context string to prepend to agent prompt."""
    sections: list[str] = []

    # Previous attempt info
    if task.spawn_count > 0:
        sections.append(f"## Previous Attempts\n"
                       f"This task has been attempted {task.spawn_count} time(s) before.\n"
                       f"Crashes: {task.crash_count} | Rejections: {task.rejection_count}")

    # Get relevant events for this task (rejections, blocks, crashes)
    events = store.get_events(limit=50)
    task_events = [e for e in events if e.task_id == task.id]

    rejection_events = [e for e in task_events if e.event_type in ("reject", "block", "advance")]
    if rejection_events:
        sections.append("## Task History")
        for ev in rejection_events[-5:]:  # Last 5 relevant events
            details = ev.details or {}
            reason = details.get("failure_reason", "")
            from_stage = details.get("from_stage", "")
            to_stage = details.get("to_stage", "")
            if reason:
                sections.append(f"- {ev.event_type}: {reason}")
            elif from_stage and to_stage:
                sections.append(f"- {ev.event_type}: {from_stage} → {to_stage}")

    # Handoff messages from previous stage agents (Task 4: context handoff)
    _MAX_MSG_CHARS = 1024
    all_messages = store.get_task_messages(task.id, limit=10)
    handoff_messages = [m for m in all_messages if m.message_type == "handoff"]
    if handoff_messages:
        sections.append("## Handoff from Previous Stage")
        for msg in handoff_messages[-2:]:  # Last 2 handoffs
            body = msg.body if len(msg.body) <= _MAX_MSG_CHARS else ("...\n" + msg.body[-_MAX_MSG_CHARS:])
            sections.append(body)

    # Rejection feedback — focused summary instead of raw logs (Task 5)
    rejection_comments = [m for m in all_messages if m.message_type == "rejection"]
    if rejection_comments:
        sections.append("## Rejection Feedback")
        for msg in rejection_comments[-2:]:  # Last 2 rejections
            body = msg.body if len(msg.body) <= _MAX_MSG_CHARS else ("...\n" + msg.body[-_MAX_MSG_CHARS:])
            sections.append(body)

    # Check previous agent logs for this task (last 2 only to limit context)
    agent_logs_dir = project_root / ".warchief" / "agent-logs"
    if agent_logs_dir.exists():
        # Find logs from previous agents on this task
        task_logs: list[Path] = []
        for log_file in sorted(agent_logs_dir.glob("*.log")):
            try:
                prompt_file = agent_logs_dir / f"{log_file.stem}.prompt"
                if prompt_file.exists():
                    prompt_text = prompt_file.read_text()
                    if task.id in prompt_text:
                        task_logs.append(log_file)
            except (OSError, UnicodeDecodeError):
                continue

        # Only include the last 2 agent logs, truncated to limit context bloat
        _MAX_LOG_CHARS = 500
        for log_file in task_logs[-2:]:
            try:
                content = log_file.read_text()
                lines = content.strip().split("\n")
                # Filter out tool call noise (file reads, glob results, etc.)
                filtered = [
                    l for l in lines
                    if not l.startswith("Reading: ") and not l.startswith("Glob: ")
                    and not l.startswith("Grep: ") and not l.startswith("  /")
                ]
                tail = filtered[-10:] if len(filtered) > 10 else filtered
                snippet = "\n".join(tail)
                if len(snippet) > _MAX_LOG_CHARS:
                    snippet = "...\n" + snippet[-_MAX_LOG_CHARS:]
                sections.append(f"## Previous Agent Log ({log_file.stem})\n"
                               f"Last output:\n```\n{snippet}\n```")
            except (OSError, UnicodeDecodeError):
                continue

    # User messages (Q&A and feedback from retries) — reuse already-fetched messages
    qa_messages = [m for m in all_messages if m.message_type in ("question", "answer", "feedback")]
    if qa_messages:
        qa_lines = ["## Messages from User"]
        for msg in qa_messages:
            body = msg.body if len(msg.body) <= _MAX_MSG_CHARS else ("...\n" + msg.body[-_MAX_MSG_CHARS:])
            if msg.message_type == "question":
                qa_lines.append(f"Q: {body}")
            elif msg.message_type == "answer":
                qa_lines.append(f"A: {body}")
            elif msg.message_type == "feedback":
                qa_lines.append(f"USER FEEDBACK: {body}")
        if len(qa_lines) > 1:  # More than just the header
            sections.append("\n".join(qa_lines))

    # Dependency status
    if task.deps:
        sections.append("## Dependencies")
        for dep_id in task.deps:
            dep = store.get_task(dep_id)
            if dep:
                sections.append(f"- {dep_id}: {dep.title} [{dep.status}]")
            else:
                sections.append(f"- {dep_id}: (not found)")

    if not sections:
        return ""

    return "\n\n".join(sections) + "\n"
