"""Agent spawner — creates Claude Code processes for tasks."""
from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

from warchief.config import Config, STAGE_TO_ROLE
from warchief.models import AgentRecord, EventRecord, TaskRecord, get_task_branch
from warchief.roles import RoleRegistry
from warchief.task_store import TaskStore
from warchief.worktree import (
    create_branch_worktree,
    create_detached_worktree,
    create_integrator_worktree,
)

log = logging.getLogger("warchief.spawner")

# WoW character name pool — used to generate memorable agent IDs
_WARCHIEFS = [
    "thrall", "sylvanas", "garrosh", "voljin", "cairne", "rexxar", "saurfang",
    "nazgrel", "drektar", "grommash", "orgrim", "durotan", "guldan", "nerzhul",
    "zuljin", "rokhan", "baine", "chromie", "valeera", "garona", "maiev",
    "illidan", "tyrande", "malfurion", "arthas", "jaina", "uther", "anduin",
    "varian", "magni", "muradin", "falstad", "gelbin", "mekkatorque", "genn",
    "tess", "liadrin", "lorthemar", "halduron", "rommath", "khadgar",
    "medivh", "kadgar", "aegwynn", "antonidas", "rhonin", "krasus",
    "alexstrasza", "ysera", "nozdormu", "kalecgos", "wrathion",
    "bolvar", "tirion", "mograine", "whitemane", "fairbanks",
    "taran", "turalyon", "alleria", "vereesa", "nathanos",
    "thalyssra", "oculeth", "valtrois", "stellagosa", "ebonhorn",
    "mayla", "lasan", "spiritwalker", "hamuul", "dezco",
    "chen", "lili", "taran_zhu", "aysa", "ji_firepaw",
    "rastakhan", "talanji", "bwonsamdi", "zuldazar", "gonk",
    "azshara", "nzoth", "yoggsaron", "cthun", "xalatath",
]
_name_index = 0


def _next_agent_id(role: str) -> str:
    """Generate a WoW-themed agent ID like 'developer-thrall-a1b2'.

    Includes a short UUID suffix to prevent collisions on watcher restart.
    """
    global _name_index
    name = _WARCHIEFS[_name_index % len(_WARCHIEFS)]
    _name_index += 1
    suffix = uuid.uuid4().hex[:4]
    return f"{role}-{name}-{suffix}"


