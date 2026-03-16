"""Web dashboard — FastAPI + WebSocket live dashboard for Warchief.

Serves a WoW-themed single-page dashboard on localhost with REST endpoints
for task actions and a WebSocket that pushes full pipeline state every 2 seconds.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from warchief.config import STAGES, read_config
from warchief.cost_tracker import compute_cost_summary
from warchief.mcp_discovery import get_mcp_servers, is_tool_grant, resolve_tool_grant
from warchief.scratchpad import read_scratchpad
from warchief.metrics import compute_pipeline_metrics, format_duration
from warchief.models import EventRecord, MessageRecord
from warchief.task_store import TaskStore

_project_root: Path = Path.cwd()
_session_start: float = time.time()
_shared_store: TaskStore | None = None


def _store() -> TaskStore:
    """Get or create a shared DB connection.

    Reuses one connection to avoid SQLite lock contention from
    multiple dashboard processes / WebSocket ticks.
    """
    global _shared_store
    if _shared_store is None:
        _shared_store = TaskStore(_project_root / ".warchief" / "warchief.db")
    return _shared_store


def _build_state() -> dict:
    """Build the full dashboard state dict."""
    store = _store()
    tasks = store.list_tasks()
    agents = store.get_running_agents()
    metrics = compute_pipeline_metrics(store)
    config = read_config(_project_root)
    events = store.get_events(limit=20)
    all_question_tasks = store.list_tasks(has_label="question")
    question_tasks = [t for t in all_question_tasks if t.status != "closed"]

    question_data: list[dict] = []
    for qt in question_tasks:
        msgs = store.get_task_messages(qt.id)
        q_msgs = [m for m in msgs if m.message_type == "question"]
        latest_q = q_msgs[-1].body if q_msgs else ""
        question_data.append({
            "task_id": qt.id,
            "title": qt.title,
            "question": latest_q,
        })

    cost_summary = compute_cost_summary(_project_root)
    now = time.time()

    # Pipeline stages
    pipeline: list[dict] = []
    agent_map = {a.current_task: a for a in agents if a.current_task}
    for stage in STAGES:
        stage_tasks = [t for t in tasks if t.stage == stage and t.status != "closed"]
        cards = []
        for t in stage_tasks:
            agent = agent_map.get(t.id)
            age = format_duration(now - t.updated_at) if t.updated_at else ""
            scratchpad = read_scratchpad(_project_root, t.id)
            # Get latest question if task has question label
            question_text = ""
            if "question" in t.labels:
                q_msgs = [m for m in store.get_task_messages(t.id, limit=5)
                          if m.message_type == "question"]
                if q_msgs:
                    question_text = q_msgs[-1].body
            # Get block reason from events
            block_reason = ""
            if t.status == "blocked":
                block_evts = store.get_events(task_id=t.id, limit=5)
                for ev in block_evts:
                    if ev.event_type == "block" and ev.details:
                        reason = ev.details.get("failure_reason", "")
                        if reason:
                            block_reason = reason
                            break
            cards.append({
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "agent_id": agent.id if agent else None,
                "age": age,
                "labels": t.labels,
                "scratchpad": scratchpad[:500] if scratchpad else "",
                "question": question_text,
                "block_reason": block_reason,
            })
        pipeline.append({"stage": stage, "tasks": cards, "count": len(cards)})

    # Agents list
    agent_list = []
    for a in agents:
        age = format_duration(now - a.spawned_at) if a.spawned_at else ""
        agent_list.append({
            "id": a.id,
            "role": a.role,
            "status": a.status,
            "task": a.current_task or "",
            "age": age,
        })

    # Events
    max_age = 600
    recent_events = []
    for e in events:
        if e.created_at and (now - e.created_at) < max_age:
            recent_events.append({
                "type": e.event_type,
                "task_id": e.task_id or "",
                "agent_id": e.agent_id or "",
                "age": format_duration(now - e.created_at) if e.created_at else "",
            })

    # MCP servers
    mcp_servers = get_mcp_servers()

    # Check if watcher is running
    watcher_lock = _project_root / ".warchief" / "watcher.lock"
    watcher_running = False
    watcher_pid = None
    if watcher_lock.exists():
        try:
            watcher_pid = int(watcher_lock.read_text().strip())
            import os
            os.kill(watcher_pid, 0)  # Check if alive
            watcher_running = True
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            watcher_running = False

    return {
        "timestamp": now,
        "project": _project_root.name,
        "project_path": str(_project_root),
        "paused": config.paused,
        "watcher_running": watcher_running,
        "watcher_pid": watcher_pid if watcher_running else None,
        "metrics": {
            "total": metrics.total_tasks,
            "open": metrics.open_tasks,
            "in_progress": metrics.in_progress_tasks,
            "blocked": metrics.blocked_tasks,
            "closed": metrics.closed_tasks,
            "agents_running": len(agents),
            "avg_completion": format_duration(metrics.avg_completion_time)
            if metrics.avg_completion_time > 0 else "",
        },
        "tokens": {
            "input": cost_summary.total_input_tokens,
            "cache_read": cost_summary.total_cache_read_tokens,
            "cache_write": cost_summary.total_cache_write_tokens,
            "output": cost_summary.total_output_tokens,
            "cost_usd": round(cost_summary.total_cost_usd, 4),
            "session_cost_usd": round(sum(
                e.cost_usd for e in cost_summary.entries
                if e.timestamp >= _session_start
            ), 4),
            "by_model": {k: round(v, 4) for k, v in cost_summary.by_model.items()},
            "by_role": {k: round(v, 4) for k, v in cost_summary.by_role.items()},
            "budget": {
                "session_limit": config.budget.session_limit,
                "per_task_default": config.budget.per_task_default,
            },
        },
        "pipeline": pipeline,
        "agents": agent_list,
        "questions": question_data,
        "events": recent_events,
        "mcp_servers": list(mcp_servers.keys()),
    }


app = FastAPI(title="Warchief Dashboard")

# Mount static files
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = _static_dir / "index.html"
    return HTMLResponse(content=index_path.read_text(), status_code=200)


@app.get("/api/state")
async def get_state():
    return _build_state()


class ActionBody(BaseModel):
    message: str = ""


class CreateTaskBody(BaseModel):
    title: str
    description: str = ""
    type: str = "feature"
    priority: int = 5
    labels: str = ""
    deps: str = ""
    tools: str = ""
    budget: float = 0.0


@app.post("/api/answer/{task_id}")
async def answer_task(task_id: str, body: ActionBody):
    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
    if "question" not in task.labels:
        return {"error": f"Task '{task_id}' has no pending question"}

    store.create_message(MessageRecord(
        id="",
        from_agent="user",
        to_agent=task_id,
        message_type="answer",
        body=body.message,
        persistent=True,
    ))

    granted_tools: list[str] = []
    if is_tool_grant(body.message):
        granted_tools = resolve_tool_grant(body.message)
        if granted_tools:
            existing = list(task.extra_tools)
            new_tools = [t for t in granted_tools if t not in existing]
            if new_tools:
                store.update_task(task_id, extra_tools=existing + new_tools)

    new_labels = [la for la in task.labels if la != "question"]
    store.update_task(task_id, status="open", labels=new_labels)

    store.log_event(EventRecord(
        event_type="answer",
        task_id=task_id,
        details={"answer": body.message, "granted_tools": granted_tools},
        actor="user",
    ))
    return {"ok": True, "granted_tools": granted_tools}


@app.post("/api/drop/{task_id}")
async def drop_task(task_id: str):
    import os
    import signal as sig

    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    if task.assigned_agent:
        agent = store.get_agent(task.assigned_agent)
        if agent:
            if agent.pid and agent.status == "alive":
                try:
                    os.kill(agent.pid, sig.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            store.update_agent(agent.id, status="dead")
            if agent.worktree_path:
                try:
                    from warchief.worktree import remove_worktree
                    remove_worktree(_project_root, agent.id)
                except Exception:
                    pass

    # Force-update bypassing optimistic lock (watcher may be touching the same task)
    store._conn.execute(
        "UPDATE tasks SET status = 'closed', stage = NULL, assigned_agent = NULL, labels = '[]', updated_at = ? WHERE id = ?",
        (time.time(), task_id),
    )
    store._conn.execute(
        "DELETE FROM messages WHERE from_agent = ? OR to_agent = ?",
        (task_id, task_id),
    )
    store._conn.commit()
    return {"ok": True}


@app.post("/api/grant/{task_id}")
async def grant_task(task_id: str, body: ActionBody):
    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    resolved = resolve_tool_grant(body.message)
    if not resolved:
        resolved = [t.strip() for t in body.message.split(",") if t.strip()]

    existing = list(task.extra_tools)
    new_tools = [t for t in resolved if t not in existing]
    if new_tools:
        store.update_task(task_id, extra_tools=existing + new_tools)
    return {"ok": True, "granted": new_tools}


@app.post("/api/nudge/{task_id}")
async def nudge_task(task_id: str, body: ActionBody):
    from warchief.control import _do_nudge
    try:
        _do_nudge(_project_root, task_id, body.message)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/tell/{task_id}")
async def tell_task(task_id: str, body: ActionBody):
    from warchief.control import _do_tell
    try:
        _do_tell(_project_root, task_id, body.message)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/create")
async def create_task(body: CreateTaskBody):
    from warchief.models import TaskRecord
    import uuid

    task_id = f"wc-{uuid.uuid4().hex[:6]}"
    now = time.time()
    labels_list = [l.strip() for l in body.labels.split(",") if l.strip()]
    deps_list = [d.strip() for d in body.deps.split(",") if d.strip()]
    tools_list = [t.strip() for t in body.tools.split(",") if t.strip()]

    store = _store()
    record = TaskRecord(
        id=task_id,
        title=body.title,
        description=body.description,
        status="open",
        labels=labels_list,
        deps=deps_list,
        priority=body.priority,
        type=body.type,
        extra_tools=tools_list,
        budget=body.budget,
        created_at=now,
        updated_at=now,
    )
    store.create_task(record)
    return {"ok": True, "task_id": task_id}


@app.get("/api/agents")
async def list_agents():
    """List all agents with metadata for the agents page."""
    store = _store()
    agents = store.get_running_agents()
    # Also get recently dead agents from DB
    all_agents_rows = store._conn.execute(
        "SELECT * FROM agents ORDER BY spawned_at DESC LIMIT 50"
    ).fetchall()
    from warchief.task_store import _row_to_agent
    all_agents = [_row_to_agent(r) for r in all_agents_rows]

    now = time.time()
    result = []
    for a in all_agents:
        age = format_duration(now - a.spawned_at) if a.spawned_at else ""
        result.append({
            "id": a.id,
            "role": a.role,
            "status": a.status,
            "task": a.current_task or "",
            "model": a.model or "",
            "age": age,
            "spawned_at": a.spawned_at or 0,
        })
    return result


@app.get("/api/agent-log/{agent_id}")
async def get_agent_log(agent_id: str, lines: int = 200):
    """Get agent log content (last N lines)."""
    log_path = _project_root / ".warchief" / "agent-logs" / f"{agent_id}.log"
    if not log_path.exists():
        return {"lines": [], "exists": False}
    try:
        content = log_path.read_text()
        all_lines = content.strip().split("\n")
        return {"lines": all_lines[-lines:], "exists": True, "total": len(all_lines)}
    except OSError:
        return {"lines": [], "exists": False}


@app.post("/api/approve-plan/{task_id}")
async def approve_plan(task_id: str):
    """Approve a plan — task advances from planning to development."""
    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
    new_labels = [l for l in task.labels if l != "needs-plan-approval"] + ["plan-approved"]
    store.update_task(task_id, status="open", labels=new_labels)
    return {"ok": True}


@app.post("/api/reject-plan/{task_id}")
async def reject_plan(task_id: str, body: ActionBody):
    """Reject a plan — send feedback, planner will retry."""
    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
    # Store feedback as message
    store.create_message(MessageRecord(
        id="", from_agent="user", to_agent=task_id,
        message_type="feedback", body=body.message, persistent=True,
    ))
    new_labels = [l for l in task.labels if l != "needs-plan-approval"] + ["rejected"]
    store.update_task(task_id, status="open", labels=new_labels)
    return {"ok": True}


@app.post("/api/approve-investigation/{task_id}")
async def approve_investigation(task_id: str):
    """Approve investigation findings — close the task."""
    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
    store._conn.execute(
        "UPDATE tasks SET status = 'closed', stage = NULL, updated_at = ? WHERE id = ?",
        (time.time(), task_id),
    )
    store._conn.commit()
    return {"ok": True}


@app.post("/api/reject-investigation/{task_id}")
async def reject_investigation(task_id: str, body: ActionBody):
    """Reject investigation — send feedback, investigator will re-run."""
    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
    store.create_message(MessageRecord(
        id="", from_agent="user", to_agent=task_id,
        message_type="feedback", body=body.message, persistent=True,
    ))
    new_labels = [l for l in task.labels if l != "needs-review"] + ["rejected"]
    store.update_task(task_id, status="open", labels=new_labels)
    return {"ok": True}


@app.post("/api/escalate/{task_id}")
async def escalate_investigation(task_id: str):
    """Escalate investigation findings — create a conductor task to decompose into sub-tasks."""
    from warchief.models import TaskRecord
    from warchief.scratchpad import read_scratchpad
    import uuid

    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    findings = read_scratchpad(_project_root, task_id)
    now = time.time()
    conductor_id = f"wc-{uuid.uuid4().hex[:6]}"

    record = TaskRecord(
        id=conductor_id,
        title=f"Decompose: {task.title}",
        description=(
            f"Based on investigation {task_id}, break down the following findings into "
            f"actionable development tasks:\n\n{findings}"
        ),
        status="open",
        type="feature",
        priority=task.priority,
        created_at=now,
        updated_at=now,
    )
    store.create_task(record)

    # Close the investigation task
    store._conn.execute(
        "UPDATE tasks SET status = 'closed', stage = NULL, updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    store._conn.commit()
    return {"ok": True, "conductor_task_id": conductor_id}


class DecomposeBody(BaseModel):
    tasks: list[dict] = []


@app.post("/api/decompose/{task_id}")
async def decompose_task(task_id: str, body: DecomposeBody):
    """Manually decompose a task into sub-tasks."""
    from warchief.models import TaskRecord
    import uuid

    store = _store()
    task = store.get_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    if not body.tasks:
        return {"error": "No sub-tasks provided"}

    now = time.time()
    group_id = task.group_id or task.id
    created_ids = []

    for st in body.tasks:
        if not st.get("title"):
            continue
        sub_id = f"wc-{uuid.uuid4().hex[:6]}"
        record = TaskRecord(
            id=sub_id,
            title=st["title"],
            description=st.get("description", ""),
            status="open",
            type=st.get("type", "feature"),
            priority=st.get("priority", task.priority),
            group_id=group_id,
            budget=task.budget,
            created_at=now,
            updated_at=now,
        )
        store.create_task(record)
        created_ids.append(sub_id)

    if created_ids:
        store._conn.execute(
            "UPDATE tasks SET status = 'closed', stage = NULL, labels = '[\"decomposed\"]', group_id = ?, updated_at = ? WHERE id = ?",
            (group_id, now, task_id),
        )
        store._conn.commit()

    return {"ok": True, "sub_tasks": created_ids}


@app.get("/api/messages/{task_id}")
async def get_messages(task_id: str):
    """Get Q&A message history for a task."""
    store = _store()
    msgs = store.get_task_messages(task_id)
    return [
        {
            "type": m.message_type,
            "body": m.body,
            "from": m.from_agent or "",
            "created_at": m.created_at,
        }
        for m in msgs
        if m.message_type in ("question", "answer", "feedback")
    ]


@app.post("/api/watcher/start")
async def start_watcher():
    """Start the watcher as a background process."""
    import subprocess
    import sys

    lock_path = _project_root / ".warchief" / "watcher.lock"
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip())
            import os
            os.kill(pid, 0)
            return {"error": "Watcher already running", "pid": pid}
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            lock_path.unlink(missing_ok=True)

    python = sys.executable
    proc = subprocess.Popen(
        [python, "-m", "warchief", "watch"],
        cwd=str(_project_root),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "pid": proc.pid}


@app.post("/api/watcher/stop")
async def stop_watcher():
    """Stop the running watcher."""
    import os
    import signal as sig

    lock_path = _project_root / ".warchief" / "watcher.lock"
    if not lock_path.exists():
        return {"error": "Watcher not running"}
    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, sig.SIGTERM)
        return {"ok": True, "pid": pid}
    except (ValueError, ProcessLookupError, PermissionError) as e:
        lock_path.unlink(missing_ok=True)
        return {"error": f"Watcher not running: {e}"}


@app.get("/api/watcher-log")
async def get_watcher_log(lines: int = 100):
    """Get the last N lines of the watcher log."""
    log_path = _project_root / ".warchief" / "warchief.log"
    if not log_path.exists():
        return {"lines": [], "exists": False}
    try:
        content = log_path.read_text()
        all_lines = content.strip().split("\n")
        return {"lines": all_lines[-lines:], "exists": True, "total": len(all_lines)}
    except OSError:
        return {"lines": [], "exists": False}


@app.get("/api/scratchpad/{task_id}")
async def get_scratchpad(task_id: str):
    """Get the full scratchpad content for a task."""
    content = read_scratchpad(_project_root, task_id)
    return {"content": content, "task_id": task_id}


@app.get("/api/agent-file")
async def get_agent_file(path: str):
    """Read a file from an agent's worktree. Only serves files under .warchief-worktrees/."""
    from pathlib import PurePosixPath
    safe_path = Path(path).resolve()
    worktrees_dir = (_project_root / ".warchief-worktrees").resolve()
    # Security: only serve files from worktrees directory
    if not str(safe_path).startswith(str(worktrees_dir)):
        return {"error": "Access denied — only worktree files allowed"}
    if not safe_path.exists():
        return {"error": "File not found (worktree may have been cleaned up)"}
    if safe_path.is_dir():
        return {"error": "Path is a directory"}
    try:
        content = safe_path.read_text(errors="replace")
        # Cap at 50KB
        if len(content) > 50_000:
            content = content[:50_000] + "\n\n... (truncated at 50KB)"
        return {"content": content, "path": str(safe_path), "size": safe_path.stat().st_size}
    except OSError as e:
        return {"error": str(e)}


