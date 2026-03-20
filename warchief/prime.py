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
        sections.append(
            f"## Previous Attempts\n"
            f"This task has been attempted {task.spawn_count} time(s) before.\n"
            f"Crashes: {task.crash_count} | Rejections: {task.rejection_count}"
        )

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
            body = (
                msg.body
                if len(msg.body) <= _MAX_MSG_CHARS
                else ("...\n" + msg.body[-_MAX_MSG_CHARS:])
            )
            sections.append(body)

    # Rejection feedback — focused summary instead of raw logs (Task 5)
    rejection_comments = [m for m in all_messages if m.message_type == "rejection"]
    if rejection_comments:
        sections.append("## Rejection Feedback")
        for msg in rejection_comments[-2:]:  # Last 2 rejections
            body = (
                msg.body
                if len(msg.body) <= _MAX_MSG_CHARS
                else ("...\n" + msg.body[-_MAX_MSG_CHARS:])
            )
            sections.append(body)

    # Task scratchpad — structured handoff notes from previous agents
    from warchief.scratchpad import read_scratchpad_for_role

    scratchpad = read_scratchpad_for_role(project_root, task.id, role)
    if scratchpad:
        sections.append(f"## Scratchpad (handoff notes from previous agents)\n{scratchpad}")

    # User messages (Q&A and feedback from retries) — reuse already-fetched messages
    qa_messages = [m for m in all_messages if m.message_type in ("question", "answer", "feedback")]
    if qa_messages:
        qa_lines = ["## Messages from User"]
        for msg in qa_messages:
            body = (
                msg.body
                if len(msg.body) <= _MAX_MSG_CHARS
                else ("...\n" + msg.body[-_MAX_MSG_CHARS:])
            )
            if msg.message_type == "question":
                qa_lines.append(f"Q: {body}")
            elif msg.message_type == "answer":
                qa_lines.append(f"A: {body}")
            elif msg.message_type == "feedback":
                qa_lines.append(f"USER FEEDBACK: {body}")
        if len(qa_lines) > 1:  # More than just the header
            sections.append("\n".join(qa_lines))

    # Group sibling context
    if task.group_id:
        siblings = store.get_group_tasks(task.group_id)
        siblings = [s for s in siblings if s.id != task.id]
        if siblings and role == "developer":
            done = [s for s in siblings if "group-dev-done" in s.labels or s.status == "closed"]
            pending = [s for s in siblings if s not in done]
            all_closed = all(s.status == "closed" for s in siblings)
            lines = ["## Group Context (sibling tasks on this branch)"]
            if all_closed:
                # Lead task after rejection — responsible for ALL code on the branch
                lines.append("You are the GROUP LEAD. All sibling tasks are closed.")
                lines.append(
                    "Their code is on this branch — you are responsible for fixing ALL issues:"
                )
                for s in siblings:
                    lines.append(f"- {s.title}")
            else:
                if done:
                    lines.append("Completed siblings (their commits are already on this branch):")
                    for s in done:
                        lines.append(f"- {s.id}: {s.title}")
                if pending:
                    lines.append("Pending siblings (will develop after you):")
                    for s in pending:
                        lines.append(f"- {s.id}: {s.title}")
            sections.append("\n".join(lines))
        elif siblings and role in ("reviewer", "security_reviewer"):
            lines = [
                "## Group Context — Review ALL changes as a cohesive unit",
                "This branch contains work from multiple sub-tasks. "
                "Review the combined changes holistically:",
            ]
            for s in siblings:
                lines.append(f"- {s.id}: {s.title}")
            lines.append(f"- {task.id}: {task.title} (this task)")
            sections.append("\n".join(lines))

    # Dependency status
    if task.deps:
        sections.append("## Dependencies")
        for dep_id in task.deps:
            dep = store.get_task(dep_id)
            if dep:
                sections.append(f"- {dep_id}: {dep.title} [{dep.status}]")
            else:
                sections.append(f"- {dep_id}: (not found)")

    # Changed files context for reviewers and testers
    if role in ("reviewer", "security_reviewer", "tester"):
        import subprocess

        try:
            from warchief.config import detect_default_branch

            branch = f"feature/{task.group_id}" if task.group_id else f"feature/{task.id}"
            base = detect_default_branch(project_root)
            result = subprocess.run(
                ["git", "diff", "--stat", f"{base}...{branch}"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                sections.append(f"## Changed Files\n```\n{result.stdout.strip()}\n```")
        except (subprocess.TimeoutExpired, OSError):
            pass

    if not sections:
        return ""

    return "\n\n".join(sections) + "\n"
