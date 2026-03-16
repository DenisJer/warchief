"""Watcher — the main poll loop that monitors agents and drives transitions."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path

from warchief.config import (
    AGENT_TIMEOUT, Config, FRONTEND_EXTENSIONS, POLL_INTERVAL, STAGE_TO_ROLE,
    ZOMBIE_THRESHOLD, MAX_SPAWNS_PER_CYCLE, MAX_REJECTIONS, MAX_CRASHES,
    MAX_TOTAL_SPAWNS, MAX_AUTO_RETRIES, read_config,
)
from warchief.heartbeat import cleanup_heartbeat, is_zombie
from warchief.models import AgentRecord, EventRecord, TaskRecord, TransitionResult, get_task_branch
from warchief.preflight import run_preflight
from warchief.roles import RoleRegistry
from warchief.spawner import spawn_agent
from warchief.state_machine import dispatch_transition
from warchief.task_store import TaskStore
from warchief.cost_tracker import CostEntry, TokenUsage, append_cost_entry, estimate_cost, get_task_cost, get_session_cost
from warchief.worktree import remove_worktree

log = logging.getLogger("warchief.watcher")


class Watcher:
    """Main orchestration loop.

    Polls the task store every ``poll_interval`` seconds and:
    1. Cleans up finished/crashed agents
    2. Runs state machine transitions
    3. Checks for zombies
    4. Spawns agents for ready tasks
    """

    def __init__(
        self,
        project_root: Path,
        store: TaskStore,
        config: Config,
        registry: RoleRegistry,
        verbose: bool = False,
    ) -> None:
        self.project_root = project_root
        self.store = store
        self.config = config
        self.registry = registry
        self.poll_interval = POLL_INTERVAL
        self._running = False
        self._tick_count = 0
        self._verbose = verbose
        self._last_status_line = ""
        self._spawn_backoff: dict[str, float] = {}  # task_id -> earliest_next_spawn timestamp
        self._session_start: float = time.time()
        self._budget_warned: bool = False  # session budget warning already logged
        # Track Popen objects for reliable exit code retrieval
        self._agent_procs: dict[str, subprocess.Popen] = {}  # agent_id -> claude Popen
        self._log_writer_procs: dict[str, subprocess.Popen] = {}  # agent_id -> log_writer Popen

    def start(self) -> None:
        """Start the watcher loop. Blocks until stopped."""
        self._running = True
        self._install_signal_handlers()
        lock_path = self.project_root / ".warchief" / "watcher.lock"

        try:
            lock_fd = _acquire_lock(lock_path)
        except RuntimeError as e:
            log.error("Cannot start watcher: %s", e)
            return

        log.info("Watcher started (PID %d)", os.getpid())
        try:
            while self._running:
                try:
                    self.tick()
                except Exception:
                    log.exception("Error in watcher tick")
                time.sleep(self.poll_interval)
        finally:
            log.info("Watcher shutting down — killing agents...")
            self._kill_all_agents()
            _release_lock(lock_fd, lock_path)
            log.info("Watcher stopped")

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._running = False

    def _kill_all_agents(self) -> None:
        """Terminate all running agent processes on shutdown."""
        running = self.store.get_running_agents()
        for agent in running:
            if agent.pid and agent.status == "alive":
                log.info("Shutting down agent %s (PID %d)", agent.id, agent.pid)
                try:
                    os.kill(agent.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                self.store.update_agent(agent.id, status="dead")
                # Reset the task so it can be picked up again
                if agent.current_task:
                    task = self.store.get_task(agent.current_task)
                    if task and task.status == "in_progress":
                        self.store.update_task(task.id, status="open", assigned_agent=None)
                        self._emit(f"Reset task {task.id} (was assigned to {agent.id})")

        # Give agents a moment, then force-kill any survivors
        time.sleep(2)
        for agent in running:
            if agent.pid and agent.status == "alive":
                try:
                    os.kill(agent.pid, 0)  # Check if still alive
                    log.warning("Force-killing agent %s (PID %d)", agent.id, agent.pid)
                    os.kill(agent.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    def _emit(self, msg: str) -> None:
        """Print a progress message and always log it."""
        log.info("[EMIT] %s", msg)
        if self._verbose:
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}] {msg}", flush=True)

    def _print_status_line(self) -> None:
        """Print a compact status line showing current pipeline state."""
        if not self._verbose:
            return
        tasks = self.store.list_tasks()
        agents = self.store.get_running_agents()
        by_status: dict[str, int] = {}
        for t in tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1

        parts = []
        for s in ["open", "in_progress", "blocked", "closed"]:
            if by_status.get(s, 0) > 0:
                parts.append(f"{s}={by_status[s]}")
        alive = sum(1 for a in agents if a.status == "alive")
        status_line = f"Tasks: {', '.join(parts) or 'none'} | Agents: {alive} alive"
        if status_line != self._last_status_line:
            self._emit(status_line)
            self._last_status_line = status_line

    def tick(self) -> None:
        """Execute one poll cycle."""
        self._tick_count += 1

        # Reload config on each tick for hot-reload
        self.config = read_config(self.project_root)
        if self.config.paused:
            if self._tick_count % 12 == 0:
                self._emit("Pipeline paused — skipping tick")
            return

        # Log tick details periodically
        if self._tick_count % 6 == 0 or self._tick_count <= 3:
            agents = self.store.get_running_agents()
            alive = [a for a in agents if a.status == "alive"]
            tracked = len(self._agent_procs)
            log.info(
                "Tick %d: %d alive agents, %d tracked procs",
                self._tick_count, len(alive), tracked,
            )
            for a in alive:
                is_alive = _is_process_alive(a.pid) if a.pid else False
                log.info("  Agent %s (PID %d) task=%s proc_alive=%s",
                         a.id, a.pid or 0, a.current_task, is_alive)

        self.cleanup_finished()
        self.check_zombies()
        self.reset_orphans()
        self.check_budgets()
        self.process_transitions()
        self.spawn_ready()
        self.save_checkpoint()
        self._print_status_line()
        self._auto_recover_blocked()

    # ── Auto-recovery for blocked tasks ────────────────────────

    def _auto_recover_blocked(self) -> None:
        """Automatically recover blocked tasks where possible.

        Runs every 30s (6 ticks). Examines each blocked task's failure
        reason and applies the appropriate recovery strategy:

        - Acceptance rejected → back to development with rejection_count++
        - Spawn limit → reset spawn_count, restore to last stage
        - Crash limit → reset crash_count, restore to last stage (with backoff)
        - Max rejections → reset rejection_count, back to development
        - No commits → reset spawn_count, stay in development

        Tracks auto_unblock events per task to prevent infinite loops.
        After MAX_AUTO_RETRIES, the task stays blocked for manual review.
        """
        if self._tick_count % 6 != 0:
            return

        blocked = self.store.list_tasks(status="blocked")

        # Clear announced questions that have been answered
        if hasattr(self, "_announced_questions"):
            blocked_ids = {t.id for t in blocked if "question" in t.labels}
            answered = self._announced_questions - blocked_ids
            if answered:
                self._announced_questions -= answered
                for tid in answered:
                    self._emit(f"Question answered for task {tid}")

        if not blocked:
            return

        # Re-announce testing tasks periodically (manual mode)
        testing_tasks = self.store.list_tasks(has_label="needs-testing")
        for task in testing_tasks:
            if hasattr(self, "_announced_testing") and task.id in self._announced_testing:
                if self._tick_count % 12 == 0:
                    changed = self._get_changed_files(task)
                    self._announce_testing(task, changed)
            else:
                changed = self._get_changed_files(task)
                self._announce_testing(task, changed)

        # Clear announced testing for tasks that were approved
        if hasattr(self, "_announced_testing"):
            testing_ids = {t.id for t in testing_tasks}
            approved = self._announced_testing - testing_ids
            if approved:
                self._announced_testing -= approved

        for task in blocked:
            # Questions need a user answer — announce them loudly, don't auto-recover
            if "question" in task.labels:
                self._announce_question(task)
                continue

            # Count previous auto-unblock attempts for this task
            events = self.store.get_events(task_id=task.id, limit=200)
            auto_unblock_count = sum(
                1 for e in events if e.event_type == "auto_unblock"
            )

            if auto_unblock_count >= MAX_AUTO_RETRIES:
                # Already retried enough — require manual intervention
                if self._tick_count % 12 == 0:
                    self._emit(
                        f"ATTENTION: Task {task.id} ({task.title[:40]}) "
                        f"BLOCKED after {auto_unblock_count} auto-retries — needs manual review"
                    )
                continue

            # Find the most recent block event to determine failure reason
            block_event = next(
                (e for e in events if e.event_type == "block"), None
            )
            failure_reason = (
                block_event.details.get("failure_reason", "") if block_event else ""
            )

            recovery = self._plan_recovery(task, failure_reason)
            if recovery is None:
                if self._tick_count % 12 == 0:
                    self._emit(
                        f"ATTENTION: Task {task.id} ({task.title[:40]}) "
                        f"BLOCKED: {failure_reason or 'unknown reason'}"
                    )
                continue

            # Apply the recovery
            self.store.update_task(task.id, **recovery)
            self.store.log_event(EventRecord(
                event_type="auto_unblock",
                task_id=task.id,
                details={
                    "failure_reason": failure_reason,
                    "recovery": recovery,
                    "attempt": auto_unblock_count + 1,
                },
                actor="watcher",
            ))
            self._emit(
                f"Auto-recovered task {task.id} ({task.title[:40]}): "
                f"{failure_reason} → retry #{auto_unblock_count + 1}"
            )

    def _plan_recovery(
        self, task: TaskRecord, failure_reason: str,
    ) -> dict | None:
        """Determine recovery updates for a blocked task. Returns None if unrecoverable."""

        # Tasks with "question" label should not be auto-recovered
        if "question" in task.labels:
            return None

        # Acceptance tests failed → back to development for fixes
        if "Acceptance tests failed" in failure_reason:
            new_labels = [l for l in task.labels if l != "rejected" and not l.startswith("stage:")]
            new_labels.append("stage:development")
            return {
                "status": "open",
                "stage": "development",
                "labels": new_labels,
                "rejection_count": task.rejection_count + 1,
                "assigned_agent": None,
            }

        # Spawn limit reached → reset counter, restore to development
        if "Spawn limit" in failure_reason:
            stage = task.stage or "development"
            new_labels = [l for l in task.labels if not l.startswith("stage:")]
            new_labels.append(f"stage:{stage}")
            return {
                "status": "open",
                "stage": stage,
                "labels": new_labels,
                "spawn_count": 0,
                "assigned_agent": None,
            }

        # Crash limit → reset counter, keep same stage
        if "Crashed" in failure_reason:
            stage = task.stage or "development"
            new_labels = [l for l in task.labels if not l.startswith("stage:")]
            new_labels.append(f"stage:{stage}")
            # Add backoff — delay re-spawn
            self._spawn_backoff[task.id] = time.time() + 60
            return {
                "status": "open",
                "stage": stage,
                "labels": new_labels,
                "crash_count": 0,
                "assigned_agent": None,
            }

        # Max rejections → reset counter, back to development
        if "Rejected" in failure_reason:
            new_labels = [l for l in task.labels if l != "rejected" and not l.startswith("stage:")]
            new_labels.append("stage:development")
            return {
                "status": "open",
                "stage": "development",
                "labels": new_labels,
                "rejection_count": 0,
                "assigned_agent": None,
            }

        # No commits after N development attempts → reset, stay in development
        if "No commits" in failure_reason:
            new_labels = [l for l in task.labels if not l.startswith("stage:")]
            new_labels.append("stage:development")
            return {
                "status": "open",
                "stage": "development",
                "labels": new_labels,
                "spawn_count": 0,
                "assigned_agent": None,
            }

        # Worktree creation failures → reset crash count
        if "Worktree creation failed" in failure_reason:
            stage = task.stage or "development"
            new_labels = [l for l in task.labels if not l.startswith("stage:")]
            new_labels.append(f"stage:{stage}")
            self._spawn_backoff[task.id] = time.time() + 30
            return {
                "status": "open",
                "stage": stage,
                "labels": new_labels,
                "crash_count": 0,
                "assigned_agent": None,
            }

        # Unknown failure reason — can't auto-recover
        return None

    # ── Handoff / rejection message storage ────────────────────

    def _store_handoff_or_rejection(
        self, task: TaskRecord, agent: AgentRecord, result: TransitionResult,
    ) -> None:
        """Extract agent's last comment and store as handoff or rejection message.

        When an agent advances the stage, its comment becomes a handoff for the
        next agent. When it rejects, the comment becomes rejection feedback.
        """
        from warchief.models import MessageRecord
        # Find the agent's last comment event
        events = self.store.get_events(task_id=task.id, limit=20)
        agent_comments = [
            e for e in events
            if e.event_type == "comment" and e.agent_id == agent.id
        ]
        if not agent_comments:
            return

        last_comment = agent_comments[-1]
        comment_text = (last_comment.details or {}).get("comment", "")
        if not comment_text:
            return

        is_rejection = result.next_stage == "development" and task.stage != "development"
        msg_type = "rejection" if is_rejection else "handoff"

        msg = MessageRecord(
            id=f"{msg_type}-{agent.id}",
            to_agent=task.id,
            body=f"[{agent.role}] {comment_text}",
            from_agent=agent.id,
            message_type=msg_type,
            persistent=True,
        )
        self.store.create_message(msg)
        log.info("Stored %s message from %s for task %s", msg_type, agent.id, task.id)

    # ── Group PR gate ──────────────────────────────────────────

    def _check_group_pr_gate(self, task: TaskRecord) -> None:
        """For grouped tasks, only one task creates the PR.

        When a grouped task reaches pr-creation, check if all siblings are
        also at pr-creation (or already closed). If not, hold this task by
        adding a 'group-waiting' label. If all are ready, let this task
        proceed and close the rest.
        """
        siblings = self.store.get_group_tasks(task.group_id)
        not_ready = [
            s for s in siblings
            if s.id != task.id
            and s.stage != "pr-creation"
            and s.status != "closed"
        ]

        if not_ready:
            # Not all siblings are done — hold this task
            fresh = self.store.get_task(task.id)
            if not fresh:
                return
            new_labels = list(fresh.labels)
            if "group-waiting" not in new_labels:
                new_labels.append("group-waiting")
            self.store.update_task(
                task.id, stage="pr-creation", labels=new_labels,
                status="open", assigned_agent=None,
            )
            waiting_ids = [s.id for s in not_ready]
            self._emit(
                f"Task {task.id}: waiting for group siblings {waiting_ids} "
                f"before creating PR"
            )
            return

        # All siblings are at pr-creation or closed — pick this task as the PR creator
        # Close all OTHER siblings (they share the same branch)
        for s in siblings:
            if s.id == task.id:
                continue
            if s.status == "closed":
                continue
            self.store.update_task(s.id, status="closed")
            self.store.log_event(EventRecord(
                event_type="advance",
                task_id=s.id,
                details={
                    "from_stage": s.stage,
                    "to_stage": "closed",
                    "reason": f"Group PR will be created by {task.id}",
                },
                actor="watcher",
            ))
            self._emit(f"Task {s.id}: closed (group PR via {task.id})")

        # Remove group-waiting label from the chosen task
        fresh = self.store.get_task(task.id)
        if fresh:
            new_labels = [l for l in fresh.labels if l != "group-waiting"]
            if new_labels != list(fresh.labels):
                self.store.update_task(task.id, labels=new_labels)

        self._emit(
            f"Task {task.id}: all group siblings done, creating combined PR "
            f"on branch feature/{task.group_id}"
        )

    # ── E2E testing gate ────────────────────────────────────────

    def _check_e2e_gate(self, task: TaskRecord, transition: TransitionResult) -> None:
        """After tester agent passes, optionally block for manual e2e Playwright testing.

        Only blocks if:
        - config has auto_run=false (manual e2e mode), AND
        - frontend files were changed

        Otherwise the task proceeds normally to pr-creation.
        """
        tc = self.config.testing
        if tc.auto_run:
            return  # Let it proceed — tester agent already ran tests

        changed_files = self._get_changed_files(task)
        has_frontend = any(
            ("." + f.rsplit(".", 1)[-1] if "." in f else "").lower()
            in FRONTEND_EXTENSIONS
            for f in changed_files
        )

        if not has_frontend:
            return  # No frontend changes — proceed to pr-creation

        # Block for manual Playwright e2e testing
        fresh = self.store.get_task(task.id)
        if not fresh:
            return
        # Override the transition — stay in testing with needs-testing label
        new_labels = [l for l in fresh.labels if not l.startswith("stage:")]
        new_labels.append("stage:testing")
        if "needs-testing" not in new_labels:
            new_labels.append("needs-testing")
        self.store.update_task(
            task.id, stage="testing", labels=new_labels,
        )
        self._announce_testing(task, changed_files)

    def _get_changed_files(self, task: TaskRecord) -> list[str]:
        """Get list of files changed on the task's feature branch."""
        base = task.base_branch or self.config.base_branch or "main"
        branch = get_task_branch(task)
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...{branch}"],
                cwd=self.project_root, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        except (subprocess.TimeoutExpired, OSError):
            pass
        return []

    def _announce_testing(self, task: TaskRecord, changed_files: list[str]) -> None:
        """Announce that a task needs manual testing."""
        if not hasattr(self, "_announced_testing"):
            self._announced_testing: set[str] = set()

        self._announced_testing.add(task.id)

        bell = "\a"
        ts = time.strftime("%H:%M:%S")
        print(f"{bell}", end="", flush=True)
        print(f"\n{'=' * 60}", flush=True)
        print(f"  [{ts}] TESTING NEEDED — task {task.id}", flush=True)
        print(f"  {task.title}", flush=True)
        if changed_files:
            print(f"\n  Changed files ({len(changed_files)}):", flush=True)
            for f in changed_files[:10]:
                print(f"    {f}", flush=True)
            if len(changed_files) > 10:
                print(f"    ... and {len(changed_files) - 10} more", flush=True)
        print(f"\n  1. Test the changes manually", flush=True)
        print(f"  2. Approve:  approve {task.id}", flush=True)
        print(f"  3. Reject:   reject {task.id} \"feedback\"", flush=True)
        print(f"{'=' * 60}\n", flush=True)

        log.info("Testing announced for task %s (%d frontend files)", task.id, len(frontend_files))

    # ── Question announcements ─────────────────────────────────

    def _announce_question(self, task: TaskRecord) -> None:
        """Loudly announce a pending question so the user notices it.

        Plays a terminal bell and prints the question text.
        Only announces each question once (tracks by task_id).
        """
        # Track which questions we've already announced
        if not hasattr(self, "_announced_questions"):
            self._announced_questions: set[str] = set()

        if task.id in self._announced_questions:
            # Re-announce every 60s (12 ticks) as a reminder
            if self._tick_count % 12 != 0:
                return

        self._announced_questions.add(task.id)

        # Get the actual question text
        question_text = ""
        try:
            messages = self.store.get_task_messages(task.id)
            questions = [m for m in messages if m.message_type == "question"]
            if questions:
                question_text = questions[-1].body
        except Exception:
            pass

        # Bell character to trigger terminal/system notification
        bell = "\a"

        ts = time.strftime("%H:%M:%S")
        print(f"{bell}", end="", flush=True)
        print(f"\n{'=' * 60}", flush=True)
        print(f"  [{ts}] QUESTION from agent — task {task.id}", flush=True)
        print(f"  {task.title}", flush=True)
        if question_text:
            # Show first 200 chars of question
            preview = question_text[:200]
            if len(question_text) > 200:
                preview += "..."
            print(f"\n  {preview}", flush=True)
        print(f"\n  Answer with: warchief answer {task.id} \"your answer\"", flush=True)
        print(f"{'=' * 60}\n", flush=True)

        log.info("Question announced for task %s", task.id)

    # ── Cost tracking ──────────────────────────────────────────

    def _record_agent_cost(self, agent: AgentRecord) -> None:
        """Read the .usage.json file written by the agent log writer and persist cost data."""
        usage_path = self.project_root / ".warchief" / "agent-logs" / f"{agent.id}.usage.json"
        if not usage_path.exists():
            return

        try:
            data = json.loads(usage_path.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Failed to read usage data for %s", agent.id)
            return

        # Resolve model: CLI output > agent record > role config
        model = data.get("model") or agent.model or ""
        if not model:
            model = self.config.role_models.get(agent.role, "")
        if not model:
            try:
                model = self.registry.get_model(agent.role)
            except KeyError:
                pass

        usage = TokenUsage(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            cache_write_tokens=data.get("cache_write_tokens", 0),
        )

        # Claude CLI often returns cost_usd=0 — estimate from tokens if needed
        cost_usd = data.get("cost_usd", 0.0)
        if not cost_usd:
            cost_usd = estimate_cost(usage, model)

        entry = CostEntry(
            agent_id=agent.id,
            task_id=agent.current_task or "",
            role=agent.role,
            model=model,
            usage=usage,
            cost_usd=cost_usd,
            timestamp=data.get("timestamp", time.time()),
        )
        append_cost_entry(self.project_root, entry)
        log.info("Recorded cost for %s: $%.4f (%d in / %d out / %d cache_read / %d cache_write)",
                 agent.id, entry.cost_usd,
                 entry.usage.input_tokens, entry.usage.output_tokens,
                 entry.usage.cache_read_tokens, entry.usage.cache_write_tokens)

    # ── Cleanup ─────────────────────────────────────────────────

    def cleanup_finished(self) -> None:
        """Detect agents whose processes have exited and handle transitions."""
        running = self.store.get_running_agents()
        for agent in running:
            if agent.status not in ("alive", "zombie"):
                continue
            if agent.pid and not _is_process_alive(agent.pid):
                # Try to get exit code from tracked Popen object first (reliable)
                exit_code = None
                proc = self._agent_procs.pop(agent.id, None)
                if proc is not None:
                    try:
                        exit_code = proc.wait(timeout=0)
                    except Exception:
                        exit_code = proc.returncode
                if exit_code is None:
                    exit_code = _get_exit_code(agent.pid)

                log.info("Agent %s (PID %d) has exited (code=%s)",
                         agent.id, agent.pid, exit_code)
                status_word = "finished" if exit_code == 0 else f"crashed (exit {exit_code})"
                self._emit(f"Agent {agent.id} {status_word}")

                self.store.update_agent(agent.id, status="dead")

                # Cleanup the log_writer subprocess for this agent
                lw_proc = self._log_writer_procs.pop(agent.id, None)
                if lw_proc is not None:
                    try:
                        lw_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        lw_proc.kill()
                        log.warning("Force-killed log_writer for agent %s", agent.id)

                # Record cost/token usage from agent's .usage.json file
                self._record_agent_cost(agent)

                task = self.store.get_task(agent.current_task) if agent.current_task else None
                if task:
                    self._handle_agent_exit(task, agent, exit_code)

    def _handle_agent_exit(
        self, task: TaskRecord, agent: AgentRecord, exit_code: int | None,
    ) -> None:
        """Run the state machine for an agent that has exited."""
        # Re-read task from DB to get fresh status — the agent may have
        # called `warchief agent-update` just before exiting
        fresh_task = self.store.get_task(task.id)
        if fresh_task is not None:
            task = fresh_task

        log.info(
            "Processing exit: task=%s status=%s stage=%s exit_code=%s role=%s",
            task.id, task.status, task.stage, exit_code, agent.role,
        )

        result = dispatch_transition(
            task_status=task.status,
            task_stage=task.stage or "",
            task_labels=task.labels,
            agent_role=agent.role,
            agent_exit_code=exit_code,
            branch_has_commits=self._branch_has_commits(task),
            rejection_count=task.rejection_count,
            crash_count=task.crash_count,
            spawn_count=task.spawn_count,
            max_rejections=MAX_REJECTIONS,
            max_crashes=MAX_CRASHES,
            max_spawns=MAX_TOTAL_SPAWNS,
        )

        log.info(
            "Transition result: task=%s next_stage=%s status=%s has_changes=%s failure=%s",
            task.id, result.next_stage, result.status, result.has_changes, result.failure_reason,
        )

        # Build a single update dict to avoid optimistic locking failures
        # from multiple sequential update_task calls
        task_updates: dict = {"assigned_agent": None}

        if result.has_changes:
            if result.status:
                task_updates["status"] = result.status
            # Handle label mutations
            current_labels = list(task.labels)
            for label in result.remove_labels:
                if label in current_labels:
                    current_labels.remove(label)
            for label in result.add_labels:
                if label not in current_labels:
                    current_labels.append(label)
            if current_labels != list(task.labels):
                task_updates["labels"] = current_labels
            if result.next_stage:
                task_updates["stage"] = result.next_stage
            if result.failure_reason:
                task_updates["status"] = result.status or "blocked"

        # Handle crash counting in the same update
        agent_crashed = exit_code is not None and exit_code != 0
        if agent_crashed and task.status == "in_progress":
            task_updates["crash_count"] = task.crash_count + 1
            self.store.update_agent(agent.id, crash_count=agent.crash_count + 1)

        # Skip unnecessary stages based on changed files
        if result.next_stage in ("security-review", "testing"):
            changed_files = self._get_changed_files(task)
            from warchief.state_machine import should_skip_security_review, should_skip_testing
            skip = False
            if result.next_stage == "security-review" and should_skip_security_review(changed_files):
                skip = True
                self._emit(f"Task {task.id}: skipping security-review (docs/config only)")
            elif result.next_stage == "testing" and should_skip_testing(changed_files):
                skip = True
                self._emit(f"Task {task.id}: skipping testing (no code changes)")

            if skip:
                from warchief.state_machine import get_next_stage
                skipped_stage = result.next_stage
                next_next = get_next_stage(skipped_stage, task.labels)
                if next_next:
                    task_updates["stage"] = next_next
                    # Fix labels: remove the skipped stage label, add the new one
                    labels = task_updates.get("labels", list(task.labels))
                    labels = [l for l in labels if l != f"stage:{skipped_stage}"]
                    if f"stage:{next_next}" not in labels:
                        labels.append(f"stage:{next_next}")
                    task_updates["labels"] = labels
                    result = TransitionResult(
                        status=result.status,
                        remove_labels=result.remove_labels,
                        add_labels=[f"stage:{next_next}"],
                        next_stage=next_next,
                    )

        # Apply ALL task updates in a single call (avoids optimistic lock failures)
        self.store.update_task(task.id, **task_updates)

        # Log the transition event
        if result.has_changes:
            event_type = "transition"
            if result.failure_reason:
                event_type = "block"
            elif result.next_stage:
                event_type = "advance"

            self.store.log_event(EventRecord(
                event_type=event_type,
                task_id=task.id,
                agent_id=agent.id,
                details={
                    "from_stage": task.stage,
                    "to_stage": result.next_stage,
                    "status": result.status,
                    "failure_reason": result.failure_reason,
                    "exit_code": exit_code,
                },
                actor="watcher",
            ))

            log.info("Transition: task %s %s -> %s (status=%s)",
                     task.id, task.stage, result.next_stage, result.status)
            if result.next_stage:
                self._emit(f"Task {task.id} ({task.title}): {task.stage} -> {result.next_stage}")
            elif result.failure_reason:
                self._emit(f"Task {task.id} BLOCKED: {result.failure_reason}")

        # Store handoff/rejection messages for next agent's context
        self._store_handoff_or_rejection(task, agent, result)

        # Handle post-testing — if tester passed and there are frontend files,
        # optionally block for manual e2e Playwright testing
        if task.stage == "testing" and result.next_stage == "pr-creation":
            self._check_e2e_gate(task, result)

        # Group-aware PR creation: wait until all group siblings are done
        if result.next_stage == "pr-creation" and task.group_id:
            self._check_group_pr_gate(task)

        # Manage spawn backoff
        if result.next_stage:
            self._spawn_backoff.pop(task.id, None)
        elif result.status == "open" and not result.next_stage:
            delay = min(10 * (2 ** task.crash_count), 300)
            self._spawn_backoff[task.id] = time.time() + delay

        # Cleanup heartbeat
        cleanup_heartbeat(self.project_root, agent.id)

    def _apply_transition(
        self, task: TaskRecord, agent: AgentRecord, result: TransitionResult,
    ) -> None:
        """Apply a TransitionResult to the database.

        Used by reset_orphans for stale task transitions.
        For agent exits, _handle_agent_exit batches updates directly.
        """
        updates: dict = {}

        if result.status:
            updates["status"] = result.status

        current_labels = list(task.labels)
        for label in result.remove_labels:
            if label in current_labels:
                current_labels.remove(label)
        for label in result.add_labels:
            if label not in current_labels:
                current_labels.append(label)
        if current_labels != list(task.labels):
            updates["labels"] = current_labels

        if result.next_stage:
            updates["stage"] = result.next_stage

        if result.failure_reason:
            updates["status"] = result.status or "blocked"

        if updates:
            self.store.update_task(task.id, **updates)

        event_type = "transition"
        if result.failure_reason:
            event_type = "block"
        elif result.next_stage:
            event_type = "advance"

        self.store.log_event(EventRecord(
            event_type=event_type,
            task_id=task.id,
            agent_id=agent.id,
            details={
                "from_stage": task.stage,
                "to_stage": result.next_stage,
                "status": result.status,
                "failure_reason": result.failure_reason,
            },
            actor="watcher",
        ))

        log.info("Transition: task %s %s -> %s (status=%s)",
                 task.id, task.stage, result.next_stage, result.status)
        if result.next_stage:
            self._emit(f"Task {task.id} ({task.title}): {task.stage} -> {result.next_stage}")
        elif result.failure_reason:
            self._emit(f"Task {task.id} BLOCKED: {result.failure_reason}")

    # ── Zombie detection ────────────────────────────────────────

    def check_zombies(self) -> None:
        """Detect agents that are alive but haven't sent heartbeats or exceeded timeout."""
        running = self.store.get_running_agents()
        timeout = self.config.agent_timeout or AGENT_TIMEOUT
        now = time.time()

        for agent in running:
            if agent.status != "alive":
                continue

            # Check agent timeout — kill agents running longer than allowed
            if agent.spawned_at and (now - agent.spawned_at) > timeout:
                log.warning("Agent %s exceeded timeout (%ds), killing", agent.id, timeout)
                self._emit(f"Agent {agent.id} TIMEOUT after {int(now - agent.spawned_at)}s")
                self.store.update_agent(agent.id, status="dead")
                self.store.log_event(EventRecord(
                    event_type="timeout",
                    task_id=agent.current_task,
                    agent_id=agent.id,
                    details={"elapsed": int(now - agent.spawned_at), "timeout": timeout},
                    actor="watcher",
                ))
                if agent.pid:
                    try:
                        os.kill(agent.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
                # Reset task so it can be retried
                if agent.current_task:
                    task = self.store.get_task(agent.current_task)
                    if task and task.status == "in_progress":
                        self.store.update_task(
                            task.id, status="open", assigned_agent=None,
                            crash_count=task.crash_count + 1,
                        )
                continue

            if is_zombie(self.project_root, agent.id, ZOMBIE_THRESHOLD):
                log.warning("Agent %s detected as zombie", agent.id)
                self.store.update_agent(agent.id, status="zombie")
                self.store.log_event(EventRecord(
                    event_type="zombie",
                    task_id=agent.current_task,
                    agent_id=agent.id,
                    actor="watcher",
                ))
                # Try to kill the process
                if agent.pid:
                    try:
                        os.kill(agent.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass

    # ── Orphan recovery ─────────────────────────────────────────

    def reset_orphans(self) -> None:
        """Reset tasks that are in_progress but have no live agent.

        Also clears stale agent assignments on open tasks so they
        can be picked up by new agents.
        """
        orphans = self.store.get_orphaned_tasks()
        for task in orphans:
            log.warning("Orphaned task %s (was assigned to %s)",
                        task.id, task.assigned_agent)
            self.store.update_task(
                task.id, status="open", assigned_agent=None,
            )
            self.store.log_event(EventRecord(
                event_type="orphan_reset",
                task_id=task.id,
                agent_id=task.assigned_agent,
                actor="watcher",
            ))
            self._emit(f"Reset orphaned task {task.id}")

        # Handle stale agent assignments on open tasks — run transitions
        stale = self.store.get_stale_assigned_tasks()
        for task in stale:
            agent = self.store.get_agent(task.assigned_agent) if task.assigned_agent else None
            log.warning("Stale agent %s on open task %s — running transition",
                        task.assigned_agent, task.id)

            if agent:
                # Run the state machine so the task can advance
                result = dispatch_transition(
                    task_status=task.status,
                    task_stage=task.stage or "",
                    task_labels=task.labels,
                    agent_role=agent.role,
                    agent_exit_code=0,  # Agent updated status to open — treat as clean exit
                    branch_has_commits=self._branch_has_commits(task),
                    rejection_count=task.rejection_count,
                    crash_count=task.crash_count,
                    spawn_count=task.spawn_count,
                    max_rejections=MAX_REJECTIONS,
                    max_crashes=MAX_CRASHES,
                    max_spawns=MAX_TOTAL_SPAWNS,
                )
                if result.has_changes:
                    self._apply_transition(task, agent, result)
                    self._emit(f"Transition applied for stale task {task.id}")

            # Clear agent assignment after transition
            self.store.update_task(task.id, assigned_agent=None)
            self._emit(f"Cleared stale agent from task {task.id}")

        # Cleanup orphaned worktrees (no matching alive agent)
        from warchief.worktree import list_worktrees
        worktree_ids = set(list_worktrees(self.project_root))
        if worktree_ids:
            alive_ids = {a.id for a in self.store.get_running_agents() if a.status == "alive"}
            orphaned_wt = worktree_ids - alive_ids
            for wt_id in orphaned_wt:
                remove_worktree(self.project_root, wt_id)
                self._emit(f"Cleaned up orphaned worktree: {wt_id}")

    # ── Transition processing ───────────────────────────────────

    def process_transitions(self) -> None:
        """Process any tasks that need state machine evaluation.

        This handles cases where tasks were updated externally (e.g., by
        the conductor or another agent) and need transition processing.
        """
        # Check for tasks with resolved dependencies
        resolved = self.store.get_tasks_with_resolved_deps()
        for task in resolved:
            current_labels = list(task.labels)
            if "waiting" in current_labels:
                current_labels.remove("waiting")
                self.store.update_task(task.id, labels=current_labels, status="open")
                log.info("Task %s: deps resolved, removing 'waiting' label", task.id)

        # Check if group-waiting tasks can now proceed
        self._check_group_waiting_tasks()

        # Auto-release tasks that have no stage into the pipeline
        self._release_unstaged_tasks()

    def _check_group_waiting_tasks(self) -> None:
        """Re-evaluate tasks with 'group-waiting' label.

        A task gets group-waiting when it reaches pr-creation but siblings
        aren't done yet. Each tick we re-check — once all siblings are at
        pr-creation or closed, we run the group gate logic.
        """
        waiting = self.store.list_tasks(has_label="group-waiting")
        for task in waiting:
            if not task.group_id:
                continue
            siblings = self.store.get_group_tasks(task.group_id)
            not_ready = [
                s for s in siblings
                if s.id != task.id
                and s.stage != "pr-creation"
                and s.status != "closed"
            ]
            if not not_ready:
                # All siblings ready — run the gate to pick one PR creator
                self._check_group_pr_gate(task)

    def _release_unstaged_tasks(self) -> None:
        """Release open tasks with no stage into the first pipeline stage.

        This ensures tasks created by the conductor (or manually) get
        picked up even if the watcher was already running.
        """
        tasks = self.store.list_tasks(status="open")
        for task in tasks:
            if task.stage:
                continue
            if any(l.startswith("stage:") for l in task.labels):
                continue
            # Don't release tasks still waiting on deps
            if "waiting" in task.labels:
                continue
            # Release into development (first stage)
            first_stage = "development"
            new_labels = list(task.labels) + [f"stage:{first_stage}"]
            self.store.update_task(task.id, stage=first_stage, labels=new_labels)
            self._emit(f"Released task {task.id} ({task.title}) into {first_stage}")
            log.info("Auto-released task %s into stage %s", task.id, first_stage)

    # ── Budget Enforcement ──────────────────────────────────────

    def check_budgets(self) -> None:
        """Check session and per-task budgets. Runs every 6th tick (~30s)."""
        if self._tick_count % 6 != 0:
            return

        budget_cfg = self.config.budget

        # Session budget check
        if budget_cfg.session_limit > 0:
            session_cost = get_session_cost(self.project_root, self._session_start)
            warn_threshold = budget_cfg.session_limit * budget_cfg.warn_at_percent / 100

            if session_cost >= budget_cfg.session_limit:
                log.warning(
                    "SESSION BUDGET EXCEEDED: $%.2f / $%.2f — pausing pipeline",
                    session_cost, budget_cfg.session_limit,
                )
                self._emit(
                    f"Budget exceeded: ${session_cost:.2f} / ${budget_cfg.session_limit:.2f} — PAUSING"
                )
                self.config.paused = True
                from warchief.config import write_config
                write_config(self.project_root, self.config)
                self.store.log_event(EventRecord(
                    event_type="block",
                    details={
                        "failure_reason": f"Session budget exceeded: ${session_cost:.2f} / ${budget_cfg.session_limit:.2f}",
                        "budget_type": "session",
                    },
                    actor="watcher",
                ))
                return

            if session_cost >= warn_threshold and not self._budget_warned:
                self._budget_warned = True
                log.warning(
                    "Session budget warning: $%.2f / $%.2f (%.0f%%)",
                    session_cost, budget_cfg.session_limit,
                    session_cost / budget_cfg.session_limit * 100,
                )

        # Per-task budget check
        per_task_limit = budget_cfg.per_task_default
        if per_task_limit <= 0:
            return

        tasks = self.store.list_tasks(status="in_progress")
        tasks += self.store.list_tasks(status="open")
        for task in tasks:
            # Use task-specific budget if set, otherwise config default
            limit = task.budget if task.budget > 0 else per_task_limit
            task_cost = get_task_cost(self.project_root, task.id)
            if task_cost >= limit and "budget-exceeded" not in task.labels:
                log.warning(
                    "Task %s budget exceeded: $%.2f / $%.2f — blocking",
                    task.id, task_cost, limit,
                )
                self._emit(
                    f"Task {task.id} budget exceeded: ${task_cost:.2f} / ${limit:.2f} — BLOCKED"
                )
                new_labels = list(task.labels) + ["budget-exceeded"]
                self.store.update_task(
                    task.id, status="blocked", labels=new_labels,
                )
                self.store.log_event(EventRecord(
                    event_type="block",
                    task_id=task.id,
                    details={
                        "failure_reason": f"Task budget exceeded: ${task_cost:.2f} / ${limit:.2f}",
                        "budget_type": "per_task",
                    },
                    actor="watcher",
                ))

    # ── Spawning ────────────────────────────────────────────────

    def spawn_ready(self) -> None:
        """Find tasks ready for work and spawn agents."""
        spawned_this_cycle = 0
        failed_this_cycle = 0
        max_failures_per_cycle = 3  # Stop trying after 3 failures in one tick

        for stage, role in STAGE_TO_ROLE.items():
            if spawned_this_cycle >= MAX_SPAWNS_PER_CYCLE:
                break
            if failed_this_cycle >= max_failures_per_cycle:
                log.warning("Too many spawn failures this cycle, stopping")
                break

            ready = self.store.get_ready_tasks(stage)
            now = time.time()
            for task in ready:
                if spawned_this_cycle >= MAX_SPAWNS_PER_CYCLE:
                    break
                if failed_this_cycle >= max_failures_per_cycle:
                    break

                if task.id in self._spawn_backoff and now < self._spawn_backoff[task.id]:
                    continue  # Still in backoff period

                # Don't spawn for tasks waiting on group siblings
                if "group-waiting" in task.labels:
                    continue

                errors = run_preflight(
                    task, role, self.project_root,
                    self.store, self.config, self.registry,
                )
                if errors:
                    log.debug("Preflight failed for %s: %s", task.id, errors)
                    continue

                agent = spawn_agent(
                    task, role, self.project_root,
                    self.store, self.config, self.registry,
                )
                if agent:
                    spawned_this_cycle += 1
                    # Track Popen objects for reliable exit code retrieval and cleanup
                    proc = getattr(agent, "_claude_proc", None)
                    if proc is not None:
                        self._agent_procs[agent.id] = proc
                    lw_proc = getattr(agent, "_log_writer_proc", None)
                    if lw_proc is not None:
                        self._log_writer_procs[agent.id] = lw_proc
                    self._emit(f"Spawned {agent.id} ({role}) for task {task.id}: {task.title}")
                else:
                    failed_this_cycle += 1

    # ── Checkpoint ──────────────────────────────────────────────

    def save_checkpoint(self) -> None:
        """Save watcher state for crash recovery."""
        state = {
            "tick_count": self._tick_count,
            "timestamp": time.time(),
            "pid": os.getpid(),
        }
        checkpoint_path = self.project_root / ".warchief" / "watcher_state.json"
        try:
            # Remove broken symlinks before writing
            if checkpoint_path.is_symlink():
                checkpoint_path.unlink()
            checkpoint_path.write_text(json.dumps(state, indent=2))
        except OSError as e:
            log.warning("Failed to save checkpoint: %s", e)

    # ── Helpers ─────────────────────────────────────────────────

    def _branch_has_commits(self, task: TaskRecord) -> bool:
        """Check if the feature branch has commits beyond the base."""
        base = task.base_branch or self.config.base_branch or "main"
        branch = get_task_branch(task)
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"{base}..{branch}"],
                cwd=self.project_root, capture_output=True, text=True,
            )
            return bool(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        def handle_stop(signum, frame):
            log.info("Received signal %d, stopping watcher", signum)
            self.stop()

        signal.signal(signal.SIGTERM, handle_stop)
        signal.signal(signal.SIGINT, handle_stop)


def _is_process_alive(pid: int) -> bool:
    """Check if a process is still running (not a zombie).

    os.kill(pid, 0) returns True for zombie processes, so we also
    check the process state via `ps` to detect zombies.
    """
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False

    # Process exists — check if it's a zombie
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "state="],
            capture_output=True, text=True, timeout=5,
        )
        state = result.stdout.strip()
        if state.startswith("Z"):
            return False  # Zombie — effectively dead
    except (subprocess.TimeoutExpired, OSError):
        pass  # If ps fails, assume alive (safe default)

    return True


def _get_exit_code(pid: int) -> int | None:
    """Try to get exit code of a dead process. Returns None if unknown."""
    try:
        _, status = os.waitpid(pid, os.WNOHANG)
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        return None
    except ChildProcessError:
        return None


def _acquire_lock(lock_path: Path) -> int:
    """Acquire a watcher lock file. Raises RuntimeError if already locked."""
    import fcntl
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("Another watcher is already running")
    os.write(fd, str(os.getpid()).encode())
    os.ftruncate(fd, len(str(os.getpid())))
    return fd


def _release_lock(fd: int, lock_path: Path) -> None:
    """Release the watcher lock."""
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass
