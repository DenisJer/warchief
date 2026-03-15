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


def _store() -> TaskStore:
    return TaskStore(_project_root / ".warchief" / "warchief.db")


def _build_state() -> dict:
    """Build the full dashboard state dict."""
    store = _store()
    try:
        tasks = store.list_tasks()
        agents = store.get_running_agents()
        metrics = compute_pipeline_metrics(store)
        config = read_config(_project_root)
        events = store.get_events(limit=20)
        question_tasks = store.list_tasks(has_label="question")

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
            stage_tasks = [t for t in tasks if t.stage == stage]
            cards = []
            for t in stage_tasks:
                agent = agent_map.get(t.id)
                age = format_duration(now - t.updated_at) if t.updated_at else ""
                scratchpad = read_scratchpad(_project_root, t.id)
                cards.append({
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "agent_id": agent.id if agent else None,
                    "age": age,
                    "labels": t.labels,
                    "scratchpad": scratchpad[:500] if scratchpad else "",
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

        return {
            "timestamp": now,
            "paused": config.paused,
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
            },
            "pipeline": pipeline,
            "agents": agent_list,
            "questions": question_data,
            "events": recent_events,
            "mcp_servers": list(mcp_servers.keys()),
        }
    finally:
        store.close()


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


@app.post("/api/answer/{task_id}")
async def answer_task(task_id: str, body: ActionBody):
    store = _store()
    try:
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
    finally:
        store.close()


@app.post("/api/drop/{task_id}")
async def drop_task(task_id: str):
    import os
    import signal as sig

    store = _store()
    try:
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
            "UPDATE tasks SET status = 'closed', stage = NULL, assigned_agent = NULL, updated_at = ? WHERE id = ?",
            (time.time(), task_id),
        )
        store._conn.execute(
            "DELETE FROM messages WHERE from_agent = ? OR to_agent = ?",
            (task_id, task_id),
        )
        store._conn.commit()
        return {"ok": True}
    finally:
        store.close()


@app.post("/api/grant/{task_id}")
async def grant_task(task_id: str, body: ActionBody):
    store = _store()
    try:
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
    finally:
        store.close()


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
    """Start the uvicorn server."""
    global _project_root, _session_start
    _project_root = project_root
    _session_start = time.time()

    import socket
    import uvicorn

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
        return

    print(f"Warchief Web Dashboard: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
