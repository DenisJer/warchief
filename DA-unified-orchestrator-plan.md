# Opus — Unified AI Agent Orchestration Framework

## Executive Summary

Opus is a multi-agent orchestration framework that coordinates AI coding agents working in parallel on software development tasks. It manages the full lifecycle — decomposition, parallel development, code review, security review, merging, and acceptance testing — without human intervention at each step.

**Why this plan exists.** Two independent analyses of Gastown (Go, 370K LOC, Erlang-style supervision) and Debussy (Python, 2.7K LOC, clean state machine) produced two orchestration plans with different strengths:

- **DA-Orchestrator plan**: Implementation-ready. SQL schemas, per-phase file lists, hook failure modes, quantified success metrics. Python-based. 10-week timeline.
- **Maestro plan**: Strategic architecture. Multi-runtime support, distributed execution via gRPC, plugin system, web dashboard. Go-based. 16-week timeline.

This plan merges them: **DA-Orchestrator's tactical precision for Phases 1-5** (the working system) and **Maestro's strategic vision for Phases 6-8** (the platform). The result is a system that ships a working orchestrator in 10 weeks and evolves into a production platform over the following 10.

**Core thesis**: The orchestrator is infrastructure, not intelligence. It provides transport, state, lifecycle, and recovery. Intelligence lives in the AI agents via prompt templates. The framework never reasons — it routes, enforces, and heals (Gastown's ZFC principle). The state machine is explicit and testable (Debussy's `TransitionResult` pattern). Hooks enforce invariants that prompts cannot guarantee. The system self-heals through hierarchical supervision.

---

## Design Principles

### 1. Zero Framework Cognition (Gastown)
Code handles transport, lifecycle, and state. All reasoning happens in AI agents via prompts. No hardcoded heuristics. The system improves automatically as models improve.

### 2. Explicit State Machines (Debussy)
Every workflow is a finite state machine with typed transitions. Transition logic is pure functions returning structured results without side effects. Testable, debuggable, auditable.

### 3. Hard Enforcement Over Soft Instructions (Debussy)
Agent constraints enforced via Claude Code hooks at the tool-use level, not just prompt instructions. Prompts define intent; hooks enforce invariants. Three-layer enforcement: prompt + hook + `--allowed-tools` CLI flags.

### 4. Hierarchical Self-Healing (Gastown)
Daemon monitors watcher. Watcher monitors agents. Mass failure detection prevents crash loops. Exponential backoff on restarts. The system converges toward healthy state without human intervention.

### 5. Radical Simplicity
Six vocabulary terms: Workspace, Task, Pipeline, Agent, Stage, Role. No Convoys, Molecules, Wisps, Polecats, GUPPs, MEOWs. Install in under a minute. `opus init && opus plan "Build a REST API"` has agents working in 60 seconds.

### 6. Process Isolation, Shared State
Each agent runs as a separate OS process in its own git worktree. Coordination through shared SQLite (WAL mode), not shared memory or message passing.

### 7. No Magic Constants
All thresholds externalized to config. No `MAX_TOTAL_SPAWNS = 20` buried in source. Every numeric value lives in `config.toml` or role TOML files.

### 8. Fail Open With Logging
When hooks crash, allow the operation and log the failure. Failing closed blocks the entire pipeline. Failing open with aggressive logging is the safer degraded mode.

---

## Tech Stack

### Language: Python 3.11+ (Phases 1-5) → Go extension (Phase 7)

**Why Python first:**
- Debussy proves zero-dependency Python is viable for this domain
- Prompt engineering, state machine logic, and role config are the highest-leverage iteration areas — Python enables fastest iteration
- Stdlib covers all needs: `subprocess`, `sqlite3`, `threading`, `pathlib`, `shlex`, `json`, `tempfile`, `tomllib`, `signal`, `fcntl`
- The orchestrator bottleneck is I/O and LLM latency, not CPU — Go's advantages don't apply here
- Lower contribution barrier for the AI tooling community

**Why Go later (Phase 7):**
- Single static binary for distribution (no Python runtime requirement)
- The core state machine, schemas, and role definitions are language-agnostic — porting is mechanical
- Go rewrites the daemon and spawner while Python remains the plugin/prompt SDK
- GoReleaser for cross-platform releases (Linux/macOS/Windows/FreeBSD)

### Core Dependencies

| Package | Status | Purpose |
|---|---|---|
| Python stdlib | Required | Everything: subprocess, sqlite3, threading, pathlib, shlex, json, tempfile, tomllib, signal, fcntl |
| `watchdog` 3.x | Optional | Filesystem event watching for nudge delivery + heartbeat detection. Falls back to polling. |
| `rich` 13.x | Optional | Terminal dashboard, kanban board, live feed. Falls back to plain text. |
| `pytest` 7.x | Dev only | Testing framework |
| `ruff` | Dev only | Linting |
| `mypy` | Dev only | Type checking |

**Zero Python dependencies in core runtime.** `watchdog` and `rich` are optional — system works in degraded mode without them.

### What NOT to Use

| Dependency | Why Not |
|---|---|
| **Dolt** | External server SPOF, commit graph pollution, operational overhead. SQLite WAL is sufficient. |
| **tmux (for agents)** | Hard dep excludes headless/CI environments. Agents are managed subprocesses. tmux offered via `--tmux` flag for human debugging only. |
| **asyncio** | I/O-bound but not latency-sensitive. Threads + blocking subprocess is simpler and sufficient. |
| **Redis / RabbitMQ** | SQLite `messages` table IS the mail queue. Filesystem files ARE the nudge channel. |
| **LangChain / CrewAI** | Agents ARE Claude Code processes. No API abstraction needed. Framework overhead without benefit. |
| **beads / bd CLI** | External dependency coupling. Task tracking embedded in SQLite directly. |
| **CGO** | When Go phase arrives, use `modernc.org/sqlite` (pure Go) for true cross-compilation. |

### Distribution

