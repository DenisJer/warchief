"""Tests for the eval framework."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.runner import (
    EvalResult,
    EvalSuite,
    EvalTestCase,
    format_eval_summary,
    generate_eval_plan,
    grade_response,
    load_test_case,
    load_test_suite,
)


@pytest.fixture
def test_case_dir(tmp_path: Path) -> Path:
    tc_dir = tmp_path / "test_cases"
    tc_dir.mkdir()
    return tc_dir


class TestLoadTestCase:
    def test_load_valid(self, test_case_dir: Path):
        tc_file = test_case_dir / "test1.json"
        tc_file.write_text(json.dumps({
            "id": "tc-01",
            "role": "developer",
            "prompt": "Write a function",
            "expected_actions": ["function", "return"],
            "grading_criteria": ["correct"],
        }))

        tc = load_test_case(tc_file)
        assert tc.id == "tc-01"
        assert tc.role == "developer"
        assert len(tc.expected_actions) == 2

    def test_load_minimal(self, test_case_dir: Path):
        tc_file = test_case_dir / "minimal.json"
        tc_file.write_text(json.dumps({
            "role": "reviewer",
            "prompt": "Review this",
        }))

        tc = load_test_case(tc_file)
        assert tc.id == "minimal"  # defaults to filename stem
        assert tc.expected_actions == []


class TestLoadTestSuite:
    def test_load_suite(self, test_case_dir: Path):
        for i in range(3):
            (test_case_dir / f"tc_{i}.json").write_text(json.dumps({
                "role": "developer",
                "prompt": f"Task {i}",
            }))

        suite = load_test_suite(test_case_dir)
        assert suite.name == "test_cases"
        assert len(suite.test_cases) == 3

    def test_empty_dir(self, tmp_path: Path):
        suite = load_test_suite(tmp_path / "nonexistent")
        assert len(suite.test_cases) == 0

    def test_skips_invalid(self, test_case_dir: Path):
        (test_case_dir / "good.json").write_text(json.dumps({
            "role": "dev", "prompt": "ok",
        }))
        (test_case_dir / "bad.json").write_text("not json")

        suite = load_test_suite(test_case_dir)
        assert len(suite.test_cases) == 1


class TestGenerateEvalPlan:
    def test_plan_generation(self):
        suite = EvalSuite(name="test", test_cases=[
            EvalTestCase(id="tc1", role="developer", prompt="test",
                     expected_actions=[], grading_criteria=[]),
        ])
        plan = generate_eval_plan(suite, models=["model-a", "model-b"])
        assert len(plan) == 2
        assert plan[0]["model"] == "model-a"
        assert plan[1]["model"] == "model-b"

    def test_uses_tc_models(self):
        suite = EvalSuite(name="test", test_cases=[
            EvalTestCase(id="tc1", role="dev", prompt="test",
                     expected_actions=[], grading_criteria=[],
                     models=["specific-model"]),
        ])
        plan = generate_eval_plan(suite, models=["default-model"])
        assert len(plan) == 1
        assert plan[0]["model"] == "specific-model"


class TestGradeResponse:
    def test_full_pass(self):
        result = grade_response(
            "I will create a function that returns a value",
            expected_actions=["function", "return"],
            grading_criteria=["value"],
        )
        assert result.passed is True
        assert result.score == 1.0

    def test_partial_pass(self):
        result = grade_response(
            "I will create a function",
            expected_actions=["function", "return"],
            grading_criteria=["value"],
        )
        assert result.score == pytest.approx(1 / 3)
        assert result.passed is False

    def test_empty_criteria(self):
        result = grade_response("anything", [], [])
        assert result.passed is True
        assert result.score == 1.0

    def test_case_insensitive(self):
        result = grade_response(
            "FUNCTION RETURN",
            expected_actions=["function", "return"],
            grading_criteria=[],
        )
        assert result.passed is True


class TestFormatSummary:
    def test_empty(self):
        assert "No evaluation" in format_eval_summary([])

    def test_with_results(self):
        results = [
            EvalResult("tc1", "model-a", "developer", True, 0.9),
            EvalResult("tc2", "model-a", "developer", False, 0.3),
            EvalResult("tc1", "model-b", "reviewer", True, 1.0),
        ]
        output = format_eval_summary(results)
        assert "model-a" in output
        assert "model-b" in output
        assert "developer" in output
        assert "reviewer" in output


class TestRealTestCases:
    """Test that the actual eval test_cases directory loads correctly."""

    def test_load_bundled_cases(self):
        tc_dir = Path(__file__).parent.parent / "eval" / "test_cases"
        if not tc_dir.exists():
            pytest.skip("No bundled test cases")

        suite = load_test_suite(tc_dir)
        assert len(suite.test_cases) >= 4

        roles = {tc.role for tc in suite.test_cases}
        assert "conductor" in roles
        assert "reviewer" in roles
        assert "security_reviewer" in roles
        assert "integrator" in roles
