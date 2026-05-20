from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from v2.core.settings import UpdateSettings, local_manifest_path, logs_dir, resolve_local_version, settings_path

ProgressCallback = Callable[[str, int, str], None]


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    download_url: str
    sha256: str
    channel: str
    notes: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "app_name": "通洋報關平台",
            "version": self.version,
            "download_url": self.download_url,
            "sha256": self.sha256,
            "channel": self.channel,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    message: str
    manifest: UpdateManifest | None = None
    compare_result: int = 0
    should_show_popup: bool = False


class V2Updater:
    def __init__(self, current_version: str, settings: UpdateSettings) -> None:
        self.settings = settings
        self.local_version_path = local_manifest_path()
        self.current_version = resolve_local_version(current_version)
        self.log_path = logs_dir() / "update-debug.log"

    def check(self) -> UpdateCheck:
        self.current_version = resolve_local_version()
        if self.settings.channel == "dev":
            self._log(
                f"dev channel current local_version_path={self.local_version_path} "
                f"local_version={self.current_version} should_show_popup=False"
            )
            return UpdateCheck("current", f"DEV {self.current_version}，開發環境不檢查 stable 更新。", None, 0, False)

        if not self.settings.enabled:
            self._log(
                f"update disabled local_version_path={self.local_version_path} "
                f"local_version={self.current_version} channel={self.settings.channel} should_show_popup=False"
            )
            return UpdateCheck("disabled", "自動更新未啟用。")

        try:
            manifest = self._load_manifest()
        except Exception as exc:
            self._log(f"manifest load failed: {exc}")
            return UpdateCheck("error", f"更新檢查失敗：{exc}")

        self._log(
            "check result "
            f"local_version_path={self.local_version_path} "
            f"local_version={self.current_version} remote_version={manifest.version} "
            f"channel={self.settings.channel} remote_channel={manifest.channel}"
        )

        compare = _compare_versions(self.current_version, manifest.version)
        should_show_popup = compare < 0
        self._log(f"compare result={compare} should_show_popup={should_show_popup}")
        if compare >= 0:
            self._log("update result=current should_show_popup=False")
            return UpdateCheck("current", f"目前已是最新版 {self.current_version}。", manifest, compare, False)

        self._log("update result=available should_show_popup=True")
        return UpdateCheck("available", f"發現新版 {manifest.version}。", manifest, compare, True)

    def apply(self, manifest: UpdateManifest, progress: ProgressCallback | None = None) -> UpdateCheck:
        try:
            self._emit_progress(progress, "downloading", 0, "開始下載新版 EXE")
            self._log(f"progress download start version={manifest.version} url={manifest.download_url}")
            downloaded = self._download(manifest, progress=progress)
            self._log(f"progress download completed path={downloaded}")
            self._emit_progress(progress, "verifying", 90, "正在驗證 SHA256")
            self._log(f"progress verify completed sha256={manifest.sha256}")
            staged_manifest = self._stage_manifest(manifest)
            self._emit_progress(progress, "replacing", 96, "準備覆蓋主程式")
            self._log("progress replace scheduled")
            self._emit_progress(progress, "restarting", 100, "即將重新啟動")
            self._schedule_replace(downloaded, staged_manifest)
        except Exception as exc:
            self._log(f"apply failed: {exc}")
            return UpdateCheck("error", f"更新失敗，已保留目前版本：{exc}", manifest)
        return UpdateCheck("restarting", f"已下載新版 {manifest.version}，即將重新啟動。", manifest)

    def _stage_manifest(self, manifest: UpdateManifest) -> Path:
        target = Path(tempfile.gettempdir()) / "AI_Customs_ERP_V2.version.json"
        target.write_text(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._log(f"staged manifest={target} version={manifest.version} channel={manifest.channel}")
        return target

    def _load_manifest(self) -> UpdateManifest:
        manifest = _read_json_url(self.settings.stable_manifest_url)

        return UpdateManifest(
            version=str(manifest.get("version", "")).strip(),
            download_url=str(manifest.get("download_url", "")).strip(),
            sha256=str(manifest.get("sha256", "")).strip().lower(),
            channel=str(manifest.get("channel", self.settings.channel)).strip() or self.settings.channel,
            notes=str(manifest.get("notes", "")),
        )

    def _download(self, manifest: UpdateManifest, progress: ProgressCallback | None = None) -> Path:
        if not manifest.download_url:
            raise RuntimeError("version.json 缺少 download_url")
        if not manifest.sha256:
            raise RuntimeError("version.json 缺少 sha256")

        target = Path(tempfile.gettempdir()) / "AI_Customs_ERP_V2.update.exe"
        target.unlink(missing_ok=True)
        self._log(f"download start {manifest.download_url} -> {target}")

        started = time.monotonic()
        with requests.get(manifest.download_url, stream=True, timeout=(10, 180)) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    percent = 0
                    if total > 0:
                        percent = min(89, max(1, int(downloaded * 89 / total)))
                    elapsed = max(0.001, time.monotonic() - started)
                    mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024) if total else 0
                    speed = mb / elapsed
                    if total_mb:
                        message = f"下載中 {mb:.1f}/{total_mb:.1f} MB ({percent}%) - {speed:.1f} MB/s"
                    else:
                        message = f"下載中 {mb:.1f} MB - {speed:.1f} MB/s"
                    self._emit_progress(progress, "downloading", percent, message)

        digest = hashlib.sha256(target.read_bytes()).hexdigest().lower()
        self._log(f"verify sha256 actual={digest} expected={manifest.sha256}")
        if digest != manifest.sha256:
            target.unlink(missing_ok=True)
            raise RuntimeError("新版 EXE SHA256 驗證失敗")
        self._log("verify ok")
        return target

    def _schedule_replace(self, update_exe: Path, staged_manifest: Path) -> None:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("目前不是 EXE 執行狀態，略過自動覆蓋")

        current_exe = Path(sys.executable).resolve()
        backup_exe = current_exe.with_suffix(".rollback.exe")
        script_path = Path(tempfile.gettempdir()) / "AI_Customs_ERP_V2_update.bat"
        script = build_replace_script(
            current_exe=current_exe,
            update_exe=update_exe,
            backup_exe=backup_exe,
            log_path=self.log_path,
            expected_sha256=hashlib.sha256(update_exe.read_bytes()).hexdigest().lower(),
            old_pid=os.getpid(),
            staged_manifest=staged_manifest,
            local_manifest=local_manifest_path(),
            settings_file=settings_path(),
            restart=True,
            cleanup=True,
        )
        script_path.write_text(script, encoding="utf-8")
        self._log(f"replace script scheduled={script_path}")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["cmd", "/c", str(script_path)], creationflags=creationflags, close_fds=True)
        os._exit(0)

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")

    def _emit_progress(self, progress: ProgressCallback | None, stage: str, percent: int, message: str) -> None:
        self._log(f"progress {stage} percent={percent} message={message}")
        if progress:
            progress(stage, percent, message)


