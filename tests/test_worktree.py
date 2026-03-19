"""Tests for worktree management (unit-level, mocking git commands)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.worktree import (
    _worktrees_root,
    list_worktrees,
    _symlink_warchief_dir,
)


class TestWorktreeHelpers:
    def test_worktrees_root(self, tmp_path: Path):
        root = _worktrees_root(tmp_path)
        assert root == tmp_path / ".warchief-worktrees"

    def test_list_worktrees_empty(self, tmp_path: Path):
        assert list_worktrees(tmp_path) == []

    def test_list_worktrees_with_dirs(self, tmp_path: Path):
        wt_root = tmp_path / ".warchief-worktrees"
        wt_root.mkdir()
        (wt_root / "developer-thrall").mkdir()
        (wt_root / "reviewer-jaina").mkdir()

        result = list_worktrees(tmp_path)
        assert sorted(result) == ["developer-thrall", "reviewer-jaina"]

    def test_symlink_creation(self, tmp_path: Path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".warchief").mkdir()

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        _symlink_warchief_dir(project_root, wt_path)
        assert (wt_path / ".warchief").is_symlink()
        assert (wt_path / ".warchief").resolve() == (project_root / ".warchief").resolve()

    def test_symlink_idempotent(self, tmp_path: Path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".warchief").mkdir()

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        _symlink_warchief_dir(project_root, wt_path)
        _symlink_warchief_dir(project_root, wt_path)  # Should not raise
        assert (wt_path / ".warchief").is_symlink()
