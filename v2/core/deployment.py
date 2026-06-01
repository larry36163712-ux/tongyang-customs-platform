from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import ctypes
from pathlib import Path

APP_DIR_NAME = "TongYangCustomsPlatform"
APP_EXE_NAME = "TongYangCustomsPlatform.exe"
APP_DISPLAY_NAME = "通洋報關平台"
SETUP_EXE_NAME = "TongYangCustomsPlatform_Setup.exe"
LEGACY_CHINESE_EXE_NAME = "通洋報關平台.exe"
UPDATE_SCRIPT_NAMES = (
    "AI_Customs_ERP_V2_update.bat",
    "TongYangCustomsPlatform_setup_update.bat",
    "update.bat",
)
DESKTOP_ARTIFACT_NAMES = (
    APP_EXE_NAME,
    SETUP_EXE_NAME,
    LEGACY_CHINESE_EXE_NAME,
    "AI_Customs_ERP_V2.update.exe",
    "TongYangCustomsPlatform.update.exe",
    "TongYangCustomsPlatform_Setup.update.exe",
    "updater.exe",
    "SHA256.txt",
)
DESKTOP_ARTIFACT_PATTERNS = (
    "*.update.exe",
    "*.temp.exe",
    "*.tmp.exe",
    "*.new.exe",
)


def production_root() -> Path:
    if os.environ.get("TY_INSTALL_SCOPE", "").strip().lower() in {"machine", "programfiles", "program_files"}:
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            return Path(program_files) / APP_DIR_NAME
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIR_NAME
    return Path.home() / "AppData" / "Local" / APP_DIR_NAME


def legacy_program_files_root() -> Path | None:
    program_files = os.environ.get("ProgramFiles")
    if not program_files:
        return None
    return Path(program_files) / APP_DIR_NAME


def production_exe_path() -> Path:
    return production_root() / APP_EXE_NAME


def is_program_files_path(path: Path) -> bool:
    program_files_roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    for root in program_files_roots:
        if not root:
            continue
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def is_elevated_process() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_running_from_production_dir() -> bool:
    if not is_frozen_app():
        return False
    try:
        return Path(sys.executable).resolve() == production_exe_path().resolve()
    except OSError:
        return False


def ensure_runtime_layout(relaunch: bool = True) -> dict[str, object]:
    """Install the frozen EXE into the single production runtime directory.

    In production, every shortcut and updater operation should point to the
    per-user runtime directory by default:
    %LOCALAPPDATA%/TongYangCustomsPlatform/TongYangCustomsPlatform.exe. If the
    user launches a copied EXE from Downloads, Desktop, dist, or an older
    Program Files installation, we copy that EXE into the per-user directory and
    relaunch the production copy. Machine-wide Program Files mode is retained as
    an explicit opt-in via TY_INSTALL_SCOPE=machine.
    """

    state: dict[str, object] = {
        "frozen": is_frozen_app(),
        "production_root": str(production_root()),
        "production_exe": str(production_exe_path()),
        "current_exe": str(Path(sys.executable).resolve()),
        "installed": False,
        "relaunching": False,
        "shortcut_target": "",
        "cleanup_removed": [],
    }
    if not is_frozen_app():
        return state

    root = production_root()
    try:
        for dirname in ("logs", "cache", "config", "runtime"):
            (root / dirname).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        state["layout_error"] = f"{type(exc).__name__}: {exc}"
        return state

    current = Path(sys.executable).resolve()
    target = production_exe_path()
    if current != target:
        if is_program_files_path(target) and not is_elevated_process():
            state["installed"] = target.exists()
            state["install_required"] = True
            state["layout_error"] = (
                "Program Files requires elevated installer; skipped direct self-copy "
                "to avoid partial update or WinError 5."
            )
            state["cleanup_removed"] = cleanup_update_artifacts(root)
            if target.exists():
                shortcut_state = ensure_shortcuts(target)
                state["shortcut_target"] = str(target)
                state["shortcuts"] = shortcut_state
                if relaunch:
                    _launch_hidden(target)
                    state["relaunching"] = True
                    return state
            return state
        try:
            _copy_if_changed(current, target)
            _copy_runtime_manifest(current.parent, root)
            migration_state = migrate_legacy_program_files_data(root)
            state["installed"] = True
            state["migration"] = migration_state
            state["cleanup_removed"] = cleanup_update_artifacts(root)
            shortcut_state = ensure_shortcuts(target)
            state["shortcut_target"] = str(target)
            state["shortcuts"] = shortcut_state
            if relaunch:
                _launch_hidden(target)
                state["relaunching"] = True
                return state
        except OSError as exc:
            state["layout_error"] = f"{type(exc).__name__}: {exc}"
            state["cleanup_removed"] = cleanup_update_artifacts(root)
            state["desktop_cleanup_removed"] = cleanup_desktop_artifacts(target)
            return state

    state["cleanup_removed"] = cleanup_update_artifacts(root)
    state["migration"] = migrate_legacy_program_files_data(root)
    shortcut_state = ensure_shortcuts(target)
    state["shortcut_target"] = str(target)
    state["shortcuts"] = shortcut_state
    state["desktop_cleanup_removed"] = cleanup_desktop_artifacts(target)
    return state


