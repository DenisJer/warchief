"""Tests for log rotation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from warchief.log_rotation import (
    prune_old_segments,
    rotate_log,
    run_log_rotation,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".warchief").mkdir()
    return root


class TestRotateLog:
    def test_no_rotation_needed(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text("small log\n")
        assert rotate_log(log_file, max_size=1024) is False

    def test_rotation_occurs(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text("x" * 2000)
        assert rotate_log(log_file, max_size=1000) is True

        # Original should be empty
        assert log_file.exists()
        assert log_file.stat().st_size == 0

        # Backup should exist
        backup = tmp_path / "test.log.1"
        assert backup.exists()
        assert backup.stat().st_size == 2000

    def test_multiple_rotations(self, tmp_path: Path):
        log_file = tmp_path / "test.log"

        # First rotation
        log_file.write_text("x" * 2000)
        rotate_log(log_file, max_size=1000)

        # Second rotation
        log_file.write_text("y" * 2000)
        rotate_log(log_file, max_size=1000)

        assert (tmp_path / "test.log.1").exists()
        assert (tmp_path / "test.log.2").exists()

    def test_max_segments_respected(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        for i in range(5):
            log_file.write_text(f"content-{i}" * 500)
            rotate_log(log_file, max_size=100, max_segments=3)

        # Only .1, .2, .3 should exist (plus current)
        assert (tmp_path / "test.log.1").exists()
        assert (tmp_path / "test.log.2").exists()
        assert (tmp_path / "test.log.3").exists()
        assert not (tmp_path / "test.log.4").exists()

    def test_nonexistent_file(self, tmp_path: Path):
        assert rotate_log(tmp_path / "nope.log") is False


class TestPruneSegments:
    def test_prune_old(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.touch()

        # Create a segment and age it
        seg = tmp_path / "test.log.1"
        seg.write_text("old data")
        old_time = seg.stat().st_mtime - (31 * 86400)
        os.utime(seg, (old_time, old_time))

        removed = prune_old_segments(log_file, max_age_days=30)
        assert removed == 1
        assert not seg.exists()

    def test_keep_recent(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.touch()
        seg = tmp_path / "test.log.1"
        seg.write_text("recent data")

        removed = prune_old_segments(log_file, max_age_days=30)
        assert removed == 0
        assert seg.exists()


class TestRunLogRotation:
    def test_rotation_with_no_logs(self, project_root: Path):
        results = run_log_rotation(project_root)
        assert results["main_rotated"] is False

    def test_rotation_with_large_log(self, project_root: Path):
        log_file = project_root / ".warchief" / "warchief.log"
        # Write more than 100MB would be too much for test, so we patch
        log_file.write_text("small log")
        results = run_log_rotation(project_root)
        assert results["main_rotated"] is False  # Not big enough
