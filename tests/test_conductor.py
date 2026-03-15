"""Tests for conductor task decomposition."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.conductor import (
    _parse_conductor_output,
    _create_tasks_from_plan,
    run_conductor,
)
from warchief.config import Config
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def config() -> Config:
    return Config()


class TestParseOutput:
    def test_valid_json_array(self):
        raw = json.dumps([
            {"title": "Create users table", "description": "...", "priority": 8, "labels": [], "deps": []},
            {"title": "Build login form", "description": "...", "priority": 5, "labels": ["frontend"], "deps": ["$0"]},
        ])
        result = _parse_conductor_output(raw, lambda m: None)
        assert result is not None
        assert len(result) == 2
        assert result[0]["title"] == "Create users table"

    def test_json_with_markdown_fences(self):
        raw = "```json\n" + json.dumps([
            {"title": "Task 1", "description": "desc"},
        ]) + "\n```"
        result = _parse_conductor_output(raw, lambda m: None)
        assert result is not None
        assert len(result) == 1

    def test_invalid_json(self):
        result = _parse_conductor_output("not json at all", lambda m: None)
        assert result is None

    def test_not_an_array(self):
        result = _parse_conductor_output('{"title": "single"}', lambda m: None)
        assert result is None

    def test_empty_array(self):
        result = _parse_conductor_output("[]", lambda m: None)
        assert result is None

    def test_missing_title(self):
        raw = json.dumps([{"description": "no title"}])
        result = _parse_conductor_output(raw, lambda m: None)
        assert result is None


class TestCreateTasksFromPlan:
    def test_creates_tasks(self, store: TaskStore):
        plan = [
            {"title": "Task A", "description": "Do A", "priority": 8, "labels": ["backend"], "deps": []},
            {"title": "Task B", "description": "Do B", "priority": 5, "labels": ["frontend"], "deps": ["$0"]},
        ]
        created = _create_tasks_from_plan(plan, store, "main", lambda m: None)
        assert len(created) == 2
        assert created[0].title == "Task A"
        assert created[1].title == "Task B"
        # Task B should depend on Task A's ID
        assert created[1].deps == [created[0].id]
        # Task B should have "waiting" label
        assert "waiting" in created[1].labels

    def test_tasks_persisted(self, store: TaskStore):
        plan = [{"title": "Persist me", "description": "test"}]
        created = _create_tasks_from_plan(plan, store, "main", lambda m: None)
        fetched = store.get_task(created[0].id)
        assert fetched is not None
        assert fetched.title == "Persist me"

    def test_chain_deps(self, store: TaskStore):
        plan = [
            {"title": "A", "deps": []},
            {"title": "B", "deps": ["$0"]},
            {"title": "C", "deps": ["$0", "$1"]},
        ]
        created = _create_tasks_from_plan(plan, store, "main", lambda m: None)
        assert created[2].deps == [created[0].id, created[1].id]

    def test_no_deps_no_waiting_label(self, store: TaskStore):
        plan = [{"title": "Independent", "deps": []}]
        created = _create_tasks_from_plan(plan, store, "main", lambda m: None)
        assert "waiting" not in created[0].labels


class TestRunConductor:
    @patch("warchief.conductor.subprocess.run")
    def test_successful_decomposition(self, mock_run, store: TaskStore, config: Config, tmp_path: Path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {"title": "Schema migration", "description": "Create table", "priority": 9, "labels": [], "deps": []},
                {"title": "API endpoint", "description": "REST API", "priority": 7, "labels": [], "deps": ["$0"]},
            ]),
            stderr="",
        )
        tasks = run_conductor("Build user auth", tmp_path, store, config, on_status=lambda m: None)
        assert len(tasks) == 2

    @patch("warchief.conductor.subprocess.run")
    def test_conductor_failure_returns_empty(self, mock_run, store: TaskStore, config: Config, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        tasks = run_conductor("Build something", tmp_path, store, config, on_status=lambda m: None)
        assert tasks == []

    @patch("warchief.conductor.subprocess.run")
    def test_conductor_invalid_json_returns_empty(self, mock_run, store: TaskStore, config: Config, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        tasks = run_conductor("Build something", tmp_path, store, config, on_status=lambda m: None)
        assert tasks == []

    @patch("warchief.conductor.subprocess.run", side_effect=FileNotFoundError)
    def test_claude_not_found(self, mock_run, store: TaskStore, config: Config, tmp_path: Path):
        tasks = run_conductor("Build something", tmp_path, store, config, on_status=lambda m: None)
        assert tasks == []
