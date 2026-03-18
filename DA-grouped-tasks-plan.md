# Grouped Tasks: Single PR, Agent Communication, Parallel Brainstorming

## Problem Statement

When a task is decomposed into sub-tasks, each sub-task currently runs through its own full pipeline and could produce its own PR. Instead:

1. **Single PR**: All sub-tasks should produce ONE combined PR
2. **Agent Communication**: Sibling agents should share context and coordinate decisions
3. **Parallel Brainstorming**: Agents should be able to spawn investigation/brainstorming helpers

---

## Current State (what already exists)

| Feature | Status | Location |
|---|---|---|
| `group_id` on TaskRecord | Exists | `models.py:24` |
| Shared branch via `get_task_branch()` | Exists | `models.py:31-37` — returns `feature/{group_id}` |
| `get_group_tasks()` | Exists | `task_store.py:320-326` |
| `group-waiting` PR gate | Exists | `watcher.py:615-680` — waits for all siblings |
| Single PR from group gate | Partial | Only ONE task creates PR, others get closed |
| Integrator role + worktree | Exists but unused | `roles/integrator.toml`, `worktree.py:132-206` |
| Per-task scratchpad | Exists | `scratchpad.py` — no group sharing |
| Message system | Exists | `task_store.py:392-441` — per-task only |
| Prime context | Exists | `prime.py:20-104` — no sibling awareness |

---

## Phase 1: Single PR for Grouped Tasks

**Goal**: All sub-tasks from a decomposition share one branch, one reviewer pass, one PR.

### Step 1.1: Ensure shared branch works correctly

The branch sharing already works via `get_task_branch()` returning `feature/{group_id}`. But multiple developers writing to the same branch from separate worktrees causes conflicts.

**Fix**: Sub-tasks should run **sequentially on the shared branch**, not in parallel. Higher-priority tasks go first. Each developer's worktree picks up the previous developer's commits.