| Phase | Method |
|---|---|
| Phases 1-5 | `pipx install opus-orchestrator` → `opus` CLI |
| Phase 7+ | Single Go binary via Homebrew, `curl` installer, `go install`, GoReleaser |
| Versioning | Date-based: `YYYY.M.D.N`, CI auto-bumps on main push |

---

## Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              OPUS                                         │
│                                                                           │
│  ┌──────────────┐      ┌─────────────────────────────────────────────┐  │
│  │  CLI / API   │─────▶│                DAEMON                        │  │
│  │  (opus CLI)  │      │  30s heartbeat, watcher health, scheduler,  │  │
│  └──────────────┘      │  backup export, mass death detection         │  │
│                         └──────────────┬──────────────────────────────┘  │
│                                        │ monitors + restarts              │
│  ┌─────────────────────────────────────▼─────────────────────────────┐  │
│  │                           WATCHER                                  │  │
│  │  ┌──────────────┐  ┌────────────────┐  ┌──────────────────────┐  │  │
│  │  │  Poll Loop   │  │  State Machine │  │  Pipeline Checker    │  │  │
│  │  │  5s + fs     │  │  (transitions) │  │  (scan + spawn)      │  │  │
│  │  │  events      │  │  pure funcs    │  │  priority + deps     │  │  │
│  │  └──────────────┘  └────────────────┘  └──────────────────────┘  │  │
│  └──────────┬─────────────────────────────────────┬──────────────────┘  │
│             │ spawns                               │ monitors             │
│  ┌──────────▼─────────────────────────────────────▼──────────────────┐  │
│  │                        AGENT POOL                                  │  │
│  │                                                                    │  │
│  │  ┌───────────┐ ┌───────────┐ ┌──────────┐ ┌──────────┐          │  │
│  │  │ CONDUCTOR │ │ DEVELOPER │ │ REVIEWER │ │INTEGRATOR│ ...       │  │
│  │  │ (1 inst.) │ │ (n inst.) │ │ (n inst.)│ │ (1 inst.)│          │  │
│  │  │ main repo │ │ worktree  │ │ detached │ │ detached │          │  │
│  │  │ Opus model│ │ Sonnet    │ │ Sonnet   │ │ Haiku    │          │  │
│  │  └─────┬─────┘ └─────┬─────┘ └────┬─────┘ └────┬─────┘          │  │
│  │        │ identity     │ identity    │ identity    │ identity       │  │
│  │        │ + sandbox    │ + sandbox   │ + sandbox   │ + sandbox      │  │
│  │        │ + session    │ + session   │ + session   │ + session      │  │
│  │  └────────────────────────────────────────────────────────────────┘  │
│  │                                                                       │
│  │  ┌────────────────────────────────────────────────────────────────┐  │
│  │  │                  PERSISTENCE LAYER                              │  │
│  │  │  SQLite (WAL)        Git Worktrees       JSONL Event Log       │  │
│  │  │  tasks, agents,      .opus-worktrees/    pipeline_events.jsonl │  │
│  │  │  messages, events,   per-agent isolated   rotated at 100MB     │  │
│  │  │  schedule_contexts   symlinks → .opus/    30 days retained     │  │
│  │  └────────────────────────────────────────────────────────────────┘  │
│  │                                                                       │
│  │  ┌────────────────────────────────────────────────────────────────┐  │
│  │  │                  COMMUNICATION LAYER                            │  │
│  │  │  NUDGE (ephemeral)              MAIL (persistent)              │  │
│  │  │  file + SIGUSR1 signal          SQLite messages table          │  │
│  │  │  zero DB cost                   survives agent death           │  │
│  │  │  lost if agent dead             5 types: DONE, BLOCKED,        │  │
│  │  │                                 HANDOFF, HELP, ESCALATE        │  │
│  │  └────────────────────────────────────────────────────────────────┘  │
│  │                                                                       │
│  │  ┌────────────────────────────────────────────────────────────────┐  │
│  │  │                  HOOK ENFORCEMENT                               │  │
│  │  │  PreToolUse: validate-opus-transition.py (shlex-safe parsing)  │  │
│  │  │  Stop:       verify-task-updated.py                            │  │
│  │  │  PreCompact: save-conductor-context.py                         │  │
│  │  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

### Three-Layer Agent Lifecycle (from Gastown)

Every agent has three layers with different lifetimes:

1. **Identity** (permanent): name, role, capability record, work history, total tasks completed. Never destroyed. Survives everything.
2. **Sandbox** (persistent): git worktree, assigned branch, symlinks. Preserved between assignments, repaired on reuse.
3. **Session** (ephemeral): the Claude Code process + context window. Can die, be killed, or restart without losing the other two layers.

This eliminates the "restart = lose everything" problem. Context compaction? Session dies, identity and sandbox remain. Agent crashes? Sandbox is intact for retry.

---

## Agent Role System

### Role Definitions

| Role | Count | Model | Worktree | Writes Code? | Allowed Tools |
|------|-------|-------|----------|--------------|---------------|
| **Conductor** | 1 | Opus | Main repo | No | All except destructive Bash |
| **Developer** | ≤6 | Sonnet | `feature/{task_id}` | Yes | Bash, Edit, Write, Read, Glob, Grep |
| **Reviewer** | ≤4 | Sonnet | Detached at feature branch | No | Read, Glob, Grep, Bash (read-only) |
| **Security Reviewer** | ≤2 | Opus | Detached at feature branch | No | Read, Glob, Grep, Bash (read-only) |
| **Integrator** | 1 | Haiku | Detached at base | Yes (merges) | Bash (git only), Read, Edit |
| **Tester** | 1 | Sonnet | Detached at base (post-merge) | No | Bash (test runners), Read |
| **Investigator** | ≤4 | Sonnet | Main repo (no worktree) | No | Read, Glob, Grep, WebSearch, Bash (read-only) |
| **Challenger** | optional | Sonnet | Main repo | No | Read, Glob, Grep, Bash (read-only) |

### Role Configuration (TOML)

Each role defined in `roles/*.toml`:

