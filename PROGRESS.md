# Warchief Progress Report

> Project renamed from "Opus" to "Warchief" (WoW theme). `.opus/` → `.warchief/`.

---

## Phase 1: Foundation (Weeks 1-2) — ✅ COMPLETE (~95%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `task_store.py` — SQLite WAL, schema, optimistic locking | ✅ Done | 401 lines, all tables implemented |
| `models.py` — Frozen dataclasses | ✅ Done | TaskRecord, AgentRecord, MessageRecord, EventRecord, TransitionResult |
| `state_machine.py` — Pure transitions | ✅ Done | `dispatch_transition()`, all stage routing |
| `__main__.py` — CLI with all commands | ✅ Done | 1117 lines, 40 subcommands |
| `config.py` — Config loading, hot-reload | ✅ Done | TOML-based, dotted key get/set |
| `roles/*.toml` — All 8 roles | ✅ Done | 8 TOML files in `warchief/roles/` |
| `test_state_machine.py` | ✅ Done | |
| `test_task_store.py` | ✅ Done | CRUD, optimistic locking |
| `test_config.py` | ✅ Done | |
| `pyproject.toml` | ✅ Done | |
| `.github/workflows/ci.yml` | ❌ Missing | No `.github/` directory found |

---

## Phase 2: Agent Management (Weeks 3-4) — ✅ MOSTLY COMPLETE (~85%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `worktree.py` — Create/remove/repair, symlink | ✅ Done | Branch + detached modes |
| `preflight.py` — Pre-spawn validation | ✅ Done | |
| `spawner.py` — Agent spawning, CLI building | ✅ Done | WoW-themed names instead of composers |
| `watcher.py` — 5s poll loop, cleanup | ✅ Done | Full poll loop with zombie/orphan handling |
| `prime.py` — Startup context generation | ✅ Done | |
| `heartbeat.py` — File-based heartbeats | ✅ Done | |
| `hooks.py` — Hook installation | ✅ Done | |
| **Hook scripts** (`.claude/hooks/`) | ❌ Missing | `validate-opus-transition.py`, `verify-task-updated.py`, `save-conductor-context.py` not found |
| `test_spawner.py` | ✅ Done | |
| `test_worktree.py` | ❓ Unclear | |
| `test_preflight.py` | ❓ Unclear | |
| `test_hooks.py` | ❓ Unclear | |

**Key gap**: The three hook enforcement scripts are a critical part of the plan's "three-layer enforcement" (prompt + hook + `--allowed-tools`). Without them, agents can violate role boundaries.

---

## Phase 3: Pipeline & Routing (Weeks 5-6) — ✅ MOSTLY COMPLETE (~85%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `pipeline_checker.py` — Scan + spawn | ✅ Done | |
| `pipeline_template.py` — Load pipelines TOML | ✅ Done | |
| `merge_verifier.py` — git merge-base verification | ✅ Done | |
| `metrics.py` — Stage durations, rejection counts | ✅ Done | |
| `board.py` — Kanban board | ✅ Done | |
| `pipelines/default.toml` | ✅ Done | 5-stage pipeline with routing |
| `pipelines/investigation.toml` | ✅ Done | |
| Role prompts (all 11 `.md` files) | ✅ Done | conductor, developer, reviewer, security_reviewer, integrator, tester, investigator, challenger, visual_web, visual_ios |
| `prompts/consolidator.md` | ❌ Missing | Plan mentions it, not found in project |
| **Skills** (`.claude/skills/`) | ❌ Missing | `task-workflow/SKILL.md`, `code-standards/SKILL.md`, `git-strategy/SKILL.md` not found |
| `cli.py` — Separate command implementations | ⚠️ Merged | Commands live in `__main__.py` instead of separate `cli.py` |
| `test_pipeline_checker.py` | ✅ Done | |
| `test_pipeline_template.py` | ❓ Unclear | |
| `test_merge_verifier.py` | ❓ Unclear | |

---

## Phase 4: Resilience & Monitoring (Weeks 7-8) — ✅ COMPLETE (~100%)

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
| `log_rotation.py` | ✅ Done | Not in plan as separate file, but implemented |
| `test_daemon.py` | ✅ Done | |
| `test_scheduler.py` | ✅ Done | |
| `test_communication.py` | ✅ Done | |
| `test_recovery.py` | ✅ Done | |
| `test_backup.py` | ✅ Done | |

---

