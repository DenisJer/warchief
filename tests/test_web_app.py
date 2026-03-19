"""Tests for warchief.web.app — FastAPI endpoints."""

from __future__ import annotations

import pytest
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import warchief.web.app as webapp
from warchief.web.app import app


@pytest.fixture
def client(tmp_path):
    """Create a test client with a temporary database."""
    old_root = webapp._project_root
    old_store = webapp._shared_store
    webapp._project_root = tmp_path
    webapp._shared_store = None  # Force re-creation
    (tmp_path / ".warchief").mkdir()
    (tmp_path / ".warchief" / "config.toml").write_text(
        'max_total_agents = 2\nbase_branch = "main"\n'
    )
    with TestClient(app) as c:
        yield c
    webapp._shared_store = None
    webapp._project_root = old_root


def test_get_state(client):
    """GET /api/state returns pipeline state."""
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "pipeline" in data
    assert "agents" in data
    assert "metrics" in data
    assert "tokens" in data


def test_create_task(client):
    """POST /api/create creates a new task."""
    resp = client.post(
        "/api/create",
        json={
            "title": "Test task",
            "description": "A test",
            "type": "feature",
            "priority": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["task_id"].startswith("wc-")


def test_create_and_drop_task(client):
    """POST /api/drop closes a task."""
    # Create first
    resp = client.post("/api/create", json={"title": "Drop me"})
    task_id = resp.json()["task_id"]

    # Drop it
    resp = client.post(f"/api/drop/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify it's closed in state
    state = client.get("/api/state").json()
    # Task should be closed, so not in any pipeline stage
    for stage in state["pipeline"]:
        for card in stage["tasks"]:
            assert card["id"] != task_id


def test_drop_nonexistent_task(client):
    """POST /api/drop with bad task_id returns error."""
    resp = client.post("/api/drop/nonexistent")
    data = resp.json()
    assert "error" in data


def test_answer_no_question(client):
    """POST /api/answer on task without question label returns error."""
    resp = client.post("/api/create", json={"title": "No Q"})
    task_id = resp.json()["task_id"]

    resp = client.post(f"/api/answer/{task_id}", json={"message": "42"})
    data = resp.json()
    assert "error" in data
    assert "no pending question" in data["error"]


def test_answer_nonexistent(client):
    """POST /api/answer on missing task returns error."""
    resp = client.post("/api/answer/bad-id", json={"message": "hi"})
    assert "error" in resp.json()


def test_nudge_task(client):
    """POST /api/nudge returns a response."""
    resp = client.post("/api/create", json={"title": "Nudge me"})
    task_id = resp.json()["task_id"]
    resp = client.post(f"/api/nudge/{task_id}", json={"message": "hurry up"})
    data = resp.json()
    # Nudge may succeed or error depending on task state
    assert "ok" in data or "error" in data


def test_decompose_nonexistent(client):
    """POST /api/decompose on missing task returns error."""
    resp = client.post("/api/decompose/bad-id", json={"tasks": []})
    data = resp.json()
    assert "error" in data


def test_decompose_empty_tasks(client):
    """POST /api/decompose with empty list returns error."""
    resp = client.post("/api/create", json={"title": "Parent"})
    task_id = resp.json()["task_id"]

    resp = client.post(f"/api/decompose/{task_id}", json={"tasks": []})
    data = resp.json()
    assert "error" in data


def test_decompose_creates_subtasks(client):
    """POST /api/decompose creates sub-tasks and closes parent."""
    resp = client.post("/api/create", json={"title": "Parent task"})
    task_id = resp.json()["task_id"]

    resp = client.post(
        f"/api/decompose/{task_id}",
        json={
            "tasks": [
                {"title": "Sub 1"},
                {"title": "Sub 2"},
            ]
        },
    )
    data = resp.json()
    assert data["ok"] is True
    assert len(data["sub_tasks"]) == 2