```toml
# roles/developer.toml
[identity]
name = "developer"
prompt_file = "prompts/developer.md"
max_concurrent = 6

[model]
default = "claude-sonnet-4-6"
fallback = "claude-haiku-4-5"

[permissions]
allowed_tools = ["Bash", "Edit", "Write", "Read", "Glob", "Grep"]
disallowed_bash_commands = ["rm -rf /", "sudo", "chmod 777"]

[health]
timeout_seconds = 3600
max_crashes = 3
max_rejections = 3
max_total_spawns = 20

[worktree]
type = "branch"          # "branch" | "detached" | "none"
branch_template = "feature/{task_id}"
```

### Pipeline Template (TOML)

```toml
# pipelines/default.toml
[stages]
development     = { role = "developer", priority = 6 }
reviewing       = { role = "reviewer", priority = 4 }
security-review = { role = "security_reviewer", priority = 3, requires_label = "security" }
merging         = { role = "integrator", priority = 2 }
acceptance      = { role = "tester", priority = 1 }

[routing]
security = { insert_stage = "security-review", after = "reviewing" }
frontend = { prompt_block = "visual_verification" }

[defaults]
max_spawns_per_cycle = 2
poll_interval_seconds = 5
rejection_cooldown_seconds = 60
```

### Prompt System

- **System prompt**: Static `.md` file per role in `prompts/`. Version-controlled. Hot-reloadable (re-read on each spawn).
- **User message**: Task-specific context injected as Claude user message:
  ```
  Task: opus-042
  Base branch: feature/user-auth
  Labels: security, frontend
  Description: Add password reset flow with email verification
  Dependencies: [opus-039 (closed), opus-040 (closed)]
  ```
- **Prime context** (from Gastown): Before an agent begins work, `prime.py` outputs role instructions summary, unread mail, handoff context, and current task details — piped to agent stdin.
- **Prompt blocks**: `VISUAL_VERIFICATION_BLOCK` replaced with Playwright instructions when `frontend` label present. Empty string otherwise.
- **No `--dangerously-skip-permissions` ever.** Each role generates explicit `--allowed-tools` from its TOML definition.

---

## State Machine

### Core Abstraction

```python
@dataclass(frozen=True)
class TransitionResult:
    status: str | None = None           # New status, or None for no change
    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    next_stage: str | None = None       # Stage to advance to
    next_role: str | None = None        # Role for next stage
    failure_reason: str | None = None   # Why transition was blocked
    requires_conductor: bool = False    # Escalate to conductor?

    @property
    def has_changes(self) -> bool:
        return bool(self.status or self.add_labels or self.remove_labels or self.next_stage)
```

### Transition Logic (Pure Functions)

```python
def dispatch_transition(
    task: TaskRecord,
    agent: AgentRecord,
    pipeline: PipelineTemplate
) -> TransitionResult:
    """Pure function. No side effects. No DB calls. No subprocess calls."""
    ...

def execute_transition(result: TransitionResult, db: TaskStore) -> None:
    """Apply result to database in a single transaction."""
    ...
```

### State Diagram

```
States: open | in_progress | blocked | closed
Stages: development → reviewing → [security-review] → merging → acceptance → done

Transitions (watcher-owned):

  (development, agent_done, has_commits)      → stage:reviewing
  (development, agent_done, no_commits)       → retry (max 3), then block
  (development, agent_done, rejected)         → decrement rejection budget; retry or block
  (development, agent_crashed)                → increment crash_count; retry (max 3) or block

  (reviewing, approved)                       → stage:merging (or stage:security-review if security label)
  (reviewing, rejected)                       → stage:development with rejection context
  (reviewing, crashed)                        → retry reviewing

  (security-review, approved)                 → stage:merging
  (security-review, rejected)                 → stage:development (counts as 2x rejection)

  (merging, merged + verified)                → stage:acceptance (trigger dep resolution)
  (merging, merge_failed)                     → stage:development with conflict context
  (merging, unverified)                       → retry merging

  (acceptance, passed)                        → closed, cleanup worktrees
  (acceptance, failed)                        → blocked, conductor must triage

  (any, agent_sets_blocked)                   → remove stage, park for conductor
  (any, premature_close_at_non_terminal)      → re-open and advance (defense against prompt non-compliance)
```

### Ownership Boundaries

| Entity | Owns |
|--------|------|
| **Watcher** | All stage label mutations. Transitions between stages. |
| **Agents** | Status mutations (`open` ↔ `in_progress`). Adding `rejected` label. |
| **Conductor** | Task creation. `blocked` resolution. Dependency declaration. |
| **Hooks** | Enforce these boundaries. Block violations at tool-use level. |

---

## Persistence Layer

### SQLite Schema

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,           -- "opus-042"
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,          -- open | in_progress | blocked | closed
    stage TEXT,                    -- current stage label or NULL
    labels TEXT,                   -- JSON array ["security", "frontend"]
    deps TEXT,                     -- JSON array of task IDs
    assigned_agent TEXT,           -- FK to agents.id
    base_branch TEXT,
    rejection_count INTEGER DEFAULT 0,
    spawn_count INTEGER DEFAULT 0,
    crash_count INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    type TEXT DEFAULT 'feature',   -- feature | bug | investigation
    created_at REAL,
    updated_at REAL,
    closed_at REAL,
    version INTEGER DEFAULT 0      -- optimistic locking
);

CREATE TABLE agents (
    id TEXT PRIMARY KEY,           -- "developer-beethoven"
    role TEXT NOT NULL,
    status TEXT NOT NULL,          -- idle | alive | zombie | crashed | retired
    current_task TEXT,
    worktree_path TEXT,
    pid INTEGER,
    model TEXT,
    spawned_at REAL,
    last_heartbeat REAL,
    crash_count INTEGER DEFAULT 0,
    total_tasks_completed INTEGER DEFAULT 0
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    from_agent TEXT,
    to_agent TEXT NOT NULL,
    message_type TEXT,             -- DONE | BLOCKED | HANDOFF | HELP | ESCALATE
    body TEXT NOT NULL,
    persistent INTEGER DEFAULT 0,  -- 0 = nudge, 1 = mail
    read_at REAL,
    created_at REAL
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    agent_id TEXT,
    event_type TEXT NOT NULL,      -- spawn | advance | reject | block | timeout | crash | merge | close
    details TEXT,                  -- JSON
    actor TEXT,                    -- agent identity for attribution
    created_at REAL
);