## Phase 5: Polish & Evaluation (Weeks 9-10) — ✅ MOSTLY COMPLETE (~80%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `eval/runner.py` — Model eval framework | ✅ Done | Framework exists |
| `eval/test_cases/*.json` | ✅ Done | conductor_decomposition, reviewer_approval, security_reviewer, integrator_merge |
| `sessions.py` — Multi-project sessions | ✅ Done | |
| `doctor.py` — 10 health checks | ✅ Done | |
| Log rotation | ✅ Done | |
| End-to-end test | ✅ Done | `test_e2e.py` exists |
| **Documentation** (`docs/`) | ⚠️ Partial | `docs/` directory exists but unclear if it has all planned files (quickstart, concepts/, prompts.md) |
| `CHANGELOG.md` | ❌ Missing | |
| `.github/workflows/release.yml` | ❌ Missing | |
| `.github/workflows/eval.yml` | ❌ Missing | |
| `pipx install` readiness | ❓ Unclear | pyproject.toml exists but publishability unknown |

---

## Phase 6: TUI & Observability (Weeks 11-13) — ⚠️ PARTIAL (~65%)

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `dashboard.py` — Interactive TUI | ✅ Done | Rich TUI + plain text fallback |
| `cost_tracker.py` — Token usage tracking | ✅ Done | Per-role/task/model breakdown |
| `observability.py` — Prometheus export | ✅ Done | `.prom` file export |
| `warchief costs` command | ✅ Done | |
| `warchief dashboard` command | ✅ Done | |
| **OpenTelemetry integration** | ❌ Missing | Plan says OTel metrics (histograms, spans) — current impl is Prometheus text format only |
| **Textual-based interactive TUI** | ❓ Partial | Has rich-based dashboard, unclear if full textual interactive app (agent tree view, problems view) |
| **Cost budget / auto-pause** | ❌ Missing | Plan says "pause pipeline when budget exceeded" — not implemented |

---

## Phase 7: Go Binary & Distribution (Weeks 14-16) — ❌ NOT STARTED (0%)

| Plan Item | Status |
|-----------|--------|
| Go module setup | ❌ |
| Port task_store → Go | ❌ |
| Port state_machine → Go | ❌ |
| Port daemon/watcher/spawner → Go | ❌ |
| GoReleaser | ❌ |
| Homebrew formula | ❌ |
| `cmd/`, `internal/` Go packages | ❌ |

---

## Phase 8: Platform (Weeks 17-20) — ❌ NOT STARTED (0%)

| Plan Item | Status |
|-----------|--------|
| Multi-runtime support (Codex, Gemini) | ❌ |
| Plugin system | ❌ |
| Web dashboard (htmx) | ❌ |
| Container sandboxing | ❌ |
| Distributed execution (gRPC) | ❌ |
| PostgreSQL adapter | ❌ |
| YAML pipeline definitions | ❌ |

---

## Overall Summary

| Phase | Status | Completion |
|-------|--------|------------|
| **Phase 1**: Foundation | ✅ Complete | ~95% |
| **Phase 2**: Agent Management | ✅ Mostly Complete | ~85% |
| **Phase 3**: Pipeline & Routing | ✅ Mostly Complete | ~85% |
| **Phase 4**: Resilience & Monitoring | ✅ Complete | ~100% |
| **Phase 5**: Polish & Evaluation | ✅ Mostly Complete | ~80% |
| **Phase 6**: TUI & Observability | ⚠️ Partial | ~65% |
| **Phase 7**: Go Binary | ❌ Not Started | 0% |
| **Phase 8**: Platform | ❌ Not Started | 0% |

---

## Critical Gaps (within "done" phases)

1. **Hook enforcement scripts** — The `.claude/hooks/` scripts (`validate-opus-transition.py`, `verify-task-updated.py`, `save-conductor-context.py`) are missing. This is arguably the most important gap because the plan's security model depends on hooks preventing agents from violating role boundaries.

2. **GitHub CI/CD** — No `.github/workflows/` at all (ci.yml, release.yml, eval.yml).

3. **Skills** — `.claude/skills/` (task-workflow, code-standards, git-strategy) not created.

4. **Cost budget enforcement** — Cost tracking exists but no auto-pause when budget exceeded.

5. **OpenTelemetry** — Only basic Prometheus text export, not full OTel integration with histograms/spans.

---

## Bottom Line

**Phases 1-5 (the working orchestrator) are ~90% built.** The core engine works — task management, state machine, agent spawning, pipeline routing, self-healing, monitoring, and evaluation are all implemented. The main holes are enforcement hooks, CI/CD, and distribution polish.

**Phases 6-8 (the platform evolution) are 0-65% done** — Phase 6 has partial coverage with dashboard and cost tracking, while Phases 7 (Go rewrite) and 8 (platform features) haven't started.
