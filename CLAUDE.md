# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
pip install -e .                    # Install (REQUIRED after any code changes)
pip install -e ".[dev,ui,web]"      # Install with all extras
pytest tests/ -x -q                 # Run all tests (446 tests, must all pass)
pytest tests/test_state_machine.py  # Run single test file
ruff check warchief/                # Lint
ruff format --check warchief/ tests/  # Format check (CI enforces this)
mypy warchief/                      # Type check
./release.sh --patch                # Release to PyPI + update Homebrew tap
```

### Frontend (Vue 3 SPA)

```bash
cd warchief/web/frontend
npm install                         # First time only
npm run dev                         # Vite dev server (localhost:5173, proxies API to :8095)
npm run build                       # Build to warchief/web/static/ (required before release)
```

`release.sh` runs `npm run build` automatically before building the Python package. After frontend changes, rebuild before testing the web dashboard.

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

`app.py` — all REST endpoints + WebSocket. Frontend is a Vue 3 SPA (`warchief/web/frontend/`) built with Vite + Pinia store, compiled to `warchief/web/static/`. Views: Dashboard, Tasks, Agents. Components: TaskCard, PipelineView, QuestionPanel, EventLog, etc. Vite dev server proxies `/api/*` and `/ws` to the FastAPI backend.

### Budget System (config.py → watcher.py → cost_tracker.py)

`BudgetConfig` in config.toml: `session_limit` pauses entire pipeline, `per_task_default` blocks individual tasks. Tasks can override with `budget` field. Watcher checks every 30s via `check_budgets()`. `compute_cost_summary()` merges `costs.jsonl` + live `.usage.json` files.

### MCP Tool Discovery (mcp_discovery.py)

Reads three sources: `~/.claude.json` mcpServers, `~/.claude/settings.json` plugins, claude.ai built-ins. `resolve_tool_grant()` matches natural language ("allow figma console") to tool patterns (`mcp__figma-console__*`). Task `extra_tools` field merged with role defaults at spawn time.

### Auto-Decompose (watcher.py + prompts/planner.md)

Planner agents can signal `DECOMPOSE: [{...}]` via `--comment`. Watcher's `_check_decompose()` parses JSON, creates sub-tasks with shared `group_id`, closes parent with "decomposed" label. Manual decompose available via web dashboard `/api/decompose/{task_id}`.

### Grouped Task Pipeline (watcher.py)

Decomposed sub-tasks share a `group_id` and a single branch (`feature/{group_id}`). Three key mechanisms:

1. **Sequential development** (`spawn_ready`): Only one developer per group runs at a time to prevent merge conflicts on the shared branch.
2. **Group dev gate** (`_check_group_dev_gate`): After each developer finishes, the gate holds the task with `group-dev-done` + `group-waiting` labels until ALL siblings complete development. When the last sibling finishes, it elects the highest-priority task as **group lead**, closes all others, and advances the lead through testing → reviewing → PR creation.
3. **Group PR gate** (`_check_group_pr_gate`): Ensures only one PR is created per group. The lead task creates the PR containing all siblings' work on the shared branch.

Key labels: `group-dev-done` (sibling finished dev), `group-waiting` (held at gate), `decomposed` (parent closed after decompose).

When changing group logic, update tests in `test_group_pipeline.py`.

### Auto-Label Detection (watcher.py)

`_detect_labels()` scans changed files after development stage. Auth/crypto/token patterns → `security` label. Frontend extensions → `frontend` label. Labels drive pipeline routing (security-review stage, E2E tests).

### Pipeline Configuration (pipelines/*.toml)

Pipeline stages and routing are defined in TOML files, not hardcoded:
- `pipelines/default.toml` — standard dev → review → [security-review] → pr-create flow
- `pipelines/investigation.toml` — research-focused: investigation → challenge → consolidation → planning → dev

Each defines stage ordering, role assignments, label-based routing rules (e.g., `security` label inserts security-review), spawn limits, poll intervals, and cooldowns.

### Startup Cleanup (watcher.py)

`_startup_cleanup()` runs once on watcher start: removes stale worktrees (checks PID alive), marks dead agents, resets orphaned `in_progress` tasks, prunes git worktrees, ensures main repo is on default branch (not stuck on a feature branch), and clears stale sessions.

### Worktree Hardening (worktree.py)

`create_worktree()` handles: broken directories from failed attempts (shutil.rmtree fallback), branches already checked out in other worktrees (auto-cleanup + re-add), main repo on feature branch (auto-checkout to default). `remove_worktree()` falls back to `shutil.rmtree` when git leaves directories behind.

## Key Conventions

- **`pip install -e .` after code changes** — CLI runs from installed package, not source
- **CLI command is `warchief create`**, not `warchief add`
- **Agents must NOT commit** `.claude/`, `.warchief/`, `debug/` files
- **Pipeline creates PRs**, never merges directly to main
- **Test directory**: `/Users/denisasjersovas/Desktop/warchiefTest/` (separate git repo)
- **Token display**: Cache tokens shown separately, never summed into "Input"
- **DB**: SQLite WAL mode, `busy_timeout=10000`, optimistic locking via `version` column
- **Models are frozen dataclasses** — use `object.__setattr__` for runtime attachments (see spawner.py Popen tracking)
- **Grouped tasks share one branch** — `feature/{group_id}`, sequential dev, one combined PR
- **Docs-only guard**: Developer producing only `.md/.txt/.rst` files gets rejected back to development

## Roles

Defined in `warchief/roles/*.toml` (permissions, model, limits) + `prompts/*.md` (system prompt). Key roles: `planner` (reads codebase, writes plan or decomposes), `developer` (writes code, commits), `tester` (writes + commits tests), `reviewer` (reviews code + tests), `investigator` (research only), `conductor` (Opus, decomposes requirements), `pr_creator` (pushes + creates PR).

## CI (GitHub Actions)

`.github/workflows/ci.yml` runs on push to main + PRs:
- **Lint**: `ruff check` + `ruff format --check` on `warchief/` and `tests/`
- **Typecheck**: `mypy warchief/`
- **Test**: `pytest` across Python 3.11, 3.12, 3.13 with coverage

## Distribution

- **PyPI**: `warchief-orchestrator` — `./release.sh --major|--minor|--patch`
- **Homebrew**: `DenisJer/homebrew-tap` — auto-updated by release.sh
- Release script: bumps version → builds frontend → runs tests → builds Python package → publishes → commits + tags → updates Homebrew formula