CREATE TABLE schedule_contexts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending | dispatched | consumed | failed
    created_at REAL,
    dispatched_at REAL
);
```

**WAL mode**: `PRAGMA journal_mode=WAL;` on connection open. Concurrent readers while writer active.

**Optimistic locking**: `tasks.version` incremented on every update. `WHERE version = {read_version}` prevents lost updates when watcher and daemon write simultaneously.

**Atomic file writes**: All non-SQLite files use `tempfile.mkstemp` + `os.replace()`.

### Worktree Layout

```
project_root/
├── .opus/
│   ├── opus.db                    # SQLite — shared by all agents via symlink
│   ├── config.toml                # Workspace configuration
│   ├── watcher_state.json         # Watcher in-memory state checkpoint
│   ├── watcher.lock               # Single-watcher enforcement
│   ├── daemon.pid                 # Daemon PID file
│   ├── watcher.log                # Rotated daily, 30 days retained
│   ├── pipeline_events.jsonl      # Rotated at 100MB, 10 segments retained
│   ├── conductor-context.md       # Volatile conductor session memory
│   ├── conductor-history.md       # Append-only conductor history (never cleared)
│   ├── nudges/                    # Ephemeral nudge files per agent
│   │   └── {agent_id}/
│   ├── heartbeats/                # Agent heartbeat timestamps
│   │   └── {agent_id}
│   └── backup/
│       ├── 2026-03-13-snapshot.jsonl.gz
│       └── ...
├── .opus-worktrees/
│   ├── developer-beethoven/       # git worktree on feature/{task_id}
│   │   ├── .opus -> ../../.opus   # symlink — shares DB and config
│   │   └── [project files]
│   ├── reviewer-chopin/           # detached at origin/feature/{task_id}
│   │   ├── .opus -> ../../.opus
│   │   └── [project files]
│   └── integrator-liszt/          # detached at origin/{base}
│       ├── .opus -> ../../.opus
│       └── [project files]
└── [main project files]
```

---

## Communication System

### Two Channels, Different Durability

| Channel | Mechanism | Durability | DB Cost | Use Cases |
|---------|-----------|-----------|---------|-----------|
| **Nudge** | File in `.opus/nudges/{id}/` + `SIGUSR1` to process | Ephemeral — lost if agent dead | 0 | heartbeat ping, "you have mail", "dep resolved" |
| **Mail** | Row in `messages` table | Survives agent death | 1 row | DONE, BLOCKED, HANDOFF, HELP, ESCALATE |

**Only 5 message types permitted as mail.** All other communication must use nudge. This prevents SQLite bloat from chatty agents (the Dolt commit-graph explosion Gastown documents).

### Conductor Notifications

Every 12 watcher ticks (60s), the watcher sends a summary nudge to the conductor listing blocked/rejected tasks requiring attention. The conductor reads this and intervenes.

---

## Hook Enforcement

Three Python scripts installed into each agent's `.claude/settings.json`:

### `validate-opus-transition.py` (PreToolUse — on Bash)

```
1. Read hook input JSON from stdin
2. If tool is not Bash → allow
3. Parse command with shlex.split() (NOT command.split())
4. If command is not 'opus' → allow
5. If subcommand is 'update':
   - Read OPUS_ROLE and OPUS_TASK from env
   - Validate: agent can only update its own OPUS_TASK
   - Validate: agent cannot add/remove stage labels (only watcher can)
   - Validate: status transition is allowed for this role
   - If invalid → {"decision": "block", "reason": "..."}
6. If subcommand is 'create' → block (only conductor can create tasks)
7. All other opus commands → allow
8. On any exception → log to .opus/hook_errors.log, allow (fail open)
```

### `verify-task-updated.py` (Stop)

```
1. Read OPUS_TASK from env
2. Query: opus show OPUS_TASK --json
3. If status == 'in_progress' → block: "Update task status before exiting"
4. Otherwise → allow exit
```

### `save-conductor-context.py` (PreCompact)

```
1. Fires before Claude context window is compacted
2. Echo to stdout: "IMPORTANT: Write your current state to conductor-context.md NOW"
3. Claude reads this and persists state before compaction
```

---

## Failure Handling

### Detection & Recovery Matrix

| Failure | Detection | Recovery | Max Retries |
|---------|-----------|----------|-------------|
| Agent crash (exit ≠ 0) | `proc.poll()` returns non-zero | Increment crash_count, reset task to `open` | 3 |
| Agent timeout | `now - spawned_at > role_timeout` | SIGTERM → 10s → SIGKILL, reset task | — |
| Zombie agent | Heartbeat file stale >120s | `os.kill(pid, 0)` verify, then SIGTERM/SIGKILL | — |
| Empty branch | `git rev-list --count` == 0 after developer completes | Retry development | 3 |
| Reviewer rejection | `rejected` label on task | 60s cooldown, back to development | 3 (then block) |
| Security rejection | `rejected` label from security reviewer | Back to development, counts as 2x | 3 (effective 1.5) |
| Premature close | Agent sets `closed` at non-terminal stage | Re-open and advance | — |
| Merge failed | Integrator adds `rejected` with conflict details | Back to development with context | 2 |
| Merge unverified | `git merge-base --is-ancestor` fails | Retry merge | 2 |
| Orphaned task | `in_progress` + no live agent (on watcher startup) | Reset to `open` | — |
| Watcher crash | Daemon detects missing watcher process | Restart watcher, orphan recovery | — |
| Mass death | 3+ agent deaths within 30s | Pause all spawning, alert conductor | — |
| Hook crash | Exception in hook script | Fail open, log to `.opus/hook_errors.log` | — |
| Watcher crash mid-transition | Incomplete DB write | Single-transaction wraps both label mutations. On restart, `recover_orphans()` re-applies last stage from events log. | — |

### Crash Loop Prevention (from Gastown)

Exponential backoff per agent: 1s → 2s → 4s → 8s → ... → max 5 minutes between restart attempts. Sliding window counter: 3 deaths in 30 seconds triggers system-wide pause.

---

## End-to-End Pipeline Flow

```
1. Human: opus start "build user authentication system"
   → CLI creates tmux layout (conductor pane, board pane, watcher pane)
   → Conductor spawns with opus model
   → Watcher starts: opus watch
   → Board auto-refresh: watch -n 5 'opus board'

