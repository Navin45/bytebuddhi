"""Bounded log rotation with size, file count, and age limits.

Avoids unbounded log growth while never deleting or moving log files while
a process is actively writing to them.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_MAX_FILES = 5
DEFAULT_MAX_AGE_DAYS = 14


def rotate_log_file(
    target: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> None:
    """Rotate log file if size exceeds max_bytes and purge expired backups."""
    if not target.is_file():
        return

    # Clean up backups exceeding age limit
    now = time.time()
    max_age_seconds = max_age_days * 86400

    parent = target.parent
    if parent.is_dir():
        for candidate in parent.glob(f"{target.name}.*"):
            with contextlib.suppress(OSError):
                if now - candidate.stat().st_mtime > max_age_seconds:
                    candidate.unlink(missing_ok=True)

    try:
        size = target.stat().st_size
    except OSError:
        return

    if size < max_bytes:
        return

    # Rotate existing files: e.g. .4 -> .5 (or delete if >= max_files), .3 -> .4, etc.
    for i in range(max_files - 1, 0, -1):
        src = target.with_name(f"{target.name}.{i}")
        if not src.exists():
            continue
        if i + 1 >= max_files:
            src.unlink(missing_ok=True)
        else:
            dst = target.with_name(f"{target.name}.{i + 1}")
            with contextlib.suppress(OSError):
                src.replace(dst)

    # Move current log to .1
    dst1 = target.with_name(f"{target.name}.1")
    with contextlib.suppress(OSError):
        target.replace(dst1)
