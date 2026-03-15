"""Pure-function state machine. The heart of Warchief.

Every function here is pure: no DB calls, no subprocess calls, no I/O.
Input: current state. Output: what should change.
"""
from __future__ import annotations

from warchief.models import TransitionResult

# Stage flow order (without optional stages)
_STAGE_ORDER = ["development", "reviewing", "testing", "pr-creation"]
_STAGE_ORDER_WITH_SECURITY = [
    "development", "reviewing", "security-review", "testing", "pr-creation"
]


def get_next_stage(current_stage: str, task_labels: list[str]) -> str | None:
    """Given current stage and labels, return the next stage in the pipeline."""
    has_security = "security" in task_labels
    order = _STAGE_ORDER_WITH_SECURITY if has_security else _STAGE_ORDER

    try:
        idx = order.index(current_stage)
    except ValueError:
        return None

    if idx + 1 < len(order):
        return order[idx + 1]
    return None


def verify_single_stage(labels: list[str]) -> list[str]:
    """If multiple stage labels exist, keep only the first one."""
    stage_labels = [l for l in labels if l.startswith("stage:")]
    if len(stage_labels) <= 1:
        return labels
    keep = stage_labels[0]
    return [l for l in labels if not l.startswith("stage:") or l == keep]


def dispatch_transition(
    task_status: str,
    task_stage: str,
    task_labels: list[str],
    agent_role: str,
    agent_exit_code: int | None = 0,
    branch_has_commits: bool = True,
    rejection_count: int = 0,
    crash_count: int = 0,
    spawn_count: int = 0,
    max_rejections: int = 3,
    max_crashes: int = 3,
    max_spawns: int = 20,
) -> TransitionResult:
    """Determine the next state transition. Pure function — no side effects."""

    stage_label = f"stage:{task_stage}" if task_stage else None
    has_rejected = "rejected" in task_labels

    # --- Spawn limit reached ---
    # Only block on spawn limit when the task would be re-spawned (status=open).
    # Don't block when an agent just finished and is reporting results (closed)
    # — let stage handlers evaluate the completion first.
    if spawn_count >= max_spawns and task_status == "open":
        return TransitionResult(
            status="blocked",
            remove_labels=[stage_label] if stage_label else [],
            failure_reason=f"Spawn limit reached ({spawn_count}/{max_spawns})",
            requires_conductor=True,
        )

    # --- Agent crashed (non-zero exit or signal death) ---
    agent_crashed = (agent_exit_code is not None and agent_exit_code != 0)
    agent_died_unknown = (agent_exit_code is None)

    if agent_crashed and task_status == "in_progress":
        if crash_count < max_crashes:
            return TransitionResult(status="open")
        return TransitionResult(
            status="blocked",
            remove_labels=[stage_label] if stage_label else [],
            failure_reason=f"Crashed {crash_count + 1} times at {task_stage}",
            requires_conductor=True,
        )

    # --- Agent exited cleanly (code 0) but task still in_progress ---
    # This means the agent completed its work but forgot to update status.
    # Treat as if the agent set status to "open" (work complete) so the
    # stage-specific handlers below can evaluate and potentially advance.
    if task_status == "in_progress" and agent_exit_code == 0:
        task_status = "open"

    # --- Agent died with unknown exit code and task still in_progress ---
    if task_status == "in_progress" and agent_died_unknown:
        return TransitionResult(status="open")

    # --- Task explicitly blocked by agent ---
    if task_status == "blocked":
        return TransitionResult(
            remove_labels=[stage_label] if stage_label else [],
            requires_conductor=True,
        )

    # --- No stage (shouldn't happen, but defensive) ---
    if not task_stage:
        return TransitionResult()

    # --- DEVELOPMENT stage ---
    if task_stage == "development":
        return _handle_development(
            task_status, task_labels, stage_label,
            has_rejected, branch_has_commits,
            rejection_count, max_rejections, spawn_count,
        )

    # --- REVIEWING stage ---
    if task_stage == "reviewing":
        return _handle_reviewing(task_status, task_labels, stage_label, has_rejected)

    # --- SECURITY-REVIEW stage ---
    if task_stage == "security-review":
        return _handle_security_review(task_status, task_labels, stage_label, has_rejected)

    # --- TESTING stage (human-driven) ---
    if task_stage == "testing":
        return _handle_testing(task_status, task_labels, stage_label)

    # --- PR-CREATION stage ---
    if task_stage == "pr-creation":
        return _handle_pr_creation(task_status, task_labels, stage_label)

    return TransitionResult()