def migrate_legacy_program_files_data(target_root: Path | None = None) -> dict[str, object]:
    """Copy user data from an older Program Files install into per-user install.

    The migration is intentionally non-destructive: Program Files is not deleted,
    and files already present in the per-user target are preserved. The installer
    owns the new runtime manifest, so legacy config/version.json is skipped.
    """

    target = target_root or production_root()
    legacy = legacy_program_files_root()
    state: dict[str, object] = {
        "source": str(legacy) if legacy else "",
        "target": str(target),
        "copied": [],
        "skipped": [],
        "errors": [],
    }
    if not legacy or not legacy.exists():
        state["status"] = "no_legacy_program_files_install"
        return state
    try:
        if legacy.resolve() == target.resolve():
            state["status"] = "same_install_root"
            return state
    except OSError:
        pass

    data_dirs = ("config", "logs", "database", "parser_cache", "uploads")
    for dirname in data_dirs:
        source_dir = legacy / dirname
        if not source_dir.exists() or not source_dir.is_dir():
            continue
        destination_dir = target / dirname
        destination_dir.mkdir(parents=True, exist_ok=True)
        for source in source_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_dir)
            if dirname == "config" and relative.as_posix().lower() == "version.json":
                state["skipped"].append(str(source))
                continue
            destination = destination_dir / relative
            if destination.exists():
                state["skipped"].append(str(source))
                continue
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                state["copied"].append(str(destination))
            except OSError as exc:
                state["errors"].append(f"{source}: {type(exc).__name__}: {exc}")
    state["status"] = "completed_with_errors" if state["errors"] else "completed"
    return state


def cleanup_update_artifacts(root: Path | None = None) -> list[str]:
    root = root or production_root()
    temp_dir = Path(tempfile.gettempdir())
    candidates = [
        root / "config" / "pending_update.json",
        root / "config" / "update_state.json",
        root / "config" / "local_manifest.json",
        root / "config" / "updater_cache.json",
        root / "config" / "sha_cache.json",
        root / "config" / "stale_sha_cache.json",
        root / "config" / "version.pending.json",
        temp_dir / "AI_Customs_ERP_V2.update.exe",
        temp_dir / "AI_Customs_ERP_V2_update.bat",
        temp_dir / "TongYangCustoms_Setup.update.exe",
        temp_dir / "TongYangCustoms_setup_update.bat",
        temp_dir / "TongYangCustomsPlatform.update.exe",
        temp_dir / "TongYangCustomsPlatform_Setup.update.exe",
        temp_dir / "TongYangCustomsPlatform_setup_update.bat",
    ]
    directories = [
        root / "cache" / "updater",
        root / "config" / "updater_cache",
        root / "config" / "temp_update",
        temp_dir / "TongYangCustomsPlatform.temp_update",
        temp_dir / "temp_update",
    ]
    removed: list[str] = []
    for path in candidates:
        try:
            if path.exists():
                path.unlink()
                removed.append(str(path))
        except OSError:
            pass
    for path in directories:
        try:
            if path.exists() and path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))
        except OSError:
            pass
    return removed


