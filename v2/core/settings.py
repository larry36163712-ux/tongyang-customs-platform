from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class UpdateSettings:
    enabled: bool = True
    check_on_startup: bool = True
    channel: str = "stable"
    stable_manifest_url: str = (
        "https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json"
    )
    beta_repo_api_url: str = "https://api.github.com/repos/larry36163712-ux/tongyang-customs-platform/releases"


@dataclass
class V2Settings:
    version: str = ""
    update: UpdateSettings = field(default_factory=UpdateSettings)


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def settings_path() -> Path:
    config_dir = app_base_dir() / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "v2_settings.json"


def local_manifest_path() -> Path:
    config_dir = app_base_dir() / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "version.json"


def logs_dir() -> Path:
    path = app_base_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def version_debug_log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = logs_dir() / "version_debug.log"
    exe_path = Path(sys.executable).resolve()
    manifest_path = local_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] exe_path={exe_path} version_json_path={manifest_path} {message}\n")


def read_local_manifest() -> dict:
    path = local_manifest_path()
    if not path.exists():
        version_debug_log("local manifest missing")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        version_debug_log(f"local manifest read failed error={exc}")
        return {}
    if not isinstance(data, dict):
        version_debug_log("local manifest invalid type")
        return {}
    return data


def load_settings() -> V2Settings:
    path = settings_path()
    if not path.exists():
        settings = V2Settings(version=resolve_local_version())
        if not getattr(sys, "frozen", False):
            settings.update.channel = "dev"
        save_settings(settings)
        version_debug_log(f"load_settings created settings local_version={settings.version} channel={settings.update.channel}")
        return settings

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    update_data = data.get("update", {})
    channel = str(update_data.get("channel", "stable")).lower()
    if channel not in {"dev", "stable"}:
        channel = "stable"
    if not getattr(sys, "frozen", False):
        channel = "dev"

    local_version = resolve_local_version()
    version_debug_log(f"load_settings local_version={local_version} channel={channel}")
    return V2Settings(
        version=local_version,
        update=UpdateSettings(
            enabled=bool(update_data.get("enabled", True)),
            check_on_startup=bool(update_data.get("check_on_startup", True)),
            channel=channel,
            stable_manifest_url=str(
                update_data.get(
                    "stable_manifest_url",
                    UpdateSettings.stable_manifest_url,
                )
            ),
            beta_repo_api_url=str(update_data.get("beta_repo_api_url", UpdateSettings.beta_repo_api_url)),
        ),
    )


def save_settings(settings: V2Settings) -> None:
    path = settings_path()
    settings.version = resolve_local_version()
    if settings.update.channel not in {"dev", "stable"}:
        settings.update.channel = "stable"
    data = {"update": asdict(settings.update)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_local_version(default: str = "") -> str:
    data = read_local_manifest()
    version = str(data.get("version", "")).strip()
    if version:
        return version
    return default
