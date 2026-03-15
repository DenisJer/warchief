# Warchief — AI Agent Orchestration Framework

WoW-themed multi-agent orchestration system for Claude Code CLI. Commands parallel coding agents through automated pipelines with human oversight.

## Quick Reference

```bash
pip install -e .              # Install (required after code changes)
pip install -e ".[dev,ui]"    # Install with dev/UI extras
warchief init                 # Initialize .warchief/ in a project
warchief create "task title"  # Create a task (NOT "add")
warchief start "requirement"  # Launch tmux UI + pipeline
warchief watch                # Run orchestrator without tmux
warchief doctor               # Health checks
pytest                        # Run tests
ruff check warchief/          # Lint
```

## Architecture

### Pipeline Stages
`development` → `reviewing` → `[security-review]` → `testing` → `pr-creation`

**No merging to main.** Pipeline always creates PRs via `gh pr create`.

### Testing Stage
Configured per-project in `.warchief/config.toml`:
```toml
[testing]
test_command = "npm test"              # Unit/integration tests (always runs)
e2e_command = "npx playwright test"    # E2E tests (runs only if frontend files changed)
test_timeout = 300
auto_run = true                        # false = manual approve/reject
```

- **Tests configured + auto_run** → watcher runs tests automatically, fails → back to development
- **Tests configured + !auto_run** → blocks with "needs-testing", user does `approve`/`reject`
- **No tests configured** → testing stage is skipped entirely
- Frontend detection: `.html`, `.css`, `.scss`, `.js`, `.jsx`, `.ts`, `.tsx`, `.vue`, `.svelte`

### Key Modules
| Module | Purpose |
|--------|---------|
| `watcher.py` | Orchestrator loop — spawns agents, detects zombies, announces questions |
| `spawner.py` | Builds prompts, launches Claude CLI with git worktrees |
| `state_machine.py` | Stage transitions based on agent results |
| `prime.py` | Builds agent context (Q&A history, feedback, previous attempts) |
| `cost_tracker.py` | Merges costs.jsonl + live .usage.json for real-time cost display |
| `agent_log_writer.py` | Captures Claude stream-json output, writes .usage.json |
| `tmux_ui.py` | 4-pane tmux layout (dashboard, orchestrator, agent logs, control) |
| `control.py` | Interactive REPL (answer, tell, nudge, retry, status, costs) |
| `agent_monitor.py` | Live agent log viewer, auto-follows newest agent |
| `test_runner.py` | Runs project test commands (unit + e2e) in temporary worktrees |
| `doctor.py` | Health checks (claude cli, gh, tmux, git, db, agents, worktrees) |
| `config.py` | Stage definitions, role mappings, thresholds |
| `models.py` | Data classes (TaskRecord, AgentRecord, MessageRecord, etc.) |
| `task_store.py` | SQLite-backed task/agent/message persistence |
| `worktree.py` | Git worktree management for agent isolation |

### Agent Roles
Defined in `warchief/roles/*.toml` (config) + `prompts/*.md` (system prompts):
- `developer` — writes code in branch worktrees
- `reviewer` — reviews code in detached worktrees
- `security_reviewer` — security-focused review
- `pr_creator` — pushes branch + creates PR via gh cli
- `conductor` — breaks requirements into tasks

### Human-in-the-Loop
- Agent asks question → task blocked with "question" label → user `answer` → re-spawn
- `tell <id> <msg>` — message for next agent spawn
- `nudge <id> <msg>` — message + kill agent + restart at development stage
- `retry <id> <msg>` — reopen closed/failed task with feedback
- `approve <id>` — approve task after manual testing (when auto_run=false)
- `reject <id> <msg>` — reject after testing, back to development with feedback

### Cost Tracking Flow
`claude (stream-json)` → `agent_log_writer (.usage.json)` → `watcher (costs.jsonl)` → `dashboard`

## Development Rules

- **Always `pip install -e .`** after modifying source files — the CLI runs from the installed package
- **Test directory:** `/Users/denisasjersovas/Desktop/warchiefTest/` (separate git repo)
- Agents must NOT commit `.claude/`, `.warchief/`, `debug/` files — `warchief init` sets up `.gitignore`
- Python 3.11+, no runtime dependencies (rich/watchdog/textual are optional UI extras)
- Tests: `pytest tests/` — test files mirror module names (`test_<module>.py`)
- Lint: `ruff check warchief/`, type check: `mypy warchief/`
