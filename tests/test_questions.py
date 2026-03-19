"""Tests for the human-in-the-loop Q&A mechanism."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from warchief.config import Config, SPECIAL_LABELS
from warchief.models import AgentRecord, EventRecord, MessageRecord, TaskRecord
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


class TestQuestionLabel:
    def test_question_in_special_labels(self):
        assert "question" in SPECIAL_LABELS


class TestAgentUpdateQuestion:
    """Test --question flag on agent-update command."""

    def test_question_stores_message_and_label(self, store, project_root):
        """Simulate what cmd_agent_update does when --question is passed."""
        task = TaskRecord(
            id="wc-q01",
            title="Create supabase schema",
            status="in_progress",
            stage="development",
        )
        store.create_task(task)

        # Simulate agent-update --question behavior
        task = store.get_task("wc-q01")
        updates = {"status": "blocked"}
        current_labels = list(task.labels)
        if "question" not in current_labels:
            current_labels.append("question")
        updates["labels"] = current_labels

        store.create_message(
            MessageRecord(
                id="",
                from_agent="wc-q01",
                to_agent="user",
                message_type="question",
                body="How should I handle supabase schema?",
                persistent=True,
            )
        )
        store.log_event(
            EventRecord(
                event_type="question",
                task_id="wc-q01",
                details={"question": "How should I handle supabase schema?"},
                actor="wc-q01",
            )
        )
        store.update_task("wc-q01", **updates)

        # Verify
        task = store.get_task("wc-q01")
        assert task.status == "blocked"
        assert "question" in task.labels

        messages = store.get_task_messages("wc-q01")
        assert len(messages) == 1
        assert messages[0].message_type == "question"
        assert messages[0].body == "How should I handle supabase schema?"
        assert messages[0].from_agent == "wc-q01"
        assert messages[0].to_agent == "user"


class TestAnswerCommand:
    """Test the answer command behavior."""

    def test_answer_removes_label_and_unblocks(self, store):
        task = TaskRecord(
            id="wc-a01",
            title="Test task",
            status="blocked",
            stage="development",
            labels=["stage:development", "question"],
        )
        store.create_task(task)

        # Store a question first
        store.create_message(
            MessageRecord(
                id="",
                from_agent="wc-a01",
                to_agent="user",
                message_type="question",
                body="How to proceed?",
                persistent=True,
            )
        )

        # Simulate answer command
        store.create_message(
            MessageRecord(
                id="",
                from_agent="user",
                to_agent="wc-a01",
                message_type="answer",
                body="Use supabase CLI",
                persistent=True,
            )
        )
        new_labels = [l for l in task.labels if l != "question"]
        store.update_task("wc-a01", status="open", labels=new_labels)
        store.log_event(
            EventRecord(
                event_type="answer",
                task_id="wc-a01",
                details={"answer": "Use supabase CLI"},
                actor="user",
            )
        )

        # Verify
        task = store.get_task("wc-a01")
        assert task.status == "open"
        assert "question" not in task.labels

        messages = store.get_task_messages("wc-a01")
        assert len(messages) == 2
        assert messages[0].message_type == "question"
        assert messages[1].message_type == "answer"
        assert messages[1].body == "Use supabase CLI"


class TestGetTaskMessages:
    """Test the get_task_messages store method."""

    def test_returns_empty_for_no_messages(self, store):
        store.create_task(TaskRecord(id="wc-m01", title="Test"))
        messages = store.get_task_messages("wc-m01")
        assert messages == []

    def test_returns_questions_and_answers_in_order(self, store):
        store.create_task(TaskRecord(id="wc-m02", title="Test"))

        # Question
        store.create_message(
            MessageRecord(
                id="",
                from_agent="wc-m02",
                to_agent="user",
                message_type="question",
                body="Q1",
                persistent=True,
                created_at=100.0,
            )
        )
        # Answer
        store.create_message(
            MessageRecord(
                id="",
                from_agent="user",
                to_agent="wc-m02",
                message_type="answer",
                body="A1",
                persistent=True,
                created_at=200.0,
            )
        )
        # Second question
        store.create_message(
            MessageRecord(
                id="",
                from_agent="wc-m02",
                to_agent="user",
                message_type="question",
                body="Q2",
                persistent=True,
                created_at=300.0,
            )
        )

        messages = store.get_task_messages("wc-m02")
        assert len(messages) == 3
        assert messages[0].body == "Q1"
        assert messages[1].body == "A1"
        assert messages[2].body == "Q2"


class TestPrimeContextQA:
    """Test that prime context includes Q&A history."""

    def test_includes_qa_history(self, store, project_root):
        task = TaskRecord(
            id="wc-p01",
            title="Build schema",
            status="open",
            stage="development",
            spawn_count=1,
        )
        store.create_task(task)

        store.create_message(
            MessageRecord(
                id="",
                from_agent="wc-p01",
                to_agent="user",
                message_type="question",
                body="How to handle schema?",
                persistent=True,
            )
        )
        store.create_message(
            MessageRecord(
                id="",
                from_agent="user",
                to_agent="wc-p01",
                message_type="answer",
                body="Use supabase CLI",
                persistent=True,
            )
        )

        ctx = build_prime_context(task, "developer", store, project_root)
        assert "## Messages from User" in ctx
        assert "Q: How to handle schema?" in ctx
        assert "A: Use supabase CLI" in ctx

    def test_no_qa_section_when_no_messages(self, store, project_root):
        task = TaskRecord(
            id="wc-p02",
            title="No questions",
            status="open",
            stage="development",
        )
        store.create_task(task)

        ctx = build_prime_context(task, "developer", store, project_root)
        assert "Q&A with User" not in ctx


class TestAutoRecoverySkipsQuestions:
    """Test that watcher auto-recovery skips tasks with question label."""

    def test_plan_recovery_returns_none_for_question(self, watcher, store):
        task = TaskRecord(
            id="wc-qr1",
            title="Question task",
            status="blocked",
            stage="development",
            labels=["stage:development", "question"],
        )
        result = watcher._plan_recovery(task, "Some failure reason")
        assert result is None

    def test_auto_recover_skips_question_tasks(self, watcher, store):
        store.create_task(
            TaskRecord(
                id="wc-qr2",
                title="Question blocked",
                status="blocked",
                stage="development",
                labels=["stage:development", "question"],
            )
        )
        store.log_event(
            EventRecord(
                event_type="block",
                task_id="wc-qr2",
                details={"failure_reason": "Spawn limit reached (20/20)"},
                actor="watcher",
            )
        )

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-qr2")
        assert task.status == "blocked"  # Should NOT be auto-recovered
        assert "question" in task.labels

    def test_auto_recover_works_for_non_question_tasks(self, watcher, store):
        """Ensure normal blocked tasks are still auto-recovered."""
        store.create_task(
            TaskRecord(
                id="wc-qr3",
                title="Normal blocked",
                status="blocked",
                stage="development",
                labels=["stage:development"],
                spawn_count=20,
            )
        )
        store.log_event(
            EventRecord(
                event_type="block",
                task_id="wc-qr3",
                details={"failure_reason": "Spawn limit reached (20/20)"},
                actor="watcher",
            )
        )

        watcher._tick_count = 6
        watcher._auto_recover_blocked()

        task = store.get_task("wc-qr3")
        assert task.status == "open"  # Should be recovered


class TestDashboardQuestions:
    """Test that dashboard shows pending questions."""

    def test_plain_dashboard_shows_questions(self, store, project_root):
        from warchief.dashboard import _build_plain_snapshot

        store.create_task(
            TaskRecord(
                id="wc-dq1",
                title="Schema task",
                status="blocked",
                stage="development",
                labels=["stage:development", "question"],
            )
        )
        store.create_message(
            MessageRecord(
                id="",
                from_agent="wc-dq1",
                to_agent="user",
                message_type="question",
                body="How to create schema?",
                persistent=True,
            )
        )

        output = _build_plain_snapshot(store, project_root)
        assert "QUESTIONS" in output
        assert "wc-dq1" in output
        assert "How to create schema?" in output

    def test_plain_dashboard_no_questions_section_when_empty(self, store, project_root):
        from warchief.dashboard import _build_plain_snapshot

        store.create_task(
            TaskRecord(
                id="wc-dq2",
                title="Normal task",
                status="open",
                stage="development",
            )
        )

        output = _build_plain_snapshot(store, project_root)
        assert "QUESTIONS" not in output


class TestSpawnerQuestionInstructions:
    """Test that spawner includes question instructions in prompts."""

    def test_task_prompt_includes_question_instructions(self):
        from warchief.spawner import build_claude_command
        from warchief.roles import RoleRegistry

        registry = RoleRegistry(Path(__file__).parent.parent / "warchief" / "roles")
        task = TaskRecord(
            id="wc-sp1",
            title="Test task",
            status="open",
            stage="development",
        )
        config = Config(base_branch="main")
        project_root = Path("/tmp/fake-project")

        cmd, cwd, prompt = build_claude_command(
            "developer",
            registry,
            task,
            None,
            project_root,
            config,
        )
        assert "Asking Questions" in prompt
        assert '--question "Your question here"' in prompt
        assert "EXIT immediately" in prompt


class TestQuestionsCommand:
    """Test the questions list command."""

    def test_lists_pending_questions(self, store):
        store.create_task(
            TaskRecord(
                id="wc-lq1",
                title="Question task",
                status="blocked",
                labels=["question"],
            )
        )
        store.create_message(
            MessageRecord(
                id="",
                from_agent="wc-lq1",
                to_agent="user",
                message_type="question",
                body="What DB to use?",
                persistent=True,
            )
        )

        tasks = store.list_tasks(has_label="question")
        assert len(tasks) == 1
        assert tasks[0].id == "wc-lq1"

        messages = store.get_task_messages("wc-lq1")
        questions = [m for m in messages if m.message_type == "question"]
        assert len(questions) == 1
        assert questions[0].body == "What DB to use?"
