"""Scheduler — capacity-controlled dispatch of schedule_contexts."""

from __future__ import annotations

import fcntl
import logging
import os
import time
from pathlib import Path

from warchief.config import Config, STAGE_TO_ROLE, MAX_SPAWNS_PER_CYCLE
from warchief.models import EventRecord
from warchief.preflight import run_preflight
from warchief.roles import RoleRegistry
from warchief.spawner import spawn_agent
from warchief.task_store import TaskStore

log = logging.getLogger("warchief.scheduler")


class Scheduler:
    """Reads schedule_contexts from the DB and dispatches agents within capacity.

    Uses ``fcntl.flock`` to prevent double-dispatch across concurrent processes.
    """

    def __init__(
        self,
        project_root: Path,
        store: TaskStore,
        config: Config,
        registry: RoleRegistry,
    ) -> None:
        self.project_root = project_root
        self.store = store
        self.config = config
        self.registry = registry

    def dispatch_pending(self, max_spawns: int = MAX_SPAWNS_PER_CYCLE) -> int:
        """Process pending schedule_contexts and spawn agents.

        Returns number of agents spawned.
        """
        lock_path = self.project_root / ".warchief" / "scheduler.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.debug("Another scheduler is running, skipping")
            os.close(fd)
            return 0

        try:
            return self._do_dispatch(max_spawns)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _do_dispatch(self, max_spawns: int) -> int:
        pending = self._get_pending_contexts()
        if not pending:
            return 0

        # Check current capacity
        running = self.store.get_running_agents()
        available_slots = self.config.max_total_agents - len(running)
        if available_slots <= 0:
            log.debug(
                "No agent slots available (%d/%d running)",
                len(running),
                self.config.max_total_agents,
            )
            return 0

        spawned = 0
        for ctx in pending:
            if spawned >= max_spawns or spawned >= available_slots:
                break

            task = self.store.get_task(ctx["task_id"])
            if task is None:
                self._mark_context(ctx["id"], "failed")
                continue

            if task.status != "open" or task.assigned_agent:
                self._mark_context(ctx["id"], "consumed")
                continue

            role = ctx["role"]
            errors = run_preflight(
                task,
                role,
                self.project_root,
                self.store,
                self.config,
                self.registry,
            )
            if errors:
                log.debug("Preflight failed for schedule %s: %s", ctx["id"], errors)
                continue

            agent = spawn_agent(
                task,
                role,
                self.project_root,
                self.store,
                self.config,
                self.registry,
            )
            if agent:
                self._mark_context(ctx["id"], "dispatched")
                spawned += 1
            else:
                self._mark_context(ctx["id"], "failed")

        return spawned

    def create_context(self, task_id: str, role: str) -> str:
        """Create a new schedule_context for later dispatch."""
        import uuid

        ctx_id = f"sched-{uuid.uuid4().hex[:8]}"
        self.store.create_schedule_context(ctx_id, task_id, role)
        log.info("Created schedule context %s for task %s (%s)", ctx_id, task_id, role)
        return ctx_id

    def _get_pending_contexts(self) -> list[dict]:
        return self.store.get_pending_schedule_contexts()

    def _mark_context(self, ctx_id: str, status: str) -> None:
        self.store.update_schedule_context(ctx_id, status)
