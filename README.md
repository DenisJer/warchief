# Warchief — AI Agent Orchestration Framework

Command your coding agents like a true Warchief. A WoW-themed multi-agent orchestration system that coordinates parallel Claude Code instances through an automated development pipeline with human oversight.

```
  development → reviewing → [security-review] → testing → pr-creation
```

No merging to main. Pipeline always creates PRs via `gh pr create`.

## Quick Start

```bash
# Install
cd ~/Desktop/warchief
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Go to your project
cd ~/Desktop/your-project

# Initialize
warchief init

# Launch — creates tasks from requirement, spawns agents, opens tmux UI
warchief start "implement password reset with email verification"

# Or create tasks manually
warchief create "Build auth middleware" --priority 8 --labels security
warchief create "Add dark mode toggle" --priority 5
warchief start  # starts pipeline for existing tasks
```

## Requirements

- **Python 3.11+**
- **Git** — project must be a git repo with at least one commit
- **Claude Code CLI** — `claude` on PATH (required for agent spawning)
- **GitHub CLI** — `gh` on PATH (required for PR creation stage)
- **tmux** — optional, for the 4-pane terminal UI

No other runtime dependencies. Rich, Textual, FastAPI are optional extras.

## Installation

```bash
# Basic install
pip install -e .

# With live terminal dashboard (rich)
pip install -e ".[ui]"

# With web dashboard (FastAPI + WebSocket)
pip install -e ".[web]"

# With everything
pip install -e ".[dev,ui,web]"

# Make available globally (add to shell rc)
export PATH="$HOME/Desktop/warchief/.venv/bin:$PATH"
```

## Pipeline

### Stages

| Stage | Role | What Happens |
|-------|------|-------------|
| **development** | Developer (Sonnet) | Writes code in an isolated git worktree, commits to feature branch |
| **reviewing** | Reviewer (Sonnet) | Reviews code in detached worktree, approves or rejects with feedback |
| **security-review** | Security Reviewer (Opus) | Security audit — only runs for tasks labeled `security` |
| **testing** | Configured per-project | Runs unit tests + optional E2E tests (Playwright) |
| **pr-creation** | PR Creator (Sonnet) | Pushes branch, creates PR via `gh pr create` |

### Testing Stage Configuration

Testing behavior is configured per-project in `.warchief/config.toml`:

```toml
[testing]
test_command = "npm test"              # Unit/integration tests (always runs)
e2e_command = "npx playwright test"    # E2E tests (runs only if frontend files changed)
test_timeout = 300
auto_run = true                        # false = manual approve/reject
```

- **Tests configured + auto_run** — watcher runs tests automatically; failure sends task back to development
- **Tests configured + !auto_run** — blocks with "needs-testing" label; user must `approve` or `reject`
- **No tests configured** — testing stage is skipped entirely
- Frontend file detection: `.html`, `.css`, `.scss`, `.js`, `.jsx`, `.ts`, `.tsx`, `.vue`, `.svelte`

### Agent Roles

Each role is defined in `warchief/roles/*.toml` (permissions, model, limits) and `prompts/*.md` (system prompt):

| Role | Default Model | Max Concurrent | Worktree | Purpose |
|------|--------------|----------------|----------|---------|
| Conductor | Opus | 1 | none | Decomposes requirements into tasks |
| Developer | Sonnet | 6 | branch | Writes code on feature branches |
| Reviewer | Sonnet | 4 | detached | Reviews code, approves/rejects |
| Security Reviewer | Opus | 2 | detached | Security-focused audit |
| Tester | Sonnet | 1 | detached | Runs acceptance tests |
| PR Creator | Sonnet | 2 | branch | Pushes branch + creates PR via gh |
| Investigator | Sonnet | 4 | none | Research tasks |
| Challenger | Sonnet | 2 | none | Devil's advocate review |

Models can be overridden per-project:
```toml
[role_models]
developer = "claude-opus-4-20250514"
reviewer = "claude-sonnet-4-20250514"
```

### Worktree Isolation

Each agent works in its own git worktree — no conflicts between parallel agents:

