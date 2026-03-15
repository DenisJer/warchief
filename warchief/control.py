"""Control — interactive command pane for the tmux UI.

Provides a REPL for answering agent questions, viewing status,
and managing the pipeline without leaving the tmux session.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path


HELP_TEXT = """
Warchief Control
================
Commands:
  questions / q       Show pending questions from agents
  answer <id> <text>  Answer an agent's question
  tell <id> <text>    Send a message to a task (next agent sees it)
  nudge <id> <text>   Send a message AND restart the agent immediately
  retry <id> <text>   Reopen a task with feedback
  testing             Show tasks waiting for Playwright testing
  approve <id>        Approve a task after manual testing
  reject <id> <text>  Reject a task after testing (sends back to development)
  status / s          Show pipeline status summary
  agents / a          List running agents
  costs / c           Show cost summary
  tasks / t           List all tasks
  help / h            Show this help
  quit                Exit control pane
"""


def run_control(project_root: Path) -> None:
    """Run the interactive control REPL."""
    print(HELP_TEXT)

    # Check for questions on startup
    _show_questions(project_root)

    last_question_check = time.time()
    known_question_ids: set[str] = set()

    # Seed known questions
    try:
        store = _get_store(project_root)
        for t in store.list_tasks(has_label="question"):
            known_question_ids.add(t.id)
        store.close()
    except Exception:
        pass

    try:
        while True:
            # Check for NEW questions every 5 seconds
            if time.time() - last_question_check > 5:
                new_questions = _check_new_questions(project_root, known_question_ids)
                if new_questions:
                    print(f"\n\a{'=' * 50}")
                    print(f"  NEW QUESTION(S) from agent!")
                    print(f"{'=' * 50}")
                    _show_questions(project_root)
                    for q in new_questions:
                        known_question_ids.add(q)
                last_question_check = time.time()

            try:
                line = input("\nwarchief> ").strip()
            except EOFError:
                break

            if not line:
                continue

            parts = line.split(None, 2)
            cmd = parts[0].lower()

            if cmd in ("quit", "exit"):
                break
            elif cmd in ("help", "h"):
                print(HELP_TEXT)
            elif cmd in ("questions", "q"):
                _show_questions(project_root)
            elif cmd == "answer" and len(parts) >= 3:
                _do_answer(project_root, parts[1], parts[2])
            elif cmd == "answer":
                print("Usage: answer <task-id> <your answer>")
            elif cmd == "tell" and len(parts) >= 3:
                _do_tell(project_root, parts[1], parts[2])
            elif cmd == "tell":
                print("Usage: tell <task-id> <message>")
            elif cmd == "nudge" and len(parts) >= 3:
                _do_nudge(project_root, parts[1], parts[2])
            elif cmd == "nudge":
                print("Usage: nudge <task-id> <message>")
            elif cmd == "retry" and len(parts) >= 3:
                _do_retry(project_root, parts[1], parts[2])
            elif cmd == "retry":
                print("Usage: retry <task-id> <feedback>")
            elif cmd == "testing":
                _show_testing(project_root)
            elif cmd == "approve" and len(parts) >= 2:
                _do_approve(project_root, parts[1])
            elif cmd == "approve":
                print("Usage: approve <task-id>")
            elif cmd == "reject" and len(parts) >= 3:
                _do_reject(project_root, parts[1], parts[2])
            elif cmd == "reject" and len(parts) >= 2:
                print("Usage: reject <task-id> <feedback>")
            elif cmd in ("status", "s"):
                _show_status(project_root)
            elif cmd in ("agents", "a"):
                _show_agents(project_root)
            elif cmd in ("costs", "c"):
                _show_costs(project_root)
            elif cmd in ("tasks", "t"):
                _show_tasks(project_root)
            else:
                print(f"Unknown command: {cmd}. Type 'help' for commands.")

    except KeyboardInterrupt:
        pass


def _get_store(project_root: Path):
    from warchief.task_store import TaskStore
    return TaskStore(project_root / ".warchief" / "warchief.db")


def _check_new_questions(project_root: Path, known_ids: set[str]) -> list[str]:
    """Return task IDs of questions we haven't seen before."""
    try:
        store = _get_store(project_root)
        tasks = store.list_tasks(has_label="question")
        store.close()
        return [t.id for t in tasks if t.id not in known_ids]
    except Exception:
        return []


def _count_questions(project_root: Path) -> int:
    try:
        store = _get_store(project_root)
        tasks = store.list_tasks(has_label="question")
        store.close()
        return len(tasks)
    except Exception:
        return 0


def _show_questions(project_root: Path) -> None:
    try:
        store = _get_store(project_root)
        tasks = store.list_tasks(has_label="question")
        if not tasks:
            print("No pending questions.")
            store.close()
            return

        print(f"\nPending Questions ({len(tasks)}):")
        print("-" * 50)
        for t in tasks:
            messages = store.get_task_messages(t.id)
            questions = [m for m in messages if m.message_type == "question"]
            latest = questions[-1].body if questions else "(no question text)"
            print(f'  {t.id} "{t.title}"')
            print(f"    Q: {latest}")
            print(f'    -> answer {t.id} "your answer"')
            print()
        store.close()
    except Exception as e:
        print(f"Error: {e}")