def _read_json_url(url: str) -> dict | list:
    response = requests.get(
        url,
        timeout=(10, 30),
        headers={
            "User-Agent": "AI-Customs-ERP-V2/1.0",
            "Accept": "application/json",
        },
    )
    response.raise_for_status()
    return response.json()


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


def _compare_versions(local: str, remote: str) -> int:
    local_key = _version_key(local)
    remote_key = _version_key(remote)
    if local_key == remote_key:
        return 0
    return 1 if local_key > remote_key else -1


def build_replace_script(
    current_exe: Path,
    update_exe: Path,
    backup_exe: Path,
    log_path: Path,
    expected_sha256: str,
    old_pid: int,
    staged_manifest: Path | None = None,
    local_manifest: Path | None = None,
    settings_file: Path | None = None,
    restart: bool = True,
    cleanup: bool = True,
) -> str:
    restart_line = (
        'echo [%date% %time%] progress restart start >> "%LOG%"\nfor /f "usebackq delims=" %%p in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath $env:CURRENT -PassThru; $p.Id"`) do echo [%date% %time%] restart pid=%%p >> "%LOG%"\nif errorlevel 1 (echo [%date% %time%] restart failed >> "%LOG%") else (echo [%date% %time%] restart success >> "%LOG%")'
        if restart
        else 'echo [%date% %time%] restart skipped >> "%LOG%"'
    )
    cleanup_lines = (
        'del /f /q "%UPDATE%" >> "%LOG%" 2>&1\n'
        'if defined STAGED_MANIFEST del /f /q "%STAGED_MANIFEST%" >> "%LOG%" 2>&1\n'
        'del /f /q "%BACKUP%" >> "%LOG%" 2>&1'
        if cleanup
        else 'echo [%date% %time%] cleanup skipped >> "%LOG%"'
    )
    manifest_env = ""
    manifest_sync = 'echo [%date% %time%] manifest sync skipped >> "%LOG%"'
    if staged_manifest and local_manifest and settings_file:
        manifest_env = f"""set "STAGED_MANIFEST={staged_manifest}"
set "LOCAL_MANIFEST={local_manifest}"
set "SETTINGS_FILE={settings_file}"
"""
        manifest_sync = r"""if exist "%STAGED_MANIFEST%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "New-Item -ItemType Directory -Force -Path (Split-Path -Parent $env:LOCAL_MANIFEST) | Out-Null; New-Item -ItemType Directory -Force -Path (Split-Path -Parent $env:SETTINGS_FILE) | Out-Null" >> "%LOG%" 2>&1
  copy /y "%STAGED_MANIFEST%" "%LOCAL_MANIFEST%" >> "%LOG%" 2>&1
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$manifest = Get-Content -LiteralPath $env:LOCAL_MANIFEST -Raw | ConvertFrom-Json; $settingsPath = $env:SETTINGS_FILE; if (Test-Path -LiteralPath $settingsPath) { $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json } else { $settings = [pscustomobject]@{} }; $settings | Add-Member -Force -NotePropertyName version -NotePropertyValue ([string]$manifest.version); if (-not $settings.PSObject.Properties['update']) { $settings | Add-Member -NotePropertyName update -NotePropertyValue ([pscustomobject]@{}) }; $settings.update | Add-Member -Force -NotePropertyName channel -NotePropertyValue ([string]$manifest.channel); $settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $settingsPath -Encoding UTF8" >> "%LOG%" 2>&1
  echo [%date% %time%] manifest synced >> "%LOG%"
) else (
  echo [%date% %time%] staged manifest missing >> "%LOG%"
)"""
    return f"""@echo off
setlocal EnableExtensions
set "CURRENT={current_exe}"
set "UPDATE={update_exe}"
set "BACKUP={backup_exe}"
set "LOG={log_path}"
set "EXPECTED_SHA={expected_sha256.lower()}"
set "OLD_PID={old_pid}"
{manifest_env}

if not exist "%~dp0" mkdir "%~dp0" > nul 2>&1
if not exist "%LOG%" type nul > "%LOG%"
echo [%date% %time%] update replace started >> "%LOG%"
echo [%date% %time%] old exe path=%CURRENT% >> "%LOG%"
echo [%date% %time%] new exe path=%UPDATE% >> "%LOG%"
echo [%date% %time%] progress replace start >> "%LOG%"

if not "%OLD_PID%"=="0" (
  echo [%date% %time%] waiting for old pid=%OLD_PID% >> "%LOG%"
  for /l %%i in (1,1,60) do (
    tasklist /FI "PID eq %OLD_PID%" | findstr /R /C:" %OLD_PID% " > nul
    if errorlevel 1 goto old_process_exited
    ping 127.0.0.1 -n 2 > nul
  )
  echo [%date% %time%] old process still running, terminating pid=%OLD_PID% >> "%LOG%"
  taskkill /PID %OLD_PID% /F >> "%LOG%" 2>&1
  ping 127.0.0.1 -n 3 > nul
)
:old_process_exited
echo [%date% %time%] old process exited >> "%LOG%"

for /l %%i in (1,1,30) do (
  copy /y "%CURRENT%" "%BACKUP%" >> "%LOG%" 2>&1
  if not errorlevel 1 goto backup_done
  ping 127.0.0.1 -n 2 > nul
)
echo [%date% %time%] backup failed >> "%LOG%"
goto rollback

:backup_done
echo [%date% %time%] backup success path=%BACKUP% >> "%LOG%"
copy /y "%UPDATE%" "%CURRENT%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] replace copy failed >> "%LOG%"
  goto rollback
)
if not exist "%CURRENT%" (
  echo [%date% %time%] current exe missing after replace >> "%LOG%"
  goto rollback
)

for /f "usebackq delims=" %%h in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath $env:CURRENT).Hash.ToLower()"`) do set "ACTUAL_SHA=%%h"
echo [%date% %time%] replaced sha256=%ACTUAL_SHA% >> "%LOG%"
if /i not "%ACTUAL_SHA%"=="%EXPECTED_SHA%" (
  echo [%date% %time%] sha256 mismatch, rollback >> "%LOG%"
  goto rollback
)

echo [%date% %time%] replace verified >> "%LOG%"
echo [%date% %time%] replace success current=%CURRENT% >> "%LOG%"
echo [%date% %time%] progress replace completed >> "%LOG%"
{manifest_sync}
{restart_line}
{cleanup_lines}
echo [%date% %time%] update replace completed >> "%LOG%"
exit /b 0

:rollback
if exist "%BACKUP%" (
  copy /y "%BACKUP%" "%CURRENT%" >> "%LOG%" 2>&1
)
if exist "%CURRENT%" (
  {restart_line}
)
echo [%date% %time%] replace fail rollback current=%CURRENT% >> "%LOG%"
echo [%date% %time%] update rollback completed >> "%LOG%"
exit /b 1
"""