Changes:
- `watcher.py:spawn_ready()` — for grouped tasks in development, only spawn ONE developer at a time. Check if any sibling is `in_progress` at `development` stage before spawning another.
- Keep parallel spawning for `planning` stage (plans don't conflict).

### Step 1.2: Group-level review instead of per-task review

Currently each task goes through its own review. For groups, we want ONE review of the combined work.

**Option A (simpler)**: Skip per-task review for grouped sub-tasks. After ALL sub-tasks finish development, advance the group to a single review pass.

**Option B (keep per-task review)**: Each task gets reviewed individually but the reviewer sees the full branch diff (all sibling work).

**Recommendation**: Option A — add a new concept: "group stage tracking."

Changes:
- `watcher.py` — new method `_check_group_stage_gate()`: when a grouped task finishes development, check if all siblings are also done with development. If not, add `group-waiting` label and hold. If yes, pick ONE task as the "group lead" and advance it through review → PR. Close the others.
- `config.py` — add `PIPELINE_GROUP_MEMBER = ["planning", "development"]` (truncated pipeline for non-lead tasks).
- The "group lead" task (highest priority or first created) gets the full pipeline: `planning → development → reviewing → pr-creation`.

### Step 1.3: Combined PR with all sub-task context

Changes:
- `prompts/pr_creator.md` — inject all sibling task titles, descriptions, and scratchpad summaries into the PR creator's prompt so the PR description covers all sub-tasks.
- `spawner.py` — when building prompt for `pr_creator` role on a grouped task, append sibling context.
- `prime.py:build_prime_context()` — add group context section: list all sibling tasks, their status, their scratchpad summaries.

### Step 1.4: Dashboard updates

Changes:
- `web/app.py` — API endpoint to show group status (all siblings, their stages, combined diff).
- Frontend — group tasks visually in the pipeline view, show them as connected.

---

## Phase 2: Inter-Agent Communication (Group Scratchpad)

**Goal**: Agents working on sibling tasks can read what other agents decided, share conventions, flag interface changes.

### Step 2.1: Group scratchpad

A shared scratchpad at `.warchief/scratchpads/group-{group_id}.md` that all sibling agents can read and append to.

Changes:
- `scratchpad.py` — add `append_group_scratchpad(project_root, group_id, agent_id, role, content)` and `read_group_scratchpad(project_root, group_id)`.
- `prime.py:build_prime_context()` — if task has `group_id`, include group scratchpad in agent context.
- `spawner.py` — developers/reviewers of grouped tasks get group scratchpad injected.

### Step 2.2: Sibling task awareness in prompts

When spawning a developer for a grouped task, tell it about its siblings:

```
## Sibling Tasks (same group)
- wc-abc123: "Add auth middleware" — COMPLETED (developer wrote src/auth.py)
- wc-def456: "Add login UI" — IN PROGRESS (developer is working on it)
- wc-ghi789: "Add password reset" — WAITING (not started yet)

## Group Scratchpad (shared decisions)
- [13:05] developer-thrall: Using JWT with httpOnly cookies for auth tokens
- [13:12] developer-cairne: Login form at /login, register at /register
```

Changes:
- `prime.py` — new function `build_group_context(task, store, project_root)` that gathers sibling status + group scratchpad.
- `spawner.py` — inject group context for grouped tasks.

### Step 2.3: Developer handoff to group scratchpad

After a developer commits, automatically append key decisions to the group scratchpad so the next sibling developer sees them.

Changes:
- `watcher.py:_store_handoff_or_rejection()` — if task has `group_id`, also append the handoff to the group scratchpad.

---

## Phase 3: Parallel Brainstorming Agents

**Goal**: When a task is complex, spawn parallel investigation/challenger agents to help the primary agent.

### Step 3.1: Agent-requested investigation

Allow a developer agent to request a parallel investigation without blocking:

```bash
warchief agent-update --task-id wc-XXX --investigate "What's the best approach for caching user sessions?"
```

This creates a lightweight investigation sub-task that runs in parallel. The results get appended to the parent task's scratchpad. The developer continues working and sees the results on next context refresh.

Changes:
- `__main__.py:cmd_agent_update()` — handle `--investigate` flag.
- `watcher.py` — detect investigation requests, spawn investigator agents in parallel.
- `models.py` — add `parent_task` field to link ad-hoc investigations to their source.
- `config.py` — add `PIPELINE_ADHOC_INVESTIGATION = ["investigation"]` — no review, no PR.

### Step 3.2: Automatic challenger for high-priority grouped tasks

For grouped tasks with priority >= 8, automatically spawn a challenger agent after the planner decomposes. The challenger reviews the decomposition plan and flags risks.

Changes:
- `watcher.py:_create_sub_tasks()` — after creating sub-tasks, if parent priority >= 8, create a challenger task that reviews the decomposition.
- `prompts/challenger.md` — already exists, review its prompt for group-level review capability.

### Step 3.3: Agent-to-agent messaging (future)

Full bidirectional messaging where agents can send questions to sibling agents:

```bash
warchief agent-update --task-id wc-XXX --ask-sibling wc-YYY "What interface does CalendarManager expose?"
```

The sibling's next spawn includes the question. Answer flows back via group scratchpad.

Changes:
- `task_store.py` — add `create_sibling_message()` method.
- `prime.py` — include sibling questions in agent context.
- `watcher.py` — route sibling messages.
- Agent prompts — instructions for reading/answering sibling questions.

---

## Implementation Order

```
Phase 1 (Single PR) — 3-4 steps, modifies: watcher.py, config.py, prime.py, spawner.py, pr_creator.md
  1.1 Sequential development for grouped tasks
  1.2 Group-level review gate
  1.3 Combined PR context
  1.4 Dashboard updates

Phase 2 (Communication) — 3 steps, modifies: scratchpad.py, prime.py, spawner.py, watcher.py
  2.1 Group scratchpad
  2.2 Sibling awareness in prompts
  2.3 Auto-append handoffs to group scratchpad

Phase 3 (Brainstorming) — 3 steps, modifies: watcher.py, models.py, __main__.py, config.py
  3.1 Agent-requested investigation
  3.2 Auto-challenger for high-priority groups
  3.3 Agent-to-agent messaging (future)
```

Each step should be developed, tested, and validated before moving to the next.

---

## Key Design Decisions to Make

1. **Sequential vs parallel development**: Sequential is safer (no merge conflicts) but slower. Could allow parallel for tasks that touch completely different directories.

2. **Group review scope**: Review ALL code on the branch (combined diff) or review each task's changes separately?

3. **Group lead selection**: First task created? Highest priority? Last to finish development?

4. **Investigation result delivery**: Append to scratchpad (async) or block parent until investigation completes (sync)?

5. **Max parallel investigators per task**: Prevent cost explosion — cap at 2?
