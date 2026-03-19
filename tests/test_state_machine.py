"""Tests for the pure-function state machine."""

from __future__ import annotations

import pytest

from warchief.state_machine import (
    dispatch_transition,
    get_next_stage,
    verify_single_stage,
)


# ── get_next_stage ──────────────────────────────────────────────


class TestGetNextStage:
    def test_development_to_testing(self):
        # Testing before reviewing in new pipeline order
        assert get_next_stage("development", []) == "testing"

    def test_testing_to_reviewing(self):
        assert get_next_stage("testing", []) == "reviewing"

    def test_reviewing_to_pr_creation_no_security(self):
        assert get_next_stage("reviewing", []) == "pr-creation"

    def test_reviewing_to_security_with_label(self):
        assert get_next_stage("reviewing", ["security"]) == "security-review"

    def test_security_review_to_pr_creation(self):
        assert get_next_stage("security-review", ["security"]) == "pr-creation"

    def test_pr_creation_is_terminal(self):
        assert get_next_stage("pr-creation", []) is None

    def test_unknown_stage(self):
        assert get_next_stage("nonexistent", []) is None

    def test_bug_skips_planning(self):
        assert get_next_stage("development", [], task_type="bug") == "testing"

    def test_feature_starts_with_planning(self):
        from warchief.state_machine import get_first_stage

        assert get_first_stage("feature") == "planning"
        assert get_first_stage("bug") == "development"
        assert get_first_stage("investigation") == "investigation"


# ── verify_single_stage ─────────────────────────────────────────


class TestVerifySingleStage:
    def test_no_stage_labels(self):
        labels = ["frontend", "security"]
        assert verify_single_stage(labels) == labels

    def test_single_stage_label(self):
        labels = ["stage:development", "frontend"]
        assert verify_single_stage(labels) == labels

    def test_multiple_stage_labels_keeps_first(self):
        labels = ["stage:development", "frontend", "stage:reviewing"]
        result = verify_single_stage(labels)
        assert result == ["stage:development", "frontend"]

    def test_all_stage_labels(self):
        labels = ["stage:development", "stage:reviewing", "stage:pr-creation"]
        result = verify_single_stage(labels)
        assert result == ["stage:development"]


# ── dispatch_transition: spawn limit ────────────────────────────


class TestSpawnLimit:
    def test_spawn_limit_blocks(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            spawn_count=20,
            max_spawns=20,
        )
        assert r.status == "blocked"
        assert "Spawn limit" in r.failure_reason
        assert r.requires_conductor is True

    def test_under_spawn_limit_proceeds(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            spawn_count=19,
            max_spawns=20,
            branch_has_commits=True,
        )
        assert r.status != "blocked"


# ── dispatch_transition: agent crashes ──────────────────────────


class TestAgentCrash:
    def test_crash_resets_to_open(self):
        r = dispatch_transition(
            task_status="in_progress",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            agent_exit_code=1,
            crash_count=0,
        )
        assert r.status == "open"

    def test_crash_none_exit_code(self):
        r = dispatch_transition(
            task_status="in_progress",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            agent_exit_code=None,
            crash_count=0,
        )
        assert r.status == "open"

    def test_crash_limit_blocks(self):
        r = dispatch_transition(
            task_status="in_progress",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            agent_exit_code=1,
            crash_count=3,
            max_crashes=3,
        )
        assert r.status == "blocked"
        assert "Crashed" in r.failure_reason
        assert r.requires_conductor is True

    def test_in_progress_no_crash_resets(self):
        r = dispatch_transition(
            task_status="in_progress",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            agent_exit_code=0,
        )
        assert r.status == "open"


# ── dispatch_transition: blocked ────────────────────────────────


class TestBlocked:
    def test_agent_sets_blocked(self):
        r = dispatch_transition(
            task_status="blocked",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
        )
        assert r.requires_conductor is True
        assert "stage:development" in r.remove_labels


# ── dispatch_transition: development ────────────────────────────


