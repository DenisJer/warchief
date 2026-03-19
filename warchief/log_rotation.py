"""Log rotation — rotate warchief.log and event logs."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger("warchief.log_rotation")

DEFAULT_MAX_SIZE = 100 * 1024 * 1024  # 100 MB
DEFAULT_MAX_SEGMENTS = 10
DEFAULT_MAX_AGE_DAYS = 30


def rotate_log(
    log_path: Path,
    max_size: int = DEFAULT_MAX_SIZE,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> bool:
    """Rotate a log file if it exceeds max_size.

    Creates numbered backups: file.1, file.2, etc.
    Returns True if rotation occurred.
    """
    if not log_path.exists():
        return False

    if log_path.stat().st_size < max_size:
        return False

    # Shift existing segments
    for i in range(max_segments - 1, 0, -1):
        src = log_path.parent / f"{log_path.name}.{i}"
        dst = log_path.parent / f"{log_path.name}.{i + 1}"
        if src.exists():
            if i + 1 > max_segments:
                src.unlink()
            else:
                src.rename(dst)

    # Move current to .1
    backup = log_path.parent / f"{log_path.name}.1"
    log_path.rename(backup)

    # Touch new empty log
    log_path.touch()

    log.info("Rotated %s (was %d bytes)", log_path, backup.stat().st_size)
    return True


def prune_old_segments(
    log_path: Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> int:
    """Remove log segments older than max_age_days. Returns count removed."""
    parent = log_path.parent
    prefix = log_path.name
    removed = 0
    cutoff = time.time() - (max_age_days * 86400)

    for f in parent.iterdir():
        if f.name.startswith(prefix + ".") and f.is_file():
            try:
                seg_num = f.name.split(".")[-1]
                int(seg_num)  # Verify it's a numbered segment
            except ValueError:
                continue

            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
                log.info("Pruned old log segment: %s", f)

    return removed


def run_log_rotation(project_root: Path) -> dict:
    """Rotate all project logs. Returns summary."""
    wc_dir = project_root / ".warchief"
    results: dict[str, bool | int] = {}

    # Main log
    main_log = wc_dir / "warchief.log"
    results["main_rotated"] = rotate_log(main_log)
    results["main_pruned"] = prune_old_segments(main_log)

    return results
