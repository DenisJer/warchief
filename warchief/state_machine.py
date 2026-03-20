"""Pure-function state machine. The heart of Warchief.

Every function here is pure: no DB calls, no subprocess calls, no I/O.
Input: current state. Output: what should change.
"""

from __future__ import annotations

from warchief.config import TYPE_TO_PIPELINE, PIPELINE_FEATURE
from warchief.models import TransitionResult


def get_pipeline_for_type(task_type: str) -> list[str]:
    """Get the pipeline stage sequence for a task type."""
    return TYPE_TO_PIPELINE.get(task_type, PIPELINE_FEATURE)


def get_next_stage(
    current_stage: str,
    task_labels: list[str],
    task_type: str = "feature",
) -> str | None:
    """Given current stage, labels, and type, return the next pipeline stage."""
    pipeline = get_pipeline_for_type(task_type)

    # Security review is optional — skip if not labeled
    has_security = "security" in task_labels
    if not has_security:
        pipeline = [s for s in pipeline if s != "security-review"]

    try:
        idx = pipeline.index(current_stage)
    except ValueError:
        return None

    if idx + 1 < len(pipeline):
        return pipeline[idx + 1]
    return None


def get_first_stage(task_type: str) -> str:
    """Get the first stage for a task type."""
    pipeline = get_pipeline_for_type(task_type)
    return pipeline[0]


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
    task_type: str = "feature",
) -> TransitionResult:
    """Determine the next state transition. Pure function — no side effects."""

    stage_label = f"stage:{task_stage}" if task_stage else None
    has_rejected = "rejected" in task_labels

    # --- Spawn limit reached ---
    if spawn_count >= max_spawns and task_status == "open":
        return TransitionResult(
            status="blocked",
            remove_labels=[stage_label] if stage_label else [],
            failure_reason=f"Spawn limit reached ({spawn_count}/{max_spawns})",
            requires_conductor=True,
        )

    # --- Agent crashed (non-zero exit or signal death) ---
    agent_crashed = agent_exit_code is not None and agent_exit_code != 0
    agent_died_unknown = agent_exit_code is None

    if agent_crashed and task_status == "in_progress":
        if crash_count < max_crashes:
            return TransitionResult(status="open")
        return TransitionResult(
            status="blocked",
            remove_labels=[stage_label] if stage_label else [],
            failure_reason=f"Crashed {crash_count + 1} times at {task_stage}",
            requires_conductor=True,
        )

    # --- Agent exited cleanly but task still in_progress ---
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

    # --- PLANNING stage ---
    if task_stage == "planning":
        return _handle_planning(task_status, task_labels, stage_label, task_type)

    # --- DEVELOPMENT stage ---
    if task_stage == "development":
        return _handle_development(
            task_status,
            task_labels,
            stage_label,
            has_rejected,
            branch_has_commits,
            rejection_count,
            max_rejections,
            spawn_count,
            task_type,
        )

    # --- CHALLENGE stage ---
    if task_stage == "challenge":
        return _handle_challenge(task_status, task_labels, stage_label, has_rejected, task_type)

    # --- REVIEWING stage ---
    if task_stage == "reviewing":
        return _handle_reviewing(task_status, task_labels, stage_label, has_rejected, task_type)

    # --- SECURITY-REVIEW stage ---
    if task_stage == "security-review":
        return _handle_security_review(
            task_status, task_labels, stage_label, has_rejected, task_type
        )

    # --- TESTING stage ---
    if task_stage == "testing":
        return _handle_testing(task_status, task_labels, stage_label, task_type)

    # --- PR-CREATION stage ---
    if task_stage == "pr-creation":
        return _handle_pr_creation(task_status, task_labels, stage_label, agent_role)

    # --- INVESTIGATION stage ---
    if task_stage == "investigation":
        return _handle_investigation(task_status, task_labels, stage_label)

    return TransitionResult()


def _handle_planning(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
    task_type: str,
) -> TransitionResult:
    """Planning stage — planner writes a plan, waits for user approval."""
    is_open = task_status in ("open", "closed")
    if not is_open:
        return TransitionResult()

    has_rejected = "rejected" in task_labels

    if has_rejected:
        # User rejected the plan — stay in planning for another attempt
        return TransitionResult(
            status="open",
            remove_labels=["rejected"],
        )

    # Plan complete — block for user approval
    if "plan-approved" in task_labels:
        # User approved — advance to development
        next_stage = get_next_stage("planning", task_labels, task_type)
        return TransitionResult(
            status="open",
            remove_labels=["plan-approved", stage_label] if stage_label else ["plan-approved"],
            add_labels=[f"stage:{next_stage}"] if next_stage else [],
            next_stage=next_stage,
        )

    # Planner finished — block for user approval (unless already waiting)
    if "needs-plan-approval" not in task_labels:
        return TransitionResult(
            status="blocked",
            add_labels=["needs-plan-approval"],
        )

    return TransitionResult()