def _handle_development(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
    has_rejected: bool,
    branch_has_commits: bool,
    rejection_count: int,
    max_rejections: int,
    spawn_count: int = 0,
) -> TransitionResult:
    # Premature close at non-terminal stage: treat as open
    is_open = task_status in ("open", "closed")

    if not is_open:
        return TransitionResult()

    if has_rejected:
        if rejection_count >= max_rejections:
            return TransitionResult(
                status="blocked",
                remove_labels=["rejected", stage_label] if stage_label else ["rejected"],
                failure_reason=f"Rejected {rejection_count} times",
                requires_conductor=True,
            )
        # Remove rejected label, stay in development for retry
        return TransitionResult(
            status="open",
            remove_labels=["rejected"],
        )

    if not branch_has_commits:
        if spawn_count >= 3:
            return TransitionResult(
                status="blocked",
                remove_labels=[stage_label] if stage_label else [],
                failure_reason=f"No commits after {spawn_count} development attempts",
                requires_conductor=True,
            )
        return TransitionResult(status="open")

    # Success: advance to reviewing
    next_stage = get_next_stage("development", task_labels)
    return TransitionResult(
        status="open",
        remove_labels=[stage_label] if stage_label else [],
        add_labels=[f"stage:{next_stage}"] if next_stage else [],
        next_stage=next_stage,
    )


def _handle_reviewing(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
    has_rejected: bool,
) -> TransitionResult:
    is_open = task_status in ("open", "closed")
    if not is_open:
        return TransitionResult()

    if has_rejected:
        # Back to development
        return TransitionResult(
            status="open",
            remove_labels=["rejected", stage_label] if stage_label else ["rejected"],
            add_labels=["stage:development"],
            next_stage="development",
        )

    # Approved: advance
    next_stage = get_next_stage("reviewing", task_labels)
    return TransitionResult(
        status="open",
        remove_labels=[stage_label] if stage_label else [],
        add_labels=[f"stage:{next_stage}"] if next_stage else [],
        next_stage=next_stage,
    )


def _handle_security_review(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
    has_rejected: bool,
) -> TransitionResult:
    is_open = task_status in ("open", "closed")
    if not is_open:
        return TransitionResult()

    if has_rejected:
        return TransitionResult(
            status="open",
            remove_labels=["rejected", stage_label] if stage_label else ["rejected"],
            add_labels=["stage:development"],
            next_stage="development",
        )

    next_stage = get_next_stage("security-review", task_labels)
    return TransitionResult(
        status="open",
        remove_labels=[stage_label] if stage_label else [],
        add_labels=[f"stage:{next_stage}"] if next_stage else [],
        next_stage=next_stage,
    )


# Extensions for documentation-only changes (skip testing)
DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc"}

# Extensions for config-only changes (skip security review)
CONFIG_EXTENSIONS = {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf"}


def should_skip_testing(changed_files: list[str]) -> bool:
    """Determine if the testing stage can be skipped.

    Returns True if only non-code files were changed (no frontend, no source).
    Also skips for documentation-only changes.
    """
    from warchief.config import FRONTEND_EXTENSIONS
    for f in changed_files:
        ext = "." + f.rsplit(".", 1)[-1] if "." in f else ""
        ext_lower = ext.lower()
        if ext_lower in FRONTEND_EXTENSIONS:
            return False
        # Source code files that need testing but aren't frontend
        if ext_lower in (".py", ".go", ".rs", ".java", ".rb", ".php", ".c", ".cpp", ".h"):
            return False
    return True


def should_skip_security_review(changed_files: list[str]) -> bool:
    """Determine if the security review stage can be skipped.

    Returns True if only docs or config files were changed.
    """
    for f in changed_files:
        ext = "." + f.rsplit(".", 1)[-1] if "." in f else ""
        ext_lower = ext.lower()
        if ext_lower not in DOC_EXTENSIONS | CONFIG_EXTENSIONS:
            return False
    return True


def _handle_testing(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
) -> TransitionResult:
    """Testing stage — tester agent writes and runs tests.

    Tester agent:
    - Approves (status=open, no rejected label) → advance to pr-creation
    - Rejects (status=open, rejected label) → back to development
    - Can also block for manual testing (needs-testing label)
    """
    is_open = task_status in ("open", "closed")
    if not is_open:
        return TransitionResult()

    has_rejected = "rejected" in task_labels

    if has_rejected:
        # Tests failed / tester rejected — back to development
        return TransitionResult(
            status="open",
            remove_labels=["rejected", "needs-testing", stage_label] if stage_label else ["rejected", "needs-testing"],
            add_labels=["stage:development"],
            next_stage="development",
        )

    # If "needs-testing" is on, waiting for manual approval (e2e)
    if "needs-testing" in task_labels:
        return TransitionResult()

    # Tests passed — advance to pr-creation
    next_stage = get_next_stage("testing", task_labels)
    return TransitionResult(
        status="open",
        remove_labels=[stage_label] if stage_label else [],
        add_labels=[f"stage:{next_stage}"] if next_stage else [],
        next_stage=next_stage,
    )


def _handle_pr_creation(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
) -> TransitionResult:
    if task_status in ("open", "closed"):
        # PR was created successfully — close the task (terminal state).
        return TransitionResult(
            status="closed",
            remove_labels=[stage_label] if stage_label else [],
        )

    return TransitionResult()
