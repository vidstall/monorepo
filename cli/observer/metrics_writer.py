from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class MetricsFileRegistry:
    """One threading.Lock per metrics file, created lazily on first write.
    A sampler tick writes many independent per-entity files (unlike
    cli.scenario.system_log.SystemLog, which owns exactly one growing file
    and one lock) -- per-file locking avoids serializing unrelated writes
    while still guarding read-modify-write races on any single file across
    concurrent collector calls or overlapping ticks."""

    def __init__(self) -> None:
        self._locks: dict[Path, threading.Lock] = {}
        self._meta_lock = threading.Lock()

    def lock_for(self, path: Path) -> threading.Lock:
        with self._meta_lock:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            return lock


def write_metrics_entry(
    registry: MetricsFileRegistry,
    path: Path,
    identity: dict[str, Any],
    array_key: str,
    entry: dict[str, Any],
) -> None:
    """Append one time-series entry to `path`'s `array_key` array, creating
    the file with its `identity` block on first sight of this entity.
    Atomic per file (tmp-write then os.replace), same pattern as
    cli.scenario.system_log.SystemLog._flush() generalized from "one
    growing file" to "one file per entity, many files"."""
    lock = registry.lock_for(path)
    with lock:
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                doc = {"identity": identity, array_key: []}
        else:
            doc = {"identity": identity, array_key: []}

        doc.setdefault(array_key, []).append(entry)

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
        os.replace(tmp_path, path)