def _handle_challenge(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
    has_rejected: bool,
    task_type: str = "feature",
) -> TransitionResult:
    """Challenge stage — stress-tests code or findings before proceeding.

    On rejection: sends task back to development (or investigation) for fixes.
    On approval: advances to the next stage (testing or consolidation).
    """
    is_open = task_status in ("open", "closed")
    if not is_open:
        return TransitionResult()

    if has_rejected:
        # Challenger found issues — send back to development
        # For investigation tasks, send back to investigation
        back_stage = "investigation" if task_type == "investigation" else "development"
        return TransitionResult(
            status="open",
            remove_labels=["rejected", stage_label] if stage_label else ["rejected"],
            add_labels=[f"stage:{back_stage}"],
            next_stage=back_stage,
        )

    # Challenger approved — advance to next stage
    next_stage = get_next_stage("challenge", task_labels, task_type)
    return TransitionResult(
        status="open",
        remove_labels=[stage_label] if stage_label else [],
        add_labels=[f"stage:{next_stage}"] if next_stage else [],
        next_stage=next_stage,
    )


def _handle_development(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
    has_rejected: bool,
    branch_has_commits: bool,
    rejection_count: int,
    max_rejections: int,
    spawn_count: int = 0,
    task_type: str = "feature",
) -> TransitionResult:
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

    next_stage = get_next_stage("development", task_labels, task_type)
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
    task_type: str = "feature",
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

    next_stage = get_next_stage("reviewing", task_labels, task_type)
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
    task_type: str = "feature",
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

    next_stage = get_next_stage("security-review", task_labels, task_type)
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
    """Returns True if only non-code files were changed."""
    if not changed_files:
        return False  # Unknown changes — don't skip
    from warchief.config import FRONTEND_EXTENSIONS

    for f in changed_files:
        ext = "." + f.rsplit(".", 1)[-1] if "." in f else ""
        ext_lower = ext.lower()
        if ext_lower in FRONTEND_EXTENSIONS:
            return False
        if ext_lower in (".py", ".go", ".rs", ".java", ".rb", ".php", ".c", ".cpp", ".h"):
            return False
    return True


def should_skip_security_review(changed_files: list[str]) -> bool:
    """Returns True if only docs or config files were changed."""
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
    task_type: str = "feature",
) -> TransitionResult:
    is_open = task_status in ("open", "closed")
    if not is_open:
        return TransitionResult()

    has_rejected = "rejected" in task_labels

    if has_rejected:
        return TransitionResult(
            status="open",
            remove_labels=["rejected", "needs-testing", stage_label]
            if stage_label
            else ["rejected", "needs-testing"],
            add_labels=["stage:development"],
            next_stage="development",
        )

    if "needs-testing" in task_labels:
        return TransitionResult()

    next_stage = get_next_stage("testing", task_labels, task_type)
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
    agent_role: str = "",
) -> TransitionResult:
    # Only close when PR creator has finished (not when reviewer advances here)
    if task_status in ("open", "closed") and agent_role == "pr_creator":
        return TransitionResult(
            status="closed",
            remove_labels=[stage_label] if stage_label else [],
        )
    return TransitionResult()


def _handle_investigation(
    task_status: str,
    task_labels: list[str],
    stage_label: str | None,
) -> TransitionResult:
    """Investigation stage — agent researches, writes findings to scratchpad.

    On completion:
    - Blocks with "needs-review" label for user to review findings
    - User can: approve (close), reject (re-investigate), or escalate (create sub-tasks)
    """
    is_open = task_status in ("open", "closed")
    if not is_open:
        return TransitionResult()

    has_rejected = "rejected" in task_labels

    if has_rejected:
        # User wants more investigation
        return TransitionResult(
            status="open",
            remove_labels=["rejected", "needs-review"],
        )

    # Investigation complete — block for user review
    if "needs-review" not in task_labels:
        return TransitionResult(
            status="blocked",
            add_labels=["needs-review"],
        )

    return TransitionResult()
