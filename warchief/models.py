from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskRecord:
    id: str
    title: str
    description: str = ""
    status: str = "open"
    stage: str | None = None
    labels: list[str] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    assigned_agent: str | None = None
    base_branch: str = ""
    rejection_count: int = 0
    spawn_count: int = 0
    crash_count: int = 0
    priority: int = 0
    type: str = "feature"
    extra_tools: list[str] = field(default_factory=list)
    budget: float = 0.0  # 0 = use config default. Per-task budget in USD
    group_id: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    closed_at: float | None = None
    version: int = 0


def get_task_branch(task: TaskRecord) -> str:
    """Return the feature branch name for a task.

    Grouped tasks share a single branch (``feature/{group_id}``).
    Standalone tasks use ``feature/{task.id}``.
    """
    return f"feature/{task.group_id}" if task.group_id else f"feature/{task.id}"


@dataclass(frozen=True)
class AgentRecord:
    id: str
    role: str
    status: str = "idle"
    current_task: str | None = None
    worktree_path: str | None = None
    pid: int | None = None
    model: str = ""
    spawned_at: float | None = None
    last_heartbeat: float | None = None
    crash_count: int = 0
    total_tasks_completed: int = 0


@dataclass(frozen=True)
class MessageRecord:
    id: str
    to_agent: str
    body: str
    from_agent: str | None = None
    message_type: str | None = None
    persistent: bool = False
    read_at: float | None = None
    created_at: float = 0.0


@dataclass(frozen=True)
class EventRecord:
    event_type: str
    task_id: str | None = None
    agent_id: str | None = None
    id: int | None = None
    details: dict = field(default_factory=dict)  # type: ignore[type-arg]
    actor: str | None = None
    created_at: float = 0.0


@dataclass(frozen=True)
class TransitionResult:
    status: str | None = None
    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    next_stage: str | None = None
    next_role: str | None = None
    failure_reason: str | None = None
    requires_conductor: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(
            self.status
            or self.add_labels
            or self.remove_labels
            or self.next_stage
            or self.failure_reason
        )
