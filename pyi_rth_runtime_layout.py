from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


if getattr(sys, "frozen", False):
    base_dir = Path(sys.executable).resolve().parent
    bundled_dir = Path(getattr(sys, "_MEIPASS", base_dir))
    current_temp = bundled_dir.resolve()
    cutoff = datetime.now() - timedelta(hours=24)
    for name in ("uploads", "logs", "database", "config", "parser_cache", "templates"):
        (base_dir / name).mkdir(parents=True, exist_ok=True)

    for filename in ("settings.json", "version.json"):
        target = base_dir / "config" / filename
        source = bundled_dir / filename
        if source.exists() and not target.exists():
            shutil.copy2(source, target)

    settings_target = base_dir / "config" / "settings.json"
    if not settings_target.exists():
        settings_target.write_text(
            """{
  "app_name": "通洋報關平台",
  "version": "1.0.0",
  "release_methods": ["C1", "C2", "C3M", "C3X"],
  "uploads_dir": "uploads",
  "exports_dir": "exports",
  "logs_dir": "logs",
  "database_dir": "database",
  "parser_cache_dir": "parser_cache",
  "templates_dir": "templates",
  "retention_days": {"uploads": 30, "logs": 90, "parser_cache": 7},
  "update": {"enabled": true, "version_url": "https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json", "check_on_startup": true},
  "sync": {"enabled": true, "source_dir": "sync_source", "targets": ["templates", "app/parser/templates"]}
}
""",
            encoding="utf-8",
        )

    version_target = base_dir / "config" / "version.json"
    if not version_target.exists():
        version_target.write_text(
            """{
  "app_name": "通洋報關平台",
  "version": "1.0.0",
  "download_url": "https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/default.exe",
  "sha256": "",
  "notes": "GitHub Releases update manifest."
}
""",
            encoding="utf-8",
        )

    db_path = base_dir / "database" / "history.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                summary TEXT NOT NULL
            )
            """
        )

    for temp_dir in Path(tempfile.gettempdir()).glob("_MEI*"):
        try:
            if temp_dir.resolve() == current_temp or not temp_dir.is_dir():
                continue
            if datetime.fromtimestamp(temp_dir.stat().st_mtime) < cutoff:
                shutil.rmtree(temp_dir, ignore_errors=True)
        except OSError:
            pass