class TestDevelopment:
    def test_success_advances_to_testing(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=True,
        )
        assert r.status == "open"
        assert r.next_stage == "testing"
        assert "stage:testing" in r.add_labels
        assert "stage:development" in r.remove_labels

    def test_no_commits_stays(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=False,
        )
        assert r.status == "open"
        assert r.next_stage is None

    def test_rejected_retries(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development", "rejected"],
            agent_role="developer",
            rejection_count=1,
        )
        assert r.status == "open"
        assert "rejected" in r.remove_labels

    def test_rejected_max_blocks(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development", "rejected"],
            agent_role="developer",
            rejection_count=3,
            max_rejections=3,
        )
        assert r.status == "blocked"
        assert "Rejected" in r.failure_reason

    def test_closed_treated_as_open(self):
        r = dispatch_transition(
            task_status="closed",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=True,
        )
        assert r.status == "open"
        assert r.next_stage == "testing"

    def test_no_commits_after_3_spawns_blocks(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=False,
            spawn_count=3,
        )
        assert r.status == "blocked"
        assert "No commits after 3 development attempts" in r.failure_reason
        assert r.requires_conductor is True
        assert "stage:development" in r.remove_labels

    def test_no_commits_after_5_spawns_blocks(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=False,
            spawn_count=5,
        )
        assert r.status == "blocked"
        assert "No commits after 5 development attempts" in r.failure_reason

    def test_no_commits_under_3_spawns_stays_open(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=False,
            spawn_count=2,
        )
        assert r.status == "open"
        assert r.next_stage is None
        assert r.failure_reason is None

    def test_no_commits_zero_spawns_stays_open(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=False,
            spawn_count=0,
        )
        assert r.status == "open"
        assert r.next_stage is None


# ── dispatch_transition: reviewing ──────────────────────────────


class TestReviewing:
    def test_approved_advances_to_pr_creation(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="reviewing",
            task_labels=["stage:reviewing"],
            agent_role="reviewer",
        )
        assert r.next_stage == "pr-creation"
        assert "stage:pr-creation" in r.add_labels

    def test_approved_with_security_label(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="reviewing",
            task_labels=["stage:reviewing", "security"],
            agent_role="reviewer",
        )
        assert r.next_stage == "security-review"

    def test_rejected_back_to_development(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="reviewing",
            task_labels=["stage:reviewing", "rejected"],
            agent_role="reviewer",
        )
        assert r.next_stage == "development"
        assert "stage:development" in r.add_labels
        assert "rejected" in r.remove_labels

    def test_non_open_noop(self):
        r = dispatch_transition(
            task_status="in_progress",
            task_stage="reviewing",
            task_labels=["stage:reviewing"],
            agent_role="reviewer",
            agent_exit_code=0,
        )
        # in_progress with exit_code=0 → reset to open
        assert r.status == "open"


# ── dispatch_transition: security-review ────────────────────────


class TestSecurityReview:
    def test_approved_advances_to_pr_creation(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="security-review",
            task_labels=["stage:security-review", "security"],
            agent_role="security_reviewer",
        )
        assert r.next_stage == "pr-creation"

    def test_rejected_back_to_development(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="security-review",
            task_labels=["stage:security-review", "security", "rejected"],
            agent_role="security_reviewer",
        )
        assert r.next_stage == "development"


# ── dispatch_transition: testing ──────────────────────────────────


class TestTesting:
    def test_needs_testing_stays_put(self):
        """Task with needs-testing label should not advance."""
        r = dispatch_transition(
            task_status="open",
            task_stage="testing",
            task_labels=["stage:testing", "needs-testing"],
            agent_role="developer",
        )
        assert r.next_stage is None
        assert not r.has_changes

    def test_approved_advances_to_reviewing(self):
        """After tester passes, advance to reviewing."""
        r = dispatch_transition(
            task_status="open",
            task_stage="testing",
            task_labels=["stage:testing"],
            agent_role="tester",
        )
        assert r.next_stage == "reviewing"
        assert "stage:reviewing" in r.add_labels

    def test_rejected_back_to_development(self):
        """Rejected after testing goes back to development."""
        r = dispatch_transition(
            task_status="open",
            task_stage="testing",
            task_labels=["stage:testing", "needs-testing", "rejected"],
            agent_role="developer",
        )
        assert r.next_stage == "development"
        assert "stage:development" in r.add_labels
        assert "rejected" in r.remove_labels
        assert "needs-testing" in r.remove_labels


