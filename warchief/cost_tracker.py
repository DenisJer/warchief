"""Cost tracking — track token usage and costs per agent and task."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from warchief.task_store import TaskStore


# Approximate pricing per 1M tokens (as of 2025)
# input = base input price, output = output price,
# cache_read = cached input read price, cache_write = cached input write price
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-20250514": {
        "input": 15.0, "output": 75.0,
        "cache_read": 1.50, "cache_write": 18.75,
    },
    "claude-sonnet-4-20250514": {
        "input": 3.0, "output": 15.0,
        "cache_read": 0.30, "cache_write": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80, "output": 4.0,
        "cache_read": 0.08, "cache_write": 1.0,
    },
    # Fallback for unknown models (sonnet pricing)
    "default": {
        "input": 3.0, "output": 15.0,
        "cache_read": 0.30, "cache_write": 3.75,
    },
}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class CostEntry:
    agent_id: str
    task_id: str
    role: str
    model: str
    usage: TokenUsage
    cost_usd: float
    timestamp: float = 0.0


@dataclass
class CostSummary:
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    by_role: dict[str, float] = field(default_factory=dict)
    by_task: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)
    entries: list[CostEntry] = field(default_factory=list)


def estimate_cost(usage: TokenUsage, model: str) -> float:
    """Estimate cost in USD based on token usage and model.

    Includes cache read/write tokens at their respective rates.
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
    cache_read_cost = (usage.cache_read_tokens / 1_000_000) * pricing.get("cache_read", 0)
    cache_write_cost = (usage.cache_write_tokens / 1_000_000) * pricing.get("cache_write", 0)
    return input_cost + output_cost + cache_read_cost + cache_write_cost


def parse_claude_output(output: str) -> TokenUsage | None:
    """Parse token usage from Claude CLI output.

    Claude CLI outputs lines like:
      Input tokens: 1234
      Output tokens: 567
    """
    usage = TokenUsage()
    found = False

    for line in output.splitlines():
        line = line.strip()

        match = re.match(r"input\s+tokens?:\s*(\d[\d,]*)", line, re.IGNORECASE)
        if match:
            usage.input_tokens = int(match.group(1).replace(",", ""))
            found = True
            continue

        match = re.match(r"output\s+tokens?:\s*(\d[\d,]*)", line, re.IGNORECASE)
        if match:
            usage.output_tokens = int(match.group(1).replace(",", ""))
            found = True
            continue

        match = re.match(r"cache\s+read\s+tokens?:\s*(\d[\d,]*)", line, re.IGNORECASE)
        if match:
            usage.cache_read_tokens = int(match.group(1).replace(",", ""))
            found = True
            continue

        match = re.match(r"cache\s+write\s+tokens?:\s*(\d[\d,]*)", line, re.IGNORECASE)
        if match:
            usage.cache_write_tokens = int(match.group(1).replace(",", ""))
            found = True

    return usage if found else None


