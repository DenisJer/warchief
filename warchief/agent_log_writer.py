"""Agent log writer — converts Claude stream-json output into readable logs."""

from __future__ import annotations

import json
import os
import sys
import time


def stream_to_readable(input_stream=None, output_stream=None) -> None:
    """Read stream-json from stdin, write readable text to stdout.

    Claude's stream-json format emits one JSON object per line:
    - {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}
    - {"type": "result", "result": "...", "cost_usd": 0.01, ...}

    Also writes a .usage.json summary file alongside the log for cost tracking.
    """
    inp = input_stream or sys.stdin
    out = output_stream or sys.stdout

    ts = time.strftime("%H:%M:%S")
    out.write(f"[{ts}] Agent started\n")
    out.flush()

    for line in inp:
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Not JSON — pass through raw
            out.write(line + "\n")
            out.flush()
            continue

        event_type = event.get("type", "")

        if event_type == "assistant":
            # Extract text content from assistant messages
            message = event.get("message", {})
            content_blocks = message.get("content", [])
            for block in content_blocks:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text.strip():
                        out.write(text + "\n")
                        out.flush()
                elif block.get("type") == "tool_use":
                    tool_name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    ts = time.strftime("%H:%M:%S")
                    out.write(f"\n[{ts}] Tool: {tool_name}\n")
                    # Show key info based on tool type
                    if tool_name in ("Edit", "Write"):
                        path = tool_input.get("file_path", "")
                        out.write(f"  File: {path}\n")
                    elif tool_name == "Bash":
                        cmd = tool_input.get("command", "")
                        out.write(f"  $ {cmd}\n")
                    elif tool_name == "Read":
                        path = tool_input.get("file_path", "")
                        out.write(f"  Reading: {path}\n")
                    elif tool_name in ("Glob", "Grep"):
                        pattern = tool_input.get("pattern", "")
                        out.write(f"  Pattern: {pattern}\n")
                    out.flush()

        elif event_type == "system":
            # Capture session ID from system events
            session_id = event.get("session_id", "")
            if session_id:
                _save_session_id(session_id)

        elif event_type == "result":
            ts = time.strftime("%H:%M:%S")
            cost = event.get("cost_usd")
            duration = event.get("duration_ms")
            usage = event.get("usage", {})
            # Session ID may also appear in result
            session_id = event.get("session_id", "")
            if session_id:
                _save_session_id(session_id)
            out.write(f"\n[{ts}] Agent finished")
            if cost is not None:
                out.write(f" (cost: ${cost:.4f})")
            if duration is not None:
                out.write(f" ({duration / 1000:.1f}s)")
            if usage:
                in_tok = usage.get("input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
                cache_r = usage.get("cache_read_input_tokens", 0)
                cache_w = usage.get("cache_creation_input_tokens", 0)
                out.write(f" (tokens: {in_tok:,} in / {out_tok:,} out")
                if cache_r or cache_w:
                    out.write(f" / {cache_r:,} cache_r / {cache_w:,} cache_w")
                out.write(")")
            out.write("\n")
            out.flush()

            # Write usage summary for the watcher to pick up
            _write_usage_summary(event)

        elif event_type == "error":
            error_msg = event.get("error", {}).get("message", str(event))
            ts = time.strftime("%H:%M:%S")
            out.write(f"\n[{ts}] ERROR: {error_msg}\n")
            out.flush()


def _save_session_id(session_id: str) -> None:
    """Save the Claude session ID for potential resume later."""
    agent_id = os.environ.get("WARCHIEF_AGENT", "")
    db_path = os.environ.get("WARCHIEF_DB", "")
    if not agent_id or not db_path:
        return
    logs_dir = os.path.join(os.path.dirname(db_path), "agent-logs")
    session_path = os.path.join(logs_dir, f"{agent_id}.session")
    try:
        with open(session_path, "w") as f:
            f.write(session_id)
    except OSError:
        pass


def _write_usage_summary(result_event: dict) -> None:
    """Write a .usage.json file next to the agent log for cost tracking.

    Uses WARCHIEF_AGENT env var to determine the filename.
    """
    agent_id = os.environ.get("WARCHIEF_AGENT", "")
    db_path = os.environ.get("WARCHIEF_DB", "")
    if not agent_id or not db_path:
        return

    # Write to agent-logs directory alongside the .log file
    logs_dir = os.path.dirname(db_path)  # .warchief dir
    logs_dir = os.path.join(logs_dir, "agent-logs")
    usage_path = os.path.join(logs_dir, f"{agent_id}.usage.json")

    usage = result_event.get("usage", {})
    summary = {
        "cost_usd": result_event.get("cost_usd", 0),
        "duration_ms": result_event.get("duration_ms", 0),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        "model": result_event.get("model", ""),
        "session_id": result_event.get("session_id", ""),
        "timestamp": time.time(),
    }

    try:
        with open(usage_path, "w") as f:
            json.dump(summary, f)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        stream_to_readable()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