def build_claude_command(
    role_name: str,
    registry: RoleRegistry,
    task: TaskRecord,
    worktree_path: Path | None,
    project_root: Path,
    config: Config,
) -> list[str]:
    """Build the Claude Code CLI command from role TOML permissions."""
    allowed_tools = registry.get_allowed_tools(role_name)
    # Merge task-level extra tools (e.g. MCP tools granted per-task)
    if task.extra_tools:
        allowed_tools = allowed_tools + [t for t in task.extra_tools if t not in allowed_tools]
    model = config.role_models.get(role_name) or registry.get_model(role_name)

    prompt_file = registry.get_role(role_name).get("identity", {}).get("prompt_file", "")
    # Look for prompt files: first in project root, then in the warchief package
    prompt_path = None
    if prompt_file:
        candidate = project_root / prompt_file
        if candidate.exists():
            prompt_path = candidate
        else:
            # Fall back to warchief package directory
            package_dir = Path(__file__).parent.parent
            candidate = package_dir / prompt_file
            if candidate.exists():
                prompt_path = candidate

    cmd = ["claude", "--print", "--verbose", "--output-format", "stream-json"]

    max_turns = registry.get_max_turns(role_name)

    if model:
        cmd.extend(["--model", model])

    if max_turns:
        cmd.extend(["--max-turns", str(max_turns)])

    if allowed_tools:
        for tool in allowed_tools:
            cmd.extend(["--allowedTools", tool])

    cwd = str(worktree_path) if worktree_path else str(project_root)

    # Build the task prompt
    labels_str = ", ".join(task.labels) if task.labels else "none"
    deps_str = ", ".join(task.deps) if task.deps else "none"

    task_prompt = (
        f"You are a {role_name} agent working on task {task.id}.\n"
        f"Task: {task.title}\n"
        f"Description: {task.description}\n"
        f"Labels: {labels_str}\n"
        f"Dependencies: {deps_str}\n"
        f"Base branch: {task.base_branch or 'main'}\n"
        f"\n## HARD RULES (violating these breaks the pipeline)\n"
        f"- NEVER `cd` outside your current working directory\n"
        f"- NEVER read/write/access the `.warchief/` directory\n"
        f"- NEVER run `warchief` commands other than `warchief agent-update`\n"
        f"- NEVER push to main/master — only work on feature branches\n"
        f"- NEVER run `git push` to any remote\n"
        f"\n## Asking Questions\n"
        f"If you are unsure how to proceed or need clarification from the user, ask a question:\n"
        f"  warchief agent-update --task-id {task.id} --status blocked --question \"Your question here\"\n"
        f"Then EXIT immediately. The user will answer, and you will be re-spawned with their response.\n"
    )

    # Developer agents MUST commit AND update status — append explicit instructions
    log.info("BUILD_CMD: role_name=%r, prompt_path=%s, prompt_path_exists=%s",
             role_name, prompt_path, prompt_path.exists() if prompt_path else "N/A")
    if role_name == "developer":
        task_prompt += (
            "\n## CRITICAL: Before you exit, you MUST do these three things:\n"
            "### Step 1: Commit your work\n"
            "IMPORTANT: Only `git add` the specific files YOU created or modified.\n"
            "NEVER use `git add -A` or `git add .` — this will commit junk files.\n"
            "```bash\n"
            "git add <file1> <file2> ...  # Only YOUR files\n"
            "git commit -m 'feat: <descriptive message>'\n"
            "```\n"
            "### Step 2: Write handoff notes\n"
            "Summarize what you did and WHY — the next agent (reviewer) reads this:\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --handoff 'What: <files changed>. "
            "Why: <key decisions and trade-offs>. Issues: <known limitations or concerns>'\n"
            "```\n"
            "### Step 3: Signal completion\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --status open\n"
            "```\n"
            "If you skip ANY step, the pipeline CANNOT advance.\n"
            "If you are stuck or the task is impossible, run:\n"
            f"  warchief agent-update --task-id {task.id} --status blocked --comment '<reason>'\n"
        )
    elif role_name == "reviewer":
        task_prompt += (
            "\n## CRITICAL: Before you exit, you MUST do these two things:\n"
            "### Step 1: Write handoff notes\n"
            "Summarize your review findings for the next agent:\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --handoff 'Reviewed: <what you checked>. "
            "Verdict: <approved/rejected>. Feedback: <specific issues or praise>'\n"
            "```\n"
            "### Step 2: Signal your decision\n"
            "If APPROVED:\n"
            f"  warchief agent-update --task-id {task.id} --status open\n"
            "If REJECTED (changes needed):\n"
            f"  warchief agent-update --task-id {task.id} --status open --add-label rejected\n"
            f"  warchief agent-update --task-id {task.id} --comment '<specific feedback>'\n"
        )
    elif role_name == "planner":
        task_prompt += (
            "\n## CRITICAL: Before you exit, you MUST do these two things:\n"
            "### Step 1: Write your plan as handoff notes\n"
            "The user will review your plan before development starts.\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --handoff 'YOUR FULL PLAN HERE — "
            "files to change, approach, dependencies, risks, scope estimate'\n"
            "```\n"
            "### Step 2: Signal completion\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --status open\n"
            "```\n"
        )
    elif role_name == "investigator":
        task_prompt += (
            "\n## CRITICAL: Before you exit, you MUST do these two things:\n"
            "### Step 1: Write your findings as handoff notes\n"
            "The user will review your findings and decide next steps.\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --handoff 'YOUR FINDINGS — "
            "answer, evidence, recommendations, risks'\n"
            "```\n"
            "### Step 2: Signal completion\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --status open\n"
            "```\n"
        )
    elif role_name in ("security_reviewer", "tester"):
        task_prompt += (
            "\n## CRITICAL: Before you exit, you MUST do these two things:\n"
            "### Step 1: Write handoff notes\n"
            "```bash\n"
            f"warchief agent-update --task-id {task.id} --handoff 'Checked: <what you tested/reviewed>. "
            "Result: <passed/failed>. Details: <findings or concerns>'\n"
            "```\n"
            "### Step 2: Signal your decision\n"
            "If PASSED:\n"
            f"  warchief agent-update --task-id {task.id} --status open\n"
            "If FAILED:\n"
            f"  warchief agent-update --task-id {task.id} --status open --add-label rejected\n"
            f"  warchief agent-update --task-id {task.id} --comment '<specific feedback>'\n"
        )
    elif role_name == "integrator":
        task_prompt += (
            "\n## CRITICAL: Before you exit, signal merge result:\n"
            "If MERGED successfully:\n"
            f"  warchief agent-update --task-id {task.id} --status closed\n"
            "If MERGE FAILED:\n"
            f"  warchief agent-update --task-id {task.id} --status blocked --comment '<conflict details>'\n"
        )
    elif role_name == "pr_creator":
        task_prompt += (
            "\n## CRITICAL: Before you exit, signal PR result:\n"
            "If PR CREATED successfully:\n"
            f"  warchief agent-update --task-id {task.id} --status closed --comment 'PR created: <URL>'\n"
            "If PR FAILED:\n"
            f"  warchief agent-update --task-id {task.id} --status blocked --comment '<error details>'\n"
        )

    # Load role prompt if available
    if prompt_path and prompt_path.exists():
        role_prompt = prompt_path.read_text()
        task_prompt = role_prompt + "\n\n---\n\n" + task_prompt

    # Return prompt separately — will be piped via stdin
    return cmd, cwd, task_prompt