2. Conductor runs:
   → Reads project context and existing code
   → Decomposes into 5-8 file-isolated tasks
   → opus create "Add User model" --type feature
   → opus create "Add auth endpoints" --deps opus-001 --labels security
   → opus create "Add login form" --deps opus-002 --labels frontend
   → opus release opus-001 --stage development

3. Watcher tick (every 5s):
   → check_pipeline() finds opus-001: stage:development, status:open
   → Preflight: base branch exists? Task non-empty? Slot available?
   → spawn_agent("developer", "opus-001")
     → Creates worktree: .opus-worktrees/developer-beethoven/
     → Spawns: claude --allowed-tools Bash,Edit,Write,Read,Glob,Grep
                      --model claude-sonnet-4-6
                      --system-prompt "$(cat prompts/developer.md)"
                      "Task: opus-001\nBase: feature/user-auth\n..."
     → Sets OPUS_ROLE=developer, OPUS_TASK=opus-001

4. Developer-beethoven:
   → opus update opus-001 --status in_progress
   → Implements, writes tests, commits, pushes feature/opus-001
   → opus update opus-001 --status open
   → Exits cleanly

5. Watcher detects completion:
   → proc.poll() returns 0
   → Checks: branch has commits? Yes.
   → dispatch_transition() → TransitionResult(remove stage:development, add stage:reviewing)
   → execute_transition() in single SQLite transaction
   → Log advance event

6. Watcher spawns reviewer-chopin in detached worktree at feature/opus-001
   → Reviewer approves → watcher advances to stage:merging

7. Integrator-liszt merges feature/opus-001 into feature/user-auth
   → Watcher verifies: git merge-base --is-ancestor ✓
   → Advances to stage:acceptance
   → release_ready() unblocks opus-002 (dep on opus-001 now closed)

