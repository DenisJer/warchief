"""Tests for merge verifier."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from warchief.merge_verifier import verify_merge, get_feature_branch_name, get_merge_status


class TestVerifyMerge:
    @patch("warchief.merge_verifier.subprocess.run")
    def test_merged_returns_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert verify_merge(Path("/project"), "feature/wc-01", "main") is True

    @patch("warchief.merge_verifier.subprocess.run")
    def test_not_merged_returns_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert verify_merge(Path("/project"), "feature/wc-01", "main") is False

    @patch("warchief.merge_verifier.subprocess.run", side_effect=FileNotFoundError)
    def test_git_not_found(self, mock_run):
        assert verify_merge(Path("/project"), "feature/wc-01", "main") is False


class TestGetFeatureBranchName:
    def test_format(self):
        assert get_feature_branch_name("wc-abc123") == "feature/wc-abc123"


class TestGetMergeStatus:
    @patch("warchief.merge_verifier.subprocess.run")
    def test_merged_status(self, mock_run):
        # First call: merge-base --is-ancestor (success)
        # Second call: rev-list (0 0)
        mock_run.side_effect = [
            MagicMock(returncode=0),  # is-ancestor
            MagicMock(returncode=0, stdout="0\t0\n"),  # rev-list
        ]
        status = get_merge_status(Path("/project"), "feature/wc-01", "main")
        assert status["merged"] is True
        assert status["ahead"] == 0
        assert status["behind"] == 0

    @patch("warchief.merge_verifier.subprocess.run")
    def test_not_merged_ahead(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),  # not ancestor
            MagicMock(returncode=0, stdout="2\t5\n"),  # rev-list
            MagicMock(returncode=0, stdout=""),  # merge-tree (no conflicts)
        ]
        status = get_merge_status(Path("/project"), "feature/wc-01", "main")
        assert status["merged"] is False
        assert status["ahead"] == 5
        assert status["behind"] == 2
