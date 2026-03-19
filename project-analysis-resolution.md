# Warchief Project Analysis — Consolidated Resolution

**Date**: 2026-03-19
**Teams**: Skeptic, Testing, Brainstorm, Developer

---

## Executive Summary

Four parallel analysis teams reviewed the Warchief codebase. Combined findings: **4 critical**, **10 high**, **25 medium**, and **20+ low** severity issues across bugs, test gaps, architecture, and missing features. The codebase is functional and well-structured for its maturity, but has several areas that need hardening before production-grade reliability.

---

## PART 1: CRITICAL ISSUES (Fix Immediately)

### C1. Path Traversal in Web Endpoints
**Source**: Skeptic
**Files**: `web/app.py` — `/api/agent-diff/{agent_id}`, `/api/agent-file/{agent_id}`
**Problem**: Agent ID is used directly in file path construction without sanitization. An attacker can read arbitrary files via `../../etc/passwd` style paths.
**Fix**: Validate agent ID against `^[a-zA-Z0-9_-]+$` regex before constructing paths.

### C2. Agent Registration Race Condition
**Source**: Skeptic
**File**: `watcher.py` — `_register_agent()` + `spawn_agent()`
**Problem**: Agent is registered in DB before `spawn_agent()` returns the PID. If spawn fails, a ghost agent record exists with no process. The watcher may treat it as "alive" until the next health check.
**Fix**: Register agent only after successful spawn, or mark as "pending" until PID is confirmed.

