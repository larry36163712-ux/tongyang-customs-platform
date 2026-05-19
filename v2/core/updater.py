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
from datetime import datetime
from pathlib import Path

from v2.core.settings import UpdateSettings, app_base_dir, logs_dir


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    download_url: str
    sha256: str
    channel: str
    notes: str = ""


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    message: str
    manifest: UpdateManifest | None = None


class V2Updater:
    def __init__(self, current_version: str, settings: UpdateSettings) -> None:
        self.current_version = current_version
        self.settings = settings
        self.log_path = logs_dir() / "update-debug.log"

    def check(self) -> UpdateCheck:
        if not self.settings.enabled:
            self._log("update disabled")
            return UpdateCheck("disabled", "自動更新未啟用。")

        try:
            manifest = self._load_manifest()
        except Exception as exc:
            self._log(f"manifest load failed: {exc}")
            return UpdateCheck("error", f"更新檢查失敗：{exc}")

        if _version_key(manifest.version) <= _version_key(self.current_version):
            self._log(f"current version ok: current={self.current_version} latest={manifest.version}")
            return UpdateCheck("current", f"目前已是最新版 {self.current_version}。", manifest)

        self._log(f"update available: current={self.current_version} latest={manifest.version}")
        return UpdateCheck("available", f"發現新版 {manifest.version}。", manifest)

    def apply(self, manifest: UpdateManifest) -> UpdateCheck:
        try:
            downloaded = self._download(manifest)
            self._schedule_replace(downloaded)
        except Exception as exc:
            self._log(f"apply failed: {exc}")
            return UpdateCheck("error", f"更新失敗，已保留目前版本：{exc}", manifest)
        return UpdateCheck("restarting", f"已下載新版 {manifest.version}，即將重新啟動。", manifest)

    def _load_manifest(self) -> UpdateManifest:
        if self.settings.channel == "beta":
            manifest = self._load_beta_manifest()
        else:
            manifest = _read_json_url(self.settings.stable_manifest_url)

        return UpdateManifest(
            version=str(manifest.get("version", "")).strip(),
            download_url=str(manifest.get("download_url", "")).strip(),
            sha256=str(manifest.get("sha256", "")).strip().lower(),
            channel=str(manifest.get("channel", self.settings.channel)).strip() or self.settings.channel,
            notes=str(manifest.get("notes", "")),
        )

    def _load_beta_manifest(self) -> dict:
        releases = _read_json_url(self.settings.beta_repo_api_url)
        if not isinstance(releases, list):
            raise RuntimeError("GitHub beta release API 回傳格式不正確")

        for release in releases:
            if not release.get("prerelease"):
                continue
            assets = release.get("assets", [])
            manifest_asset = next((asset for asset in assets if asset.get("name") == "version.json"), None)
            if manifest_asset:
                return _read_json_url(manifest_asset["browser_download_url"])
        raise RuntimeError("找不到 beta release version.json")

    def _download(self, manifest: UpdateManifest) -> Path:
        if not manifest.download_url:
            raise RuntimeError("version.json 缺少 download_url")
        if not manifest.sha256:
            raise RuntimeError("version.json 缺少 sha256")

        target = Path(tempfile.gettempdir()) / "AI_Customs_ERP_V2.update.exe"
        target.unlink(missing_ok=True)
        self._log(f"downloading {manifest.download_url} -> {target}")

        with _open_url(manifest.download_url, timeout=120) as response:
            target.write_bytes(response.read())

        digest = hashlib.sha256(target.read_bytes()).hexdigest().lower()
        self._log(f"download sha256={digest}")
        if digest != manifest.sha256:
            target.unlink(missing_ok=True)
            raise RuntimeError("新版 EXE SHA256 驗證失敗")
        return target

    def _schedule_replace(self, update_exe: Path) -> None:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("目前不是 EXE 執行狀態，略過自動覆蓋")

        current_exe = Path(sys.executable).resolve()
        backup_exe = current_exe.with_suffix(".rollback.exe")
        script_path = Path(tempfile.gettempdir()) / "AI_Customs_ERP_V2_update.bat"
        log_path = self.log_path

        script = f"""@echo off
setlocal
set CURRENT={current_exe}
set UPDATE={update_exe}
set BACKUP={backup_exe}
set LOG={log_path}
echo [%date% %time%] update replace started >> "%LOG%"
ping 127.0.0.1 -n 3 > nul
if exist "%BACKUP%" del /f /q "%BACKUP%"
copy /y "%CURRENT%" "%BACKUP%" >> "%LOG%" 2>&1
copy /y "%UPDATE%" "%CURRENT%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] replace failed, rollback >> "%LOG%"
  copy /y "%BACKUP%" "%CURRENT%" >> "%LOG%" 2>&1
  start "" "%CURRENT%"
  exit /b 1
)
start "" "%CURRENT%"
ping 127.0.0.1 -n 4 > nul
del /f /q "%UPDATE%" >> "%LOG%" 2>&1
del /f /q "%BACKUP%" >> "%LOG%" 2>&1
echo [%date% %time%] update replace completed >> "%LOG%"
exit /b 0
"""
        script_path.write_text(script, encoding="utf-8")
        self._log(f"scheduled replace script={script_path}")
        subprocess.Popen(["cmd", "/c", str(script_path)], creationflags=subprocess.CREATE_NO_WINDOW)
        os._exit(0)

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")


def _read_json_url(url: str) -> dict | list:
    with _open_url(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _open_url(url: str, timeout: int):
    request = urllib.request.Request(
        _quote_url(url),
        headers={
            "User-Agent": "AI-Customs-ERP-V2/1.0",
            "Accept": "application/json, application/octet-stream;q=0.9, */*;q=0.8",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _quote_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parsed.path, safe="/%")
    query = urllib.parse.quote(parsed.query, safe="=&%")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, parsed.fragment))


def _version_key(value: str) -> tuple[int, ...]:
    clean = value.lower().lstrip("v").replace("-beta", ".-1.")
    parts: list[int] = []
    for chunk in clean.replace("-", ".").split("."):
        if not chunk:
            continue
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)
