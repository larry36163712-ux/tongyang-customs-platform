from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from engine.intake.folder_scanner import FolderScanner


@dataclass(frozen=True)
class FolderChange:
    added: list[Path]
    changed: list[Path]
    removed: list[Path]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed)


class FolderWatcher:
    """Production polling watcher for intake folders.

    A polling watcher keeps the packaged desktop app independent from platform
    specific filesystem services while still detecting real files as users drop
    them into a shared customs intake folder.
    """

    def __init__(self, folder: str | Path, scanner: FolderScanner | None = None, interval_seconds: float = 2.0) -> None:
        self.folder = Path(folder)
        self.scanner = scanner or FolderScanner()
        self.interval_seconds = max(0.5, interval_seconds)
        self._snapshot = self._scan_snapshot()

    def poll(self) -> FolderChange:
        before = self._snapshot
        after = self._scan_snapshot()
        self._snapshot = after
        before_paths = set(before)
        after_paths = set(after)
        added = sorted(after_paths - before_paths, key=lambda path: str(path).casefold())
        removed = sorted(before_paths - after_paths, key=lambda path: str(path).casefold())
        changed = sorted(
            path
            for path in before_paths & after_paths
            if before[path] != after[path]
        )
        return FolderChange(added=added, changed=changed, removed=removed)

    def watch(self, callback: Callable[[FolderChange], None], stop: Callable[[], bool] | None = None) -> None:
        while not (stop and stop()):
            change = self.poll()
            if change.has_changes:
                callback(change)
            time.sleep(self.interval_seconds)

    def _scan_snapshot(self) -> dict[Path, tuple[int, int]]:
        return {
            path: (path.stat().st_mtime_ns, path.stat().st_size)
            for path in self.scanner.scan(self.folder)
        }
