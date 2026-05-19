from __future__ import annotations

import shutil
from pathlib import Path

from app.runtime import app_base_dir


def sync_local_rules(sync_config: dict) -> list[str]:
    if not sync_config.get("enabled", True):
        return []

    base_dir = app_base_dir()
    source_dir = Path(sync_config.get("source_dir", "sync_source"))
    if not source_dir.is_absolute():
        source_dir = base_dir / source_dir
    if not source_dir.exists():
        source_dir.mkdir(parents=True, exist_ok=True)
        return []

    changed: list[str] = []
    for target in sync_config.get("targets", ["templates"]):
        target_dir = Path(target)
        if not target_dir.is_absolute():
            target_dir = base_dir / target_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        changed.extend(_copy_newer_files(source_dir, target_dir))
    return changed


def _copy_newer_files(source_dir: Path, target_dir: Path) -> list[str]:
    changed: list[str] = []
    for source in source_dir.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_dir)
        target = target_dir / relative
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        changed.append(str(relative))
    return changed