@app.get("/agents", response_class=HTMLResponse)
async def agents_page():
    agents_path = _static_dir / "agents.html"
    return HTMLResponse(content=agents_path.read_text(), status_code=200)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            state = _build_state()
            await ws.send_json(state)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


def run_server(project_root: Path, port: int = 8095) -> None:
    """Start the uvicorn server.

    Only one web dashboard per project. If another is already running,
    prints its URL and exits. Different projects can run on different ports.
    """
    global _project_root, _session_start, _shared_store
    _project_root = project_root
    _session_start = time.time()

    import fcntl
    import socket
    import uvicorn

    # One dashboard per project — lock file prevents duplicates
    lock_path = project_root / ".warchief" / "dashboard.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        # Another dashboard is running — try to read its port
        try:
            existing_port = lock_path.read_text().strip()
            print(f"Dashboard already running for this project: http://localhost:{existing_port}")
        except OSError:
            print("Dashboard already running for this project.")
        return

    _shared_store = TaskStore(_project_root / ".warchief" / "warchief.db")

    # Auto-find available port starting from requested port
    for attempt in range(20):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("0.0.0.0", port))
            sock.close()
            break
        except OSError:
            port += 1
    else:
        print(f"Error: Could not find an available port (tried {port - 20} to {port - 1})", file=__import__('sys').stderr)
        lock_fd.close()
        return

    # Write port to lock file so other instances can show the URL
    lock_path.write_text(str(port))

    url = f"http://localhost:{port}"
    print(f"Warchief Web Dashboard: {url}")

    # Open browser after a short delay (so server is ready)
    import threading
    import webbrowser
    threading.Timer(1.0, webbrowser.open, args=[url]).start()

    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    finally:
        # Release lock on shutdown
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
