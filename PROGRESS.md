# Warchief Progress Report

> v0.2.1 — Published to PyPI as `warchief-orchestrator`
> 40 modules, 9 roles, 11 prompts, 37 test files, 433 tests, ~15,800 lines

---

## Phase 1: Foundation — ✅ COMPLETE (100%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `task_store.py` — SQLite WAL, optimistic locking | ✅ Done | Tasks, agents, messages, events. `extra_tools` column for MCP grants |
| `models.py` — Frozen dataclasses | ✅ Done | TaskRecord (with extra_tools), AgentRecord, MessageRecord, EventRecord, TransitionResult |
| `state_machine.py` — Pure transitions | ✅ Done | `dispatch_transition()`, all stage routing |
| `__main__.py` — CLI with 42 subcommands | ✅ Done | ~1600 lines, all commands implemented |
| `config.py` — TOML config, hot-reload | ✅ Done | Testing config section added |
| `roles/*.toml` — All 9 roles | ✅ Done | developer, reviewer, security_reviewer, conductor, pr_creator, tester, integrator, investigator, challenger |
| Tests | ✅ Done | test_state_machine, test_task_store, test_config |
| `pyproject.toml` | ✅ Done | Published to PyPI with extras: ui, web, dev |
| `LICENSE` | ✅ Done | MIT |
| `.github/workflows/ci.yml` | ⚠️ Written but excluded | OAuth token needs `workflow` scope to push |

---

## Phase 2: Agent Management — ✅ COMPLETE (95%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `worktree.py` — Create/remove/repair | ✅ Done | Branch + detached + integrator modes |
| `preflight.py` — Pre-spawn validation | ✅ Done | |
| `spawner.py` — Agent spawning, CLI building | ✅ Done | WoW-themed names, MCP tool merging from task.extra_tools |
| `watcher.py` — Poll loop, zombie detection | ✅ Done | Mass death detection, orphan recovery |
| `prime.py` — Context injection | ✅ Done | Scratchpad-based (replaced raw log injection). Role-aware, capped at 2KB |
| `heartbeat.py` — File-based heartbeats | ✅ Done | |
| `hooks.py` — Hook installation + .claudeignore | ✅ Done | verify_task_updated stop hook, .claudeignore for node_modules/dist/etc. |
| `scratchpad.py` — Per-task handoff notes | ✅ Done | Agents write --handoff notes, next agent reads structured context |
| `mcp_discovery.py` — MCP tool discovery | ✅ Done | Reads ~/.claude.json mcpServers + plugins + claude.ai built-ins |
| `agent_log_writer.py` — Stream-json parser | ✅ Done | Captures Claude output, writes .usage.json |
| Tests | ✅ Done | test_spawner, test_worktree, test_preflight, test_hooks, test_prime |

**Remaining gap**: Only `verify_task_updated` hook implemented. `validate-transition` and `save-conductor-context` hooks not built — lower priority since prompt enforcement + --allowedTools cover most cases.

---

## Phase 3: Pipeline & Routing — ✅ COMPLETE (95%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `pipeline_checker.py` — Scan + spawn | ✅ Done | |
| `pipeline_template.py` — Load pipelines TOML | ✅ Done | |
| `merge_verifier.py` — git merge-base verification | ✅ Done | |
| `metrics.py` — Stage durations, rejection counts | ✅ Done | |
| `board.py` — Kanban board | ✅ Done | |
| `test_runner.py` — Unit + E2E test execution | ✅ Done | Runs in temporary worktrees, frontend file detection |
| `pipelines/default.toml` | ✅ Done | 5-stage: development → reviewing → security-review → testing → pr-creation |
| `pipelines/investigation.toml` | ✅ Done | |
| Role prompts (11 `.md` files) | ✅ Done | All roles + visual_web, visual_ios |
| Tests | ✅ Done | test_pipeline_checker, test_pipeline_template, test_merge_verifier, test_test_runner |

**Not planned anymore**: Skills (`.claude/skills/`) — decided against, using role TOML + prompts instead. `consolidator.md` prompt not needed.

---

## Phase 4: Resilience & Monitoring — ✅ COMPLETE (100%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `daemon.py` — Background supervisor | ✅ Done | PID file, watcher restart, mass death detection |
| `scheduler.py` — Capacity-controlled dispatch | ✅ Done | |
| `communication.py` — Nudge + mail | ✅ Done | File + SIGUSR1 nudges, DB mail |
| `recovery.py` — Orphan/zombie/worktree recovery | ✅ Done | |
| `backup.py` — JSONL export/restore | ✅ Done | Compressed snapshots |
| `handoff.py` — Session cycling | ✅ Done | |
| `diagnostics.py` — Log tail, failure formatting | ✅ Done | |
| `feed.py` — Real-time event feed | ✅ Done | |
| `log_rotation.py` | ✅ Done | |
| Tests | ✅ Done | test_daemon, test_scheduler, test_communication, test_recovery, test_backup, test_heartbeat, test_handoff, test_log_rotation |

---

## Phase 5: Polish & Evaluation — ✅ MOSTLY COMPLETE (85%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `eval/runner.py` — Eval framework | ✅ Done | |
| `eval/test_cases/*.json` | ✅ Done | 4 test cases |
| `sessions.py` — Multi-project sessions | ✅ Done | |
| `doctor.py` — 10 health checks | ✅ Done | |
| `test_e2e.py` — End-to-end test | ✅ Done | |
| `release.sh` — Automated PyPI releases | ✅ Done | `./release.sh --major/--minor/--patch` |
| `README.md` — Comprehensive docs | ✅ Done | Full feature docs, command reference, architecture |
| `CHANGELOG.md` | ❌ Missing | |
| `docs/` — Detailed documentation | ⚠️ Empty | `docs/concepts/` directory exists but no content |
| `.github/workflows/release.yml` | ❌ Missing | |

---

## Phase 6: UI & Observability — ✅ MOSTLY COMPLETE (85%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `dashboard.py` — Terminal dashboard | ✅ Done | Rich live + plain text fallback |
| `web/app.py` — Web dashboard | ✅ Done | FastAPI + WebSocket, WoW dark theme |
| `web/static/index.html` — Single-page UI | ✅ Done | Pipeline view, agents, tokens (separate!), questions, events, actions |
| `cost_tracker.py` — Token usage tracking | ✅ Done | Per-model/role breakdown, session vs all-time, cache tokens shown separately |
| `observability.py` — Prometheus export | ✅ Done | `.prom` file export |
| `tmux_ui.py` — 4-pane tmux layout | ✅ Done | Dashboard + orchestrator + agent logs + control |
| `control.py` — Interactive REPL | ✅ Done | answer, tell, nudge, retry, approve, reject |
| `agent_monitor.py` — Live agent log viewer | ✅ Done | Auto-follows newest agent |
| `warchief dashboard --web` | ✅ Done | Auto port finding, http://localhost:8095 |
| Session vs all-time cost tracking | ✅ Done | Web dashboard shows both |
| Cost budget check API | ✅ Done | `check_budget(project_root, budget_usd)` |
| **Cost budget auto-pause** | ❌ Missing | API exists but not wired into watcher loop |
| **OpenTelemetry integration** | ❌ Missing | Only Prometheus text format |

---

## Phase 7: Go Binary & Distribution — ❌ DEFERRED

Originally planned as a Go rewrite. **Decision: staying Python.** Distributed via PyPI instead.

| Plan Item | Status | Notes |
|-----------|--------|-------|
| PyPI distribution | ✅ Done | `pip install warchief-orchestrator` |
| `release.sh` — Automated releases | ✅ Done | Version bump + build + publish + tag |
| Homebrew formula | ❌ Not done | Could create `DenisJer/homebrew-tap` |
| Go rewrite | ❌ Deferred | Python is sufficient for current use |

---

## Phase 8: Platform (Future) — ❌ NOT STARTED

| Plan Item | Status |
|-----------|--------|
| Multi-runtime support (Codex, Gemini) | ❌ |
| Plugin system | ❌ |
| Container sandboxing | ❌ |
| Distributed execution (gRPC) | ❌ |
| PostgreSQL adapter | ❌ |
| YAML pipeline definitions | ❌ |

---

## Recent Changes (2026-03-15 → 2026-03-16)

| Change | Impact |
|--------|--------|
| Fixed token display — cache tokens shown separately, not summed into "Input" | Accurate cost visibility |
| Agent log truncation (500 chars), message limit (10), body cap (1KB) | ~33% less input token waste |
| Context budget warning (>15K chars logged) | Early detection of prompt bloat |
| `.claudeignore` in worktrees — blocks node_modules, dist, etc. | Prevents agents scanning heavy dirs |
| `warchief drop <id>` — kill agent + close + cleanup | Easy task removal |
| `warchief grant <id> <tools>` — MCP tool grants per-task | Agents can use Figma, Supabase, etc. |
| MCP discovery — reads ~/.claude.json + plugins + claude.ai built-ins | Natural language tool grants |
| Auto tool grant detection in `warchief answer` | "allow figma console" auto-resolves |
| Web dashboard (FastAPI + WebSocket) | `warchief dashboard --web` |
| Session vs all-time cost tracking | See current session spend |
| Cost breakdown by model and role | Know where money goes |
| Auto port finding for web dashboard | Multiple projects simultaneously |
| Task scratchpad — structured handoff notes | Agents pass context efficiently |
| Published to PyPI v0.2.1 | `pip install warchief-orchestrator` |
| `release.sh --major/--minor/--patch` | One-command releases |

---

## Overall Summary

| Phase | Status | Completion |
|-------|--------|------------|
| **Phase 1**: Foundation | ✅ Complete | 100% |
| **Phase 2**: Agent Management | ✅ Complete | 95% |
| **Phase 3**: Pipeline & Routing | ✅ Complete | 95% |
| **Phase 4**: Resilience & Monitoring | ✅ Complete | 100% |
| **Phase 5**: Polish & Evaluation | ✅ Mostly Complete | 85% |
| **Phase 6**: UI & Observability | ✅ Mostly Complete | 85% |
| **Phase 7**: Distribution | ✅ Done (PyPI) | 80% |
| **Phase 8**: Platform | ❌ Future | 0% |

---

## What's Missing (priority order)

### High Priority
1. **Cost budget auto-pause** — `check_budget()` exists but not called in watcher loop. Wire it up so pipeline pauses when budget exceeded.
2. **Homebrew tap** — create `DenisJer/homebrew-tap` so macOS users can `brew install warchief`.

### Medium Priority
3. **CHANGELOG.md** — track releases properly.
4. **Additional hook scripts** — `validate-transition.py` (prevent agents from calling wrong agent-update statuses), `save-conductor-context.py` (persist conductor decomposition).
5. **`docs/`** — quickstart guide, concepts (pipeline, roles, worktrees), prompt writing guide.
6. **CI/CD** — `.github/workflows/ci.yml` (needs workflow token scope), `release.yml` for automated PyPI on tag push.

### Low Priority
7. **OpenTelemetry** — upgrade from Prometheus text to proper OTel spans/histograms.
8. **Multi-runtime** — support Codex, Gemini as alternative agent backends.
9. **Container sandboxing** — run agents in Docker for stricter isolation.
