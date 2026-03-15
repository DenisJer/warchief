"""Tests for pipeline checker."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from warchief.config import Config
from warchief.models import AgentRecord, TaskRecord
from warchief.pipeline_checker import check_pipeline, release_ready, _serialize_pr_creator
from warchief.pipeline_template import load_pipeline
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def pipeline() -> "PipelineTemplate":
    path = Path(__file__).parent.parent / "pipelines" / "default.toml"
    return load_pipeline(path)


@pytest.fixture
def config() -> Config:
    return Config(max_total_agents=8)


class TestCheckPipeline:
    @patch("warchief.pipeline_checker._past_rejection_cooldown", return_value=True)
    def test_finds_ready_tasks(self, mock_cooldown, store, pipeline, config):
        store.create_task(TaskRecord(
            id="wc-r01", title="Ready task", status="open",
            stage="development", labels=["stage:development"], priority=5,
        ))

        ready = check_pipeline(store, pipeline, config)
        assert len(ready) == 1
        assert ready[0][0].id == "wc-r01"
        assert ready[0][1] == "developer"

    @patch("warchief.pipeline_checker._past_rejection_cooldown", return_value=True)
    def test_respects_max_spawns(self, mock_cooldown, store, pipeline, config):
        for i in range(5):
            store.create_task(TaskRecord(
                id=f"wc-r{i:02d}", title=f"Task {i}", status="open",
                stage="development", labels=["stage:development"], priority=5,
            ))

        ready = check_pipeline(store, pipeline, config, max_spawns=2)
        assert len(ready) == 2

    @patch("warchief.pipeline_checker._past_rejection_cooldown", return_value=True)
    def test_priority_sorting(self, mock_cooldown, store, pipeline, config):
        store.create_task(TaskRecord(
            id="wc-low", title="Low", status="open",
            stage="development", labels=["stage:development"], priority=1,
        ))
        store.create_task(TaskRecord(
            id="wc-high", title="High", status="open",
            stage="development", labels=["stage:development"], priority=9,
        ))

        ready = check_pipeline(store, pipeline, config)
        assert ready[0][0].id == "wc-high"

    @patch("warchief.pipeline_checker._past_rejection_cooldown", return_value=True)
    def test_skips_security_without_label(self, mock_cooldown, store, pipeline, config):
        store.create_task(TaskRecord(
            id="wc-sec", title="Sec task", status="open",
            stage="security-review", labels=["stage:security-review"], priority=5,
        ))

        ready = check_pipeline(store, pipeline, config)
        assert len(ready) == 0  # No security label


class TestReleaseReady:
    def test_release_unstaged_task(self, store, pipeline):
        store.create_task(TaskRecord(
            id="wc-new", title="New task", status="open",
        ))

        released = release_ready(store, pipeline)
        assert len(released) == 1

        task = store.get_task("wc-new")
        assert task.stage == "development"
        assert "stage:development" in task.labels

    def test_skip_staged_task(self, store, pipeline):
        store.create_task(TaskRecord(
            id="wc-staged", title="Staged", status="open",
            stage="reviewing",
        ))

        released = release_ready(store, pipeline)
        assert len(released) == 0

    def test_skip_closed_task(self, store, pipeline):
        store.create_task(TaskRecord(
            id="wc-done", title="Done", status="closed",
        ))

        released = release_ready(store, pipeline)
        assert len(released) == 0


class TestSerializePrCreator:
    def test_allows_one_pr_creator(self, store):
        ready = [
            (TaskRecord(id="wc-m1", title="PR 1"), "pr_creator", 10),
            (TaskRecord(id="wc-m2", title="PR 2"), "pr_creator", 8),
            (TaskRecord(id="wc-d1", title="Dev 1"), "developer", 6),
        ]
        result = _serialize_pr_creator(ready, store)
        pr_creator_tasks = [t for t, r in result if r == "pr_creator"]
        assert len(pr_creator_tasks) == 1

    def test_skips_if_pr_creator_running(self, store):
        store.register_agent(AgentRecord(
            id="pr-thrall", role="pr_creator", status="alive",
        ))
        ready = [
            (TaskRecord(id="wc-m1", title="PR 1"), "pr_creator", 10),
        ]
        result = _serialize_pr_creator(ready, store)
        pr_creator_tasks = [t for t, r in result if r == "pr_creator"]
        assert len(pr_creator_tasks) == 0
