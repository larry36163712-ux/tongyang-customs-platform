from __future__ import annotations

import json

from app.runtime import app_base_dir


def app_version(default: str = "") -> str:
    version_file = app_base_dir() / "config" / "version.json"
    if version_file.exists():
        try:
            data = json.loads(version_file.read_text(encoding="utf-8"))
            version = str(data.get("version", "")).strip()
            if version:
                return version
        except Exception:
            pass
    return default
