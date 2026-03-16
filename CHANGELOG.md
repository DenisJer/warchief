# Changelog

All notable changes to Warchief are documented here.

## [0.5.0] — 2026-03-16

### Pipeline
- **Type-aware pipelines**: Feature (planning → dev → test → review → PR), Bug (dev → test → review → PR), Investigation (investigate → user review)
- **Testing before reviewing**: Reviewer now sees code + tests together, catches bad tests
- **Planning stage**: Planner agent analyzes codebase and writes implementation plan before development starts
- **Investigation flow**: Investigator researches, user reviews findings, can request more info or escalate to development tasks
- **Auto-decompose**: Planner detects large tasks and automatically splits into parallel sub-tasks
- **Auto-label detection**: After development, watcher scans changed files and auto-adds `security` (auth/crypto patterns) and `frontend` (.html/.css/.vue/.tsx) labels

### Web Dashboard
- **Task creation modal**: Create tasks from dashboard with type selector, priority slider, label picker, and advanced options (deps, tools, budget)
- **Agents page** (`/agents`): Split view with active/history agent list + live log viewer with syntax coloring and auto-follow
- **File viewer**: Click file paths in agent logs to view file contents in slide-out panel
- **Q&A chat modal**: Click "Answer Question" on task card to see full Q&A history and respond inline
- **Scratchpad viewer**: "View Plan" / "View Findings" button shows full agent notes in readable overlay
- **Decompose modal**: Manually split tasks into sub-tasks from the dashboard
- **Blocked reason banners**: Orange banner on blocked task cards explains why (plan approval, review, question, budget, decomposed)
- **Button tooltips**: Hover descriptions on all action buttons
- **Layout fixes**: Page scrolls, buttons wrap, stage columns scroll at max height
- **One dashboard per project**: Lock prevents duplicate dashboards; shows existing URL if already running

### Cost & Token Optimization
- **Cost budget enforcement**: Session limit (pauses pipeline) + per-task limit (blocks individual tasks) + per-task override via `--budget`
- **Budget progress bar**: Visual bar in web + terminal dashboards with green/yellow/red states
- **Cost breakdown by model and role**: See where money goes (Opus vs Sonnet, developer vs reviewer)
- **Session vs all-time costs**: Dashboard shows both
- **Cache-friendly prompts**: Static role prompt first (cacheable), dynamic task details last
- **"Be concise" in agent rules**: Reduces output tokens ($75/M for Opus)
- **Project context CLAUDE.md**: Auto-generated project summary installed in agent worktrees, skips expensive codebase exploration

### Agent Improvements
- **Scratchpad handoff**: Agents write structured notes (`--handoff`) that next agent reads instead of raw log injection
- **Tester commits tests**: Explicit 3-step exit (commit tests → write handoff → signal result)
- **Reviewer reviews tests**: Updated prompt with test quality checklist
- **MCP tool grants**: `warchief grant <id> figma console` — natural language tool discovery from ~/.claude.json + plugins + claude.ai built-ins
- **Auto tool grant in answers**: "allow figma console" auto-resolves to MCP tool patterns
- **`.claudeignore` in worktrees**: Prevents agents from scanning node_modules, dist, build artifacts

### Commands
- **`warchief drop <id>`**: Kill agent, close task, clean up logs/scratchpad/labels
- **`warchief grant <id> <tools>`**: Grant MCP tools per-task
- **`warchief grant <id> --list`**: List available MCP servers
- **`--budget` flag on create**: Per-task cost budget override

### Fixes
- **Token display**: Cache tokens shown separately (not summed into "Input")
- **Context budget**: Agent logs capped at 500 chars, messages limited to 10, bodies capped at 1KB
- **Drop clears stage + labels**: Tasks disappear from pipeline and questions after drop
- **DB lock prevention**: Shared connection in web dashboard, busy_timeout 10s
- **Optimistic lock bypass**: Web drop uses direct SQL to avoid watcher race conditions

## [0.4.0] — 2026-03-16

### Added
- Web dashboard task creation, agents page, file viewer
- Q&A chat modal, scratchpad viewer, decompose modal
- Blocked reason banners, button tooltips

## [0.3.0] — 2026-03-15

### Added
- FastAPI web dashboard with WebSocket live updates
- Cost breakdown by model and role
- Session vs all-time cost tracking
- Auto-open browser on dashboard start
- Auto port finding for multiple projects

## [0.2.0] — 2026-03-15

### Added
- Task scratchpad — structured handoff notes between agents
- MCP tool discovery and grants
- `warchief drop` command
- `warchief grant` command
- Cost budget enforcement (session + per-task)
- `.claudeignore` in agent worktrees
- Token display fix (cache tokens separate)
- Context budget limits (truncation, message limits)

## [0.1.0] — 2026-03-15

### Added
- Initial release on PyPI as `warchief-orchestrator`
- Full pipeline: development → reviewing → security-review → testing → pr-creation
- 9 agent roles with TOML config and Markdown prompts
- SQLite persistence with WAL mode and optimistic locking
- Git worktree isolation for parallel agents
- Tmux 4-pane UI, terminal dashboard, cost tracking
- Self-healing: zombie detection, orphan recovery, mass death detection
- 433 tests across 28 test files
