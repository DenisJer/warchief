"""Tests for the watcher — unit-level with mocked subprocess/os calls."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.config import Config
from warchief.models import AgentRecord, EventRecord, TaskRecord
from warchief.roles import RoleRegistry
from warchief.task_store import TaskStore
from warchief.watcher import Watcher, _is_process_alive


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


class TestIsProcessAlive:
    def test_current_process_is_alive(self):
        import os
        assert _is_process_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        assert _is_process_alive(99999999) is False


class TestWatcherCleanup:
    @patch("warchief.watcher._is_process_alive", return_value=False)
    @patch("warchief.watcher._get_exit_code", return_value=0)
    def test_cleanup_dead_agent(self, mock_exit, mock_alive, watcher, store):
        # Create a task and agent
        store.create_task(TaskRecord(
            id="wc-t01", title="Test task", status="open",
            stage="development", labels=["stage:development"],
        ))
        store.register_agent(AgentRecord(
            id="dev-thrall", role="developer", status="alive",
            current_task="wc-t01", pid=12345,
        ))
        store.update_task("wc-t01", status="in_progress", assigned_agent="dev-thrall")

        watcher.cleanup_finished()

        agent = store.get_agent("dev-thrall")
        assert agent.status == "dead"

    @patch("warchief.watcher._is_process_alive", return_value=True)
    def test_alive_agent_not_cleaned(self, mock_alive, watcher, store):
        store.register_agent(AgentRecord(
            id="dev-jaina", role="developer", status="alive",
            current_task="wc-t01", pid=12345,
        ))

        watcher.cleanup_finished()

        agent = store.get_agent("dev-jaina")
        assert agent.status == "alive"


class TestWatcherOrphans:
    def test_reset_orphans(self, watcher, store):
        # Task in_progress but no matching alive agent
        store.create_task(TaskRecord(
            id="wc-orphan", title="Orphan task", status="in_progress",
            stage="development", assigned_agent="dev-ghost",
        ))

        watcher.reset_orphans()

        task = store.get_task("wc-orphan")
        assert task.status == "open"
        assert task.assigned_agent is None


class TestWatcherTransitions:
    def test_resolve_waiting_deps(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-dep1", title="Dep", status="closed",
        ))
        store.create_task(TaskRecord(
            id="wc-waiter", title="Waiter", status="open",
            labels=["waiting"], deps=["wc-dep1"],
        ))

        watcher.process_transitions()

        task = store.get_task("wc-waiter")
        assert "waiting" not in task.labels
        assert task.status == "open"

    def test_waiting_with_unresolved_deps(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-dep2", title="Dep", status="open",
        ))
        store.create_task(TaskRecord(
            id="wc-waiter2", title="Waiter", status="open",
            labels=["waiting"], deps=["wc-dep2"],
        ))

        watcher.process_transitions()

        task = store.get_task("wc-waiter2")
        assert "waiting" in task.labels


class TestWatcherSpawn:
    @patch("warchief.watcher.run_preflight", return_value=["error"])
    def test_skip_on_preflight_failure(self, mock_pf, watcher, store):
        store.create_task(TaskRecord(
            id="wc-ready", title="Ready", status="open",
            stage="development", labels=["stage:development"],
        ))

        watcher.spawn_ready()

        task = store.get_task("wc-ready")
        assert task.status == "open"  # Not spawned
        assert task.assigned_agent is None

    @patch("warchief.watcher.run_preflight", return_value=[])
    @patch("warchief.watcher.spawn_agent", return_value=None)
    def test_spawn_called_for_ready_tasks(self, mock_spawn, mock_pf, watcher, store):
        store.create_task(TaskRecord(
            id="wc-ready2", title="Ready", status="open",
            stage="development", labels=["stage:development"],
        ))

        watcher.spawn_ready()
        mock_spawn.assert_called_once()


class TestWatcherCheckpoint:
    def test_save_checkpoint(self, watcher, project_root):
        watcher._tick_count = 42
        watcher.save_checkpoint()

        import json
        cp = json.loads((project_root / ".warchief" / "watcher_state.json").read_text())
        assert cp["tick_count"] == 42


class TestWatcherTick:
    @patch("warchief.watcher.read_config")
    def test_paused_skips_tick(self, mock_config, watcher, store):
        paused_config = Config(paused=True)
        mock_config.return_value = paused_config

        # Should not raise and should skip processing
        watcher.tick()

    @patch("warchief.watcher.read_config")
    @patch.object(Watcher, "cleanup_finished")
    @patch.object(Watcher, "check_zombies")
    @patch.object(Watcher, "reset_orphans")
    @patch.object(Watcher, "process_transitions")
    @patch.object(Watcher, "spawn_ready")
    @patch.object(Watcher, "save_checkpoint")
    def test_tick_calls_all_steps(self, mock_cp, mock_spawn, mock_trans,
                                  mock_orphan, mock_zombie, mock_cleanup,
                                  mock_config, watcher):
        mock_config.return_value = Config()

        watcher.tick()

        mock_cleanup.assert_called_once()
        mock_zombie.assert_called_once()
        mock_orphan.assert_called_once()
        mock_trans.assert_called_once()
        mock_spawn.assert_called_once()
        mock_cp.assert_called_once()


class TestAutoRecoverBlocked:
    """Tests for the auto-unblock mechanism."""

    def _block_task(self, store, task_id, failure_reason):
        """Helper: log a block event with a failure reason."""
        store.log_event(EventRecord(
            event_type="block",
            task_id=task_id,
            details={"failure_reason": failure_reason},
            actor="watcher",
        ))

    def test_acceptance_rejected_back_to_development(self, watcher, store):
        """Legacy test: acceptance stage no longer exists but the recovery
        logic still handles 'Acceptance tests failed' failure reasons for
        any tasks that may have been blocked before the pipeline change."""
        store.create_task(TaskRecord(
            id="wc-acc", title="Acceptance fail", status="blocked",
            stage="pr-creation", labels=["stage:pr-creation", "rejected"],
        ))
        self._block_task(store, "wc-acc", "Acceptance tests failed")

        watcher._tick_count = 6  # Trigger on tick % 6 == 0
        watcher._auto_recover_blocked()

        task = store.get_task("wc-acc")
        assert task.status == "open"
        assert task.stage == "development"
        assert "stage:development" in task.labels
        assert "rejected" not in task.labels
        assert "stage:pr-creation" not in task.labels
        assert task.rejection_count == 1

    def test_spawn_limit_resets_count(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-spawn", title="Spawn limit", status="blocked",
            stage="development", labels=["stage:development"],
            spawn_count=20,
        ))
        self._block_task(store, "wc-spawn", "Spawn limit reached (20/20)")

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-spawn")
        assert task.status == "open"
        assert task.spawn_count == 0
        assert task.stage == "development"

    def test_crash_limit_resets_with_backoff(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-crash", title="Crash limit", status="blocked",
            stage="reviewing", labels=["stage:reviewing"],
            crash_count=3,
        ))
        self._block_task(store, "wc-crash", "Crashed 4 times at reviewing")

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-crash")
        assert task.status == "open"
        assert task.crash_count == 0
        assert task.stage == "reviewing"
        # Should have set a backoff
        assert "wc-crash" in watcher._spawn_backoff

    def test_max_rejections_resets_to_development(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-rej", title="Max rejections", status="blocked",
            stage="development", labels=["stage:development", "rejected"],
            rejection_count=3,
        ))
        self._block_task(store, "wc-rej", "Rejected 3 times")

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-rej")
        assert task.status == "open"
        assert task.rejection_count == 0
        assert task.stage == "development"
        assert "rejected" not in task.labels

    def test_no_commits_resets_spawn_count(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-nocom", title="No commits", status="blocked",
            stage="development", labels=["stage:development"],
            spawn_count=3,
        ))
        self._block_task(store, "wc-nocom", "No commits after 3 development attempts")

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-nocom")
        assert task.status == "open"
        assert task.spawn_count == 0
        assert task.stage == "development"

    def test_stops_after_max_auto_retries(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-stuck", title="Stuck task", status="blocked",
            stage="pr-creation", labels=["stage:pr-creation", "rejected"],
        ))
        self._block_task(store, "wc-stuck", "Acceptance tests failed")
        # Simulate 2 previous auto-unblock attempts
        for i in range(2):
            store.log_event(EventRecord(
                event_type="auto_unblock",
                task_id="wc-stuck",
                details={"attempt": i + 1},
                actor="watcher",
            ))

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-stuck")
        assert task.status == "blocked"  # NOT recovered — exhausted retries

    def test_unknown_failure_not_recovered(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-unk", title="Unknown block", status="blocked",
            stage="development", labels=["stage:development"],
        ))
        self._block_task(store, "wc-unk", "Something completely unexpected")

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-unk")
        assert task.status == "blocked"  # Not recovered

    def test_skips_on_non_trigger_tick(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-skip", title="Skip", status="blocked",
            stage="development", labels=["stage:development"],
        ))
        self._block_task(store, "wc-skip", "Spawn limit reached (20/20)")

        watcher._tick_count = 4  # Not divisible by 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-skip")
        assert task.status == "blocked"  # No change — wrong tick

    def test_logs_auto_unblock_event(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-evt", title="Event logging", status="blocked",
            stage="development", labels=["stage:development"],
            spawn_count=20,
        ))
        self._block_task(store, "wc-evt", "Spawn limit reached (20/20)")

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        events = store.get_events(task_id="wc-evt")
        auto_events = [e for e in events if e.event_type == "auto_unblock"]
        assert len(auto_events) == 1
        assert auto_events[0].details["attempt"] == 1

    def test_worktree_failure_resets(self, watcher, store):
        store.create_task(TaskRecord(
            id="wc-wt", title="Worktree fail", status="blocked",
            stage="development", labels=["stage:development"],
            crash_count=3,
        ))
        self._block_task(store, "wc-wt", "Worktree creation failed 3 times: error")

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-wt")
        assert task.status == "open"
        assert task.crash_count == 0
