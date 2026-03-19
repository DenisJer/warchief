"""Shared fixtures for Warchief tests."""

from __future__ import annotations

import pytest
from pathlib import Path

from warchief.task_store import TaskStore
from warchief.models import TaskRecord


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def store(tmp_db: Path) -> TaskStore:
    s = TaskStore(tmp_db)
    yield s
    s.close()


@pytest.fixture
def sample_task() -> TaskRecord:
    return TaskRecord(
        id="wc-test01",
        title="Implement login page",
        description="Build the login page with OAuth support",
        status="open",
        stage="development",
        labels=["stage:development", "frontend"],
        deps=[],
        base_branch="main",
        priority=5,
        type="feature",
    )
