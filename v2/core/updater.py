from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from v2.core.settings import (
    UpdateSettings,
    local_manifest_path,
    logs_dir,
    read_local_manifest,
    resolve_local_version,
    settings_path,
    version_debug_log,
)

ProgressCallback = Callable[[str, int, str], None]


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    download_url: str
    sha256: str
    channel: str
    notes: str = ""
    build_id: str = ""
    build_time: str = ""
    exe_url: str = ""
    release_notes: str = ""
    minimum_supported_version: str = ""
    release_id: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "app_name": "通洋報關平台",
            "version": self.version,
            "exe_url": self.exe_url or self.download_url,
            "download_url": self.download_url,
            "sha256": self.sha256,
            "build_id": self.build_id,
            "channel": self.channel,
            "release_notes": self.release_notes or self.notes,
            "notes": self.notes or self.release_notes,
            "build_time": self.build_time,
            "minimum_supported_version": self.minimum_supported_version,
            "release_id": self.release_id or self.build_id,
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
        self.current_version = resolve_local_version()
        self.log_path = logs_dir() / "updater.log"
        self.compat_log_path = logs_dir() / "update-debug.log"
        self.pending_manifest_path = self.local_version_path.with_name("version.pending.json")

    def check(self) -> UpdateCheck:
        self.current_version = resolve_local_version()
        if self.settings.channel == "dev" and not getattr(sys, "frozen", False):
            self._log(
                f"dev channel current local_version_path={self.local_version_path} "
                f"local_version={self.current_version} should_show_popup=False"
            )
            version_debug_log(
                f"local_version={self.current_version} remote_version=DEV_SKIPPED "
                f"channel={self.settings.channel} remote_channel=DEV_SKIPPED "
                "compare_result=0 should_show_popup=False"
            )
            return UpdateCheck("current", f"DEV {self.current_version}，開發環境不檢查 stable 更新。", None, 0, False)

        if not self.settings.enabled:
            self._log(
                f"update disabled local_version_path={self.local_version_path} "
                f"local_version={self.current_version} channel={self.settings.channel} should_show_popup=False"
            )
            return UpdateCheck("disabled", "自動更新未啟用。")

        self._repair_desktop_shortcuts()

        try:
            manifest = self._load_manifest()
        except Exception as exc:
            self._log(f"manifest load failed: {exc}")
            return UpdateCheck("error", f"更新檢查失敗：{exc}")

        if manifest.channel != self.settings.channel:
            message = f"manifest channel mismatch: local={self.settings.channel} remote={manifest.channel}"
            self._log(message)
            return UpdateCheck("error", message, manifest)

        local_manifest = read_local_manifest()
        local_sha256 = self._current_exe_sha256(local_manifest)
        self._repair_or_cleanup_pending_manifest(manifest, local_sha256)
        local_manifest = read_local_manifest()
        self.current_version = resolve_local_version()
        local_sha256 = self._current_exe_sha256(local_manifest)
        sha_changed = bool(manifest.sha256 and local_sha256 and manifest.sha256 != local_sha256)
        manifest_metadata_changed = bool(
            (manifest.build_id and manifest.build_id != str(local_manifest.get("build_id", "")).strip())
            or (manifest.build_time and manifest.build_time != str(local_manifest.get("build_time", "")).strip())
        )
        compare = _compare_versions(self.current_version, manifest.version)
        normalized_local = normalize_version(self.current_version)
        normalized_remote = normalize_version(manifest.version)
        if manifest.sha256 and local_sha256 == manifest.sha256:
            self._log(
                "local exe sha matches remote; forcing current state and syncing manifest "
                f"local_version={self.current_version} remote_version={manifest.version}"
            )
            self._sync_local_manifest(manifest)
            local_manifest = read_local_manifest()
            self.current_version = resolve_local_version()
            local_sha256 = self._current_exe_sha256(local_manifest)
            compare = _compare_versions(self.current_version, manifest.version)
            normalized_local = normalize_version(self.current_version)
            manifest_metadata_changed = False
            self._log(
                "update result=current sha_match should_show_popup=False "
                f"current_local_version={self.current_version} remote_version={manifest.version} "
                f"local_sha256={local_sha256} remote_sha256={manifest.sha256}"
            )
            version_debug_log(
                f"local_version={self.current_version} remote_version={manifest.version} "
                f"channel={self.settings.channel} remote_channel={manifest.channel} "
                "compare_result=0 sha_match=True should_show_popup=False"
            )
            return UpdateCheck("current", f"目前已是最新版 {self.current_version}。", manifest, compare, False)
        content_changed_same_version = compare == 0 and sha_changed
        should_show_popup = compare < 0 or content_changed_same_version
        self._log(
            "check decision "
            f"local_version_path={self.local_version_path} current_local_version={self.current_version} "
            f"normalized_local={normalized_local} remote_version={manifest.version} normalized_remote={normalized_remote} "
            f"compare_result={compare} local_sha256={local_sha256} remote_sha256={manifest.sha256} "
            f"sha_changed={sha_changed} metadata_changed={manifest_metadata_changed} "
            f"pending_manifest={self.pending_manifest_path.exists()} should_show_popup={should_show_popup}"
        )
        version_debug_log(
            f"local_version={self.current_version} remote_version={manifest.version} "
            f"channel={self.settings.channel} remote_channel={manifest.channel} "
            f"compare_result={compare} normalized_local={normalized_local} normalized_remote={normalized_remote} "
            f"local_sha256={local_sha256} remote_sha256={manifest.sha256} "
            f"sha_changed={sha_changed} metadata_changed={manifest_metadata_changed} should_show_popup={should_show_popup}"
        )
        if compare > 0:
            self._log("update result=current should_show_popup=False")
            return UpdateCheck("current", f"目前已是最新版 {self.current_version}。", manifest, compare, False)
        if compare == 0 and not content_changed_same_version:
            self._log("update result=current same_version_same_build should_show_popup=False")
            return UpdateCheck("current", f"目前已是最新版 {self.current_version}。", manifest, compare, False)

        self._log("update result=available should_show_popup=True")
        if content_changed_same_version:
            return UpdateCheck("available", f"發現同版本新版 build {manifest.version}。", manifest, compare, True)
        return UpdateCheck("available", f"發現新版 {manifest.version}。", manifest, compare, True)

    def apply(self, manifest: UpdateManifest, progress: ProgressCallback | None = None) -> UpdateCheck:
        try:
            self._emit_progress(progress, "downloading", 0, "開始下載新版 EXE")
            self._log(f"progress download start version={manifest.version} url={manifest.download_url}")
            downloaded = self._download(manifest, progress=progress)
            self._log(f"progress download completed path={downloaded}")
            self._emit_progress(progress, "verifying", 90, "正在驗證 SHA256")
            self._log(f"progress verify completed sha256={manifest.sha256}")
            self._write_pending_manifest(manifest)
            self._emit_progress(progress, "replacing", 96, "準備覆蓋主程式")
            self._log("progress replace scheduled")
            self._emit_progress(progress, "restarting", 100, "即將重新啟動")
            self._schedule_replace(downloaded)
        except Exception as exc:
            self._log(f"apply failed: {exc}")
            return UpdateCheck("error", f"更新失敗，已保留目前版本：{exc}", manifest)
        return UpdateCheck("restarting", f"已下載新版 {manifest.version}，即將重新啟動。", manifest)

    def reset_state(self) -> dict[str, object]:
        """Clear dirty updater state and rebuild local state from the running EXE.

        The reset flow is intentionally SHA-first. If the current process EXE
        already matches GitHub latest, we immediately sync the local manifest and
        return a current state so the UI cannot keep showing a stale update.
        """

        before_manifest = read_local_manifest()
        before_sha = self._current_exe_sha256(before_manifest)
        before_version = resolve_local_version()
        self._log(
            "reset state start "
            f"exe_path={Path(sys.executable).resolve()} local_version={before_version} local_sha={before_sha}"
        )
        removed = self._clear_dirty_state_files()
        manifest: UpdateManifest | None = None
        remote_error = ""
        try:
            manifest = self._load_manifest()
        except Exception as exc:
            remote_error = f"{type(exc).__name__}: {exc}"
            self._log(f"reset remote load failed error={remote_error}")

        current_sha = before_sha or self._current_exe_sha256({})
        if manifest and manifest.sha256 and current_sha == manifest.sha256:
            self._log("reset state remote sha matches current exe; syncing remote manifest")
            self._sync_local_manifest(manifest)
            finalized = True
            update_state = "current_sha_match"
        else:
            clean = self._build_clean_local_manifest(before_manifest, manifest, current_sha)
            self.local_version_path.parent.mkdir(parents=True, exist_ok=True)
            self.local_version_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            finalized = False
            update_state = "available" if manifest and manifest.sha256 and current_sha and current_sha != manifest.sha256 else "reset_local_only"
            self._log(
                "reset state wrote clean local manifest "
                f"version={clean.get('version')} sha256={clean.get('sha256')} update_state={update_state}"
            )

        state = self.debug_state()
        state.update(
            {
                "reset_removed": removed,
                "reset_remote_error": remote_error,
                "reset_current_sha": current_sha,
                "update_state": update_state,
                "finalize_state": "finalized" if finalized else "clean_local_manifest",
            }
        )
        self._log("reset state completed " + json.dumps(state, ensure_ascii=False, sort_keys=True))
        return state

    def _clear_dirty_state_files(self) -> list[str]:
        config_dir = self.local_version_path.parent
        temp_dir = Path(tempfile.gettempdir())
        candidates = [
            self.pending_manifest_path,
            config_dir / "pending_update.json",
            config_dir / "update_state.json",
            config_dir / "local_manifest.json",
            config_dir / "updater_cache.json",
            config_dir / "sha_cache.json",
            config_dir / "stale_sha_cache.json",
            temp_dir / "AI_Customs_ERP_V2.update.exe",
            temp_dir / "AI_Customs_ERP_V2_update.bat",
            temp_dir / "TongYangCustomsPlatform.update.exe",
        ]
        removed: list[str] = []
        for path in candidates:
            try:
                if path.exists():
                    path.unlink()
                    removed.append(str(path))
            except OSError as exc:
                self._log(f"reset state cleanup failed path={path} error={exc}")
        cache_dir = config_dir / "updater_cache"
        if cache_dir.exists() and cache_dir.is_dir():
            removed.extend(self._remove_directory(cache_dir, "reset updater cache cleanup failed"))
        for dirty_dir in (config_dir / "temp_update", temp_dir / "temp_update", temp_dir / "TongYangCustomsPlatform.temp_update"):
            if dirty_dir.exists() and dirty_dir.is_dir():
                removed.extend(self._remove_directory(dirty_dir, "reset temp update cleanup failed"))
        return removed

    def _remove_directory(self, path: Path, log_prefix: str) -> list[str]:
        removed: list[str] = []
        try:
            for child in path.rglob("*"):
                if child.is_file():
                    removed.append(str(child))
            shutil.rmtree(path)
            removed.append(str(path))
        except OSError as exc:
            self._log(f"{log_prefix} path={path} error={exc}")
            try:
                if path.exists():
                    for child in path.rglob("*"):
                        if child.is_file():
                            child.unlink()
                            removed.append(str(child))
                    path.rmdir()
                    removed.append(str(path))
            except OSError as retry_exc:
                self._log(f"{log_prefix} retry failed path={path} error={retry_exc}")
        return removed

    def _build_clean_local_manifest(
        self,
        previous: dict,
        remote: UpdateManifest | None,
        current_sha: str,
    ) -> dict[str, str]:
        version = str(previous.get("version") or (remote.version if remote else "") or self.current_version).strip()
        channel = str(previous.get("channel") or self.settings.channel).strip() or self.settings.channel
        exe_path = str(Path(sys.executable).resolve())
        return {
            "app_name": "通洋報關平台",
            "version": version,
            "channel": channel,
            "exe_url": exe_path,
            "download_url": exe_path,
            "sha256": current_sha,
            "build_id": str(previous.get("build_id") or (f"{version}-{current_sha[:12]}" if current_sha else version)),
            "build_time": str(previous.get("build_time", "")),
            "release_id": str(previous.get("release_id") or previous.get("build_id") or version),
            "release_notes": "Local updater state reset",
            "notes": "Local updater state reset",
            "minimum_supported_version": str(previous.get("minimum_supported_version") or version),
            "current_exe_path": exe_path,
        }

    def _write_pending_manifest(self, manifest: UpdateManifest) -> None:
        self.pending_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.pending_manifest_path.write_text(
            json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._log(f"pending manifest written path={self.pending_manifest_path} version={manifest.version}")

    def _sync_local_manifest(self, manifest: UpdateManifest) -> None:
        target = local_manifest_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.current_version = resolve_local_version()
        self._log(f"local manifest synced path={target} version={self.current_version} channel={manifest.channel}")
        version_debug_log(
            f"local_version={self.current_version} remote_version={manifest.version} "
            f"channel={manifest.channel} remote_channel={manifest.channel} "
            "compare_result=0 should_show_popup=False update_completed_state=synced"
        )

    def _load_manifest(self) -> UpdateManifest:
        manifest_url = (
            self.settings.dev_manifest_url
            if self.settings.channel == "dev"
            else self.settings.stable_manifest_url
        )
        self._log(f"manifest fetch channel={self.settings.channel} url={manifest_url}")
        manifest = _read_json_url(manifest_url)
        self._validate_manifest_contract(manifest)

        return UpdateManifest(
            version=str(manifest.get("version", "")).strip(),
            download_url=str(manifest.get("exe_url") or manifest.get("download_url") or "").strip(),
            sha256=str(manifest.get("sha256", "")).strip().lower(),
            channel=str(manifest.get("channel", self.settings.channel)).strip() or self.settings.channel,
            notes=str(manifest.get("notes") or manifest.get("release_notes") or ""),
            build_id=str(manifest.get("build_id", "")).strip(),
            build_time=str(manifest.get("build_time", "")),
            exe_url=str(manifest.get("exe_url") or manifest.get("download_url") or "").strip(),
            release_notes=str(manifest.get("release_notes") or manifest.get("notes") or ""),
            minimum_supported_version=str(manifest.get("minimum_supported_version", "")),
            release_id=str(manifest.get("release_id") or manifest.get("build_id", "")).strip(),
        )

    def _validate_manifest_contract(self, manifest: dict | list) -> None:
        if not isinstance(manifest, dict):
            raise RuntimeError("version.json must be a JSON object")
        required = (
            "version",
            "channel",
            "exe_url",
            "release_notes",
            "minimum_supported_version",
            "build_id",
            "build_time",
            "sha256",
        )
        missing = [field for field in required if not str(manifest.get(field, "")).strip()]
        if missing:
            raise RuntimeError(f"version.json missing required fields: {', '.join(missing)}")
        channel = str(manifest.get("channel", "")).strip()
        if channel not in {"stable", "dev"}:
            raise RuntimeError(f"version.json invalid channel: {channel}")
        sha256 = str(manifest.get("sha256", "")).strip().lower()
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise RuntimeError("version.json invalid sha256")
        exe_url = str(manifest.get("exe_url", "")).strip()
        if not exe_url.endswith("/TongYangCustomsPlatform.exe"):
            raise RuntimeError("version.json exe_url must point to TongYangCustomsPlatform.exe")
        if channel == "stable" and "/releases/latest/download/" not in exe_url:
            raise RuntimeError("stable version.json exe_url must use /releases/latest/download/")
        if channel == "dev" and "/releases/download/" not in exe_url:
            raise RuntimeError("dev version.json exe_url must use a tag-specific release download URL")

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

    def _schedule_replace(self, update_exe: Path) -> None:
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
            local_manifest_path=self.local_version_path,
            pending_manifest_path=self.pending_manifest_path,
            expected_sha256=hashlib.sha256(update_exe.read_bytes()).hexdigest().lower(),
            old_pid=os.getpid(),
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
        line = f"[{stamp}] {message}\n"
        for path in (self.log_path, self.compat_log_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def _emit_progress(self, progress: ProgressCallback | None, stage: str, percent: int, message: str) -> None:
        self._log(f"progress {stage} percent={percent} message={message}")
        if progress:
            progress(stage, percent, message)

    def _current_exe_sha256(self, local_manifest: dict) -> str:
        if getattr(sys, "frozen", False):
            exe_path = Path(sys.executable).resolve()
            if exe_path.is_file():
                return hashlib.sha256(exe_path.read_bytes()).hexdigest().lower()
        return str(local_manifest.get("sha256", "")).strip().lower()

    def debug_state(self) -> dict[str, object]:
        local_manifest = read_local_manifest()
        local_version = resolve_local_version()
        local_sha = self._current_exe_sha256(local_manifest)
        pending = self._read_pending_manifest()
        state: dict[str, object] = {
            "executable_path": str(Path(sys.executable).resolve()),
            "frozen": bool(getattr(sys, "frozen", False)),
            "local_manifest_path": str(self.local_version_path),
            "pending_manifest_path": str(self.pending_manifest_path),
            "local_version": local_version,
            "local_sha": local_sha,
            "pending_version": str(pending.get("version", "")),
            "pending_sha": str(pending.get("sha256", "")),
            "pending_exists": self.pending_manifest_path.exists(),
            "cache_state": "GitHub requests use Cache-Control=no-cache; local cache is manifest files only.",
            "finalize_state": "pending" if self.pending_manifest_path.exists() else "none",
            "update_state": "unknown",
        }
        shortcuts = inspect_desktop_shortcuts(str(Path(sys.executable).resolve()))
        state["shortcut_state"] = shortcuts
        repaired = self._repair_desktop_shortcuts()
        if repaired:
            state["shortcut_repaired"] = repaired
        try:
            manifest = self._load_manifest()
            compare = _compare_versions(local_version, manifest.version)
            sha_match = bool(manifest.sha256 and local_sha == manifest.sha256)
            sha_changed = bool(manifest.sha256 and local_sha and local_sha != manifest.sha256)
            if sha_match:
                update_state = "current_sha_match"
            elif compare < 0 or (compare == 0 and sha_changed):
                update_state = "available"
            elif compare == 0:
                update_state = "current"
            else:
                update_state = "local_newer"
            state.update(
                {
                    "remote_version": manifest.version,
                    "remote_sha": manifest.sha256,
                    "remote_channel": manifest.channel,
                    "download_url": manifest.download_url,
                    "compare_result": compare,
                    "normalized_local": normalize_version(local_version),
                    "normalized_remote": normalize_version(manifest.version),
                    "sha_match": sha_match,
                    "sha_changed": sha_changed,
                    "update_state": update_state,
                    "finalize_state": "finalized_by_sha" if sha_match and pending else state["finalize_state"],
                }
            )
        except Exception as exc:
            state.update({"remote_error": f"{type(exc).__name__}: {exc}", "update_state": "remote_error"})
        self._log("debug panel state " + json.dumps(state, ensure_ascii=False, sort_keys=True))
        return state

    def _read_pending_manifest(self) -> dict:
        if not self.pending_manifest_path.exists():
            return {}
        try:
            data = json.loads(self.pending_manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _repair_or_cleanup_pending_manifest(self, remote: UpdateManifest, local_sha256: str) -> None:
        if not self.pending_manifest_path.exists():
            return
        try:
            pending_data = json.loads(self.pending_manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            self._log(f"pending manifest invalid; cleanup path={self.pending_manifest_path} error={exc}")
            self.pending_manifest_path.unlink(missing_ok=True)
            return
        pending_sha = str(pending_data.get("sha256", "")).strip().lower()
        pending_version = str(pending_data.get("version", "")).strip()
        self._log(
            f"pending manifest found version={pending_version} pending_sha256={pending_sha} "
            f"current_exe_sha256={local_sha256} remote_sha256={remote.sha256}"
        )
        if pending_sha and local_sha256 == pending_sha:
            self._log("pending update finalized after restart; current exe sha matches pending")
            self.local_version_path.write_text(json.dumps(pending_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.pending_manifest_path.unlink(missing_ok=True)
            self.current_version = resolve_local_version()
            return
        if remote.sha256 and local_sha256 == remote.sha256:
            self._log("pending cleanup; current exe sha matches remote")
            self._sync_local_manifest(remote)
            self.pending_manifest_path.unlink(missing_ok=True)
            return
        self._log("pending update not applied; removing stale pending manifest")
        self.pending_manifest_path.unlink(missing_ok=True)

    def _repair_desktop_shortcuts(self) -> list[dict[str, str]]:
        if not getattr(sys, "frozen", False):
            return []
        current_exe = Path(sys.executable).resolve()
        if current_exe.name.lower() != "tongyangcustomsplatform.exe":
            return []
        repaired = repair_desktop_shortcuts(str(current_exe))
        if repaired:
            self._log("shortcut repaired " + json.dumps(repaired, ensure_ascii=False))
        return repaired


def inspect_desktop_shortcuts(current_exe: str) -> list[dict[str, str]]:
    return _shortcut_ps(current_exe, repair=False)


def repair_desktop_shortcuts(current_exe: str) -> list[dict[str, str]]:
    return _shortcut_ps(current_exe, repair=True)


def _shortcut_ps(current_exe: str, repair: bool) -> list[dict[str, str]]:
    script = r'''
$ErrorActionPreference = "Stop"
$current = $env:TY_CURRENT_EXE
$repair = $env:TY_REPAIR_SHORTCUT -eq "1"
$shell = New-Object -ComObject WScript.Shell
$dirs = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("CommonDesktopDirectory")) | Where-Object { $_ -and (Test-Path $_) }
$rows = @()
foreach ($dir in $dirs) {
  foreach ($lnk in Get-ChildItem -LiteralPath $dir -Filter *.lnk -Force -ErrorAction SilentlyContinue) {
    try {
      $sc = $shell.CreateShortcut($lnk.FullName)
      $target = [string]$sc.TargetPath
      $name = [string]$lnk.BaseName
      $targetName = ""
      if ($target) { $targetName = [IO.Path]::GetFileName($target) }
      $isTongYang = $targetName -ieq "TongYangCustomsPlatform.exe" -or $name -match "TongYang|Customs|通洋|報關|报关"
      if (-not $isTongYang) { continue }
      $before = $target
      $action = "inspect"
      if ($repair -and $current -and $target -ne $current) {
        $sc.TargetPath = $current
        $sc.WorkingDirectory = [IO.Path]::GetDirectoryName($current)
        $sc.Save()
        $target = $sc.TargetPath
        $action = "repaired"
      }
      $rows += [pscustomobject]@{
        shortcut_path = $lnk.FullName
        shortcut_name = $lnk.Name
        target_path = $target
        previous_target_path = $before
        matches_current = ([string]$target -eq [string]$current)
        action = $action
      }
    } catch {
      $rows += [pscustomobject]@{
        shortcut_path = $lnk.FullName
        shortcut_name = $lnk.Name
        target_path = ""
        previous_target_path = ""
        matches_current = $false
        action = "error: $($_.Exception.Message)"
      }
    }
  }
}
$rows | ConvertTo-Json -Depth 4 -Compress
'''
    env = dict(os.environ)
    env["TY_CURRENT_EXE"] = current_exe
    env["TY_REPAIR_SHORTCUT"] = "1" if repair else "0"
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=12,
            env=env,
            check=False,
        )
    except Exception:
        return []
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [{str(key): str(value) for key, value in data.items()}]
    if isinstance(data, list):
        return [{str(key): str(value) for key, value in item.items()} for item in data if isinstance(item, dict)]
    return []


def _read_json_url(url: str) -> dict | list:
    response = requests.get(
        url,
        timeout=(10, 30),
        headers={
            "User-Agent": "AI-Customs-ERP-V2/1.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


def normalize_version(value: str) -> str:
    clean = str(value or "").strip().lower()
    clean = clean.removeprefix("refs/tags/")
    clean = clean.lstrip("v")
    clean = clean.replace("_", "-")
    return clean


def _version_key(value: str) -> tuple[tuple[int, ...], int, tuple[int, ...]]:
    clean = normalize_version(value)
    main, sep, prerelease = clean.partition("-")
    numbers: list[int] = []
    for chunk in main.split("."):
        if not chunk:
            continue
        match = "".join(char for char in chunk if char.isdigit())
        numbers.append(int(match or "0"))
    while len(numbers) < 3:
        numbers.append(0)
    prerelease_rank = 1 if not sep else 0
    prerelease_numbers = tuple(int(part) for part in re.findall(r"\d+", prerelease)) if sep else ()
    return tuple(numbers), prerelease_rank, prerelease_numbers


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
    local_manifest_path: Path | None = None,
    pending_manifest_path: Path | None = None,
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
        'del /f /q "%BACKUP%" >> "%LOG%" 2>&1'
        if cleanup
        else 'echo [%date% %time%] cleanup skipped >> "%LOG%"'
    )
    return f"""@echo off
setlocal EnableExtensions
set "CURRENT={current_exe}"
set "UPDATE={update_exe}"
set "BACKUP={backup_exe}"
set "LOG={log_path}"
set "LOCAL_MANIFEST={local_manifest_path or ""}"
set "PENDING_MANIFEST={pending_manifest_path or ""}"
set "EXPECTED_SHA={expected_sha256.lower()}"
set "OLD_PID={old_pid}"

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
if not "%PENDING_MANIFEST%"=="" (
  if exist "%PENDING_MANIFEST%" (
    copy /y "%PENDING_MANIFEST%" "%LOCAL_MANIFEST%" >> "%LOG%" 2>&1
    if errorlevel 1 (
      echo [%date% %time%] local manifest finalize failed >> "%LOG%"
      goto rollback
    )
    del /f /q "%PENDING_MANIFEST%" >> "%LOG%" 2>&1
    echo [%date% %time%] local manifest finalized path=%LOCAL_MANIFEST% >> "%LOG%"
  ) else (
    echo [%date% %time%] pending manifest missing path=%PENDING_MANIFEST% >> "%LOG%"
  )
)
echo [%date% %time%] replace success current=%CURRENT% >> "%LOG%"
echo [%date% %time%] progress replace completed >> "%LOG%"
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