### C3. `should_skip_security_review` Returns True on Empty Input
**Source**: Skeptic
**File**: `state_machine.py`
**Problem**: When `changed_files` is empty (e.g., git error), security review is silently skipped. This means a failed `git diff` results in no security review rather than a safe default.
**Fix**: Return `False` (don't skip) when `changed_files` is empty — fail safe.

### C4. Dashboard Lock File Stores Port, Not PID
**Source**: Skeptic
**File**: `web/app.py:685-998`
**Problem**: Lock file contains the port number, but stale-lock detection reads it as a PID and calls `os.kill(port_number, 0)`. This could match an unrelated process.
**Fix**: Store both PID and port in the lock file (e.g., JSON `{"pid": 1234, "port": 8095}`).

---

## PART 2: HIGH SEVERITY ISSUES

### H1. SQLite Thread Safety
**Source**: Skeptic + Developer
**File**: `task_store.py`
**Problem**: Single connection with `check_same_thread=False`. Lock only protects writes; reads are unprotected. Web dashboard async handlers can issue concurrent reads during watcher writes.
**Fix**: Wrap reads in the lock too, or use `aiosqlite` for the web layer.

### H2. Watcher God Class (1900+ lines)
**Source**: Developer
**File**: `watcher.py`
**Problem**: Single class handles agent lifecycle, group gates, budget checks, recovery, cleanup, label detection, and more. Hard to test, reason about, or modify safely.
**Fix**: Extract into focused collaborator classes: `GroupGateManager`, `BudgetChecker`, `AgentRecovery`, `TaskLifecycle`.

### H3. `build_claude_command` Return Type Lie
**Source**: Developer
**File**: `spawner.py`
**Problem**: Type annotation says `list[str]` but actually returns a 3-tuple `(cmd, env, prompt_text)`. Callers unpack correctly, but this defeats type checking entirely.
**Fix**: Return a `NamedTuple` or update the type annotation.

### H4. Stale WebSocket Cache on Agent-Only Changes
**Source**: Skeptic
**File**: `web/app.py`
**Problem**: State cache hash only checks task timestamps + counts. If only agent status changes (no task modification), clients see stale data until the next task update.
**Fix**: Include agent status in the cache hash.

### H5. Orphan Reset Assumes exit_code=0
**Source**: Skeptic
**File**: `watcher.py`
**Problem**: `_reset_orphaned_tasks` calls `dispatch_transition(exit_code=0)` for tasks stuck as `in_progress`. If the agent actually crashed, exit_code=0 advances the task to the next stage as if it succeeded.
**Fix**: Use `exit_code=1` for orphaned tasks (treat as failure).

### H6. `store._conn` Direct Access (Encapsulation Violation)
**Source**: Developer
**Files**: `watcher.py`, `web/app.py`, `cost_tracker.py`
**Problem**: Multiple modules bypass `TaskStore` methods and access `store._conn` directly for raw SQL. This breaks encapsulation and makes DB changes risky.
**Fix**: Add proper `TaskStore` methods for all needed operations.

### H7. Hardcoded `base = "main"` in prime.py
**Source**: Developer
**File**: `prime.py:162`
**Problem**: Changed-files context for reviewers/testers hardcodes `main`. Projects using `master` or other default branches get empty diffs.
**Fix**: Use the task's `base_branch` or fall back to config's `base_branch`.

### H8. No Timeout on Agent Spawn
**Source**: Skeptic
**File**: `spawner.py`
**Problem**: If `claude --print` hangs (API outage, network issue), the watcher waits indefinitely. There's no watchdog timer on agent processes.
**Fix**: Add a configurable timeout (e.g., 30 minutes default) and kill hung agents.

---

## PART 3: MEDIUM SEVERITY ISSUES

| # | Issue | Source | File |
|---|-------|--------|------|
| M1 | `_apply_transition` duplicates logic from `_handle_agent_exit` | Dev | watcher.py |
| M2 | `_detect_labels` imports `re` inside a loop | Skeptic | watcher.py:2149 |
| M3 | Optimistic lock retry uses stale `crash_count` values | Skeptic | watcher.py:1534 |
| M4 | `costs.jsonl` append is not atomic (partial JSON on crash) | Skeptic | cost_tracker.py |
| M5 | WebSocket sends full state every 2s even when unchanged | Skeptic | web/app.py |
| M6 | `compute_cost_summary` re-parses entire cost log on every call | Dev | cost_tracker.py |
| M7 | No input validation on web API bodies (title length, type enum) | Dev | web/app.py |
| M8 | No log rotation for `warchief.log` | Dev | config.py |
| M9 | Hardcoded `__version__ = "0.1.0"` out of sync with pyproject.toml | Dev | __main__.py:14 |
| M10 | Redundant subprocess imports inside methods | Dev | watcher.py |
| M11 | `remove_labels` can contain `None` values | Skeptic | state_machine.py |
| M12 | TOML config values with `${...}` could be injection vectors | Skeptic | config.py |

---

## PART 4: TEST COVERAGE GAPS (Testing Team)

### Zero/Minimal Coverage
| Module | Tests | Gap |
|--------|-------|-----|
| `worktree.py` (core functions) | 0 | `create_branch_worktree`, `remove_worktree`, `finalize_integration` untested |
| `spawner.py` (`spawn_agent`) | 0 | 330+ line function with error recovery, completely untested |
| `web/app.py` (16+ endpoints) | 4 tested | Missing: retry, grant, approve-plan, reject-plan, decompose, agent-diff/file, config |
| `watcher.py` (`_handle_agent_exit`) | 0 | Most complex function in the codebase, untested |
| `watcher.py` (`_startup_cleanup`) | 0 | Critical startup logic untested |
| `watcher.py` (`_detect_labels`) | 0 | Security label detection untested |
| WebSocket `/ws` | 0 | Real-time state push completely untested |

### Top 10 Recommended New Tests
1. `_handle_agent_exit` integration tests (docs-only guard, stage skipping, group gates)
2. `_detect_labels` unit tests (security patterns, frontend extensions, edge cases)
3. `spawn_agent` error paths (worktree failure, CLI not found, OSError)
4. Web API endpoint coverage (especially path traversal in agent-diff/file)
5. `_startup_cleanup` with mocked state (dead processes, orphaned tasks)
6. `check_budgets` integration (session limit -> pause, per-task limit -> block)
7. `create_branch_worktree` with mocked git (branch conflicts, broken dirs)
8. Scratchpad truncation boundary tests
9. `_check_group_dev_gate` full scenarios (hold, advance, lead election)
10. `project_context.py` framework detection and CLAUDE.md merging

### Test Infrastructure Issues
- `test_spawner.py` mutates global `_name_index` — not parallel-safe
- `test_web_app.py` mutates module-level globals — not parallel-safe
- `test_mcp_discovery.py` depends on real `~/.claude.json` — non-deterministic
- Multiple test files duplicate fixtures instead of using shared `conftest.py`

---

## PART 5: FEATURE IDEAS (Brainstorm Team)

### Must-Have (Highest Impact)
| # | Feature | Rationale |
|---|---------|-----------|
| F1 | **Live agent output streaming in dashboard** | Biggest pain point: agents are a black box. Stream stdout to WebSocket. |
| F2 | **Learning from rejections (rejection memory)** | Track why code was rejected, feed patterns back to agents. Prevents repeated mistakes. |
| F3 | **`warchief start --issue <url>` GitHub integration** | Pull issue title/body/comments as task context. Most natural workflow. |
| F4 | **Dry run mode** (`--dry-run`) | Preview decomposed tasks and estimated cost before spending money. |
| F5 | **Autonomous PR review response** | Monitor created PRs for review comments -> spawn developer to fix. Closes the loop. |
| F6 | **Notification system** (Slack, webhook, desktop) | Event hooks for state changes. `EventRecord` infra already exists. |
| F7 | **Post-run summary** | After pipeline completes, show total cost, time, files changed, PR link. |
| F8 | **Smart session resume** | On crash recovery, resume from where agents left off instead of restarting stages. |

### Nice-to-Have
| # | Feature | Rationale |
|---|---------|-----------|
| F9 | Diff viewer in dashboard | Show actual code changes per task without leaving the browser. |
| F10 | Cost forecasting | Predict total pipeline cost based on task complexity and historical data. |
| F11 | TDD pipeline mode | Run tests first, then develop until tests pass. Inverted development flow. |
| F12 | Pipeline template marketplace | `warchief pipeline install django-fullstack` for pre-configured stacks. |
| F13 | Plugin/hook system | User-defined lifecycle hooks in config.toml for Jira, Slack, deploys. |
| F14 | Cost-optimized model selection | Track success rate per model per role; downgrade when confidence is high. |

### Moonshot
| # | Feature | Rationale |
|---|---------|-----------|
| F15 | Visual verification agent | Screenshot-based UI testing. Groundwork exists in prompts. |
| F16 | Multi-repo orchestration | Coordinated tasks across frontend + backend repos. |
| F17 | Human-AI pair programming | Real-time collaborative mode between user and agent. |
| F18 | Parallel dev with file-level locking | Multiple developers on same branch with file-level conflict prevention. |

---

## PART 6: RESOLUTION — PRIORITIZED ACTION PLAN

### Phase 1: Security & Correctness (Week 1)
- [ ] **C1**: Add path validation to `/api/agent-diff` and `/api/agent-file`
- [ ] **C2**: Fix agent registration race (register after spawn confirms PID)
- [ ] **C3**: Fix `should_skip_security_review` to fail-safe on empty input
- [ ] **C4**: Fix dashboard lock file to store PID + port
- [ ] **H1**: Wrap TaskStore reads in the lock
- [ ] **H5**: Use exit_code=1 for orphaned task reset
- [ ] **H7**: Fix hardcoded `base = "main"` in prime.py

### Phase 2: Architecture & Reliability (Week 2-3)
- [ ] **H2**: Extract Watcher into collaborator classes
- [ ] **H3**: Fix `build_claude_command` return type
- [ ] **H6**: Replace all `store._conn` direct access with proper TaskStore methods
- [ ] **H8**: Add configurable timeout for agent processes
- [ ] **M1**: Consolidate `_apply_transition` and `_handle_agent_exit` logic
- [ ] **M5**: Only send WebSocket updates when state actually changes
- [ ] **M6**: Cache `compute_cost_summary` results
- [ ] **H4**: Include agent status in WebSocket cache hash

### Phase 3: Test Coverage (Week 3-4)
- [ ] Write `_handle_agent_exit` integration tests
- [ ] Write `_detect_labels` unit tests
- [ ] Write `spawn_agent` error path tests
- [ ] Write web API endpoint tests (including path traversal)
- [ ] Write `_startup_cleanup` tests
- [ ] Write `check_budgets` integration tests
- [ ] Fix test infrastructure (shared fixtures, parallel safety)

### Phase 4: High-Impact Features (Week 5+)
- [ ] **F1**: Live agent output streaming in dashboard
- [ ] **F4**: Dry run mode
- [ ] **F3**: GitHub issue integration (`--issue`)
- [ ] **F5**: Autonomous PR review response
- [ ] **F6**: Webhook/notification system
- [ ] **F7**: Post-run summary

---

## Key Metrics

| Category | Count |
|----------|-------|
| Critical bugs | 4 |
| High severity | 8 |
| Medium severity | 12 |
| Low severity | 20+ |
| Untested critical paths | 7 modules |
| Must-have features | 8 |
| Nice-to-have features | 6 |
| Moonshot ideas | 4 |

**The single highest-leverage improvement**: Breaking the Watcher god class into focused modules (H2) would make every other fix easier and enable proper testing of the currently-untested critical paths.

**The single highest-impact feature**: Live agent output streaming (F1) transforms the UX from "waiting and hoping" to "watching and steering."