- **Branch worktree** — Developer/PR Creator: creates `feature/{task-id}` branch
- **Detached worktree** — Reviewer/Tester: read-only checkout at the feature branch HEAD
- Worktrees are auto-created at spawn and cleaned up when agents finish
- Located in `.warchief-worktrees/` (gitignored)

### State Machine

The pipeline is driven by a pure-function state machine with no side effects:

```
dispatch_transition(task_state) → TransitionResult {
    status, next_stage, add_labels, remove_labels, failure_reason
}
```

Transitions are fully testable — the watcher applies the result to the database.

### Rejection & Crash Handling

- **Rejection**: Reviewer rejects → task returns to development with feedback (max 3 before blocked)
- **Crash**: Agent process dies → task reset to open for retry (max 3 before blocked)
- **Blocked tasks**: Require user intervention via `retry`, `nudge`, or `drop`

### Self-Healing

- **Zombie detection** — agents with no heartbeat for 60s are killed and tasks reset
- **Orphan recovery** — tasks stuck in `in_progress` with no live agent are reset
- **Mass death detection** — 3+ agents dying within 30s triggers auto-pause
- **Stale assignment cleanup** — open tasks with dead assigned agents are freed

## Human-in-the-Loop

Agents can ask questions and receive user feedback without breaking the pipeline:

### Questions

When an agent is unsure, it asks a question and exits. The user answers, and the agent is re-spawned with the answer in its context.

```bash
# See pending questions
warchief questions

# Answer
warchief answer <task-id> "Use PostgreSQL, not SQLite"
```

### Feedback & Control

| Command | Effect |
|---------|--------|
| `warchief answer <id> "text"` | Answer agent question, unblock task |
| `warchief tell <id> "text"` | Message for next agent spawn (doesn't interrupt) |
| `warchief nudge <id> "text"` | Kill current agent + restart with message |
| `warchief retry <id> "text"` | Reopen closed/failed task with feedback |
| `warchief approve <id>` | Approve task after manual testing |
| `warchief reject <id> "text"` | Reject after testing, back to development |
| `warchief drop <id>` | Kill agent, close task, clean up logs |

### MCP Tool Grants

Agents run with restricted tool permissions by default. Grant additional tools (MCP servers, plugins) per-task:

```bash
# At task creation
warchief create "Design login page" --tools "mcp__figma-console__*,mcp__figma__*"

# Grant tools to existing task
warchief grant <task-id> figma console
warchief grant <task-id> supabase
warchief grant <task-id> --list   # show available MCP servers

# Auto-detected when answering questions
warchief answer <task-id> "allow figma console tools"
# → resolves to mcp__figma-console__* and updates task permissions
```

Tool discovery reads from three sources:
- `~/.claude.json` mcpServers → `mcp__{name}__*`
- `~/.claude/settings.json` plugins → `mcp__plugin_{name}_{key}__*`
- Claude.ai built-in MCPs → `mcp__claude_ai_{Name}__*`

## Dashboards

### Web Dashboard

Interactive web UI with live WebSocket updates:

```bash
pip install -e ".[web]"
warchief dashboard --web              # http://localhost:8095
warchief dashboard --web --port 8096  # custom port
```

Features:
- Pipeline visualization with task cards flowing through stages
- Agent monitoring (role, task, age, alive/zombie status)
- Token tracking: input, cache read, cache write, output (shown separately, not summed)
- Cost breakdown by model and role (session + all-time)
- Questions panel with inline answer input
- Action buttons: drop, grant, nudge, tell
- WebSocket auto-refresh every 2 seconds

### Terminal Dashboard

Rich live-updating terminal dashboard:

```bash
pip install -e ".[ui]"
warchief dashboard          # live auto-refresh
warchief dashboard --snapshot  # single snapshot
```

### Tmux UI

4-pane layout launched automatically by `warchief start`:

```
┌──────────────┬──────────────┐
│  Dashboard   │   Agent      │
│  (live)      │   Logs       │
├──────────────┤   (auto-     │
│  Orchestrator│    follows)  │
│  (watcher)   │              │
├──────────────┴──────────────┤
│  Control (answer/tell/nudge) │
└─────────────────────────────┘
```

## Cost Tracking

Every agent's token usage is tracked automatically:

```
claude (stream-json) → agent_log_writer (.usage.json) → watcher (costs.jsonl) → dashboard
```

- **Per-agent**: input, output, cache read, cache write tokens
- **Cost estimation**: uses Anthropic pricing per model (Opus/Sonnet/Haiku rates)
- **Session vs all-time**: web dashboard shows both
- **By model**: see how much Opus vs Sonnet is costing
- **By role**: see developer vs reviewer vs tester costs
- **Budget checks**: `check_budget(project_root, budget_usd)` API

```bash
warchief costs   # CLI cost breakdown
```

Token display shows each type separately (not lumped together):
- **Input** — actual input tokens
- **Cache Read** — tokens read from prompt cache (cheaper rate)
- **Cache Write** — tokens written to cache
- **Output** — generated tokens

## Commands Reference

### Task Management

```bash
warchief create "title" [--type feature|bug|investigation] [--priority 1-10]
                        [--labels "a,b"] [--deps "wc-id1,wc-id2"]
                        [--tools "mcp__figma__*"] [--description "..."]
warchief list [--status open|blocked|closed] [--stage development] [--label security]
warchief show <id> [--json]
warchief update <id> [--status open|blocked|closed] [--add-label x] [--remove-label x]
warchief drop <id>                    # kill agent + close + cleanup
warchief grant <id> <tools>           # grant MCP tools
warchief grant <id> --list            # list available MCP servers
warchief release <id> --stage <stage> # manually place task in pipeline
```

### Pipeline Control

```bash
warchief start ["requirement"]   # create task + launch tmux UI + pipeline
warchief start --no-tmux         # without tmux
warchief watch                   # run orchestrator (no tmux)
warchief stop                    # stop orchestrator
warchief pause                   # pause (no new agent spawns)
warchief resume                  # resume
warchief status                  # show pipeline + agents + watcher state
warchief kill-agent <agent-id>   # kill specific agent
```

### Monitoring

```bash
warchief dashboard [--web] [--port 8095] [--snapshot] [--refresh 2.0]
warchief board                   # kanban board
warchief feed                    # activity event feed
warchief metrics                 # pipeline metrics
warchief costs                   # cost breakdown
warchief logs <agent> [-f] [-n 50] [--events]
warchief questions               # list pending agent questions
warchief observe                 # export Prometheus metrics
```

### Communication

```bash
warchief answer <id> "answer text"
warchief tell <id> "message"
warchief nudge <id> "message"    # kill + restart + message
warchief retry <id> "feedback"   # reopen closed task
warchief approve <id>            # approve after manual testing
warchief reject <id> "feedback"  # reject after testing
```

### Operations

```bash
warchief doctor                  # health checks (10 diagnostics)
warchief backup                  # backup state
warchief restore <file>          # restore from backup
warchief purge [--keep-closed] [--keep-events 500]
warchief daemon start|stop|status
warchief sessions                # list active sessions
warchief connect [session]       # connect to running session
warchief config [key] [value]    # view/edit config
```

## Configuration

`.warchief/config.toml`:

```toml
max_total_agents = 8          # global agent limit
base_branch = "main"          # default base branch
paused = false                # pause pipeline
agent_timeout = 3600          # kill agents older than this (seconds)

[role_models]                 # override default models per role
conductor = "claude-opus-4-20250514"
developer = "claude-sonnet-4-20250514"

[max_role_agents]             # override max concurrent per role
developer = 6
reviewer = 4

[testing]
test_command = "npm test"
e2e_command = "npx playwright test"
test_timeout = 300
auto_run = true
```

## Project Structure

```
your-project/
├── .warchief/                    # Created by 'warchief init'
│   ├── warchief.db               # SQLite (WAL mode, optimistic locking)
│   ├── config.toml               # Project configuration
│   ├── warchief.log              # Orchestrator log
│   ├── watcher.lock              # Single-watcher enforcement (flock)
│   ├── daemon.pid                # Daemon PID
│   ├── agent-logs/               # Per-agent output logs
│   │   ├── developer-thrall-a1b2.log
│   │   ├── developer-thrall-a1b2.prompt
│   │   └── developer-thrall-a1b2.usage.json
│   ├── costs.jsonl               # Accumulated token usage
│   ├── heartbeats/               # Agent heartbeat files
│   ├── nudges/                   # Ephemeral nudge notifications
│   └── backups/                  # Compressed state backups
├── .warchief-worktrees/          # Agent worktrees (auto-managed)
│   ├── developer-thrall-a1b2/
│   ├── reviewer-jaina-c3d4/
│   └── ...
└── (your project files)
```

## Warchief Framework Structure

```
warchief/
├── __main__.py          # CLI entry point — all commands
├── watcher.py           # Orchestrator loop — spawns agents, detects zombies
├── spawner.py           # Builds prompts, launches Claude CLI with worktrees
├── state_machine.py     # Stage transitions (pure functions, no side effects)
├── prime.py             # Agent context injection (Q&A, feedback, previous logs)
├── cost_tracker.py      # Token usage tracking, cost estimation, budget checks
├── agent_log_writer.py  # Captures Claude stream-json, writes .usage.json
├── mcp_discovery.py     # MCP tool discovery from Claude config + plugins
├── task_store.py        # SQLite persistence (tasks, agents, messages, events)
├── models.py            # Data classes (TaskRecord, AgentRecord, etc.)
├── config.py            # Stage definitions, role mappings, TOML config
├── worktree.py          # Git worktree lifecycle (create/remove/cleanup)
├── hooks.py             # Claude Code hooks for agent enforcement
├── tmux_ui.py           # 4-pane tmux layout
├── dashboard.py         # Terminal dashboard (rich.live + plain text)
├── control.py           # Interactive REPL for tmux control pane
├── agent_monitor.py     # Live agent log viewer, auto-follows newest
├── test_runner.py       # Runs project test commands in worktrees
├── conductor.py         # Requirement → task decomposition
├── doctor.py            # 10 health checks
├── roles/               # Role definitions (TOML)
│   ├── developer.toml
│   ├── reviewer.toml
│   └── ...
├── web/                 # Web dashboard
│   ├── app.py           # FastAPI + WebSocket + REST API
│   └── static/
│       └── index.html   # Single-page dashboard (inline CSS/JS)
└── (other modules: backup, daemon, feed, metrics, recovery, etc.)

prompts/                 # Agent system prompts (Markdown)
├── developer.md
├── reviewer.md
├── conductor.md
└── ...

tests/                   # 433 tests across 28 files
├── test_watcher.py
├── test_spawner.py
├── test_state_machine.py
└── ...
```

## Troubleshooting

```bash
warchief doctor   # Run all 10 health checks
```

| Problem | Solution |
|---------|----------|
| "Watcher not running" | Run `warchief start` or `warchief watch` |
| Agents failing to spawn | Check `warchief doctor` — usually `claude` not on PATH |
| Tasks stuck in "open" | Check `warchief status` — watcher might not be running |
| Tasks stuck in "in_progress" | Agent may have died — `warchief doctor` detects orphans |
| Agent can't use MCP tools | Grant tools: `warchief grant <id> figma console` |
| High token costs | Check `warchief costs` — Opus roles cost more |
| Port 8095 already in use | Use `--port 8096` or kill the old process |
| Worktree errors | Run `warchief purge` to clean up stale worktrees |

## Architecture Principles

- **Zero runtime dependencies** — stdlib only; rich/textual/fastapi are optional extras
- **SQLite WAL mode** — concurrent agent access with optimistic locking
- **Pure-function state machine** — no side effects, fully testable transitions
- **Git worktree isolation** — each agent gets its own working copy
- **TOML configuration** — roles, pipelines, and project config
- **File-based heartbeats** — simple, no network coordination required
- **`.claudeignore` in worktrees** — prevents agents from scanning node_modules, dist, etc.
- **Context budget management** — agent prompts are truncated to prevent token waste
- **433 tests** across 28 test files, ~15,700 lines of code