def _do_answer(project_root: Path, task_id: str, answer_text: str) -> None:
    import uuid
    try:
        store = _get_store(project_root)
        task = store.get_task(task_id)
        if not task:
            print(f"Task {task_id} not found.")
            store.close()
            return

        if "question" not in task.labels:
            print(f"Task {task_id} has no pending question.")
            store.close()
            return

        from warchief.models import MessageRecord, EventRecord
        store.create_message(MessageRecord(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            from_agent="user",
            to_agent=task_id,
            message_type="answer",
            body=answer_text,
            persistent=True,
            created_at=time.time(),
        ))

        new_labels = [l for l in task.labels if l != "question"]
        store.update_task(task_id, status="open", labels=new_labels)

        store.log_event(EventRecord(
            event_type="answer",
            task_id=task_id,
            details={"answer": answer_text},
            actor="user",
            created_at=time.time(),
        ))

        store.close()
        print(f"Answered {task_id}. Agent will re-spawn with your response.")
    except Exception as e:
        print(f"Error: {e}")


def _do_tell(project_root: Path, task_id: str, message: str) -> None:
    """Store a message for a task. The next agent spawned will see it."""
    import uuid
    try:
        store = _get_store(project_root)
        task = store.get_task(task_id)
        if not task:
            print(f"Task {task_id} not found.")
            store.close()
            return

        from warchief.models import MessageRecord, EventRecord
        store.create_message(MessageRecord(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            from_agent="user",
            to_agent=task_id,
            message_type="feedback",
            body=message,
            persistent=True,
            created_at=time.time(),
        ))
        store.log_event(EventRecord(
            event_type="user_message",
            task_id=task_id,
            details={"message": message},
            actor="user",
            created_at=time.time(),
        ))
        store.close()

        agent_info = f" (agent {task.assigned_agent} is working on it)" if task.assigned_agent else ""
        print(f"Message stored for {task_id}{agent_info}.")
        print(f"The next agent spawned for this task will see your message.")
    except Exception as e:
        print(f"Error: {e}")


