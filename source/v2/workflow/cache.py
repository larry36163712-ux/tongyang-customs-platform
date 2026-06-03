from __future__ import annotations

import hashlib
import json
from pathlib import Path


class WorkflowCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def key_for_file(self, path: Path) -> str:
        stat = path.stat()
        raw = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8", errors="ignore")
        return hashlib.sha256(raw).hexdigest()

    def read_text(self, key: str) -> str | None:
        path = self.root / f"{key}.txt"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="ignore")

    def write_text(self, key: str, text: str) -> None:
        (self.root / f"{key}.txt").write_text(text, encoding="utf-8")

    def write_debug(self, key: str, data: dict[str, object]) -> None:
        (self.root / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