def spawn_agent(
    task: TaskRecord,
    role: str,
    project_root: Path,
    store: TaskStore,
    config: Config,
    registry: RoleRegistry,
) -> AgentRecord | None:
    """Spawn a Claude Code agent process for a task.

    Returns the AgentRecord if spawned, None if spawn failed.
    On failure, marks the task as blocked to prevent infinite retry loops.
    """
    agent_id = _next_agent_id(role)
    now = time.time()

    # Create worktree based on role config
    worktree_config = registry.get_role(role).get("worktree", {})
    wt_type = worktree_config.get("type", "none")
    worktree_path: Path | None = None
    base = task.base_branch or config.base_branch or "main"

    # Use shared group branch if task belongs to a group
    task_branch = get_task_branch(task)

    try:
        if wt_type == "branch":
            worktree_path = create_branch_worktree(
                project_root, agent_id, task_branch, base,
            )
        elif wt_type == "integrator":
            worktree_path = create_integrator_worktree(
                project_root, agent_id, base, task_branch,
            )
        elif wt_type == "detached":
            # Reviewer/tester: detach at the feature branch
            commit_ref = task_branch
            try:
                worktree_path = create_detached_worktree(
                    project_root, agent_id, commit_ref,
                )
            except subprocess.CalledProcessError:
                # Branch may not exist yet; detach at base
                worktree_path = create_detached_worktree(
                    project_root, agent_id, base,
                )
    except subprocess.CalledProcessError as e:
        log.error("Failed to create worktree for %s: %s", agent_id, e)
        # Increment crash count and block if too many failures
        new_crash_count = task.crash_count + 1
        if new_crash_count >= 3:
            store.update_task(task.id, status="blocked", crash_count=new_crash_count)
            store.log_event(EventRecord(
                event_type="block",
                task_id=task.id,
                details={"failure_reason": f"Worktree creation failed {new_crash_count} times: {e}"},
                actor="spawner",
            ))
            log.error("Task %s blocked after %d worktree failures", task.id, new_crash_count)
        else:
            store.update_task(task.id, crash_count=new_crash_count)
        return None

    # Install hooks in agent worktree
    if worktree_path:
        from warchief.hooks import install_agent_hooks
        try:
            install_agent_hooks(
                worktree_path, agent_id, task.id, role,
                str(project_root / ".warchief" / "warchief.db"),
            )
        except Exception as e:
            log.warning("Failed to install hooks for %s: %s", agent_id, e)

    # Build command
    cmd, cwd, task_prompt = build_claude_command(
        role, registry, task, worktree_path, project_root, config,
    )

    # Inject prime context (previous attempts, rejections, task history)
    from warchief.prime import build_prime_context
    prime_ctx = build_prime_context(task, role, store, project_root)
    if prime_ctx:
        task_prompt += "\n" + prime_ctx

    # Context budget warning — flag prompts that are unusually large
    _PROMPT_WARN_CHARS = 15_000  # ~4k tokens
    if len(task_prompt) > _PROMPT_WARN_CHARS:
        log.warning(
            "Large prompt for %s on task %s: %d chars (~%d tokens). "
            "Consider reducing task description or clearing old messages.",
            agent_id, task.id, len(task_prompt), len(task_prompt) // 4,
        )

    # Set environment variables for hooks
    env = os.environ.copy()
    env["WARCHIEF_ROLE"] = role
    env["WARCHIEF_TASK"] = task.id
    env["WARCHIEF_AGENT"] = agent_id
    env["WARCHIEF_DB"] = str(project_root / ".warchief" / "warchief.db")
    # Remove Claude Code nesting detection env vars so spawned agents can run
    # Must remove ALL of these — Claude CLI checks multiple vars
    for key in ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]:
        env.pop(key, None)

    # Create agent log directory and output file
    agent_logs_dir = project_root / ".warchief" / "agent-logs"
    agent_logs_dir.mkdir(parents=True, exist_ok=True)
    agent_log_path = agent_logs_dir / f"{agent_id}.log"
    agent_log_file = open(agent_log_path, "w")

    # Spawn claude piped through the log writer for readable output
    # claude (stream-json) -> agent_log_writer.py -> log file
    log_writer_path = Path(__file__).parent / "agent_log_writer.py"
    import sys
    python = sys.executable

    # Debug: log prompt content indicators
    log.info("Prompt for %s: len=%d, has_CRITICAL=%s, has_wc-cmd=%s, has_Grunt=%s",
             agent_id, len(task_prompt),
             "CRITICAL" in task_prompt,
             "wc-cmd" in task_prompt,
             "Grunt" in task_prompt)

    # Write prompt to a temp file for stdin piping
    prompt_path = agent_logs_dir / f"{agent_id}.prompt"
    prompt_path.write_text(task_prompt)

    # Spawn the process: prompt file -> claude -> log_writer -> log file
    log_writer_proc = None
    try:
        prompt_file = open(prompt_path, "r")
        try:
            claude_proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdin=prompt_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Own process group — Ctrl+C won't hit agents
            )
        finally:
            prompt_file.close()
        # Pipe through log writer for readable output
        log_writer_proc = subprocess.Popen(
            [python, str(log_writer_path)],
            stdin=claude_proc.stdout,
            stdout=agent_log_file,
            stderr=subprocess.STDOUT,
            env=env,  # Pass env so log_writer has WARCHIEF_AGENT/WARCHIEF_DB for cost tracking
            start_new_session=True,
        )
        claude_proc.stdout.close()  # Allow SIGPIPE if log writer dies
        agent_log_file.close()  # Popen inherited the fd — we can close our copy
    except FileNotFoundError:
        agent_log_file.close()
        log.error("Claude CLI not found. Is 'claude' installed and on PATH?")
        store.update_task(task.id, status="blocked")
        store.log_event(EventRecord(
            event_type="block",
            task_id=task.id,
            details={"failure_reason": "Claude CLI not found on PATH"},
            actor="spawner",
        ))
        return None
    except OSError as e:
        agent_log_file.close()
        log.error("Failed to spawn agent %s: %s", agent_id, e)
        store.update_task(task.id, crash_count=task.crash_count + 1)
        return None

    # Register agent — track the claude process PID for lifecycle management
    agent = AgentRecord(
        id=agent_id,
        role=role,
        status="alive",
        current_task=task.id,
        worktree_path=str(worktree_path) if worktree_path else None,
        pid=claude_proc.pid,
        model=config.role_models.get(role) or registry.get_model(role),
        spawned_at=now,
        last_heartbeat=now,
    )
    store.register_agent(agent)

    # Update task
    store.update_task(
        task.id,
        status="in_progress",
        assigned_agent=agent_id,
        spawn_count=task.spawn_count + 1,
    )

    # Log event
    store.log_event(EventRecord(
        event_type="spawn",
        task_id=task.id,
        agent_id=agent_id,
        details={"role": role, "pid": claude_proc.pid, "worktree": str(worktree_path)},
        actor="watcher",
    ))

    log.info("Spawned %s (PID %d) for task %s", agent_id, claude_proc.pid, task.id)
    # Attach Popen objects so watcher can reliably get exit codes and cleanup
    # AgentRecord is frozen, so use object.__setattr__
    object.__setattr__(agent, "_claude_proc", claude_proc)
    object.__setattr__(agent, "_log_writer_proc", log_writer_proc)
    return agent
