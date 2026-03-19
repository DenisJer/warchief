"""Tests for warchief.agent_log_writer — stream-json parsing."""

from __future__ import annotations

import io
import json

from warchief.agent_log_writer import stream_to_readable


def test_assistant_text_output():
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Hello world"}]},
    }
    inp = io.StringIO(json.dumps(event) + "\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    assert "Hello world" in out.getvalue()


def test_result_event_writes_cost():
    event = {
        "type": "result",
        "cost_usd": 0.05,
        "duration_ms": 5000,
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    inp = io.StringIO(json.dumps(event) + "\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    output = out.getvalue()
    assert "$0.05" in output or "0.0500" in output


def test_tool_use_bash_output():
    event = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}]
        },
    }
    inp = io.StringIO(json.dumps(event) + "\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    assert "ls -la" in out.getvalue()


def test_tool_use_edit_output():
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Edit",
                    "input": {"file_path": "/tmp/foo.py"},
                }
            ]
        },
    }
    inp = io.StringIO(json.dumps(event) + "\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    assert "/tmp/foo.py" in out.getvalue()


def test_tool_use_read_output():
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Read",
                    "input": {"file_path": "/tmp/bar.py"},
                }
            ]
        },
    }
    inp = io.StringIO(json.dumps(event) + "\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    assert "/tmp/bar.py" in out.getvalue()


def test_invalid_json_passthrough():
    inp = io.StringIO("not json at all\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    assert "not json at all" in out.getvalue()


def test_empty_lines_skipped():
    inp = io.StringIO("\n\n\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    # Should only have the "Agent started" line
    assert "Agent started" in out.getvalue()


def test_error_event():
    event = {
        "type": "error",
        "error": {"message": "Rate limited"},
    }
    inp = io.StringIO(json.dumps(event) + "\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    assert "ERROR" in out.getvalue()
    assert "Rate limited" in out.getvalue()


def test_result_with_cache_tokens():
    event = {
        "type": "result",
        "cost_usd": 0.10,
        "duration_ms": 10000,
        "usage": {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_read_input_tokens": 1000,
            "cache_creation_input_tokens": 300,
        },
    }
    inp = io.StringIO(json.dumps(event) + "\n")
    out = io.StringIO()
    stream_to_readable(input_stream=inp, output_stream=out)
    output = out.getvalue()
    assert "cache_r" in output
    assert "cache_w" in output
