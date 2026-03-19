"""Tests for the test runner module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from warchief.config import Config, TestingConfig
from warchief.test_runner import (
    has_test_commands,
    detect_test_commands,
    resolve_test_commands,
    _has_frontend_changes,
    format_test_failure,
    TestResult,
)


class TestHasTestCommands:
    def test_no_commands_no_project(self):
        config = Config()
        assert has_test_commands(config) is False

    def test_test_command_only(self):
        config = Config(testing=TestingConfig(test_command="pytest"))
        assert has_test_commands(config) is True

    def test_e2e_command_only(self):
        config = Config(testing=TestingConfig(e2e_command="npx playwright test"))
        assert has_test_commands(config) is True

    def test_both_commands(self):
        config = Config(
            testing=TestingConfig(
                test_command="pytest",
                e2e_command="npx playwright test",
            )
        )
        assert has_test_commands(config) is True

    def test_auto_detect_from_project(self, tmp_path):
        """No config, but project has package.json with test script."""
        pkg = {"scripts": {"test": "jest"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        config = Config()
        assert has_test_commands(config, tmp_path) is True

    def test_no_detect_empty_project(self, tmp_path):
        config = Config()
        assert has_test_commands(config, tmp_path) is False


class TestDetectTestCommands:
    def test_empty_project(self, tmp_path):
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == ""
        assert detected.e2e_command == ""

    def test_package_json_with_test(self, tmp_path):
        pkg = {"scripts": {"test": "jest --coverage"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "npm test"
        assert "package.json" in detected.source

    def test_package_json_no_test_specified(self, tmp_path):
        """npm init placeholder should be ignored."""
        pkg = {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == ""

    def test_pyproject_with_pytest(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']")
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "pytest"
        assert "pyproject.toml" in detected.source

    def test_makefile_with_test(self, tmp_path):
        (tmp_path / "Makefile").write_text("build:\n\tgo build\n\ntest:\n\tgo test ./...")
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "make test"
        assert "Makefile" in detected.source

    def test_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/foo\ngo 1.21")
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "go test ./..."
        assert "go.mod" in detected.source

    def test_cargo_toml(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "foo"')
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "cargo test"
        assert "Cargo.toml" in detected.source

    def test_playwright_config(self, tmp_path):
        (tmp_path / "playwright.config.ts").write_text("export default {}")
        detected = detect_test_commands(tmp_path)
        assert detected.e2e_command == "npx playwright test"

    def test_cypress_config(self, tmp_path):
        (tmp_path / "cypress.config.ts").write_text("export default {}")
        detected = detect_test_commands(tmp_path)
        assert detected.e2e_command == "npx cypress run"

    def test_package_json_e2e_script(self, tmp_path):
        pkg = {"scripts": {"test": "jest", "test:e2e": "playwright test"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "npm test"
        assert detected.e2e_command == "npm run test:e2e"

    def test_package_json_e2e_fallback(self, tmp_path):
        pkg = {"scripts": {"test": "jest", "e2e": "cypress run"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detected = detect_test_commands(tmp_path)
        assert detected.e2e_command == "npm run e2e"

    def test_priority_package_json_over_makefile(self, tmp_path):
        """package.json should win over Makefile."""
        pkg = {"scripts": {"test": "jest"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "Makefile").write_text("test:\n\techo test")
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "npm test"

    def test_playwright_config_js(self, tmp_path):
        (tmp_path / "playwright.config.js").write_text("module.exports = {}")
        detected = detect_test_commands(tmp_path)
        assert detected.e2e_command == "npx playwright test"

    def test_setup_cfg_pytest(self, tmp_path):
        (tmp_path / "setup.cfg").write_text("[tool:pytest]\ntestpaths = tests")
        detected = detect_test_commands(tmp_path)
        assert detected.test_command == "pytest"

    def test_cypress_json_legacy(self, tmp_path):
        (tmp_path / "cypress.json").write_text("{}")
        detected = detect_test_commands(tmp_path)
        assert detected.e2e_command == "npx cypress run"


class TestResolveTestCommands:
    def test_explicit_config_wins(self, tmp_path):
        """Explicit config should override auto-detection."""
        pkg = {"scripts": {"test": "jest"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        config = Config(testing=TestingConfig(test_command="custom-test"))
        test_cmd, e2e_cmd = resolve_test_commands(config, tmp_path)
        assert test_cmd == "custom-test"

    def test_auto_detect_fills_gaps(self, tmp_path):
        """If only test_command is configured, auto-detect e2e."""
        (tmp_path / "playwright.config.ts").write_text("export default {}")
        config = Config(testing=TestingConfig(test_command="pytest"))
        test_cmd, e2e_cmd = resolve_test_commands(config, tmp_path)
        assert test_cmd == "pytest"
        assert e2e_cmd == "npx playwright test"

    def test_fully_auto_detected(self, tmp_path):
        pkg = {"scripts": {"test": "vitest"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "playwright.config.ts").write_text("export default {}")
        config = Config()
        test_cmd, e2e_cmd = resolve_test_commands(config, tmp_path)
        assert test_cmd == "npm test"
        assert e2e_cmd == "npx playwright test"


class TestHasFrontendChanges:
    def test_no_files(self):
        assert _has_frontend_changes([]) is False

    def test_python_only(self):
        assert _has_frontend_changes(["main.py", "utils.py"]) is False

    def test_tsx_file(self):
        assert _has_frontend_changes(["src/App.tsx"]) is True

    def test_css_file(self):
        assert _has_frontend_changes(["styles/main.css"]) is True

    def test_vue_file(self):
        assert _has_frontend_changes(["components/Foo.vue"]) is True

    def test_mixed(self):
        assert _has_frontend_changes(["server.py", "index.html"]) is True

    def test_svelte_file(self):
        assert _has_frontend_changes(["App.svelte"]) is True


class TestFormatTestFailure:
    def test_basic_format(self):
        result = TestResult(
            passed=False,
            test_command_output="FAILED test_foo.py::test_bar",
            commands_run=["pytest"],
            duration_seconds=5.2,
        )
        output = format_test_failure(result, "wc-123")
        assert "Tests FAILED" in output
        assert "wc-123" in output
        assert "pytest" in output
        assert "FAILED test_foo.py" in output

    def test_e2e_output(self):
        result = TestResult(
            passed=False,
            e2e_command_output="Error: page.click failed",
            commands_run=["npx playwright test"],
            duration_seconds=12.0,
        )
        output = format_test_failure(result, "wc-456")
        assert "E2E test output" in output
        assert "page.click failed" in output
