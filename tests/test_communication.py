"""Tests for the communication layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from warchief.communication import (
    cleanup_nudges,
    read_nudges,
    send_mail,
    send_nudge,
    get_unread_mail,
    mark_mail_read,
    MAIL_TYPES,
)
from warchief.models import MessageRecord
from warchief.task_store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


class TestNudge:
    def test_send_and_read(self, tmp_path: Path):
        send_nudge(tmp_path, "dev-thrall", "you have mail")
        messages = read_nudges(tmp_path, "dev-thrall")
        assert len(messages) == 1
        assert messages[0] == "you have mail"

    def test_read_consumes(self, tmp_path: Path):
        send_nudge(tmp_path, "dev-thrall", "message 1")
        send_nudge(tmp_path, "dev-thrall", "message 2")
        messages = read_nudges(tmp_path, "dev-thrall")
        assert len(messages) == 2
        # Second read should be empty
        messages2 = read_nudges(tmp_path, "dev-thrall")
        assert len(messages2) == 0

    def test_read_empty(self, tmp_path: Path):
        messages = read_nudges(tmp_path, "dev-nobody")
        assert messages == []

    def test_cleanup(self, tmp_path: Path):
        send_nudge(tmp_path, "dev-thrall", "msg")
        cleanup_nudges(tmp_path, "dev-thrall")
        messages = read_nudges(tmp_path, "dev-thrall")
        assert messages == []

    def test_cleanup_nonexistent(self, tmp_path: Path):
        cleanup_nudges(tmp_path, "dev-ghost")  # Should not raise

    def test_send_with_pid_no_process(self, tmp_path: Path):
        result = send_nudge(tmp_path, "dev-thrall", "msg", agent_pid=99999999)
        assert result is False  # PID doesn't exist


class TestMail:
    def test_send_and_receive(self, store: TaskStore):
        send_mail(store, "dev-thrall", "Fix the bug", "DONE", from_agent="conductor")
        mail = get_unread_mail(store, "dev-thrall")
        assert len(mail) == 1
        assert mail[0].body == "Fix the bug"
        assert mail[0].message_type == "DONE"

    def test_mark_read(self, store: TaskStore):
        send_mail(store, "dev-thrall", "Deploy it", "BLOCKED")
        mail = get_unread_mail(store, "dev-thrall")
        assert len(mail) == 1
        mark_mail_read(store, mail[0].id)
        mail2 = get_unread_mail(store, "dev-thrall")
        assert len(mail2) == 0

    def test_invalid_type_rejected(self, store: TaskStore):
        send_mail(store, "dev-thrall", "chat", "CHAT")
        # Should not create the message
        mail = get_unread_mail(store, "dev-thrall")
        assert len(mail) == 0

    def test_all_valid_types(self, store: TaskStore):
        for i, mtype in enumerate(MAIL_TYPES):
            send_mail(store, f"agent-{i}", f"msg-{i}", mtype)

        for i, mtype in enumerate(MAIL_TYPES):
            mail = get_unread_mail(store, f"agent-{i}")
            assert len(mail) == 1
            assert mail[0].message_type == mtype
