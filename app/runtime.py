from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path


REQUIRED_DIRS = ("uploads", "logs", "database", "config", "parser_cache", "templates", "exports")
DEFAULT_SETTINGS = """{
  "app_name": "通洋報關平台",
  "release_methods": ["C1", "C2", "C3M", "C3X"],
  "uploads_dir": "uploads",
  "exports_dir": "exports",
  "logs_dir": "logs",
  "database_dir": "database",
  "parser_cache_dir": "parser_cache",
  "templates_dir": "templates",
  "retention_days": {
    "uploads": 30,
    "logs": 90,
    "parser_cache": 7
  },
  "update": {
    "enabled": true,
    "channel": "dev",
    "version_url": "https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json",
    "stable_version_url": "https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json",
    "check_on_startup": true
  },
  "sync": {
    "enabled": true,
    "source_dir": "sync_source",
    "targets": ["templates", "app/parser/templates"]
  }
}
"""
def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def bundled_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def ensure_runtime_layout() -> Path:
    base_dir = app_base_dir()
    for dirname in REQUIRED_DIRS:
        (base_dir / dirname).mkdir(parents=True, exist_ok=True)

    external_settings = base_dir / "config" / "settings.json"
    if not external_settings.exists():
        external_settings.write_text(DEFAULT_SETTINGS, encoding="utf-8")

    return base_dir


def settings_path() -> Path:
    base_dir = ensure_runtime_layout()
    external_settings = base_dir / "config" / "settings.json"
    if external_settings.exists():
        return external_settings
    external_settings.write_text(DEFAULT_SETTINGS, encoding="utf-8")
    return external_settings


def cleanup_pyinstaller_temp(max_age_hours: int = 24) -> None:
    if not getattr(sys, "frozen", False):
        return
    current_temp = Path(getattr(sys, "_MEIPASS", "")).resolve() if hasattr(sys, "_MEIPASS") else None
    temp_root = Path.cwd()
    try:
        import tempfile

        temp_root = Path(tempfile.gettempdir())
    except Exception:
        pass

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    for path in temp_root.glob("_MEI*"):
        if not path.is_dir():
            continue
        try:
            if current_temp and path.resolve() == current_temp:
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            if modified >= cutoff:
                continue
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def cleanup_expired_files(retention_days: dict[str, int]) -> None:
    base_dir = ensure_runtime_layout()
    now = datetime.now()
    for dirname, days in retention_days.items():
        target_dir = base_dir / dirname
        if not target_dir.exists() or days < 0:
            continue
        cutoff = now - timedelta(days=days)
        for path in target_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if modified < cutoff:
                try:
                    path.unlink()
                except OSError:
                    pass
        _remove_empty_dirs(target_dir)


def _remove_empty_dirs(root: Path) -> None:
    for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass
