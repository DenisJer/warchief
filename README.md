# Warchief — AI Agent Orchestration Framework

Command your coding agents like a true Warchief. A WoW-themed multi-agent orchestration framework that coordinates Claude Code instances for parallel software development.

## Quick Start

```bash
# Go to your project
cd ~/Desktop/your-project

# Initialize warchief
warchief init

# Create tasks
warchief create "Build user authentication" --priority 8 --labels security
warchief create "Add dark mode toggle" --priority 5
warchief create "Fix login bug" --type bug --priority 9

# View your tasks
warchief list
warchief board

# Run the full autonomous pipeline
warchief start "implement password reset flow"
```

## Requirements

- **Python 3.11+**
- **Git** (your project must be a git repo)
- **Claude Code CLI** (`claude` on PATH) — required for autonomous agent spawning
- No other runtime dependencies

## Installation

```bash
# Clone/download warchief
cd ~/Desktop/warchief

# Create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Make it available globally (add to ~/.zshrc or ~/.bashrc)
export PATH="$HOME/Desktop/warchief/.venv/bin:$PATH"

# Or create a wrapper in ~/.local/bin (already on most PATHs)
cat > ~/.local/bin/warchief << 'EOF'
#!/bin/bash
exec ~/Desktop/warchief/.venv/bin/python -m warchief "$@"
EOF
chmod +x ~/.local/bin/warchief
```

## Commands

### Task Management

| Command | Description |
|---------|-------------|
| `warchief init` | Initialize warchief in current project |
| `warchief create "title"` | Create a new task |
| `warchief list` | List all tasks |
| `warchief show <id>` | Show task details |
| `warchief show <id> --json` | Show task as JSON |
| `warchief update <id> --status blocked` | Update task status |
| `warchief update <id> --add-label security` | Add a label |
| `warchief release <id> --stage development` | Release task into pipeline |

### Pipeline Control

| Command | Description |
|---------|-------------|
| `warchief start "requirement"` | Create task + start pipeline |
| `warchief start` | Start pipeline for existing tasks |
| `warchief watch` | Run watcher in foreground |
| `warchief stop` | Stop the watcher |
| `warchief pause` | Pause pipeline (no new spawns) |
| `warchief resume` | Resume pipeline |
| `warchief status` | Show pipeline status |
| `warchief kill-agent <name>` | Kill a running agent |

### Monitoring

| Command | Description |
|---------|-------------|
| `warchief board` | Kanban board view |
| `warchief dashboard` | Live-updating terminal dashboard |
| `warchief dashboard --snapshot` | Single dashboard snapshot |
| `warchief feed` | Activity event feed |
| `warchief metrics` | Pipeline metrics |
| `warchief logs <agent>` | Agent-specific log entries |
| `warchief observe` | Export Prometheus metrics |
| `warchief costs` | Cost breakdown by role/task/model |

### Operations

| Command | Description |
|---------|-------------|
| `warchief doctor` | Health check (10 checks) |
| `warchief backup` | Backup state to compressed JSONL |
| `warchief restore` | Restore from backup |
| `warchief daemon start` | Start background daemon |
| `warchief daemon stop` | Stop daemon |
| `warchief daemon status` | Check daemon status |
| `warchief sessions` | List all warchief sessions |
| `warchief connect` | Connect to active session |
| `warchief config` | View/edit configuration |
| `warchief version` | Print version |

## How It Works

### Pipeline Stages

Tasks flow through a 5-stage pipeline automatically:

```
development → reviewing → [security-review] → merging → acceptance
```

1. **Development** — A developer agent writes code in a git worktree
2. **Reviewing** — A reviewer agent checks the code and approves/rejects
3. **Security Review** — (only for `security`-labeled tasks) Security audit
4. **Merging** — An integrator agent merges the feature branch
5. **Acceptance** — A tester agent validates the final result

### Agent Roles

Each stage has a dedicated agent role with specific permissions:

| Role | Model | Max Concurrent | Purpose |
|------|-------|----------------|---------|
| Conductor | Opus | 1 | Decomposes requirements into tasks |
| Developer | Sonnet | 6 | Writes code |
| Reviewer | Sonnet | 4 | Reviews code, approves/rejects |
| Security Reviewer | Opus | 2 | Security audit |
| Integrator | Haiku | 1 | Merges branches (serialized) |
| Tester | Sonnet | 1 | Runs acceptance tests |
| Investigator | Sonnet | 4 | Research tasks |
| Challenger | Sonnet | 2 | Devil's advocate |

### State Machine

The pipeline is driven by a pure-function state machine with no side effects. The `TransitionResult` pattern separates "what should change" from "how to change it":

```
dispatch_transition(current_state) → TransitionResult {
    status, next_stage, add_labels, remove_labels, failure_reason
}
```

### Rejection & Crash Handling

- **Rejection**: Reviewer rejects → task returns to development (max 3 rejections before blocked)
- **Crash**: Agent process dies → task reset to open for retry (max 3 crashes before blocked)
- **Blocked tasks**: Require conductor intervention

### Self-Healing

- **Watcher** — Polls every 5s, detects dead agents, resets orphaned tasks
- **Daemon** — Monitors watcher health, auto-restarts on crash
- **Mass death detection** — If 3+ agents die within 30s, pipeline auto-pauses
- **Recovery** — Zombie detection, orphan recovery, worktree cleanup

## Project Structure

```
your-project/
├── .warchief/                  # Created by 'warchief init'
│   ├── warchief.db             # SQLite database (WAL mode)
│   ├── config.toml             # Project configuration
│   ├── warchief.log            # Log file
│   ├── watcher.lock            # Single-watcher enforcement
│   ├── daemon.pid              # Daemon PID file
│   ├── heartbeats/             # Agent heartbeat files
│   ├── nudges/                 # Ephemeral agent notifications
│   ├── costs.jsonl             # Token usage tracking
│   ├── metrics.prom            # Prometheus metrics export
│   └── backups/                # Compressed state backups
├── .warchief-worktrees/        # Agent worktrees (auto-managed)
│   ├── developer-thrall/
│   ├── reviewer-jaina/
│   └── ...
└── (your project files)
```

## Configuration

Edit `.warchief/config.toml` or use `warchief config`:

```toml
max_total_agents = 8
base_branch = "main"
paused = false
agent_timeout = 3600

[role_models]
conductor = "claude-opus-4-20250514"
developer = "claude-sonnet-4-20250514"

[max_role_agents]
developer = 6
reviewer = 4
```

## Task Creation Options

```bash
warchief create "title" \
  --type feature|bug|investigation \
  --priority 1-10 \
  --labels "security,frontend" \
  --deps "wc-abc123,wc-def456" \
  --description "detailed description"
```

## Troubleshooting

### "Watcher not running" warning
This is normal if you haven't started the pipeline. Run `warchief start` or `warchief watch`.

### Agents failing to spawn
Run `warchief doctor` to diagnose. Common issues:
- `claude` CLI not on PATH
- Not in a git repository
- No commits on the base branch

### Tasks stuck in "open"
Check if there's a watcher running: `warchief status`. If agents keep failing, check `warchief feed` for error events.

### Cleanup after errors
```bash
warchief doctor        # See what's wrong
warchief status        # Check state
# If needed, manually reset:
warchief update <id> --status open
```

## Architecture

- **Zero runtime dependencies** — stdlib only (rich/textual optional for UI)
- **SQLite WAL mode** — concurrent agent access with optimistic locking
- **Pure-function state machine** — no side effects, fully testable
- **TOML configuration** — roles, pipelines, and config all in TOML
- **File-based heartbeats** — simple, no network required
- **fcntl.flock** — single-watcher and scheduler enforcement
- **335 tests** across 28 test files
