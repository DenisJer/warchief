"""Backup and restore — JSONL export with compression."""
from __future__ import annotations

import dataclasses
import gzip
import json
import logging
import time
from pathlib import Path

from warchief.task_store import TaskStore

log = logging.getLogger("warchief.backup")

BACKUP_DIR = "backup"
RETENTION_DAYS = 30


def backup_dir(project_root: Path) -> Path:
    return project_root / ".warchief" / BACKUP_DIR


def create_backup(project_root: Path, store: TaskStore) -> Path:
    """Export all data to a compressed JSONL file.

    Returns the path to the backup file.
    """
    bdir = backup_dir(project_root)
    bdir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d-%H%M%S")
    backup_path = bdir / f"{timestamp}-snapshot.jsonl.gz"

    tasks = store.list_tasks()
    events = store.get_events(limit=100000)

    with gzip.open(backup_path, "wt") as f:
        # Tasks
        for task in tasks:
            record = {"_type": "task", **dataclasses.asdict(task)}
            f.write(json.dumps(record, default=str) + "\n")

        # Events
        for event in events:
            record = {"_type": "event", **dataclasses.asdict(event)}
            f.write(json.dumps(record, default=str) + "\n")

        # Agents
        running = store.get_running_agents()
        for agent in running:
            record = {"_type": "agent", **dataclasses.asdict(agent)}
            f.write(json.dumps(record, default=str) + "\n")

    log.info("Backup created: %s (%d tasks, %d events)",
             backup_path, len(tasks), len(events))
    return backup_path


def restore_backup(project_root: Path, store: TaskStore, backup_path: Path) -> dict:
    """Restore data from a JSONL backup file.

    Returns summary of restored records.
    """
    from warchief.models import TaskRecord, EventRecord, AgentRecord

    counts = {"tasks": 0, "events": 0, "agents": 0}

    opener = gzip.open if str(backup_path).endswith(".gz") else open
    with opener(backup_path, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rtype = record.pop("_type", None)

            if rtype == "task":
                task = TaskRecord(**{
                    k: v for k, v in record.items()
                    if k in TaskRecord.__dataclass_fields__
                })
                try:
                    store.create_task(task)
                    counts["tasks"] += 1
                except Exception:
                    log.debug("Skipping duplicate task %s", record.get("id"))

            elif rtype == "event":
                event = EventRecord(**{
                    k: v for k, v in record.items()
                    if k in EventRecord.__dataclass_fields__
                })
                store.log_event(event)
                counts["events"] += 1

            elif rtype == "agent":
                agent = AgentRecord(**{
                    k: v for k, v in record.items()
                    if k in AgentRecord.__dataclass_fields__
                })
                store.register_agent(agent)
                counts["agents"] += 1

    log.info("Restore complete: %s", counts)
    return counts


def list_backups(project_root: Path) -> list[Path]:
    """List available backup files, newest first."""
    bdir = backup_dir(project_root)
    if not bdir.exists():
        return []
    files = sorted(bdir.glob("*-snapshot.jsonl*"), reverse=True)
    return files


def prune_old_backups(project_root: Path, retention_days: int = RETENTION_DAYS) -> int:
    """Remove backups older than retention_days. Returns count removed."""
    bdir = backup_dir(project_root)
    if not bdir.exists():
        return 0

    cutoff = time.time() - (retention_days * 86400)
    removed = 0

    for f in bdir.glob("*-snapshot.jsonl*"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1

    if removed:
        log.info("Pruned %d old backups", removed)
    return removed
