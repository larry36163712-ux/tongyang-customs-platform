from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.runtime import app_base_dir


GITHUB_VERSION_URL = (
    "https://github.com/larry36163712-ux/tongyang-customs-platform/"
    "releases/latest/download/version.json"
)
GITHUB_DEV_VERSION_URL = (
    "https://raw.githubusercontent.com/larry36163712-ux/tongyang-customs-platform/"
    "main/config/dev_version.json"
)


@dataclass(frozen=True)
class UpdateResult:
    status: str
    message: str
    latest_version: str = ""


def check_for_updates(current_version: str, update_config: dict, apply_update: bool = False) -> UpdateResult:
    if not update_config.get("enabled", True):
        return UpdateResult("disabled", "更新檢查未啟用。")

    channel = str(update_config.get("channel", "stable")).lower()
    if channel == "dev":
        version_url = update_config.get("dev_version_url") or update_config.get("version_url") or GITHUB_DEV_VERSION_URL
    else:
        version_url = update_config.get("stable_version_url") or update_config.get("version_url") or GITHUB_VERSION_URL
    try:
        manifest = _load_manifest(version_url)
    except Exception:
        return UpdateResult("offline", "無法連線到 GitHub，已改為離線使用。")

    latest = str(manifest.get("version", "")).strip()
    if not latest:
        return UpdateResult("error", "GitHub version.json 缺少 version。")
    if _version_tuple(latest) <= _version_tuple(current_version):
        return UpdateResult("current", f"目前已是最新版 {current_version}。", latest)

    if not apply_update:
        return UpdateResult("available", f"發現新版 {latest}。", latest)

    download_url = str(manifest.get("download_url", "")).strip()
    if not download_url:
        return UpdateResult("error", "發現新版，但 version.json 缺少 download_url。", latest)

    try:
        downloaded = _download_update(download_url, manifest.get("sha256", ""))
        _schedule_replace(downloaded)
    except Exception as exc:
        return UpdateResult("error", f"更新失敗，保留目前版本：{exc}", latest)

    return UpdateResult("restarting", f"已下載新版 {latest}，即將重新啟動。", latest)


def _load_manifest(version_url: str) -> dict:
    if version_url.startswith(("http://", "https://")):
        with _open_url(version_url, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    path = Path(version_url)
    if not path.is_absolute():
        path = app_base_dir() / version_url
    if not path.exists():
        fallback = app_base_dir() / "config" / "version.json"
        path = fallback if fallback.exists() else path
    return json.loads(path.read_text(encoding="utf-8"))


def _download_update(download_url: str, expected_sha256: str = "") -> Path:
    target = Path(tempfile.gettempdir()) / "TongYangCustoms.update.exe"
    target.unlink(missing_ok=True)

    if download_url.startswith(("http://", "https://")):
        with _open_url(download_url, timeout=60) as response:
            target.write_bytes(response.read())
    else:
        source = Path(download_url)
        if not source.is_absolute():
            source = app_base_dir() / download_url
        shutil.copy2(source, target)

    if expected_sha256:
        digest = hashlib.sha256(target.read_bytes()).hexdigest().lower()
        if digest != expected_sha256.lower():
            target.unlink(missing_ok=True)
            raise RuntimeError("新版 EXE SHA256 驗證失敗")
    return target


def _open_url(url: str, timeout: int):
    request = urllib.request.Request(
        _quote_url(url),
        headers={
            "User-Agent": "TongYangCustomsPlatform/1.0",
            "Accept": "application/octet-stream, application/json;q=0.9, */*;q=0.8",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _quote_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parsed.path, safe="/%")
    query = urllib.parse.quote(parsed.query, safe="=&%")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, parsed.fragment))


def _schedule_replace(update_exe: Path) -> None:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("目前不是 EXE 執行狀態，略過自動覆蓋")

    current_exe = Path(sys.executable).resolve()
    backup_exe = current_exe.with_suffix(".old.exe")
    script_path = Path(tempfile.gettempdir()) / "TongYangCustoms_update.bat"
    script = f"""@echo off
setlocal
set CURRENT={current_exe}
set UPDATE={update_exe}
set BACKUP={backup_exe}
ping 127.0.0.1 -n 3 > nul
if exist "%BACKUP%" del /f /q "%BACKUP%"
copy /y "%CURRENT%" "%BACKUP%" > nul
copy /y "%UPDATE%" "%CURRENT%" > nul
if errorlevel 1 (
  copy /y "%BACKUP%" "%CURRENT%" > nul
  start "" "%CURRENT%"
  exit /b 1
)
del /f /q "%UPDATE%"
del /f /q "%BACKUP%"
start "" "%CURRENT%"
exit /b 0
"""
    script_path.write_text(script, encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script_path)], creationflags=subprocess.CREATE_NO_WINDOW)
    os._exit(0)


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for part in value.lstrip("vV").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)