def _do_nudge(project_root: Path, task_id: str, message: str) -> None:
    """Send a message and restart the agent so it sees it immediately."""
    import os
    import signal
    import uuid
    try:
        store = _get_store(project_root)
        task = store.get_task(task_id)
        if not task:
            print(f"Task {task_id} not found.")
            store.close()
            return

        from warchief.models import MessageRecord, EventRecord

        # Store the message
        store.create_message(MessageRecord(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            from_agent="user",
            to_agent=task_id,
            message_type="feedback",
            body=message,
            persistent=True,
            created_at=time.time(),
        ))
        store.log_event(EventRecord(
            event_type="nudge",
            task_id=task_id,
            details={"message": message},
            actor="user",
            created_at=time.time(),
        ))

        # Kill the current agent if one is running
        if task.assigned_agent:
            agent = store.get_agent(task.assigned_agent)
            if agent and agent.pid and agent.status == "alive":
                print(f"Stopping agent {agent.id} (PID {agent.pid})...")
                try:
                    os.kill(agent.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                store.update_agent(agent.id, status="dead")

        # Always send back to development — user is giving new instructions
        new_labels = [l for l in task.labels
                      if not l.startswith("stage:") and l not in ("rejected", "question")]
        new_labels.append("stage:development")
        store.update_task(
            task_id,
            status="open",
            stage="development",
            labels=new_labels,
            assigned_agent=None,
        )

        store.close()
        print(f"Nudged task {task_id}. Agent will re-spawn with your message.")
    except Exception as e:
        print(f"Error: {e}")


def _do_retry(project_root: Path, task_id: str, feedback: str) -> None:
    import uuid
    try:
        store = _get_store(project_root)
        task = store.get_task(task_id)
        if not task:
            print(f"Task {task_id} not found.")
            store.close()
            return

        from warchief.models import MessageRecord, EventRecord
        new_labels = [l for l in task.labels
                      if not l.startswith("stage:") and l not in ("rejected", "question")]
        new_labels.append("stage:development")

        store.update_task(
            task_id, status="open", stage="development",
            labels=new_labels, assigned_agent=None,
            spawn_count=0, crash_count=0,
        )
        store.create_message(MessageRecord(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            from_agent="user",
            to_agent=task_id,
            message_type="feedback",
            body=feedback,
            persistent=True,
            created_at=time.time(),
        ))
        store.log_event(EventRecord(
            event_type="retry",
            task_id=task_id,
            details={"feedback": feedback},
            actor="user",
            created_at=time.time(),
        ))
        store.close()
        print(f"Task {task_id} reopened with feedback. Agent will re-spawn.")
    except Exception as e:
        print(f"Error: {e}")


def _show_testing(project_root: Path) -> None:
    """Show tasks waiting for manual Playwright testing."""
    try:
        store = _get_store(project_root)
        tasks = store.list_tasks(has_label="needs-testing")
        store.close()

        if not tasks:
            print("No tasks waiting for testing.")
            return

        print(f"\nTasks Awaiting Testing ({len(tasks)}):")
        print("-" * 50)
        for t in tasks:
            print(f'  {t.id} "{t.title}"')
            print(f"    Run Playwright tests, then:")
            print(f'    -> approve {t.id}')
            print(f'    -> reject {t.id} "feedback"')
            print()
    except Exception as e:
        print(f"Error: {e}")


def _do_approve(project_root: Path, task_id: str) -> None:
    """Approve a task after manual Playwright testing."""
    try:
        store = _get_store(project_root)
        task = store.get_task(task_id)
        if not task:
            print(f"Task {task_id} not found.")
            store.close()
            return

        if "needs-testing" not in task.labels:
            print(f"Task {task_id} is not waiting for testing.")
            store.close()
            return

        from warchief.models import EventRecord
        # Remove needs-testing label — state machine will advance to pr-creation
        new_labels = [l for l in task.labels if l != "needs-testing"]
        store.update_task(task_id, status="open", labels=new_labels)

        store.log_event(EventRecord(
            event_type="testing_approved",
            task_id=task_id,
            details={"approved_by": "user"},
            actor="user",
            created_at=time.time(),
        ))

        store.close()
        print(f"Approved {task_id}. Task will proceed to PR creation.")
    except Exception as e:
        print(f"Error: {e}")


def _do_reject(project_root: Path, task_id: str, feedback: str) -> None:
    """Reject a task after manual testing — sends back to development."""
    import uuid
    try:
        store = _get_store(project_root)
        task = store.get_task(task_id)
        if not task:
            print(f"Task {task_id} not found.")
            store.close()
            return

        if "needs-testing" not in task.labels:
            print(f"Task {task_id} is not waiting for testing.")
            store.close()
            return

        from warchief.models import MessageRecord, EventRecord

        # Remove needs-testing and stage labels, add rejected, send back to development
        new_labels = [l for l in task.labels
                      if l != "needs-testing" and not l.startswith("stage:")]
        new_labels.append("stage:development")

        store.update_task(
            task_id, status="open", stage="development",
            labels=new_labels, assigned_agent=None,
        )

        # Store feedback message so the developer agent sees it
        store.create_message(MessageRecord(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            from_agent="user",
            to_agent=task_id,
            message_type="feedback",
            body=f"[Testing rejected] {feedback}",
            persistent=True,
            created_at=time.time(),
        ))

        store.log_event(EventRecord(
            event_type="testing_rejected",
            task_id=task_id,
            details={"feedback": feedback},
            actor="user",
            created_at=time.time(),
        ))

        store.close()
        print(f"Rejected {task_id}. Task sent back to development with your feedback.")
    except Exception as e:
        print(f"Error: {e}")


def _show_status(project_root: Path) -> None:
    try:
        store = _get_store(project_root)
        tasks = store.list_tasks()
        agents = store.get_running_agents()
        store.close()

        by_status: dict[str, int] = {}
        for t in tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1

        alive = sum(1 for a in agents if a.status == "alive")
        print(f"\nPipeline Status:")
        print(f"  Tasks: {len(tasks)} total", end="")
        for s in ["open", "in_progress", "blocked", "closed"]:
            if by_status.get(s, 0):
                print(f" | {s}: {by_status[s]}", end="")
        print(f"\n  Agents: {alive} running")
    except Exception as e:
        print(f"Error: {e}")


def _show_agents(project_root: Path) -> None:
    try:
        store = _get_store(project_root)
        agents = store.get_running_agents()
        store.close()

        alive = [a for a in agents if a.status == "alive"]
        if not alive:
            print("No running agents.")
            return

        print(f"\nRunning Agents ({len(alive)}):")
        print("-" * 50)
        for a in alive:
            age = int(time.time() - a.spawned_at) if a.spawned_at else 0
            print(f"  {a.id:<35} {a.role:<15} -> {a.current_task or '-'} ({age}s)")
    except Exception as e:
        print(f"Error: {e}")


def _show_costs(project_root: Path) -> None:
    try:
        from warchief.cost_tracker import compute_cost_summary
        summary = compute_cost_summary(project_root)
        if not summary.entries:
            print("No cost data yet.")
            return

        print(f"\nCosts:")
        print(f"  Total: ${summary.total_cost_usd:.4f}")
        print(f"  Input:  {summary.total_input_tokens:,} tokens")
        print(f"  Output: {summary.total_output_tokens:,} tokens")
        if summary.by_role:
            print("  By role:")
            for role, cost in sorted(summary.by_role.items(), key=lambda x: -x[1]):
                print(f"    {role:<18} ${cost:.4f}")
    except Exception as e:
        print(f"Error: {e}")


def _show_tasks(project_root: Path) -> None:
    try:
        store = _get_store(project_root)
        tasks = store.list_tasks()
        store.close()

        if not tasks:
            print("No tasks.")
            return

        print(f"\nTasks ({len(tasks)}):")
        print("-" * 60)
        for t in tasks:
            stage = t.stage or "-"
            print(f"  {t.id} [{t.status:<11}] {stage:<15} {t.title[:40]}")
    except Exception as e:
        print(f"Error: {e}")
