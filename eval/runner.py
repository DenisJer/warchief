"""Eval runner — evaluate model performance per role using test cases.

Each test case is a JSON file with:
- role: which role is being tested
- prompt: the prompt to send
- expected_actions: list of expected behaviors (e.g., "updates task status")
- grading_criteria: how to evaluate the response
- models: list of models to test against (default: all configured)

This framework doesn't call the Claude API directly — it generates evaluation
plans that can be run with `claude` CLI or via the API.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalTestCase:
    id: str
    role: str
    prompt: str
    expected_actions: list[str]
    grading_criteria: list[str]
    models: list[str] = field(default_factory=list)
    context: str = ""


@dataclass
class EvalResult:
    test_case_id: str
    model: str
    role: str
    passed: bool
    score: float  # 0.0 - 1.0
    details: dict = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class EvalSuite:
    name: str
    test_cases: list[EvalTestCase] = field(default_factory=list)
    results: list[EvalResult] = field(default_factory=list)


def load_test_case(path: Path) -> EvalTestCase:
    """Load a single test case from JSON."""
    data = json.loads(path.read_text())
    return EvalTestCase(
        id=data.get("id", path.stem),
        role=data["role"],
        prompt=data["prompt"],
        expected_actions=data.get("expected_actions", []),
        grading_criteria=data.get("grading_criteria", []),
        models=data.get("models", []),
        context=data.get("context", ""),
    )


def load_test_suite(test_dir: Path) -> EvalSuite:
    """Load all test cases from a directory."""
    suite = EvalSuite(name=test_dir.name)
    if not test_dir.exists():
        return suite

    for f in sorted(test_dir.glob("*.json")):
        try:
            tc = load_test_case(f)
            suite.test_cases.append(tc)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Skipping {f.name}: {e}")
    return suite


DEFAULT_MODELS = [
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
    "claude-haiku-4-5-20251001",
]


def generate_eval_plan(suite: EvalSuite, models: list[str] | None = None) -> list[dict]:
    """Generate an evaluation plan — list of (test_case, model) pairs to run.

    Returns a list of dicts with all info needed to execute each eval.
    """
    target_models = models or DEFAULT_MODELS
    plan: list[dict] = []

    for tc in suite.test_cases:
        tc_models = tc.models if tc.models else target_models
        for model in tc_models:
            plan.append({
                "test_case_id": tc.id,
                "role": tc.role,
                "model": model,
                "prompt": tc.prompt,
                "context": tc.context,
                "expected_actions": tc.expected_actions,
                "grading_criteria": tc.grading_criteria,
            })

    return plan


def grade_response(
    response: str,
    expected_actions: list[str],
    grading_criteria: list[str],
) -> EvalResult:
    """Simple keyword-based grading of a model response.

    For production use, this should be replaced with LLM-as-judge.
    """
    checks_passed = 0
    total_checks = len(expected_actions) + len(grading_criteria)

    if total_checks == 0:
        return EvalResult(
            test_case_id="", model="", role="",
            passed=True, score=1.0, timestamp=time.time(),
        )

    details: dict = {"action_results": {}, "criteria_results": {}}

    for action in expected_actions:
        found = action.lower() in response.lower()
        details["action_results"][action] = found
        if found:
            checks_passed += 1

    for criterion in grading_criteria:
        found = criterion.lower() in response.lower()
        details["criteria_results"][criterion] = found
        if found:
            checks_passed += 1

    score = checks_passed / total_checks
    return EvalResult(
        test_case_id="", model="", role="",
        passed=score >= 0.5, score=score,
        details=details, timestamp=time.time(),
    )


def format_eval_summary(results: list[EvalResult]) -> str:
    """Format evaluation results as a summary table."""
    if not results:
        return "No evaluation results."

    lines: list[str] = []
    lines.append("Evaluation Summary")
    lines.append("=" * 60)

    # Group by model
    by_model: dict[str, list[EvalResult]] = {}
    for r in results:
        by_model.setdefault(r.model, []).append(r)

    for model, model_results in sorted(by_model.items()):
        passed = sum(1 for r in model_results if r.passed)
        total = len(model_results)
        avg_score = sum(r.score for r in model_results) / total if total else 0
        lines.append(f"\n  {model}")
        lines.append(f"    Passed: {passed}/{total}  Avg score: {avg_score:.2f}")

        # Group by role within model
        by_role: dict[str, list[EvalResult]] = {}
        for r in model_results:
            by_role.setdefault(r.role, []).append(r)

        for role, role_results in sorted(by_role.items()):
            r_passed = sum(1 for r in role_results if r.passed)
            r_total = len(role_results)
            r_avg = sum(r.score for r in role_results) / r_total if r_total else 0
            lines.append(f"      {role}: {r_passed}/{r_total} (avg {r_avg:.2f})")

    return "\n".join(lines)
