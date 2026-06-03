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
    dev_manifest_url: str = (
        "https://raw.githubusercontent.com/larry36163712-ux/tongyang-customs-platform/main/source/config/dev_version.json"
    )


@dataclass
class V2Settings:
    version: str = ""
    update: UpdateSettings = field(default_factory=UpdateSettings)
    developer_mode: bool = False


@dataclass(frozen=True)
class BuildInfo:
    version: str = ""
    channel: str = ""
    build_id: str = ""
    build_time: str = ""
    release_id: str = ""
    sha256: str = ""


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    cwd = Path.cwd()
    source_dir = cwd / "source"
    if (source_dir / "v2").exists() and (source_dir / "config").exists():
        return source_dir
    return cwd


def bundled_base_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(meipass)
    return app_base_dir()


def resource_path(*parts: str) -> Path:
    external = app_base_dir().joinpath(*parts)
    if external.exists():
        return external
    return bundled_base_dir().joinpath(*parts)


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


def read_build_info() -> BuildInfo:
    data = read_local_manifest()
    return BuildInfo(
        version=str(data.get("version", "")).strip(),
        channel=str(data.get("channel", "")).strip(),
        build_id=str(data.get("build_id", "")).strip(),
        build_time=str(data.get("build_time", "")).strip(),
        release_id=str(data.get("release_id") or data.get("build_id", "")).strip(),
        sha256=str(data.get("sha256", "")).strip().lower(),
    )


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

    local_manifest = read_local_manifest()
    local_version = str(local_manifest.get("version", "")).strip() or resolve_local_version()
    manifest_channel = str(local_manifest.get("channel", "")).strip().lower()
    channel, reconciled_reason = reconcile_update_channel(local_version, manifest_channel, channel)
    if not getattr(sys, "frozen", False) and channel != "dev":
        channel = "dev"
        reconciled_reason = reconciled_reason or "source_dev_default"

    settings = V2Settings(
        version=local_version,
        developer_mode=bool(data.get("developer_mode", False)),
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
            dev_manifest_url=str(
                update_data.get(
                    "dev_manifest_url",
                    UpdateSettings.dev_manifest_url,
                )
            ),
        ),
    )
    version_debug_log(
        f"load_settings local_version={local_version} manifest_channel={manifest_channel or '-'} "
        f"channel={channel} reconciled={bool(reconciled_reason)} reason={reconciled_reason or '-'}"
    )
    if reconciled_reason:
        save_settings(settings)
        version_debug_log(f"settings channel reconciled and saved channel={settings.update.channel} reason={reconciled_reason}")
    return settings


def save_settings(settings: V2Settings) -> None:
    path = settings_path()
    settings.version = resolve_local_version()
    if settings.update.channel not in {"dev", "stable"}:
        settings.update.channel = "stable"
    data = {"update": asdict(settings.update), "developer_mode": bool(settings.developer_mode)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_local_version(default: str = "") -> str:
    data = read_local_manifest()
    version = str(data.get("version", "")).strip()
    if version:
        return version
    return default


def reconcile_update_channel(version: str, manifest_channel: str, settings_channel: str) -> tuple[str, str]:
    configured = settings_channel if settings_channel in {"dev", "stable"} else "stable"
    manifest = manifest_channel if manifest_channel in {"dev", "stable"} else ""
    normalized_version = str(version or "").strip().lower()
    if "-rc." in normalized_version and configured != "dev":
        return "dev", "rc_version_forces_dev"
    if "-rc." in normalized_version:
        return "dev", "" if configured == "dev" else "rc_version_forces_dev"
    if manifest and manifest != configured:
        return manifest, "manifest_channel_mismatch"
    return configured, ""