def load_cost_log(project_root: Path) -> list[CostEntry]:
    """Load cost entries from the cost log file."""
    log_path = project_root / ".warchief" / "costs.jsonl"
    if not log_path.exists():
        return []

    entries: list[CostEntry] = []
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            entries.append(CostEntry(
                agent_id=data["agent_id"],
                task_id=data["task_id"],
                role=data["role"],
                model=data["model"],
                usage=TokenUsage(**data["usage"]),
                cost_usd=data["cost_usd"],
                timestamp=data.get("timestamp", 0.0),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def append_cost_entry(project_root: Path, entry: CostEntry) -> None:
    """Append a cost entry to the cost log."""
    log_path = project_root / ".warchief" / "costs.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "agent_id": entry.agent_id,
        "task_id": entry.task_id,
        "role": entry.role,
        "model": entry.model,
        "usage": {
            "input_tokens": entry.usage.input_tokens,
            "output_tokens": entry.usage.output_tokens,
            "cache_read_tokens": entry.usage.cache_read_tokens,
            "cache_write_tokens": entry.usage.cache_write_tokens,
        },
        "cost_usd": entry.cost_usd,
        "timestamp": entry.timestamp or time.time(),
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(data) + "\n")


def _load_usage_json_files(project_root: Path) -> list[CostEntry]:
    """Scan .usage.json files from agent-logs for real-time cost data.

    These files are written by agent_log_writer as soon as each agent
    finishes, before the watcher has a chance to process them into costs.jsonl.
    """
    logs_dir = project_root / ".warchief" / "agent-logs"
    if not logs_dir.exists():
        return []

    entries: list[CostEntry] = []
    for usage_file in logs_dir.glob("*.usage.json"):
        try:
            data = json.loads(usage_file.read_text())
            # Extract agent_id from filename: "<agent_id>.usage.json"
            agent_id = usage_file.stem.replace(".usage", "")
            # Parse role from agent_id: "role-name-suffix"
            parts = agent_id.split("-")
            role = parts[0] if parts else ""
            model = data.get("model", "")
            usage = TokenUsage(
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                cache_read_tokens=data.get("cache_read_tokens", 0),
                cache_write_tokens=data.get("cache_write_tokens", 0),
            )
            cost_usd = data.get("cost_usd", 0.0)
            if not cost_usd:
                cost_usd = estimate_cost(usage, model)
            entries.append(CostEntry(
                agent_id=agent_id,
                task_id="",
                role=role,
                model=model,
                usage=usage,
                cost_usd=cost_usd,
                timestamp=data.get("timestamp", 0.0),
            ))
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    return entries


def compute_cost_summary(project_root: Path) -> CostSummary:
    """Compute a cost summary from costs.jsonl and live .usage.json files.

    Merges both sources so costs show up as soon as agents finish,
    without waiting for the watcher to process them.
    """
    entries = load_cost_log(project_root)
    known_agents = {e.agent_id for e in entries}

    # Add costs from .usage.json files not yet in costs.jsonl
    for entry in _load_usage_json_files(project_root):
        if entry.agent_id not in known_agents:
            entries.append(entry)

    summary = CostSummary(entries=entries)

    for entry in entries:
        # Re-estimate cost if it was recorded as 0 but has token data
        cost = entry.cost_usd
        if not cost and (entry.usage.input_tokens or entry.usage.output_tokens
                         or entry.usage.cache_read_tokens):
            cost = estimate_cost(entry.usage, entry.model)
            entry.cost_usd = cost

        summary.total_cost_usd += cost
        summary.total_input_tokens += entry.usage.input_tokens
        summary.total_output_tokens += entry.usage.output_tokens
        summary.total_cache_read_tokens += entry.usage.cache_read_tokens
        summary.total_cache_write_tokens += entry.usage.cache_write_tokens

        summary.by_role[entry.role] = summary.by_role.get(entry.role, 0) + entry.cost_usd
        summary.by_task[entry.task_id] = summary.by_task.get(entry.task_id, 0) + entry.cost_usd
        summary.by_model[entry.model] = summary.by_model.get(entry.model, 0) + entry.cost_usd

    return summary


def format_cost_summary(summary: CostSummary) -> str:
    """Format cost summary for display."""
    lines: list[str] = []
    lines.append("Token Usage")
    lines.append("=" * 55)
    lines.append(f"  In:             {summary.total_input_tokens:,}")
    lines.append(f"  Cache Read:     {summary.total_cache_read_tokens:,}")
    lines.append(f"  Cache Write:    {summary.total_cache_write_tokens:,}")
    lines.append(f"  Out:            {summary.total_output_tokens:,}")

    if summary.by_model:
        lines.append("")
        lines.append("  By Model:")
        for model, cost in sorted(summary.by_model.items(), key=lambda x: -x[1]):
            short_model = model.split("-")[1] if "-" in model else model
            lines.append(f"    {short_model:<20} ${cost:.4f}")

    if summary.by_role:
        lines.append("")
        lines.append("  By Role:")
        for role, cost in sorted(summary.by_role.items(), key=lambda x: -x[1]):
            lines.append(f"    {role:<20} ${cost:.4f}")

    if summary.by_task:
        lines.append("")
        lines.append("  By Task (top 10):")
        sorted_tasks = sorted(summary.by_task.items(), key=lambda x: -x[1])[:10]
        for task_id, cost in sorted_tasks:
            lines.append(f"    {task_id:<20} ${cost:.4f}")

    if not summary.entries:
        lines.append("")
        lines.append("  No cost data recorded yet.")

    return "\n".join(lines)


def check_budget(project_root: Path, budget_usd: float) -> tuple[bool, float]:
    """Check if total cost is within budget.

    Returns (within_budget, remaining_usd).
    """
    summary = compute_cost_summary(project_root)
    remaining = budget_usd - summary.total_cost_usd
    return remaining > 0, remaining


def get_task_cost(project_root: Path, task_id: str) -> float:
    """Get total cost for a specific task."""
    summary = compute_cost_summary(project_root)
    return summary.by_task.get(task_id, 0.0)


def get_session_cost(project_root: Path, session_start: float) -> float:
    """Get total cost since a given timestamp."""
    summary = compute_cost_summary(project_root)
    return sum(e.cost_usd for e in summary.entries if e.timestamp >= session_start)
