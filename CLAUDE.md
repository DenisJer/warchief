# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
pip install -e .                    # Install (REQUIRED after any code changes)
pip install -e ".[dev,ui,web]"      # Install with all extras
pytest tests/ -x -q                 # Run all tests (435 tests, must all pass)
pytest tests/test_state_machine.py  # Run single test file
ruff check warchief/                # Lint
mypy warchief/                      # Type check
./release.sh --patch                # Release to PyPI + update Homebrew tap
```

## Architecture

### Pipeline Flow (type-aware)

```
Feature: planning → development → testing → reviewing → [security-review] → pr-creation
Bug:     development → testing → reviewing → pr-creation
Investigation: investigation → user review → close or escalate
```

Testing runs BEFORE reviewing — reviewer sees both code and tests together. Security-review only triggers if `security` label is present (auto-detected from file patterns). Pipeline never merges to main — always creates PRs via `gh pr create`.

### State Machine (state_machine.py)

Pure functions, no side effects. `dispatch_transition()` takes current state, returns `TransitionResult` describing what should change. The watcher applies the result to the database. All transitions are type-aware via `task_type` parameter — `get_pipeline_for_type()` returns the stage sequence.

Key: `config.py` defines `TYPE_TO_PIPELINE` mapping and `STAGE_TO_ROLE` mapping. When changing pipeline order, update both + tests in `test_state_machine.py` and `test_e2e.py`.

### Agent Spawning (spawner.py → watcher.py)

`build_claude_command()` constructs the prompt in cache-friendly order: role prompt (static, cacheable) → hard rules (static) → task details (dynamic) → exit instructions (per-role). `spawn_agent()` creates worktree → installs hooks + `.claudeignore` + project context CLAUDE.md → pipes prompt via stdin to `claude --print --verbose --output-format stream-json`.

Prompt is piped through `agent_log_writer.py` which parses stream-json and writes `.usage.json` for cost tracking.

### Context Injection (prime.py)

`build_prime_context()` gathers scratchpad (replaces raw agent logs), messages (limited to 10, each capped at 1KB), rejection feedback, and dependency status. Appended to prompt after role-specific exit instructions. Total context capped — warning logged if prompt exceeds 15K chars.

### Web Dashboard (warchief/web/)

FastAPI app with WebSocket (`/ws` pushes state every 2s). Single shared DB connection to avoid SQLite lock contention. One dashboard per project enforced via `dashboard.lock` flock. Auto-finds available port, auto-opens browser.

`app.py` — all REST endpoints + WebSocket. `static/index.html` — dashboard page. `static/agents.html` — agent log viewer page. Both are single HTML files with inline CSS/JS, no build step.

### Budget System (config.py → watcher.py → cost_tracker.py)

`BudgetConfig` in config.toml: `session_limit` pauses entire pipeline, `per_task_default` blocks individual tasks. Tasks can override with `budget` field. Watcher checks every 30s via `check_budgets()`. `compute_cost_summary()` merges `costs.jsonl` + live `.usage.json` files.

### MCP Tool Discovery (mcp_discovery.py)

Reads three sources: `~/.claude.json` mcpServers, `~/.claude/settings.json` plugins, claude.ai built-ins. `resolve_tool_grant()` matches natural language ("allow figma console") to tool patterns (`mcp__figma-console__*`). Task `extra_tools` field merged with role defaults at spawn time.

### Auto-Decompose (watcher.py + prompts/planner.md)

Planner agents can signal `DECOMPOSE: [{...}]` via `--comment`. Watcher's `_check_decompose()` parses JSON, creates sub-tasks with shared `group_id`, blocks parent with "decomposed" label. Manual decompose available via web dashboard `/api/decompose/{task_id}`.

### Auto-Label Detection (watcher.py)

`_detect_labels()` scans changed files after development stage. Auth/crypto/token patterns → `security` label. Frontend extensions → `frontend` label. Labels drive pipeline routing (security-review stage, E2E tests).

## Key Conventions

- **`pip install -e .` after code changes** — CLI runs from installed package, not source
- **CLI command is `warchief create`**, not `warchief add`
- **Agents must NOT commit** `.claude/`, `.warchief/`, `debug/` files
- **Pipeline creates PRs**, never merges directly to main
- **Test directory**: `/Users/denisasjersovas/Desktop/warchiefTest/` (separate git repo)
- **Token display**: Cache tokens shown separately, never summed into "Input"
- **DB**: SQLite WAL mode, `busy_timeout=10000`, optimistic locking via `version` column
- **Models are frozen dataclasses** — use `object.__setattr__` for runtime attachments (see spawner.py Popen tracking)

## Roles

Defined in `warchief/roles/*.toml` (permissions, model, limits) + `prompts/*.md` (system prompt). Key roles: `planner` (reads codebase, writes plan or decomposes), `developer` (writes code, commits), `tester` (writes + commits tests), `reviewer` (reviews code + tests), `investigator` (research only), `conductor` (Opus, decomposes requirements), `pr_creator` (pushes + creates PR).

## Distribution

- **PyPI**: `warchief-orchestrator` — `./release.sh --major|--minor|--patch`
- **Homebrew**: `DenisJer/homebrew-tap` — auto-updated by release.sh
- Release script: bumps version → runs tests → builds → publishes → commits + tags → updates Homebrew formula
