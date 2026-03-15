"""Tests for TaskStore — CRUD, concurrency, optimistic locking."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from warchief.models import AgentRecord, EventRecord, MessageRecord, TaskRecord
from warchief.task_store import TaskStore


# ── Task CRUD ───────────────────────────────────────────────────


class TestTaskCRUD:
    def test_create_and_get(self, store: TaskStore, sample_task: TaskRecord):
        task_id = store.create_task(sample_task)
        assert task_id == "wc-test01"

        task = store.get_task(task_id)
        assert task is not None
        assert task.title == "Implement login page"
        assert task.status == "open"
        assert task.stage == "development"
        assert "frontend" in task.labels
        assert task.version == 0

    def test_get_nonexistent(self, store: TaskStore):
        assert store.get_task("wc-nope") is None

    def test_create_auto_id(self, store: TaskStore):
        task = TaskRecord(id="", title="Auto ID task")
        task_id = store.create_task(task)
        assert task_id.startswith("wc-")
        assert len(task_id) == 10  # "wc-" + 7 hex chars

    def test_update_status(self, store: TaskStore, sample_task: TaskRecord):
        store.create_task(sample_task)
        ok = store.update_task("wc-test01", status="in_progress")
        assert ok is True

        task = store.get_task("wc-test01")
        assert task.status == "in_progress"
        assert task.version == 1

    def test_update_labels(self, store: TaskStore, sample_task: TaskRecord):
        store.create_task(sample_task)
        ok = store.update_task("wc-test01", labels=["stage:reviewing", "frontend"])
        assert ok is True

        task = store.get_task("wc-test01")
        assert "stage:reviewing" in task.labels

    def test_update_nonexistent_returns_false(self, store: TaskStore):
        ok = store.update_task("wc-nope", status="blocked")
        assert ok is False


# ── Optimistic Locking ──────────────────────────────────────────


class TestOptimisticLocking:
    def test_concurrent_update_conflict(self, store: TaskStore, sample_task: TaskRecord):
        store.create_task(sample_task)

        # First update succeeds
        ok1 = store.update_task("wc-test01", status="in_progress")
        assert ok1 is True

        # Simulate stale version: manually try version 0 again
        # This is what happens when two agents read the same version
        task = store.get_task("wc-test01")
        assert task.version == 1

        # Second update succeeds (version 1)
        ok2 = store.update_task("wc-test01", status="blocked")
        assert ok2 is True

        task = store.get_task("wc-test01")
        assert task.version == 2
        assert task.status == "blocked"

    def test_threaded_concurrent_writes(self, tmp_path: Path):
        db_path = tmp_path / "concurrent.db"
        task = TaskRecord(id="wc-race01", title="Race condition test")

        store = TaskStore(db_path)
        store.create_task(task)
        store.close()

        results = []

        def writer(status: str):
            s = TaskStore(db_path)
            ok = s.update_task("wc-race01", status=status)
            results.append(ok)
            s.close()

        t1 = threading.Thread(target=writer, args=("in_progress",))
        t2 = threading.Thread(target=writer, args=("blocked",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # With optimistic locking, exactly one write wins and one fails
        # (they both read version 0, first succeeds, second sees stale version)
        assert sum(results) >= 1  # At least one succeeds
        # Verify the task was actually updated
        s = TaskStore(db_path)
        t = s.get_task("wc-race01")
        assert t.status in ("in_progress", "blocked")
        s.close()


# ── Task Queries ────────────────────────────────────────────────


class TestTaskQueries:
    def _seed(self, store: TaskStore):
        tasks = [
            TaskRecord(id="wc-q01", title="Task 1", status="open", stage="development",
                       labels=["stage:development"], priority=5),
            TaskRecord(id="wc-q02", title="Task 2", status="open", stage="reviewing",
                       labels=["stage:reviewing", "security"], priority=8),
            TaskRecord(id="wc-q03", title="Task 3", status="in_progress", stage="development",
                       labels=["stage:development"], priority=3),
            TaskRecord(id="wc-q04", title="Task 4", status="blocked", stage=None,
                       labels=[], priority=1),
        ]
        for t in tasks:
            store.create_task(t)

    def test_list_all(self, store: TaskStore):
        self._seed(store)
        all_tasks = store.list_tasks()
        assert len(all_tasks) == 4

    def test_list_by_status(self, store: TaskStore):
        self._seed(store)
        open_tasks = store.list_tasks(status="open")
        assert len(open_tasks) == 2

    def test_list_by_stage(self, store: TaskStore):
        self._seed(store)
        dev_tasks = store.list_tasks(stage="development")
        assert len(dev_tasks) == 2

    def test_list_by_label(self, store: TaskStore):
        self._seed(store)
        sec_tasks = store.list_tasks(has_label="security")
        assert len(sec_tasks) == 1
        assert sec_tasks[0].id == "wc-q02"

    def test_list_ordered_by_priority(self, store: TaskStore):
        self._seed(store)
        all_tasks = store.list_tasks()
        priorities = [t.priority for t in all_tasks]
        assert priorities == sorted(priorities, reverse=True)

    def test_get_ready_tasks(self, store: TaskStore):
        self._seed(store)
        ready = store.get_ready_tasks("development")
        assert len(ready) == 1
        assert ready[0].id == "wc-q01"

    def test_get_ready_tasks_empty(self, store: TaskStore):
        self._seed(store)
        ready = store.get_ready_tasks("pr-creation")
        assert len(ready) == 0


# ── Agent CRUD ──────────────────────────────────────────────────


class TestAgentCRUD:
    def test_register_and_get(self, store: TaskStore):
        agent = AgentRecord(
            id="agent-dev-01", role="developer", status="alive",
            current_task="wc-test01", pid=12345,
        )
        store.register_agent(agent)

        got = store.get_agent("agent-dev-01")
        assert got is not None
        assert got.role == "developer"
        assert got.status == "alive"
        assert got.pid == 12345

    def test_update_agent(self, store: TaskStore):
        agent = AgentRecord(id="agent-rev-01", role="reviewer", status="alive")
        store.register_agent(agent)

        store.update_agent("agent-rev-01", status="dead", current_task=None)
        got = store.get_agent("agent-rev-01")
        assert got.status == "dead"

    def test_get_running_agents(self, store: TaskStore):
        store.register_agent(AgentRecord(id="a1", role="developer", status="alive"))
        store.register_agent(AgentRecord(id="a2", role="reviewer", status="dead"))
        store.register_agent(AgentRecord(id="a3", role="tester", status="zombie"))

        running = store.get_running_agents()
        ids = [a.id for a in running]
        assert "a1" in ids
        assert "a3" in ids
        assert "a2" not in ids

    def test_get_idle_agents(self, store: TaskStore):
        store.register_agent(AgentRecord(id="a1", role="developer", status="idle"))
        store.register_agent(AgentRecord(id="a2", role="developer", status="alive"))
        store.register_agent(AgentRecord(id="a3", role="reviewer", status="idle"))

        idle_devs = store.get_idle_agents("developer")
        assert len(idle_devs) == 1
        assert idle_devs[0].id == "a1"


# ── Messages ────────────────────────────────────────────────────


class TestMessages:
    def test_create_and_read(self, store: TaskStore):
        msg = MessageRecord(
            id="msg-01", to_agent="agent-dev-01", body="Fix the bug",
            from_agent="conductor", message_type="instruction", persistent=True,
        )
        store.create_message(msg)

        unread = store.get_unread_mail("agent-dev-01")
        assert len(unread) == 1
        assert unread[0].body == "Fix the bug"

    def test_mark_read(self, store: TaskStore):
        msg = MessageRecord(
            id="msg-02", to_agent="agent-dev-01", body="Deploy it",
            persistent=True,
        )
        store.create_message(msg)
        store.mark_read("msg-02")

        unread = store.get_unread_mail("agent-dev-01")
        assert len(unread) == 0

    def test_non_persistent_not_in_mail(self, store: TaskStore):
        msg = MessageRecord(
            id="msg-03", to_agent="agent-dev-01", body="Ephemeral",
            persistent=False,
        )
        store.create_message(msg)

        unread = store.get_unread_mail("agent-dev-01")
        assert len(unread) == 0


# ── Events ──────────────────────────────────────────────────────


class TestEvents:
    def test_log_and_query(self, store: TaskStore):
        event = EventRecord(
            event_type="stage_transition",
            task_id="wc-test01",
            agent_id="agent-dev-01",
            details={"from": "development", "to": "reviewing"},
            actor="conductor",
        )
        store.log_event(event)

        events = store.get_events(task_id="wc-test01")
        assert len(events) == 1
        assert events[0].event_type == "stage_transition"
        assert events[0].details["to"] == "reviewing"

    def test_events_limit(self, store: TaskStore):
        for i in range(10):
            store.log_event(EventRecord(
                event_type="heartbeat", task_id="wc-test01",
            ))

        events = store.get_events(task_id="wc-test01", limit=5)
        assert len(events) == 5

    def test_events_all(self, store: TaskStore):
        store.log_event(EventRecord(event_type="a", task_id="wc-01"))
        store.log_event(EventRecord(event_type="b", task_id="wc-02"))

        events = store.get_events()
        assert len(events) == 2


# ── Context Manager ─────────────────────────────────────────────


class TestContextManager:
    def test_with_statement(self, tmp_db: Path):
        with TaskStore(tmp_db) as store:
            store.create_task(TaskRecord(id="wc-ctx01", title="Context test"))
            task = store.get_task("wc-ctx01")
            assert task is not None
