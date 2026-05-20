from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
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
    version: str = "1.0.0"
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


def load_settings() -> V2Settings:
    path = settings_path()
    if not path.exists():
        settings = V2Settings(version=resolve_local_version())
        if not getattr(sys, "frozen", False):
            settings.update.channel = "dev"
        save_settings(settings)
        return settings

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    update_data = data.get("update", {})
    channel = str(update_data.get("channel", "stable")).lower()
    if channel not in {"dev", "stable"}:
        channel = "stable"
    if not getattr(sys, "frozen", False):
        channel = "dev"

    return V2Settings(
        version=resolve_local_version(),
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
    settings.version = resolve_local_version(settings.version)
    if settings.update.channel not in {"dev", "stable"}:
        settings.update.channel = "stable"
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_local_version(default: str = "1.0.0") -> str:
    path = local_manifest_path()
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default
    version = str(data.get("version", "")).strip()
    if version:
        return version
    return default
