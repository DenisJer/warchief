"""Test Runner — executes project test commands at the testing stage.

Auto-detects test frameworks from project files (package.json, pyproject.toml,
Makefile, etc.) or uses explicitly configured commands from config.toml.
Runs tests against the task's feature branch in a temporary worktree.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from warchief.config import Config, FRONTEND_EXTENSIONS

log = logging.getLogger("warchief.test_runner")


@dataclass
class TestResult:
    passed: bool
    test_command_output: str = ""
    e2e_command_output: str = ""
    skipped: bool = False
    skip_reason: str = ""
    duration_seconds: float = 0.0
    commands_run: list[str] = field(default_factory=list)


@dataclass
class DetectedTests:
    """Test commands auto-detected from project files."""
    test_command: str = ""
    e2e_command: str = ""
    source: str = ""  # What file/pattern triggered detection


def detect_test_commands(project_root: Path) -> DetectedTests:
    """Auto-detect test commands from project files.

    Scans for common test framework patterns and returns appropriate commands.
    Checks in priority order — first match wins for each category.
    """
    detected = DetectedTests()

    # --- Unit/integration test detection ---

    # package.json (Node.js projects)
    pkg_json = project_root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                test_script = scripts["test"]
                # Skip if it's the default npm init placeholder
                if test_script and "no test specified" not in test_script:
                    detected.test_command = "npm test"
                    detected.source = "package.json scripts.test"
        except (json.JSONDecodeError, OSError):
            pass

    # pyproject.toml (Python projects)
    if not detected.test_command:
        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                if "pytest" in content or "[tool.pytest" in content:
                    detected.test_command = "pytest"
                    detected.source = "pyproject.toml (pytest)"
            except OSError:
                pass

    # setup.cfg or pytest.ini
    if not detected.test_command:
        for cfg_file in ("setup.cfg", "pytest.ini", "tox.ini"):
            cfg_path = project_root / cfg_file
            if cfg_path.exists():
                try:
                    content = cfg_path.read_text()
                    if "pytest" in content or "testpaths" in content:
                        detected.test_command = "pytest"
                        detected.source = f"{cfg_file} (pytest)"
                        break
                except OSError:
                    pass

    # Makefile with test target
    if not detected.test_command:
        makefile = project_root / "Makefile"
        if makefile.exists():
            try:
                content = makefile.read_text()
                if "\ntest:" in content or "\ntest " in content:
                    detected.test_command = "make test"
                    detected.source = "Makefile test target"
            except OSError:
                pass

    # Go projects
    if not detected.test_command:
        go_mod = project_root / "go.mod"
        if go_mod.exists():
            detected.test_command = "go test ./..."
            detected.source = "go.mod"

    # Cargo (Rust)
    if not detected.test_command:
        cargo = project_root / "Cargo.toml"
        if cargo.exists():
            detected.test_command = "cargo test"
            detected.source = "Cargo.toml"

    # --- E2E test detection ---

    # Playwright
    pw_config_names = [
        "playwright.config.ts", "playwright.config.js",
        "playwright.config.mjs", "playwright.config.cjs",
    ]
    for pw_cfg in pw_config_names:
        if (project_root / pw_cfg).exists():
            detected.e2e_command = "npx playwright test"
            if not detected.source:
                detected.source = pw_cfg
            break

    # Cypress
    if not detected.e2e_command:
        cy_config_names = [
            "cypress.config.ts", "cypress.config.js",
            "cypress.config.mjs", "cypress.config.cjs",
            "cypress.json",
        ]
        for cy_cfg in cy_config_names:
            if (project_root / cy_cfg).exists():
                detected.e2e_command = "npx cypress run"
                if not detected.source:
                    detected.source = cy_cfg
                break

    # Also check package.json for e2e script
    if not detected.e2e_command and pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            if "test:e2e" in scripts:
                detected.e2e_command = "npm run test:e2e"
            elif "e2e" in scripts:
                detected.e2e_command = "npm run e2e"
        except (json.JSONDecodeError, OSError):
            pass

    return detected


def resolve_test_commands(config: Config, project_root: Path) -> tuple[str, str]:
    """Get effective test commands — explicit config takes priority, then auto-detect.

    Returns (test_command, e2e_command).
    """
    tc = config.testing
    test_cmd = tc.test_command
    e2e_cmd = tc.e2e_command

    # Auto-detect if not explicitly configured
    if not test_cmd or not e2e_cmd:
        detected = detect_test_commands(project_root)
        if detected.source:
            log.info("Auto-detected tests from %s", detected.source)
        if not test_cmd and detected.test_command:
            test_cmd = detected.test_command
            log.info("Auto-detected test command: %s", test_cmd)
        if not e2e_cmd and detected.e2e_command:
            e2e_cmd = detected.e2e_command
            log.info("Auto-detected e2e command: %s", e2e_cmd)

    return test_cmd, e2e_cmd


def has_test_commands(config: Config, project_root: Path | None = None) -> bool:
    """Check if any test commands are available (configured or auto-detected)."""
    if config.testing.test_command or config.testing.e2e_command:
        return True
    if project_root:
        detected = detect_test_commands(project_root)
        return bool(detected.test_command or detected.e2e_command)
    return False


def run_tests(
    project_root: Path,
    config: Config,
    branch: str,
    changed_files: list[str] | None = None,
) -> TestResult:
    """Run test commands against a feature branch.

    Creates a temporary worktree for the branch, then:
    1. Auto-detects test frameworks FROM the branch (catches tests the agent wrote)
    2. Explicit config overrides auto-detection
    3. Runs unit tests, then e2e tests if frontend files changed

    Args:
        project_root: Root of the git project.
        config: Warchief config with testing section.
        branch: Feature branch name to check out for testing.
        changed_files: List of changed file paths (for frontend detection).

    Returns:
        TestResult with pass/fail status and output.
    """
    import tempfile
    import shutil

    start = time.time()
    timeout = config.testing.test_timeout
    worktree_dir = None

    try:
        # Create a temporary worktree for the feature branch
        worktree_dir = tempfile.mkdtemp(prefix="warchief-test-")
        add_result = subprocess.run(
            ["git", "worktree", "add", "--detach", worktree_dir, branch],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )
        if add_result.returncode != 0:
            return TestResult(
                passed=False,
                test_command_output=f"Failed to checkout branch {branch}:\n{add_result.stderr}",
                duration_seconds=time.time() - start,
            )

        wt_path = Path(worktree_dir)

        # Detect tests from the BRANCH worktree (catches tests the agent added)
        test_cmd, e2e_cmd = resolve_test_commands(config, wt_path)

        if not test_cmd and not e2e_cmd:
            return TestResult(
                passed=True, skipped=True,
                skip_reason="No test framework detected in project or branch",
                duration_seconds=time.time() - start,
            )

        has_frontend = _has_frontend_changes(changed_files or [])
        result = TestResult(passed=True)

        # Run unit/integration tests (always, if available)
        if test_cmd:
            result.commands_run.append(test_cmd)
            log.info("Running test command: %s (in %s)", test_cmd, worktree_dir)
            test_out = _run_command_in_dir(test_cmd, wt_path, timeout)
            result.test_command_output = test_out.output
            if not test_out.success:
                result.passed = False
                result.duration_seconds = time.time() - start
                return result

        # Run e2e tests only if frontend files changed
        if e2e_cmd and has_frontend:
            result.commands_run.append(e2e_cmd)
            log.info("Running e2e command: %s (frontend files changed)", e2e_cmd)
            e2e_out = _run_command_in_dir(e2e_cmd, wt_path, timeout)
            result.e2e_command_output = e2e_out.output
            if not e2e_out.success:
                result.passed = False
        elif e2e_cmd and not has_frontend:
            log.info("Skipping e2e tests — no frontend files changed")

        result.duration_seconds = time.time() - start
        return result

    except Exception as e:
        return TestResult(
            passed=False,
            test_command_output=f"Error setting up test environment: {e}",
            duration_seconds=time.time() - start,
        )
    finally:
        # Cleanup the temporary worktree
        if worktree_dir:
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", worktree_dir],
                    cwd=project_root, capture_output=True, timeout=15,
                )
            except Exception:
                try:
                    shutil.rmtree(worktree_dir, ignore_errors=True)
                    subprocess.run(
                        ["git", "worktree", "prune"],
                        cwd=project_root, capture_output=True, timeout=10,
                    )
                except Exception:
                    pass


@dataclass
class _CommandResult:
    success: bool
    output: str


def _run_command_in_dir(
    command: str,
    cwd: Path,
    timeout: int,
) -> _CommandResult:
    """Run a test command in a directory."""
    try:
        log.info("Running '%s' in %s", command, cwd)
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = ""
        if proc.stdout:
            output += proc.stdout
        if proc.stderr:
            output += "\n" + proc.stderr if output else proc.stderr

        # Truncate very long output (keep first and last parts)
        if len(output) > 5000:
            output = output[:2000] + "\n\n... (truncated) ...\n\n" + output[-2000:]

        return _CommandResult(
            success=proc.returncode == 0,
            output=output.strip(),
        )

    except subprocess.TimeoutExpired:
        return _CommandResult(
            success=False,
            output=f"Test command timed out after {timeout}s: {command}",
        )
    except Exception as e:
        return _CommandResult(
            success=False,
            output=f"Error running test command: {e}",
        )


def _has_frontend_changes(changed_files: list[str]) -> bool:
    """Check if any changed files are frontend files."""
    for f in changed_files:
        ext = "." + f.rsplit(".", 1)[-1] if "." in f else ""
        if ext.lower() in FRONTEND_EXTENSIONS:
            return True
    return False


def format_test_failure(result: TestResult, task_id: str) -> str:
    """Format a test failure for display in control pane / dashboard."""
    lines = [f"Tests FAILED for task {task_id}"]
    lines.append(f"Duration: {result.duration_seconds:.1f}s")
    lines.append(f"Commands: {', '.join(result.commands_run)}")

    if result.test_command_output:
        lines.append("")
        lines.append("Unit/Integration test output:")
        lines.append(result.test_command_output)

    if result.e2e_command_output:
        lines.append("")
        lines.append("E2E test output:")
        lines.append(result.e2e_command_output)

    return "\n".join(lines)