class TestShouldSkipTesting:
    def test_python_files_need_testing(self):
        from warchief.state_machine import should_skip_testing

        assert should_skip_testing(["main.py", "utils.py", "README.md"]) is False

    def test_docs_only_skips(self):
        from warchief.state_machine import should_skip_testing

        assert should_skip_testing(["README.md", "CHANGELOG.txt"]) is True

    def test_has_frontend_files(self):
        from warchief.state_machine import should_skip_testing

        assert should_skip_testing(["main.py", "app.tsx", "style.css"]) is False

    def test_empty_list(self):
        from warchief.state_machine import should_skip_testing

        # Empty list means unknown changes — don't skip (be safe)
        assert should_skip_testing([]) is False

    def test_vue_files(self):
        from warchief.state_machine import should_skip_testing

        assert should_skip_testing(["Component.vue"]) is False

    def test_json_only_skips(self):
        from warchief.state_machine import should_skip_testing

        assert should_skip_testing(["package.json"]) is True

    def test_json_with_frontend_does_not_skip(self):
        from warchief.state_machine import should_skip_testing

        assert should_skip_testing(["package.json", "index.tsx"]) is False


class TestShouldSkipSecurityReview:
    def test_docs_only_skips(self):
        from warchief.state_machine import should_skip_security_review

        assert should_skip_security_review(["README.md", "CHANGELOG.txt"]) is True

    def test_config_only_skips(self):
        from warchief.state_machine import should_skip_security_review

        assert should_skip_security_review(["config.toml", "settings.yaml"]) is True

    def test_docs_and_config_skips(self):
        from warchief.state_machine import should_skip_security_review

        assert should_skip_security_review(["README.md", "config.toml"]) is True

    def test_source_code_does_not_skip(self):
        from warchief.state_machine import should_skip_security_review

        assert should_skip_security_review(["auth.py", "README.md"]) is False

    def test_empty_list_skips(self):
        from warchief.state_machine import should_skip_security_review

        assert should_skip_security_review([]) is True

    def test_frontend_does_not_skip(self):
        from warchief.state_machine import should_skip_security_review

        assert should_skip_security_review(["app.tsx"]) is False


# ── dispatch_transition: pr-creation ─────────────────────────────


class TestPrCreation:
    def test_closed_completes(self):
        r = dispatch_transition(
            task_status="closed",
            task_stage="pr-creation",
            task_labels=["stage:pr-creation"],
            agent_role="pr_creator",
        )
        assert r.status == "closed"
        assert "stage:pr-creation" in r.remove_labels

    def test_pr_creator_completes(self):
        """PR creator finished (open) — task is done."""
        r = dispatch_transition(
            task_status="open",
            task_stage="pr-creation",
            task_labels=["stage:pr-creation"],
            agent_role="pr_creator",
        )
        assert r.status == "closed"

    def test_non_pr_creator_does_not_close(self):
        """Task just advanced to pr-creation by reviewer — should NOT close."""
        r = dispatch_transition(
            task_status="open",
            task_stage="pr-creation",
            task_labels=["stage:pr-creation"],
            agent_role="reviewer",
        )
        assert r.status is None  # No change — wait for pr_creator to spawn

    def test_in_progress_noop(self):
        """Task still in progress — nothing to do (crash/exit handled above)."""
        r = dispatch_transition(
            task_status="in_progress",
            task_stage="pr-creation",
            task_labels=["stage:pr-creation"],
            agent_role="pr_creator",
            agent_exit_code=0,
        )
        # in_progress with exit_code=0 → reset to open → then pr-creation closes
        assert r.status == "closed"


# ── dispatch_transition: no stage ───────────────────────────────


class TestNoStage:
    def test_no_stage_noop(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="",
            task_labels=[],
            agent_role="developer",
        )
        assert not r.has_changes


# ── TransitionResult.has_changes ────────────────────────────────


class TestHasChanges:
    def test_empty_result_no_changes(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="",
            task_labels=[],
            agent_role="developer",
        )
        assert r.has_changes is False

    def test_status_change_has_changes(self):
        r = dispatch_transition(
            task_status="open",
            task_stage="development",
            task_labels=["stage:development"],
            agent_role="developer",
            branch_has_commits=True,
        )
        assert r.has_changes is True
