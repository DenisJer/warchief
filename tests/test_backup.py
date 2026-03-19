"""Tests for backup and restore."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from warchief.backup import (
    create_backup,
    list_backups,
    prune_old_backups,
    restore_backup,
)
from warchief.models import EventRecord, TaskRecord
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


class TestBackup:
    def test_create_backup(self, project_root: Path, store: TaskStore):
        store.create_task(TaskRecord(id="wc-b1", title="Task 1"))
        store.create_task(TaskRecord(id="wc-b2", title="Task 2"))
        store.log_event(EventRecord(event_type="test", task_id="wc-b1"))

        path = create_backup(project_root, store)
        assert path.exists()
        assert str(path).endswith(".jsonl.gz")

        # Verify content
        with gzip.open(path, "rt") as f:
            lines = f.readlines()
        assert len(lines) >= 3  # 2 tasks + 1 event

    def test_backup_is_valid_jsonl(self, project_root: Path, store: TaskStore):
        store.create_task(TaskRecord(id="wc-v1", title="Valid"))
        path = create_backup(project_root, store)

        with gzip.open(path, "rt") as f:
            for line in f:
                record = json.loads(line)
                assert "_type" in record


class TestRestore:
    def test_restore_from_backup(self, project_root: Path, store: TaskStore):
        store.create_task(TaskRecord(id="wc-r1", title="Restore me"))
        store.log_event(EventRecord(event_type="spawn", task_id="wc-r1"))

        path = create_backup(project_root, store)

        # Create a fresh store
        store.close()
        fresh_db = project_root / ".warchief" / "fresh.db"
        fresh_store = TaskStore(fresh_db)

        counts = restore_backup(project_root, fresh_store, path)
        assert counts["tasks"] >= 1
        assert counts["events"] >= 1

        task = fresh_store.get_task("wc-r1")
        assert task is not None
        assert task.title == "Restore me"
        fresh_store.close()


class TestListBackups:
    def test_no_backups(self, project_root: Path):
        assert list_backups(project_root) == []

    def test_lists_backups(self, project_root: Path, store: TaskStore):
        create_backup(project_root, store)
        backups = list_backups(project_root)
        assert len(backups) == 1


class TestPrune:
    def test_prune_old(self, project_root: Path, store: TaskStore):
        path = create_backup(project_root, store)
        # Manually age the file
        import os

        old_time = path.stat().st_mtime - (31 * 86400)
        os.utime(path, (old_time, old_time))

        removed = prune_old_backups(project_root, retention_days=30)
        assert removed == 1
        assert not path.exists()

    def test_keep_recent(self, project_root: Path, store: TaskStore):
        create_backup(project_root, store)
        removed = prune_old_backups(project_root, retention_days=30)
        assert removed == 0