8. All tasks complete → Tester runs acceptance suite → Conductor notifies human
```

---

## Implementation Phases

### Phase 1: Foundation (Weeks 1-2)

**Goal**: Working task store, CLI skeleton, tested state machine.

**Tasks:**
1. `opus/task_store.py` — SQLite wrapper with WAL, schema, atomic writes, optimistic locking
2. `opus/models.py` — `TaskRecord`, `AgentRecord`, `MessageRecord`, `EventRecord` frozen dataclasses
3. `opus/state_machine.py` — `TransitionResult`, `dispatch_transition()` (pure), `execute_transition()`
4. `opus/__main__.py` — argparse CLI: `start`, `watch`, `board`, `create`, `update`, `show`, `list`, `release`, `config`, `pause`, `resume`, `kill-agent`
5. `opus/config.py` — Constants, `Config` dataclass, `read_config()` / `write_config()` atomic
6. `opus/roles/` — TOML files for all 8 roles. `RoleRegistry` class.
7. `tests/test_state_machine.py` — **40+ test cases** covering every transition path, edge case, security routing, premature close, unverified merge, empty branch
8. `tests/test_task_store.py` — CRUD, concurrent writes, optimistic locking, WAL behavior
9. `pyproject.toml`, `.github/workflows/ci.yml` (ruff + mypy + pytest)

**Files to create:**
```
opus/__init__.py
opus/__main__.py
opus/config.py
opus/models.py
opus/state_machine.py
opus/task_store.py
opus/roles/__init__.py
opus/roles/conductor.toml
opus/roles/developer.toml
opus/roles/reviewer.toml
opus/roles/security_reviewer.toml
opus/roles/integrator.toml
opus/roles/tester.toml
opus/roles/investigator.toml
opus/roles/challenger.toml
tests/__init__.py
tests/conftest.py
tests/test_state_machine.py
tests/test_task_store.py
tests/test_config.py
pyproject.toml
.github/workflows/ci.yml
```

**Milestones:**
- `opus create "task"` → writes to SQLite
- `opus list` → reads back with correct status
- State machine tests green with >95% coverage
- Zero external dependencies

---

### Phase 2: Agent Management (Weeks 3-4)

**Goal**: Watcher loop, agent spawning, lifecycle management, hook enforcement.

**Tasks:**
1. `opus/worktree.py` — create/remove/repair worktree, symlink `.opus/`
2. `opus/preflight.py` — base branch exists? Task non-empty? Slot available? Deps closed?
3. `opus/spawner.py` — COMPOSERS list (80+ names), `spawn_agent()`, builds Claude CLI command from role TOML permissions, registers in DB
4. `opus/watcher.py` — `Watcher` class, 5s poll loop, `cleanup_finished()`, `check_timeouts()`, `reset_orphans()`, state checkpoint
5. `opus/prime.py` — Generate startup context (role summary, unread mail, handoff context, task record)
6. `opus/heartbeat.py` — Agent-side: write `.opus/heartbeats/{id}` every 60s. Watcher-side: detect zombies.
7. `.claude/hooks/validate-opus-transition.py` — PreToolUse with `shlex.split()`
8. `.claude/hooks/verify-task-updated.py` — Stop hook
9. `.claude/hooks/save-conductor-context.py` — PreCompact hook
10. `opus/hooks.py` — `install_hooks()`, atomic write to `.claude/settings.json`

**Files to create:**
```
opus/watcher.py
opus/spawner.py
opus/worktree.py
opus/preflight.py
opus/prime.py
opus/heartbeat.py
opus/hooks.py
.claude/hooks/validate-opus-transition.py
.claude/hooks/verify-task-updated.py
.claude/hooks/save-conductor-context.py
tests/test_spawner.py
tests/test_worktree.py
tests/test_preflight.py
tests/test_hooks.py
```

**Milestones:**
- `opus watch` runs without crashing
- Single developer agent spawns, implements, exits, watcher detects and transitions
- Zombie detection: kill agent → watcher detects and resets task within 2 ticks
- Hook enforcement: developer attempt to add stage label → blocked

---

### Phase 3: Pipeline & Routing (Weeks 5-6)

**Goal**: Full multi-stage pipeline, label-based routing, all role prompts, monitoring.

**Tasks:**
1. `opus/pipeline_checker.py` — `check_pipeline()`, `release_ready()`, priority sorting, spawn budget, integrator queue serialization
2. `opus/pipeline_template.py` — Load/validate `pipelines/*.toml`, build `STAGE_TO_ROLE` map
3. `opus/merge_verifier.py` — `git merge-base --is-ancestor` verification
4. `opus/metrics.py` — Read JSONL, compute stage averages, per-task traces, rejection/timeout counts
5. `opus/board.py` — Kanban board via `rich`. One column per stage. Agent assignments. Time in stage. `opus board --watch` for live updates.
6. All role prompts: `prompts/conductor.md` (218+ lines, task decomposition rules, good/bad examples), `developer.md`, `reviewer.md`, `security_reviewer.md`, `integrator.md`, `tester.md`, `investigator.md`, `consolidator.md`, `challenger.md`
7. Visual blocks: `prompts/visual_web.md`, `prompts/visual_ios.md`
8. Skills: `.claude/skills/task-workflow/SKILL.md`, `code-standards/SKILL.md`, `git-strategy/SKILL.md`
9. `opus/cli.py` — `cmd_start()`: full tmux layout creation, conductor spawn
10. `pipelines/default.toml`, `pipelines/investigation.toml`

**Files to create:**
```
opus/pipeline_checker.py
opus/pipeline_template.py
opus/merge_verifier.py
opus/metrics.py
opus/board.py
opus/cli.py
pipelines/default.toml
pipelines/investigation.toml
prompts/conductor.md
prompts/developer.md
prompts/reviewer.md
prompts/security_reviewer.md
prompts/integrator.md
prompts/tester.md
prompts/investigator.md
prompts/consolidator.md
prompts/challenger.md
prompts/visual_web.md
prompts/visual_ios.md
.claude/skills/task-workflow/SKILL.md
.claude/skills/code-standards/SKILL.md
.claude/skills/git-strategy/SKILL.md
tests/test_pipeline_checker.py
tests/test_pipeline_template.py
tests/test_merge_verifier.py
```

**Milestones:**
- `opus start "build user auth"` → full pipeline runs autonomously
- Task moves through all 5 stages without intervention
- Rejection loop: 3 rejections → blocked → conductor notified
- `security` label routes through security-review stage
- `opus board` renders correctly
- `opus metrics` shows stage durations

---

### Phase 4: Resilience & Monitoring (Weeks 7-8)

**Goal**: Daemon, self-healing, communication layer, capacity control, backup/restore.

**Tasks:**
1. `opus/daemon.py` — Background process, PID file, 30s heartbeat, watcher health check, capacity-controlled scheduler dispatch, mass death detection
2. `opus/scheduler.py` — Read `schedule_contexts`, check capacity, dispatch incrementally, `fcntl.flock` for double-dispatch prevention
3. `opus/communication.py` — `send_nudge()` (file + SIGUSR1), `send_mail()`, `get_unread_mail()`
4. `opus/recovery.py` — `recover_orphans()`, `recover_worktrees()`, `recover_zombie_agents()`
5. `opus/backup.py` — JSONL export, compression, restore, retain 30 days
6. `opus/handoff.py` — Session cycling with handoff mail (from Gastown)
7. `opus/diagnostics.py` — Log tail extraction, failure comment formatting
8. `opus/feed.py` — Real-time event feed via `rich.live`. `opus feed` subcommand.
9. Log rotation: `pipeline_events.jsonl` at 100MB, 10 segments retained
10. `watcher.log` rotated daily, 30 days retained

**Files to create:**
```
opus/daemon.py
opus/scheduler.py
opus/communication.py
opus/recovery.py
opus/backup.py
opus/handoff.py
opus/diagnostics.py
opus/feed.py
tests/test_daemon.py
tests/test_scheduler.py
tests/test_communication.py
tests/test_recovery.py
tests/test_backup.py
```

**Milestones:**
- `opus daemon start` → runs in background, watcher auto-restarts on crash
- Mass death: kill all agents → daemon detects within 60s, pauses dispatch
- `opus backup` → compressed JSONL snapshot. `opus restore` loads it.
- Nudge delivery verified end-to-end
- Capacity control: `max_total_agents=3`, submit 10 tasks, only 3 spawn simultaneously

---

### Phase 5: Polish & Evaluation (Weeks 9-10)

**Goal**: Model evaluation, multi-session, health checks, documentation, end-to-end validation.

**Tasks:**
1. `eval/` — Model evaluation framework. Test cases per role. Run against Opus/Sonnet/Haiku. Identify where cheap models match expensive ones.
2. `opus/sessions.py` — Multi-project session management. `opus sessions`, `opus connect {project}`
3. `opus/doctor.py` — Health checks: SQLite accessible, worktrees consistent, agents have heartbeats, watcher running, disk space adequate
4. Log rotation implementation
5. End-to-end test: real feature through full pipeline
6. Documentation: `docs/quickstart.md`, `docs/concepts/`, `docs/prompts.md`
7. Release workflow: version bump, CHANGELOG, GitHub release

**Files to create:**
```
opus/sessions.py
opus/doctor.py
eval/__init__.py
eval/runner.py
eval/README.md
eval/test_cases/conductor_decomposition.json
eval/test_cases/reviewer_approval.json
eval/test_cases/security_reviewer.json
eval/test_cases/integrator_merge.json
docs/quickstart.md
docs/concepts/agent-roles.md
docs/concepts/pipeline-stages.md
docs/concepts/communication.md
docs/concepts/state-machine.md
docs/prompts.md
CHANGELOG.md
```

**Milestones:**
- Model eval identifies ≥2 roles where Haiku matches Sonnet quality
- `opus doctor` reports green on healthy system
- Two projects running simultaneously without interference
- End-to-end test completes without human intervention
- `pipx install opus-orchestrator` works on fresh machine

---

### Phase 6: TUI & Observability (Weeks 11-13)

**Goal**: Interactive terminal dashboard, OpenTelemetry, cost tracking.

*This phase shifts from DA-Orchestrator's implementation style to Maestro's strategic vision.*

**Tasks:**
1. Interactive TUI dashboard (bubbletea-inspired, using `textual` in Python):
   - Agent tree view (supervision hierarchy, status, current task)
   - Task kanban board (live-updating)
   - Event stream (real-time pipeline events)
   - Problems view (stuck agents, blocked tasks, crash loops)
2. OpenTelemetry integration:
   - Metrics: agent spawn rate, stage duration histograms, rejection rates, throughput
   - Export to VictoriaMetrics / Prometheus
3. Cost tracking:
   - Track token usage per agent per task (parse Claude CLI output)
   - Per-task and per-role cost aggregation
   - Cost budget in config: pause pipeline when budget exceeded
4. `opus dashboard` — launch interactive TUI
5. `opus costs` — show cost breakdown

---

### Phase 7: Go Binary & Distribution (Weeks 14-16)

**Goal**: Rewrite daemon + spawner in Go for single-binary distribution. Python remains for plugins/prompts.

**Tasks:**
1. Go module: `go mod init github.com/{org}/opus`
2. Port `task_store.py` → Go with `modernc.org/sqlite` (pure Go, no CGO)
3. Port `state_machine.py` → Go with same `TransitionResult` pattern
4. Port `daemon.py`, `watcher.py`, `spawner.py`, `scheduler.py` → Go
5. Port `hooks.py` → Go (hooks themselves remain Python — they run in Claude Code's runtime)
6. CLI via `spf13/cobra`
7. GoReleaser for cross-platform releases
8. Homebrew formula + `curl` installer
9. Forward-only binary safety check (from Gastown — prevent accidental downgrades)
10. Atomic binary replacement (copy to `.new`, then rename)

**Result**: `brew install opus` or `curl -sSL opus.dev/install | sh` → single binary, zero runtime deps.

---

### Phase 8: Platform (Weeks 17-20)

**Goal**: Multi-runtime, distributed execution, plugin system, web dashboard.

**Tasks:**
1. **Multi-runtime support** — pluggable `Runtime` interface:
   ```go
   type Runtime interface {
       Name() string
       SpawnAgent(config AgentConfig) (*exec.Cmd, error)
       SupportsHooks() bool
   }
   ```
   Implementations: Claude Code (primary), Codex CLI, Gemini CLI, generic CLI fallback.

2. **Plugin system** — custom roles, custom transitions, custom hooks:
   - Go plugin interface for compiled extensions
   - Python subprocess SDK for scripted plugins
   - Plugin directory: `~/.opus/plugins/`

3. **Web dashboard** — htmx-based, served from binary:
   - Same views as TUI: agent tree, kanban, events, problems
   - Authentication via local token
   - Webhook notifications (Slack, Discord, HTTP)

4. **Container sandboxing** — Docker/Podman for untrusted agent execution:
   - Developer agents can optionally run in containers
   - mTLS proxy for secure host communication (simplified from Gastown's approach)

5. **Distributed execution** — multi-machine coordination:
   - gRPC interface: remote daemon can accept agent spawning requests
   - Central scheduler distributes across machines
   - Shared SQLite replaced by PostgreSQL adapter for network-accessible state

6. **YAML pipeline definitions** — custom workflows beyond default dev→review→merge

---

## Directory Structure (Final)

```
opus/                                     # Repository root
├── pyproject.toml
├── CHANGELOG.md
├── Makefile
│
├── opus/                                 # Python package (Phases 1-5)
│   ├── __init__.py
│   ├── __main__.py                       # CLI entry point
│   ├── cli.py                            # Command implementations
│   ├── config.py                         # Config dataclass, I/O
│   ├── models.py                         # Frozen dataclasses
│   ├── task_store.py                     # SQLite wrapper
│   ├── state_machine.py                  # Pure transitions
│   ├── watcher.py                        # Central orchestration loop
│   ├── pipeline_checker.py               # Scan + spawn
│   ├── pipeline_template.py              # Load pipelines/*.toml
│   ├── spawner.py                        # COMPOSERS + subprocess spawn
│   ├── worktree.py                       # Git worktree lifecycle
│   ├── preflight.py                      # Pre-spawn validation
│   ├── prime.py                          # Context injection
│   ├── heartbeat.py                      # Agent heartbeat
│   ├── hooks.py                          # Hook installation
│   ├── communication.py                  # Nudge + mail
│   ├── handoff.py                        # Session cycling
│   ├── merge_verifier.py                 # Post-merge verification
│   ├── recovery.py                       # Orphan + zombie recovery
│   ├── scheduler.py                      # Capacity-controlled dispatch
│   ├── daemon.py                         # Background daemon
│   ├── backup.py                         # JSONL export/restore
│   ├── diagnostics.py                    # Log tail + failure formatting
│   ├── metrics.py                        # Pipeline analytics
│   ├── board.py                          # Kanban board (rich)
│   ├── feed.py                           # Real-time event feed
│   ├── sessions.py                       # Multi-project sessions
│   ├── doctor.py                         # Health checks
│   └── roles/                            # Role TOML definitions
│       ├── __init__.py                   # RoleRegistry class
│       ├── conductor.toml
│       ├── developer.toml
│       ├── reviewer.toml
│       ├── security_reviewer.toml
│       ├── integrator.toml
│       ├── tester.toml
│       ├── investigator.toml
│       └── challenger.toml
│
├── cmd/                                  # Go entry points (Phase 7+)
│   └── opus/
│       └── main.go
├── internal/                             # Go packages (Phase 7+)
│   ├── cli/
│   ├── daemon/
│   ├── store/
│   ├── transitions/
│   ├── spawner/
│   ├── scheduler/
│   ├── supervisor/
│   ├── git/
│   ├── runtime/
│   ├── hooks/
│   ├── tui/
│   ├── web/
│   └── metrics/
│
├── pipelines/                            # Pipeline template TOML
│   ├── default.toml
│   └── investigation.toml
│
├── prompts/                              # Role system prompts
│   ├── conductor.md
│   ├── developer.md
│   ├── reviewer.md
│   ├── security_reviewer.md
│   ├── integrator.md
│   ├── tester.md
│   ├── investigator.md
│   ├── consolidator.md
│   ├── challenger.md
│   ├── visual_web.md
│   └── visual_ios.md
│
├── .claude/                              # Hook definitions
│   ├── settings.json
│   ├── hooks/
│   │   ├── validate-opus-transition.py
│   │   ├── verify-task-updated.py
│   │   └── save-conductor-context.py
│   └── skills/
│       ├── task-workflow/SKILL.md
│       ├── code-standards/SKILL.md
│       └── git-strategy/SKILL.md
│
├── eval/                                 # Model evaluation
│   ├── runner.py
│   ├── README.md
│   └── test_cases/
│
├── tests/
│   ├── conftest.py
│   ├── test_state_machine.py             # 40+ cases — highest ROI
│   ├── test_task_store.py
│   ├── test_spawner.py
│   ├── test_worktree.py
│   ├── test_preflight.py
│   ├── test_hooks.py
│   ├── test_pipeline_checker.py
│   ├── test_pipeline_template.py
│   ├── test_merge_verifier.py
│   ├── test_daemon.py
│   ├── test_scheduler.py
│   ├── test_communication.py
│   ├── test_recovery.py
│   └── test_backup.py
│
├── docs/
│   ├── quickstart.md
│   ├── prompts.md
│   ├── ai-friendly-codebase-best-practices.md
│   └── concepts/
│       ├── agent-roles.md
│       ├── pipeline-stages.md
│       ├── communication.md
│       └── state-machine.md
│
├── .github/workflows/
│   ├── ci.yml                            # ruff + mypy + pytest
│   ├── release.yml                       # version bump + publish
│   └── eval.yml                          # model eval weekly
│
├── go.mod                                # Phase 7+
├── go.sum
└── .goreleaser.yml                       # Phase 7+
```

---

## Success Metrics

### Functional Correctness
- 5-task batch completes end-to-end without intervention at >80% first-attempt rate
- Rejection loops resolve correctly: 2 rejections retry, 3 rejections block
- Merge verification catches failed merges 100% of the time
- Killed agent's task requeues and completes within 2 watcher ticks

### Reliability
- Watcher uptime: >99% during active sessions (daemon auto-restart within 60s)
- Orphan recovery: 0 permanently stuck tasks from watcher restarts
- Duplicate dispatch rate: 0 (file locking prevents it)
- Data loss across restarts: 0 records lost

### Performance
- Stage transition latency: <10s from agent completion to next stage
- `opus board` renders in <500ms regardless of task count
- Up to `max_agents` running simultaneously without race conditions

### Cost Efficiency
- After model eval (Phase 5): ≥40% of operations run on Haiku without quality regression
- No `--dangerously-skip-permissions` in any spawned agent
- Per-task cost tracking from Phase 6

### Developer Experience
- `pipx install opus-orchestrator && opus start "build X"` works on fresh machine in <5 minutes
- `opus doctor` identifies the 5 most common misconfigurations
- State machine tests: >95% coverage, <10s runtime
- Prompt files editable without touching Python, effective on next spawn

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Agent prompt non-compliance | High | Medium | Three-layer enforcement: prompt + hook + `--allowed-tools`. State machine handles premature closes. |
| SQLite write contention at 20+ agents | Medium | High | WAL mode + optimistic locking + connection-per-operation. Benchmark at 30 agents early. Fallback: PostgreSQL adapter (Phase 8). |
| Claude CLI flag changes | Medium | High | All CLI calls centralized in `spawner.py::_build_claude_command()`. Weekly eval CI exercises actual invocations. |
| Git worktree state corruption | Medium | Medium | `worktree.py::repair_worktree()` on reuse. Preflight validates remote refs. Post-completion cleanup. |
| Context compaction loses conductor state | Medium | High | PreCompact hook + periodic JSON checkpoints every 30 min + append-only `conductor-history.md`. |
| Cost overrun from Opus agents | High | Medium | Per-role model config in TOML. Default: Haiku for integrator, Sonnet for developers. Model eval framework for data-driven optimization. |
| Merge conflicts from parallel developers | Medium | Medium | Conductor prompt instructs file-isolated decomposition. Dependency system for overlapping files. Integrator rejects with full conflict context. |
| Hook script fails | Low | High | try/except at top level. Fail open with logging to `.opus/hook_errors.log`. Alert conductor via nudge. |
| Watcher crash mid-transition | Low | High | Single-transaction writes. `recover_orphans()` reads events log to re-derive last stage. |
| Pipeline events log grows unbounded | Medium | Low | Rotation at 100MB. Compress old segments. Keep 10 segments. `opus metrics` reads only recent N by default. |

---

## What We Deliberately Do NOT Build

| Feature | Why Not |
|---------|---------|
| HTTP API in core | CLI is the interface. HTTP is Phase 8 extension. |
| Custom DSL for workflows | TOML pipeline templates are sufficient. YAML considered for Phase 8. |
| Built-in test environment management | Out of scope. Agents use whatever environment exists. |
| Automatic rollback on acceptance failure | Too dangerous to automate. Conductor must triage. |
| Inter-agent chat | Agents communicate through status signals + mail. No direct messaging. Keeps system deterministic. |
| Dolt / external database | SQLite WAL handles our workload with zero ops overhead. |
| AI framework integration (LangChain etc.) | Agents ARE Claude Code processes. No API abstraction layer needed. |
