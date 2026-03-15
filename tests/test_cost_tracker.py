"""Tests for cost tracking."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from warchief.cost_tracker import (
    CostEntry,
    CostSummary,
    TokenUsage,
    append_cost_entry,
    check_budget,
    compute_cost_summary,
    estimate_cost,
    format_cost_summary,
    load_cost_log,
    parse_claude_output,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".warchief").mkdir()
    return root


class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0


class TestEstimateCost:
    def test_opus_cost(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = estimate_cost(usage, "claude-opus-4-20250514")
        assert cost == pytest.approx(15.0 + 75.0)

    def test_sonnet_cost(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = estimate_cost(usage, "claude-sonnet-4-20250514")
        assert cost == pytest.approx(3.0 + 15.0)

    def test_haiku_cost(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = estimate_cost(usage, "claude-haiku-4-5-20251001")
        assert cost == pytest.approx(0.80 + 4.0)

    def test_unknown_model_uses_default(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
        cost = estimate_cost(usage, "unknown-model")
        assert cost == pytest.approx(3.0)  # default input rate

    def test_zero_tokens(self):
        assert estimate_cost(TokenUsage(), "claude-opus-4-20250514") == 0.0


class TestParseClaudeOutput:
    def test_basic_parsing(self):
        output = """
        Some output text
        Input tokens: 1,234
        Output tokens: 567
        """
        usage = parse_claude_output(output)
        assert usage is not None
        assert usage.input_tokens == 1234
        assert usage.output_tokens == 567

    def test_with_cache(self):
        output = """
        Input tokens: 500
        Output tokens: 200
        Cache read tokens: 100
        Cache write tokens: 50
        """
        usage = parse_claude_output(output)
        assert usage is not None
        assert usage.cache_read_tokens == 100
        assert usage.cache_write_tokens == 50

    def test_no_tokens(self):
        assert parse_claude_output("just some text") is None

    def test_case_insensitive(self):
        output = "input Tokens: 100\noutput Tokens: 50"
        usage = parse_claude_output(output)
        assert usage is not None
        assert usage.input_tokens == 100


class TestCostLog:
    def test_empty_log(self, project_root: Path):
        assert load_cost_log(project_root) == []

    def test_append_and_load(self, project_root: Path):
        entry = CostEntry(
            agent_id="dev-thrall", task_id="wc-01",
            role="developer", model="claude-sonnet-4-20250514",
            usage=TokenUsage(input_tokens=1000, output_tokens=500),
            cost_usd=0.0105,
        )
        append_cost_entry(project_root, entry)
        entries = load_cost_log(project_root)
        assert len(entries) == 1
        assert entries[0].agent_id == "dev-thrall"
        assert entries[0].usage.input_tokens == 1000

    def test_multiple_entries(self, project_root: Path):
        for i in range(3):
            append_cost_entry(project_root, CostEntry(
                agent_id=f"dev-{i}", task_id=f"wc-{i}",
                role="developer", model="claude-sonnet-4-20250514",
                usage=TokenUsage(input_tokens=1000),
                cost_usd=0.003,
            ))
        entries = load_cost_log(project_root)
        assert len(entries) == 3


class TestCostSummary:
    def test_empty_summary(self, project_root: Path):
        summary = compute_cost_summary(project_root)
        assert summary.total_cost_usd == 0.0
        assert summary.entries == []

    def test_summary_computation(self, project_root: Path):
        append_cost_entry(project_root, CostEntry(
            agent_id="dev-a", task_id="wc-01",
            role="developer", model="claude-sonnet-4-20250514",
            usage=TokenUsage(input_tokens=1000, output_tokens=500),
            cost_usd=0.01,
        ))
        append_cost_entry(project_root, CostEntry(
            agent_id="rev-b", task_id="wc-01",
            role="reviewer", model="claude-sonnet-4-20250514",
            usage=TokenUsage(input_tokens=2000, output_tokens=800),
            cost_usd=0.02,
        ))

        summary = compute_cost_summary(project_root)
        assert summary.total_cost_usd == pytest.approx(0.03)
        assert summary.total_input_tokens == 3000
        assert summary.total_output_tokens == 1300
        assert "developer" in summary.by_role
        assert "reviewer" in summary.by_role
        assert "wc-01" in summary.by_task


class TestFormatCostSummary:
    def test_empty(self):
        summary = CostSummary()
        output = format_cost_summary(summary)
        assert "No cost data" in output

    def test_with_data(self):
        summary = CostSummary(
            total_cost_usd=1.50,
            total_input_tokens=100000,
            total_output_tokens=50000,
            by_model={"sonnet": 1.0, "haiku": 0.5},
            by_role={"developer": 1.0, "reviewer": 0.5},
            entries=[CostEntry("a", "t", "developer", "sonnet",
                              TokenUsage(), 1.5)],
        )
        output = format_cost_summary(summary)
        assert "100,000" in output  # in tokens
        assert "50,000" in output   # out tokens
        assert "developer" in output


class TestBudget:
    def test_within_budget(self, project_root: Path):
        within, remaining = check_budget(project_root, 10.0)
        assert within is True
        assert remaining == 10.0

    def test_over_budget(self, project_root: Path):
        append_cost_entry(project_root, CostEntry(
            agent_id="a", task_id="t", role="dev", model="m",
            usage=TokenUsage(), cost_usd=15.0,
        ))
        within, remaining = check_budget(project_root, 10.0)
        assert within is False
        assert remaining == -5.0
