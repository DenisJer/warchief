"""Tests for grouped task pipeline — sequential dev, dev gate, single PR."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.config import Config
from warchief.models import AgentRecord, TaskRecord
from warchief.prime import build_prime_context
from warchief.roles import RoleRegistry
from warchief.task_store import TaskStore
from warchief.watcher import Watcher


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


@pytest.fixture
def config() -> Config:
    return Config(max_total_agents=8, base_branch="main")


@pytest.fixture
def registry() -> RoleRegistry:
    return RoleRegistry(Path(__file__).parent.parent / "warchief" / "roles")


@pytest.fixture
def watcher(project_root, store, config, registry) -> Watcher:
    return Watcher(project_root, store, config, registry)


def _make_group_tasks(store: TaskStore, group_id: str = "grp-1", count: int = 3):
    """Create a set of grouped tasks in development stage."""
    tasks = []
    for i in range(count):
        t = TaskRecord(
            id=f"wc-g{i+1}", title=f"Sub-task {i+1}",
            status="open", stage="development",
            labels=["stage:development"],
            group_id=group_id, priority=count - i,  # first task has highest priority
            type="feature",
        )
        store.create_task(t)
        tasks.append(t)
    return tasks


class TestSequentialDevelopment:
    """Sequential development guard in spawn_ready()."""

    @patch("warchief.watcher.run_preflight", return_value=[])
    @patch("warchief.watcher.spawn_agent", return_value=None)
    def test_blocks_sibling_spawn_when_one_developing(
        self, mock_spawn, mock_preflight, watcher, store,
    ):
        """Only one developer per group should spawn at a time."""
        tasks = _make_group_tasks(store)
        # Mark first task as in_progress (agent alive)
        store.update_task("wc-g1", status="in_progress", assigned_agent="dev-1")
        store.register_agent(AgentRecord(
            id="dev-1", role="developer", status="alive",
            current_task="wc-g1", pid=12345,
        ))

        watcher.spawn_ready()

        # spawn_agent should NOT be called for sibling tasks
        # (it may be called for wc-g1 but that already has an alive agent)
        for call in mock_spawn.call_args_list:
            task_arg = call[0][0]
            assert task_arg.id not in ("wc-g2", "wc-g3"), \
                f"Should not spawn for sibling {task_arg.id} while wc-g1 is developing"

    @patch("warchief.watcher.run_preflight", return_value=[])
    @patch("warchief.watcher.spawn_agent")
    def test_allows_spawn_after_sibling_finishes(
        self, mock_spawn, mock_preflight, watcher, store,
    ):
        """Once a sibling finishes dev, next sibling can spawn."""
        tasks = _make_group_tasks(store, count=2)
        # First task is done (closed or has group-dev-done)
        store.update_task("wc-g1", status="closed")

        mock_spawn.return_value = AgentRecord(
            id="dev-2", role="developer", status="alive",
            current_task="wc-g2", pid=22222,
        )

        watcher.spawn_ready()

        # spawn_agent should be called for wc-g2
        spawned_ids = [c[0][0].id for c in mock_spawn.call_args_list]
        assert "wc-g2" in spawned_ids

    @patch("warchief.watcher.run_preflight", return_value=[])
    @patch("warchief.watcher.spawn_agent", return_value=None)
    def test_planning_stays_parallel(
        self, mock_spawn, mock_preflight, watcher, store,
    ):
        """Planning stage should NOT be gated — only development."""
        for i in range(2):
            store.create_task(TaskRecord(
                id=f"wc-p{i+1}", title=f"Plan {i+1}",
                status="open", stage="planning",
                labels=["stage:planning"],
                group_id="grp-plan", priority=2 - i,
                type="feature",
            ))
        # Mark first as in_progress
        store.update_task("wc-p1", status="in_progress", assigned_agent="plan-1")
        store.register_agent(AgentRecord(
            id="plan-1", role="planner", status="alive",
            current_task="wc-p1", pid=33333,
        ))

        mock_spawn.return_value = AgentRecord(
            id="plan-2", role="planner", status="alive",
            current_task="wc-p2", pid=33334,
        )

        watcher.spawn_ready()

        # Planning should allow parallel spawns (no sequential guard)
        spawned_ids = [c[0][0].id for c in mock_spawn.call_args_list]
        assert "wc-p2" in spawned_ids

    @patch("warchief.watcher.run_preflight", return_value=[])
    @patch("warchief.watcher.spawn_agent", return_value=None)
    def test_non_grouped_task_unaffected(
        self, mock_spawn, mock_preflight, watcher, store,
    ):
        """Tasks without group_id should not be blocked by sequential guard."""
        store.create_task(TaskRecord(
            id="wc-solo", title="Solo task", status="open",
            stage="development", labels=["stage:development"],
            type="feature",
        ))
        # Another solo task also in development
        store.create_task(TaskRecord(
            id="wc-solo2", title="Solo task 2", status="in_progress",
            stage="development", labels=["stage:development"],
            assigned_agent="dev-x", type="feature",
        ))
        store.register_agent(AgentRecord(
            id="dev-x", role="developer", status="alive",
            current_task="wc-solo2", pid=44444,
        ))

        mock_spawn.return_value = AgentRecord(
            id="dev-solo", role="developer", status="alive",
            current_task="wc-solo", pid=44445,
        )

        watcher.spawn_ready()

        spawned_ids = [c[0][0].id for c in mock_spawn.call_args_list]
        assert "wc-solo" in spawned_ids


class TestGroupDevGate:
    """_check_group_dev_gate() behavior."""

    def test_holds_first_finisher(self, watcher, store):
        """First task to finish dev should be held with group-waiting."""
        tasks = _make_group_tasks(store)

        result = watcher._check_group_dev_gate(store.get_task("wc-g1"))

        assert result is True
        updated = store.get_task("wc-g1")
        assert "group-dev-done" in updated.labels
        assert "group-waiting" in updated.labels
        assert updated.status == "open"

    @patch("warchief.watcher.Watcher._get_changed_files", return_value=[])
    def test_advances_lead_when_all_done(self, mock_changed, watcher, store):
        """When all siblings have group-dev-done, lead advances."""
        tasks = _make_group_tasks(store, count=2)
        # First task already done
        store.update_task("wc-g1", labels=["stage:development", "group-dev-done", "group-waiting"])

        # Second task finishes — now all done
        result = watcher._check_group_dev_gate(store.get_task("wc-g2"))

        assert result is True
        # Lead is wc-g1 (highest priority)
        lead = store.get_task("wc-g1")
        assert lead.status != "closed"
        assert lead.stage in ("testing", "reviewing")  # advanced past development
        assert "group-waiting" not in lead.labels

        # Non-lead sibling is closed
        sibling = store.get_task("wc-g2")
        assert sibling.status == "closed"

    def test_lead_election_by_priority(self, watcher, store):
        """Group lead should be the task with highest priority."""
        # Create tasks with explicit priorities
        for i, (tid, prio) in enumerate([("wc-lo", 1), ("wc-hi", 10), ("wc-mid", 5)]):
            store.create_task(TaskRecord(
                id=tid, title=f"Task {tid}",
                status="open", stage="development",
                labels=["stage:development", "group-dev-done", "group-waiting"],
                group_id="grp-prio", priority=prio, type="feature",
            ))

        # Last task finishes (but it's not the lead)
        store.update_task("wc-lo", labels=["stage:development", "group-dev-done"])
        # Refresh before calling gate
        watcher._check_group_dev_gate(store.get_task("wc-lo"))

        # Lead should be wc-hi (priority=10)
        lead = store.get_task("wc-hi")
        assert lead.status != "closed"
        assert lead.stage != "development"

        # Others should be closed
        assert store.get_task("wc-lo").status == "closed"
        assert store.get_task("wc-mid").status == "closed"


class TestCleanupPreservesBranch:
    """_cleanup_completed_task preserves branch for active group."""

    @patch("warchief.watcher.remove_worktree")
    def test_skips_branch_switch_for_active_group(self, mock_rm, watcher, store):
        """Should not switch off feature branch if siblings still active."""
        tasks = _make_group_tasks(store, count=2)
        # Close first task, second still open
        store.update_task("wc-g1", status="closed")

        with patch("subprocess.run") as mock_run:
            watcher._cleanup_completed_task(store.get_task("wc-g1"))
            # Should NOT call git checkout since wc-g2 is still active
            checkout_calls = [
                c for c in mock_run.call_args_list
                if "checkout" in str(c)
            ]
            assert len(checkout_calls) == 0


class TestSiblingContext:
    """prime.py sibling context injection."""

    def test_developer_gets_sibling_context(self, store, project_root):
        """Developer should see completed siblings info."""
        tasks = _make_group_tasks(store, count=2)
        store.update_task("wc-g1", labels=["stage:development", "group-dev-done"])

        ctx = build_prime_context(store.get_task("wc-g2"), "developer", store, project_root)

        assert "Group Context" in ctx
        assert "wc-g1" in ctx
        assert "already on this branch" in ctx

    def test_reviewer_gets_all_sibling_descriptions(self, store, project_root):
        """Reviewer should see all sibling task descriptions."""
        tasks = _make_group_tasks(store, count=3)

        ctx = build_prime_context(store.get_task("wc-g1"), "reviewer", store, project_root)

        assert "Review ALL changes" in ctx
        assert "wc-g2" in ctx
        assert "wc-g3" in ctx
