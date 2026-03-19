from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from warchief.models import AgentRecord, EventRecord, MessageRecord, TaskRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    stage TEXT,
    labels TEXT DEFAULT '[]',
    deps TEXT DEFAULT '[]',
    assigned_agent TEXT,
    base_branch TEXT DEFAULT '',
    rejection_count INTEGER DEFAULT 0,
    spawn_count INTEGER DEFAULT 0,
    crash_count INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    type TEXT DEFAULT 'feature',
    group_id TEXT,
    created_at REAL,
    updated_at REAL,
    closed_at REAL,
    version INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    current_task TEXT,
    worktree_path TEXT,
    pid INTEGER,
    model TEXT DEFAULT '',
    spawned_at REAL,
    last_heartbeat REAL,
    crash_count INTEGER DEFAULT 0,
    total_tasks_completed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    from_agent TEXT,
    to_agent TEXT NOT NULL,
    message_type TEXT,
    body TEXT NOT NULL,
    persistent INTEGER DEFAULT 0,
    read_at REAL,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    agent_id TEXT,
    event_type TEXT NOT NULL,
    details TEXT DEFAULT '{}',
    actor TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS schedule_contexts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at REAL,
    dispatched_at REAL
);
"""


def _generate_id() -> str:
    return f"wc-{uuid.uuid4().hex[:7]}"


def _row_to_task(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        status=row["status"],
        stage=row["stage"],
        labels=json.loads(row["labels"]) if row["labels"] else [],
        deps=json.loads(row["deps"]) if row["deps"] else [],
        assigned_agent=row["assigned_agent"],
        base_branch=row["base_branch"] or "",
        rejection_count=row["rejection_count"],
        spawn_count=row["spawn_count"],
        crash_count=row["crash_count"],
        priority=row["priority"],
        type=row["type"],
        extra_tools=json.loads(row["extra_tools"])
        if "extra_tools" in row.keys() and row["extra_tools"]
        else [],
        budget=float(row["budget"]) if "budget" in row.keys() and row["budget"] else 0.0,
        group_id=row["group_id"] if "group_id" in row.keys() else None,
        created_at=row["created_at"] or 0.0,
        updated_at=row["updated_at"] or 0.0,
        closed_at=row["closed_at"],
        version=row["version"],
    )


def _row_to_agent(row: sqlite3.Row) -> AgentRecord:
    return AgentRecord(
        id=row["id"],
        role=row["role"],
        status=row["status"],
        current_task=row["current_task"],
        worktree_path=row["worktree_path"],
        pid=row["pid"],
        model=row["model"] or "",
        spawned_at=row["spawned_at"],
        last_heartbeat=row["last_heartbeat"],
        crash_count=row["crash_count"],
        total_tasks_completed=row["total_tasks_completed"],
    )


def _row_to_message(row: sqlite3.Row) -> MessageRecord:
    return MessageRecord(
        id=row["id"],
        from_agent=row["from_agent"],
        to_agent=row["to_agent"],
        message_type=row["message_type"],
        body=row["body"],
        persistent=bool(row["persistent"]),
        read_at=row["read_at"],
        created_at=row["created_at"] or 0.0,
    )


def _row_to_event(row: sqlite3.Row) -> EventRecord:
    return EventRecord(
        id=row["id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        event_type=row["event_type"],
        details=json.loads(row["details"]) if row["details"] else {},
        actor=row["actor"],
        created_at=row["created_at"] or 0.0,
    )


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add columns that may not exist in older databases."""
        cursor = self._conn.execute("PRAGMA table_info(tasks)")
        cols = {row["name"] for row in cursor.fetchall()}
        if "group_id" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN group_id TEXT")
            self._conn.commit()
        if "extra_tools" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN extra_tools TEXT DEFAULT '[]'")
            self._conn.commit()
        if "budget" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN budget REAL DEFAULT 0.0")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TaskStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Tasks ──────────────────────────────────────────────────

    def create_task(self, task: TaskRecord) -> str:
        task_id = task.id if task.id else _generate_id()
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO tasks
                   (id, title, description, status, stage, labels, deps,
                    assigned_agent, base_branch, rejection_count, spawn_count,
                    crash_count, priority, type, extra_tools, budget, group_id,
                    created_at, updated_at, version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    task_id,
                    task.title,
                    task.description,
                    task.status,
                    task.stage,
                    json.dumps(task.labels),
                    json.dumps(task.deps),
                    task.assigned_agent,
                    task.base_branch,
                    task.rejection_count,
                    task.spawn_count,
                    task.crash_count,
                    task.priority,
                    task.type,
                    json.dumps(task.extra_tools),
                    task.budget,
                    task.group_id,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return task_id

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def update_task(
        self, task_id: str, expected_version: int | None = None, **kwargs: object
    ) -> bool:
        """Update a task with optimistic locking.

        If *expected_version* is given, the UPDATE will include
        ``AND version = ?`` so that a concurrent modification causes 0 rows
        to be affected.  When *expected_version* is ``None`` (the default),
        the current version is read automatically to provide implicit
        optimistic locking.

        Returns ``True`` if the row was updated, ``False`` otherwise.
        """
        import logging

        _log = logging.getLogger("warchief.task_store")

        with self._lock:
            if expected_version is None:
                task = self.get_task(task_id)
                if task is None:
                    return False
                expected_version = task.version

            sets: list[str] = []
            params: list[object] = []

            for key, value in kwargs.items():
                if key == "version":
                    continue
                if key in ("labels", "deps", "extra_tools"):
                    sets.append(f"{key} = ?")
                    params.append(json.dumps(value))
                else:
                    sets.append(f"{key} = ?")
                    params.append(value)

            sets.append("updated_at = ?")
            params.append(time.time())
            sets.append("version = version + 1")

            params.append(task_id)
            params.append(expected_version)

            sql = f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND version = ?"
            cursor = self._conn.execute(sql, params)
            self._conn.commit()

            if cursor.rowcount == 0:
                _log.warning(
                    "Optimistic lock failed for task %s (expected version %d)",
                    task_id,
                    expected_version,
                )
                return False
            return True

    def list_tasks(
        self,
        status: str | None = None,
        stage: str | None = None,
        has_label: str | None = None,
    ) -> list[TaskRecord]:
        conditions: list[str] = []
        params: list[object] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if stage:
            conditions.append("stage = ?")
            params.append(stage)
        if has_label:
            conditions.append("labels LIKE ?")
            params.append(f'%"{has_label}"%')

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._conn.execute(
            f"SELECT * FROM tasks{where} ORDER BY priority DESC, created_at ASC",
            params,
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_ready_tasks(self, stage: str) -> list[TaskRecord]:
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE stage = ? AND status = 'open' AND assigned_agent IS NULL
               ORDER BY priority DESC, created_at ASC""",
            (stage,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_orphaned_tasks(self) -> list[TaskRecord]:
        rows = self._conn.execute(
            """SELECT t.* FROM tasks t
               LEFT JOIN agents a ON t.assigned_agent = a.id AND a.status = 'alive'
               WHERE t.status = 'in_progress' AND a.id IS NULL""",
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_stale_assigned_tasks(self) -> list[TaskRecord]:
        """Find open tasks with an assigned_agent that is no longer alive."""
        rows = self._conn.execute(
            """SELECT t.* FROM tasks t
               LEFT JOIN agents a ON t.assigned_agent = a.id AND a.status = 'alive'
               WHERE t.status = 'open' AND t.assigned_agent IS NOT NULL AND a.id IS NULL""",
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_group_tasks(self, group_id: str) -> list[TaskRecord]:
        """Return all tasks belonging to *group_id*."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE group_id = ? ORDER BY priority DESC, created_at ASC",
            (group_id,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_tasks_with_resolved_deps(self) -> list[TaskRecord]:
        waiting = self._conn.execute(
            "SELECT * FROM tasks WHERE labels LIKE '%\"waiting\"%'",
        ).fetchall()
        result: list[TaskRecord] = []
        for row in waiting:
            task = _row_to_task(row)
            if not task.deps:
                result.append(task)
                continue
            all_closed = True
            for dep_id in task.deps:
                dep = self.get_task(dep_id)
                if dep is None or dep.status != "closed":
                    all_closed = False
                    break
            if all_closed:
                result.append(task)
        return result

    # ── Agents ─────────────────────────────────────────────────

    def register_agent(self, agent: AgentRecord) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO agents
               (id, role, status, current_task, worktree_path, pid, model,
                spawned_at, last_heartbeat, crash_count, total_tasks_completed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent.id,
                agent.role,
                agent.status,
                agent.current_task,
                agent.worktree_path,
                agent.pid,
                agent.model,
                agent.spawned_at,
                agent.last_heartbeat,
                agent.crash_count,
                agent.total_tasks_completed,
            ),
        )
        self._conn.commit()

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        row = self._conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return _row_to_agent(row) if row else None

    def update_agent(self, agent_id: str, **kwargs: object) -> None:
        sets = [f"{k} = ?" for k in kwargs]
        params = list(kwargs.values())
        params.append(agent_id)
        with self._lock:
            self._conn.execute(f"UPDATE agents SET {', '.join(sets)} WHERE id = ?", params)
            self._conn.commit()

    def get_running_agents(self) -> list[AgentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM agents WHERE status IN ('alive', 'zombie')"
        ).fetchall()
        return [_row_to_agent(r) for r in rows]

    def get_idle_agents(self, role: str) -> list[AgentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM agents WHERE status = 'idle' AND role = ?", (role,)
        ).fetchall()
        return [_row_to_agent(r) for r in rows]

    # ── Messages ───────────────────────────────────────────────

    def create_message(self, msg: MessageRecord) -> None:
        msg_id = msg.id if msg.id else f"msg-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._conn.execute(
                """INSERT INTO messages
                   (id, from_agent, to_agent, message_type, body, persistent, read_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    msg.from_agent,
                    msg.to_agent,
                    msg.message_type,
                    msg.body,
                    1 if msg.persistent else 0,
                    msg.read_at,
                    msg.created_at or time.time(),
                ),
            )
            self._conn.commit()

    def get_unread_mail(self, agent_id: str) -> list[MessageRecord]:
        rows = self._conn.execute(
            """SELECT * FROM messages
               WHERE to_agent = ? AND persistent = 1 AND read_at IS NULL
               ORDER BY created_at ASC""",
            (agent_id,),
        ).fetchall()
        return [_row_to_message(r) for r in rows]

    def get_task_messages(self, task_id: str, limit: int | None = None) -> list[MessageRecord]:
        """Get Q&A messages for a task (questions from agent, answers to task).

        When *limit* is given, only the most recent *limit* messages are returned
        (ordered oldest-first).  Without a limit all messages are returned.
        """
        if limit is not None:
            # Sub-select the newest N rows, then re-order oldest-first
            rows = self._conn.execute(
                """SELECT * FROM (
                       SELECT * FROM messages
                       WHERE from_agent = ? OR to_agent = ?
                       ORDER BY created_at DESC
                       LIMIT ?
                   ) sub ORDER BY created_at ASC""",
                (task_id, task_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM messages
                   WHERE from_agent = ? OR to_agent = ?
                   ORDER BY created_at ASC""",
                (task_id, task_id),
            ).fetchall()
        return [_row_to_message(r) for r in rows]

    def get_all_messages_by_task(self) -> dict[str, list[MessageRecord]]:
        """Load all messages grouped by task (from_agent or to_agent)."""
        rows = self._conn.execute("SELECT * FROM messages ORDER BY created_at DESC").fetchall()
        by_task: dict[str, list[MessageRecord]] = {}
        for row in rows:
            msg = _row_to_message(row)
            for task_id in (msg.from_agent, msg.to_agent):
                if task_id:
                    by_task.setdefault(task_id, []).append(msg)
        return by_task

    def delete_task_messages(self, task_id: str) -> None:
        """Delete all messages associated with a task."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE from_agent = ? OR to_agent = ?",
                (task_id, task_id),
            )
            self._conn.commit()

    def mark_read(self, message_id: str) -> None:
        self._conn.execute(
            "UPDATE messages SET read_at = ? WHERE id = ?",
            (time.time(), message_id),
        )
        self._conn.commit()

    # ── Events ─────────────────────────────────────────────────

    def log_event(self, event: EventRecord) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO events (task_id, agent_id, event_type, details, actor, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event.task_id,
                    event.agent_id,
                    event.event_type,
                    json.dumps(event.details),
                    event.actor,
                    event.created_at or time.time(),
                ),
            )
            self._conn.commit()

    def get_events(self, task_id: str | None = None, limit: int = 100) -> list[EventRecord]:
        if task_id:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_event(r) for r in rows]
