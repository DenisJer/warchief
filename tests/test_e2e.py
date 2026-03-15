"""End-to-end test — simulate a task flowing through the full pipeline."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from warchief.config import Config, STAGES
from warchief.models import AgentRecord, EventRecord, TaskRecord
from warchief.state_machine import dispatch_transition
from warchief.task_store import TaskStore


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".warchief").mkdir()
    return root


@pytest.fixture
def store(project_root: Path) -> TaskStore:
    s = TaskStore(project_root / ".warchief" / "warchief.db")
    yield s
    s.close()


class TestFullPipelineE2E:
    """Simulate a task going through development -> reviewing -> pr-creation -> closed."""

    def test_task_lifecycle(self, store: TaskStore):
        # 1. Create a task
        task_id = store.create_task(TaskRecord(
            id="wc-e2e-01",
            title="Build login page",
            description="Implement the login page with email/password",
            status="open",
            stage=None,
            labels=[],
            deps=[],
            priority=8,
            type="feature",
        ))
        assert task_id == "wc-e2e-01"

        # 2. Release into pipeline (development stage)
        store.update_task(task_id, stage="development", status="open",
                          labels=["stage:development"])
        task = store.get_task(task_id)
        assert task.stage == "development"

        # 3. Simulate agent spawn and assignment
        agent = AgentRecord(
            id="developer-thrall", role="developer", status="alive",
            current_task=task_id, pid=12345, spawned_at=time.time(),
        )
        store.register_agent(agent)
        store.update_task(task_id, status="in_progress", assigned_agent="developer-thrall")
        store.log_event(EventRecord(
            event_type="spawn", task_id=task_id, agent_id="developer-thrall",
        ))

        # 4. Developer finishes — transition to reviewing
        result = dispatch_transition(
            task_status="closed", task_stage="development",
            task_labels=["stage:development"], agent_role="developer",
            branch_has_commits=True,
        )
        assert result.next_stage == "reviewing"
        assert result.status == "open"

        store.update_task(task_id,
            stage="reviewing", status="open", assigned_agent=None,
            labels=["stage:reviewing"],
        )
        store.update_agent("developer-thrall", status="retired", current_task=None)

        # 5. Reviewer approves — transition to testing
        result = dispatch_transition(
            task_status="closed", task_stage="reviewing",
            task_labels=["stage:reviewing"], agent_role="reviewer",
        )
        assert result.next_stage == "testing"

        # 5b. Testing stage — simulate skip (no frontend files)
        # needs-testing not present, so it advances to pr-creation
        result = dispatch_transition(
            task_status="open", task_stage="testing",
            task_labels=["stage:testing"], agent_role="developer",
        )
        assert result.next_stage == "pr-creation"

        store.update_task(task_id, stage="pr-creation", status="open",
                          assigned_agent=None, labels=["stage:pr-creation"])

        # 6. PR creator creates PR — task complete
        result = dispatch_transition(
            task_status="closed", task_stage="pr-creation",
            task_labels=["stage:pr-creation"], agent_role="pr_creator",
        )
        assert result.status == "closed"

        store.update_task(task_id, status="closed", closed_at=time.time())

        # Verify final state
        final = store.get_task(task_id)
        assert final.status == "closed"
        assert final.closed_at is not None

    def test_rejection_loop(self, store: TaskStore):
        """Test that a task bounces back on reviewer rejection."""
        task_id = store.create_task(TaskRecord(
            id="wc-e2e-02", title="Bad code", status="open",
            stage="reviewing", rejection_count=0,
            labels=["stage:reviewing", "rejected"],
        ))

        # Reviewer rejects (rejected label present)
        result = dispatch_transition(
            task_status="closed", task_stage="reviewing",
            task_labels=["stage:reviewing", "rejected"],
            agent_role="reviewer",
        )
        assert result.next_stage == "development"
        assert "rejected" in (result.remove_labels or [])

        # After max rejections in development → blocked
        result = dispatch_transition(
            task_status="closed", task_stage="development",
            task_labels=["stage:development", "rejected"],
            agent_role="developer",
            rejection_count=3, max_rejections=3,
        )
        assert result.status == "blocked"

    def test_security_review_routing(self, store: TaskStore):
        """Test that security-labeled tasks route through security-review."""
        task_id = store.create_task(TaskRecord(
            id="wc-e2e-03", title="Auth feature",
            status="open", stage="reviewing", labels=["security", "stage:reviewing"],
        ))

        # Reviewer approves security-labeled task → security-review
        result = dispatch_transition(
            task_status="closed", task_stage="reviewing",
            task_labels=["security", "stage:reviewing"],
            agent_role="reviewer",
        )
        assert result.next_stage == "security-review"

    def test_backup_restore_cycle(self, project_root: Path, store: TaskStore):
        """Test backup and restore preserves data."""
        from warchief.backup import create_backup, restore_backup

        store.create_task(TaskRecord(id="wc-br1", title="Backup test"))
        store.log_event(EventRecord(event_type="test", task_id="wc-br1"))

        backup_path = create_backup(project_root, store)
        assert backup_path.exists()

        # Restore to fresh store
        fresh_db = project_root / ".warchief" / "fresh.db"
        fresh_store = TaskStore(fresh_db)
        counts = restore_backup(project_root, fresh_store, backup_path)
        assert counts["tasks"] >= 1

        task = fresh_store.get_task("wc-br1")
        assert task is not None
        assert task.title == "Backup test"
        fresh_store.close()

    def test_doctor_on_healthy_system(self, project_root: Path, store: TaskStore):
        """Doctor should report healthy on a properly set up system."""
        import subprocess as sp
        from warchief.doctor import run_doctor

        # Initialize a git repo so git/git_user checks pass
        sp.run(["git", "init", str(project_root)], capture_output=True)
        sp.run(["git", "config", "user.name", "Test"], cwd=project_root, capture_output=True)
        sp.run(["git", "config", "user.email", "t@t.com"], cwd=project_root, capture_output=True)
        sp.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=project_root, capture_output=True)

        store.create_task(TaskRecord(id="wc-doc", title="Doctor test"))
        report = run_doctor(project_root)

        # claude_cli check may fail if claude not on PATH (e.g. CI), so allow 1 error max
        errors = [c for c in report.checks if not c.ok and c.severity == "error"]
        assert len(errors) <= 1, f"Unexpected errors: {errors}"

    def test_metrics_after_pipeline(self, store: TaskStore):
        """Metrics should reflect pipeline activity."""
        from warchief.metrics import compute_pipeline_metrics

        for i in range(3):
            store.create_task(TaskRecord(
                id=f"wc-met-{i}", title=f"Task {i}",
                status="closed" if i < 2 else "in_progress",
                closed_at=time.time() if i < 2 else None,
            ))

        metrics = compute_pipeline_metrics(store)
        assert metrics.total_tasks == 3
        assert metrics.closed_tasks == 2
        assert metrics.in_progress_tasks == 1