def cleanup_desktop_artifacts(production_exe: Path | None = None) -> list[str]:
    """Remove known deployment leftovers from Desktop folders.

    The cleanup is intentionally conservative: only release/update artifact
    names and generated temp executable patterns are removed from the Desktop
    roots. User documents and unrelated shortcuts are left alone.
    """

    exe = (production_exe or production_exe_path()).resolve()
    removed: list[str] = []
    for directory in _desktop_dirs():
        for name in DESKTOP_ARTIFACT_NAMES:
            path = directory / name
            try:
                if not path.exists() or not path.is_file():
                    continue
                if path.resolve() == exe:
                    continue
                path.unlink()
                removed.append(str(path))
            except OSError:
                continue
        for name in UPDATE_SCRIPT_NAMES:
            path = directory / name
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    removed.append(str(path))
            except OSError:
                continue
        for pattern in DESKTOP_ARTIFACT_PATTERNS:
            for path in directory.glob(pattern):
                try:
                    if not path.is_file() or path.resolve() == exe:
                        continue
                    path.unlink()
                    removed.append(str(path))
                except OSError:
                    continue
    return removed


def ensure_shortcuts(exe_path: Path | None = None) -> list[dict[str, str]]:
    exe = exe_path or production_exe_path()
    script = r'''
$ErrorActionPreference = "Stop"
$exe = $env:TY_PRODUCTION_EXE
$name = $env:TY_DISPLAY_NAME
$desktop = [Environment]::GetFolderPath("Desktop")
$publicDesktop = [Environment]::GetFolderPath("CommonDesktopDirectory")
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "TongYang Customs Platform"
$publicPrograms = [Environment]::GetFolderPath("CommonPrograms")
$publicStartMenu = if ($publicPrograms) { Join-Path $publicPrograms "TongYang Customs Platform" } else { "" }
$dirs = @($desktop, $startMenu) | Where-Object { $_ }
$shell = New-Object -ComObject WScript.Shell
$rows = @()
foreach ($dir in $dirs) {
  if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  $shortcutPath = Join-Path $dir ($name + ".lnk")
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $before = [string]$shortcut.TargetPath
  $shortcut.TargetPath = $exe
  $shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($exe)
  $shortcut.IconLocation = $exe
  $shortcut.Save()
  $rows += [pscustomobject]@{
    shortcut_path = $shortcutPath
    target_path = $shortcut.TargetPath
    previous_target_path = $before
    action = "created_or_repaired"
  }
}
$canonicalDesktop = Join-Path $desktop ($name + ".lnk")
$canonicalStartMenu = Join-Path $startMenu ($name + ".lnk")
$canonicalPaths = @($canonicalDesktop, $canonicalStartMenu)
$scanDirs = @($desktop, $publicDesktop, $startMenu, $publicStartMenu) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
foreach ($dir in $scanDirs) {
  foreach ($lnk in Get-ChildItem -LiteralPath $dir -Filter *.lnk -Force -ErrorAction SilentlyContinue) {
    try {
      $sc = $shell.CreateShortcut($lnk.FullName)
      $target = [string]$sc.TargetPath
      $targetName = ""
      if ($target) { $targetName = [IO.Path]::GetFileName($target) }
      $isCanonical = $canonicalPaths -contains $lnk.FullName
      $looksRelated = $targetName -ieq "TongYangCustomsPlatform.exe" -or $lnk.BaseName -match "TongYang|Customs|通洋|報關|报关"
      if ($looksRelated -and -not $isCanonical) {
        Remove-Item -LiteralPath $lnk.FullName -Force -ErrorAction Stop
        $rows += [pscustomobject]@{
          shortcut_path = $lnk.FullName
          target_path = $target
          previous_target_path = $target
          action = "removed_duplicate_shortcut"
        }
      } elseif ($looksRelated -and $target -ne $exe) {
        $before = $target
        $sc.TargetPath = $exe
        $sc.WorkingDirectory = [IO.Path]::GetDirectoryName($exe)
        $sc.IconLocation = $exe
        $sc.Save()
        $rows += [pscustomobject]@{
          shortcut_path = $lnk.FullName
          target_path = $sc.TargetPath
          previous_target_path = $before
          action = "repaired_old_shortcut"
        }
      }
    } catch {
      $rows += [pscustomobject]@{
        shortcut_path = $lnk.FullName
        target_path = ""
        previous_target_path = ""
        action = "error: $($_.Exception.Message)"
      }
    }
  }
}
$rows | ConvertTo-Json -Depth 4 -Compress
'''
    env = dict(os.environ)
    env["TY_PRODUCTION_EXE"] = str(exe)
    env["TY_DISPLAY_NAME"] = APP_DISPLAY_NAME
    return _run_shortcut_script(script, env)


