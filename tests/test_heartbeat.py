"""Tests for the heartbeat system."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from warchief.heartbeat import (
    cleanup_heartbeat,
    is_zombie,
    list_heartbeats,
    read_heartbeat,
    write_heartbeat,
)


class TestHeartbeat:
    def test_write_and_read(self, tmp_path: Path):
        write_heartbeat(tmp_path, "dev-thrall")
        ts = read_heartbeat(tmp_path, "dev-thrall")
        assert ts is not None
        assert abs(ts - time.time()) < 2

    def test_read_nonexistent(self, tmp_path: Path):
        assert read_heartbeat(tmp_path, "dev-nobody") is None

    def test_is_zombie_fresh(self, tmp_path: Path):
        write_heartbeat(tmp_path, "dev-thrall")
        assert is_zombie(tmp_path, "dev-thrall", threshold=120) is False

    def test_is_zombie_stale(self, tmp_path: Path):
        hb_dir = tmp_path / ".warchief" / "heartbeats"
        hb_dir.mkdir(parents=True)
        # Write a timestamp 300 seconds ago
        (hb_dir / "dev-stale").write_text(str(time.time() - 300))
        assert is_zombie(tmp_path, "dev-stale", threshold=120) is True

    def test_is_zombie_no_heartbeat(self, tmp_path: Path):
        # No heartbeat file = not a zombie (hasn't started yet)
        assert is_zombie(tmp_path, "dev-new", threshold=120) is False

    def test_cleanup(self, tmp_path: Path):
        write_heartbeat(tmp_path, "dev-dead")
        cleanup_heartbeat(tmp_path, "dev-dead")
        assert read_heartbeat(tmp_path, "dev-dead") is None

    def test_cleanup_nonexistent(self, tmp_path: Path):
        # Should not raise
        cleanup_heartbeat(tmp_path, "dev-ghost")

    def test_list_heartbeats(self, tmp_path: Path):
        write_heartbeat(tmp_path, "dev-a")
        write_heartbeat(tmp_path, "dev-b")
        hbs = list_heartbeats(tmp_path)
        assert "dev-a" in hbs
        assert "dev-b" in hbs
        assert len(hbs) == 2

    def test_list_heartbeats_empty(self, tmp_path: Path):
        assert list_heartbeats(tmp_path) == {}
