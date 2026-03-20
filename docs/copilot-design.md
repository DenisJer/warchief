# Warchief Copilot — AI Orchestrator Design

## Overview

An AI copilot that runs alongside the watcher, allowing the human to communicate conversationally with the pipeline. The copilot watches agent output, decides actions (tell/nudge/answer/skip), and talks to the user.

## Architecture Decision

### Approaches Evaluated

| # | Approach | Verdict |
|---|----------|---------|
| 1 | Claude API (Anthropic SDK) | **Viable** — best latency, most control, needed for dashboard integration |
| 2 | Claude CLI with --resume | **Dead on arrival** — not a daemon, seconds of latency per turn |
| 3 | Claude CLI with MCP Server | **Best for terminal** — natural UX, ~350 lines, reuses CLI |
| 4 | Claude CLI with Named Pipe | **Dead on arrival** — CLI doesn't support persistent stdin |
| 5 | Hybrid (CLI + API) | **Best overall** — right tool for each job |

### Decision: Two-Phase Hybrid

**Phase 1: Terminal copilot via MCP Server** (`warchief copilot`)
- Human types in terminal, Claude CLI has pipeline tools via MCP
- ~350 lines of new code
- No new dependencies, consistent with rest of codebase

**Phase 2: Dashboard chat panel via API** (web integration)
- WebSocket from browser → FastAPI → Anthropic API with tool_use
- ~400 additional lines
- Requires `anthropic` SDK dependency
- Reuses tool implementations from Phase 1

The MCP server's tool implementations are shared by both phases.

## Phase 1: MCP Copilot Server

### Tools Exposed

| Tool | Description | Maps to |
|------|-------------|---------|
| `list_tasks` | Show all tasks with status/stage | `store.list_tasks()` |
| `get_task_status` | Detailed task info | `store.get_task()` |
| `get_pipeline_state` | Full pipeline overview | `_build_state()` from web/app.py |
| `tell_task` | Send message (next agent sees it) | `/api/tell/{task_id}` |
| `nudge_task` | Kill agent + send message (restart) | `/api/nudge/{task_id}` |
| `answer_question` | Answer pending agent question | `/api/answer/{task_id}` |
| `read_agent_log` | Read last N lines of agent output | agent-logs/{id}.log |
| `skip_stage` | Advance task to next stage | `store.update_task()` |
| `approve_task` | Approve plan/investigation | `/api/approve-plan/{task_id}` |
| `reject_task` | Reject with feedback | `/api/reject-plan/{task_id}` |
| `increase_budget` | Increase task budget | `/api/increase-budget/{task_id}` |

### File Structure

```
warchief/
  mcp_copilot_server.py    # MCP server (JSON-RPC over stdio)
  copilot_tools.py          # Tool implementations (shared with Phase 2)
```

### Launch

```bash
# Option A: warchief command that launches claude with MCP server
warchief copilot

# Which internally runs:
claude --mcp-server warchief-pipeline="python -m warchief.mcp_copilot_server"

# Option B: User adds to ~/.claude.json manually
# Then any Claude conversation has pipeline tools
```

### System Prompt

```markdown
You are the Warchief Copilot — an AI assistant monitoring the development pipeline.

You have tools to inspect and control the pipeline:
- View task status and agent logs
- Send messages to agents (tell = passive, nudge = kill + restart)
- Answer agent questions
- Approve/reject plans and investigations
- Skip stages or increase budgets

When the user describes what they want, figure out the right action:
- "tell the developer to use strict mode" → tell_task with the right task_id
- "STOP that agent" → nudge_task to kill and restart
- "yes use Vitest" → answer_question if there's a pending question
- "how's it going?" → read_agent_log + get_pipeline_state, summarize

Be concise. Show task IDs when relevant. Warn before destructive actions (nudge wastes tokens).
```

### Example Interaction

```
Human: what's happening right now?

Copilot: Pipeline has 1 active task:
  wc-3191ba "Initialize Nuxt.js project" — testing stage
  Agent tester-thrall-93f9 running for 2m, writing tests
  Budget: $2.78 / $4.00