def inspect_shortcuts(exe_path: Path | None = None) -> list[dict[str, str]]:
    exe = exe_path or production_exe_path()
    script = r'''
$ErrorActionPreference = "Stop"
$exe = $env:TY_PRODUCTION_EXE
$desktop = [Environment]::GetFolderPath("Desktop")
$publicDesktop = [Environment]::GetFolderPath("CommonDesktopDirectory")
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "TongYang Customs Platform"
$publicPrograms = [Environment]::GetFolderPath("CommonPrograms")
$publicStartMenu = if ($publicPrograms) { Join-Path $publicPrograms "TongYang Customs Platform" } else { "" }
$dirs = @($desktop, $publicDesktop, $startMenu, $publicStartMenu) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$shell = New-Object -ComObject WScript.Shell
$rows = @()
foreach ($dir in $dirs) {
  foreach ($lnk in Get-ChildItem -LiteralPath $dir -Filter *.lnk -Force -ErrorAction SilentlyContinue) {
    try {
      $sc = $shell.CreateShortcut($lnk.FullName)
      $target = [string]$sc.TargetPath
      $targetName = ""
      if ($target) { $targetName = [IO.Path]::GetFileName($target) }
      $looksRelated = $targetName -ieq "TongYangCustomsPlatform.exe" -or $lnk.BaseName -match "TongYang|Customs|通洋|報關|报关"
      if (-not $looksRelated) { continue }
      $rows += [pscustomobject]@{
        shortcut_path = $lnk.FullName
        target_path = $target
        previous_target_path = ""
        matches_current = ([string]$target -eq [string]$exe)
        action = "inspect"
      }
    } catch {
      $rows += [pscustomobject]@{
        shortcut_path = $lnk.FullName
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
    env["TY_PRODUCTION_EXE"] = str(exe)
    return _run_shortcut_script(script, env)


def _copy_if_changed(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _sha256(source) == _sha256(target):
        return
    if is_program_files_path(target) and not is_elevated_process():
        raise PermissionError(
            "Program Files requires elevated installer; direct EXE replace is not allowed."
        )
    temp_target = target.with_suffix(".new.exe")
    shutil.copy2(source, temp_target)
    try:
        temp_target.replace(target)
    except OSError:
        shutil.copy2(source, target)
        temp_target.unlink(missing_ok=True)


def _copy_runtime_manifest(source_dir: Path, target_root: Path) -> None:
    source_manifest = source_dir / "config" / "version.json"
    if source_manifest.exists():
        target_config = target_root / "config"
        target_config.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_manifest, target_config / "version.json")


def _desktop_dirs() -> list[Path]:
    candidates: list[Path] = []
    user_profile = os.environ.get("USERPROFILE")
    public = os.environ.get("PUBLIC")
    if user_profile:
        candidates.append(Path(user_profile) / "Desktop")
    if public:
        candidates.append(Path(public) / "Desktop")
    return [path for path in candidates if path.exists()]


def _launch_hidden(exe: Path) -> None:
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True, creationflags=flags)


def _run_shortcut_script(script: str, env: dict[str, str]) -> list[dict[str, str]]:
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
            check=False,
            creationflags=flags,
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()
