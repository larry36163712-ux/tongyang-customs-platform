from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.runtime import settings_path


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    release_methods: list[str]
    uploads_dir: str
    exports_dir: str
    logs_dir: str
    database_dir: str
    parser_cache_dir: str
    templates_dir: str
    retention_days: dict[str, int]
    update: dict
    sync: dict


def load_settings(path: str | Path | None = None) -> Settings:
    resolved_path = Path(path) if path is not None else settings_path()
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    return Settings(
        app_name=data.get("app_name", "通洋報關平台"),
        version=data.get("version", ""),
        release_methods=data.get("release_methods", ["C1", "C2", "C3M", "C3X"]),
        uploads_dir=data.get("uploads_dir", "uploads"),
        exports_dir=data.get("exports_dir", "exports"),
        logs_dir=data.get("logs_dir", "logs"),
        database_dir=data.get("database_dir", "database"),
        parser_cache_dir=data.get("parser_cache_dir", "parser_cache"),
        templates_dir=data.get("templates_dir", "templates"),
        retention_days=data.get("retention_days", {"uploads": 30, "logs": 90, "parser_cache": 7}),
        update=data.get("update", {}),
        sync=data.get("sync", {}),
    )
