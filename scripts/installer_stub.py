from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


APP_DIR_NAME = "TongYangCustomsPlatform"
APP_DISPLAY_NAME = "通洋報關平台"
APP_EXE_NAME = "TongYangCustomsPlatform.exe"
SETUP_EXE_NAME = "TongYangCustomsPlatform_Setup.exe"
LEGACY_CHINESE_EXE_NAME = "通洋報關平台.exe"
DESKTOP_ARTIFACT_NAMES = (
    APP_EXE_NAME,
    SETUP_EXE_NAME,
    LEGACY_CHINESE_EXE_NAME,
    "AI_Customs_ERP_V2.update.exe",
    "TongYangCustomsPlatform.update.exe",
    "TongYangCustomsPlatform_Setup.update.exe",
    "SHA256.txt",
)
UPDATE_SCRIPT_NAMES = (
    "AI_Customs_ERP_V2_update.bat",
    "TongYangCustomsPlatform_setup_update.bat",
    "update.bat",
)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def _program_files_root() -> Path:
    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(program_files) / APP_DIR_NAME


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin() -> None:
    params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if int(rc) <= 32:
        raise RuntimeError("無法取得系統管理員權限，安裝已取消。")


def _payload_path(name: str) -> Path:
    direct = _base_dir() / "payload" / name
    if direct.exists():
        return direct
    fallback = _base_dir() / name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"安裝包缺少必要檔案：{name}")


def _copy_payload(root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    (root / "cache").mkdir(exist_ok=True)
    (root / "config").mkdir(exist_ok=True)
    (root / "runtime").mkdir(exist_ok=True)

    app_exe = _payload_path(APP_EXE_NAME)
    target_exe = root / APP_EXE_NAME
    temp_exe = root / f"{APP_EXE_NAME}.new"
    shutil.copy2(app_exe, temp_exe)
    temp_exe.replace(target_exe)

    for name in ("version.json", "SHA256.txt"):
        try:
            source = _payload_path(name)
        except FileNotFoundError:
            continue
        destination = root / ("config" if name == "version.json" else "") / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    return {"install_root": str(root), "exe": str(target_exe)}


def _grant_runtime_permissions(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    # Builtin Users SID avoids localized group-name issues on Chinese Windows.
    users_sid = "*S-1-5-32-545"
    for path in (root / "logs", root / "cache", root / "config", root / "runtime"):
        try:
            path.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/grant",
                    f"{users_sid}:(OI)(CI)M",
                    "/T",
                    "/C",
                ],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            rows.append(
                {
                    "path": str(path),
                    "returncode": str(completed.returncode),
                    "status": "ok" if completed.returncode == 0 else "failed",
                }
            )
        except Exception as exc:
            rows.append({"path": str(path), "returncode": "", "status": f"{type(exc).__name__}: {exc}"})
    return rows


def _ensure_shortcuts(exe: Path) -> list[dict[str, str]]:
    script = r'''
$ErrorActionPreference = "Stop"
$exe = $env:TY_APP_EXE
$name = $env:TY_APP_NAME
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$startMenu = Join-Path $programs "TongYang Customs Platform"
if (-not (Test-Path -LiteralPath $startMenu)) { New-Item -ItemType Directory -Path $startMenu -Force | Out-Null }
$targets = @(
  (Join-Path $desktop ($name + ".lnk")),
  (Join-Path $startMenu ($name + ".lnk"))
)
$rows = @()
foreach ($shortcutPath in $targets) {
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $previous = [string]$shortcut.TargetPath
  $shortcut.TargetPath = $exe
  $shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($exe)
  $shortcut.IconLocation = $exe
  $shortcut.Save()
  $rows += [pscustomobject]@{ shortcut_path=$shortcutPath; target_path=$exe; previous_target_path=$previous; action="created_or_repaired" }
}
foreach ($dir in @($desktop, $startMenu)) {
  foreach ($lnk in Get-ChildItem -LiteralPath $dir -Filter *.lnk -Force -ErrorAction SilentlyContinue) {
    try {
      $sc = $shell.CreateShortcut($lnk.FullName)
      $target = [string]$sc.TargetPath
      $targetName = if ($target) { [IO.Path]::GetFileName($target) } else { "" }
      $isCanonical = ($lnk.FullName -eq (Join-Path $desktop ($name + ".lnk"))) -or ($lnk.FullName -eq (Join-Path $startMenu ($name + ".lnk")))
      $related = $targetName -ieq "TongYangCustomsPlatform.exe" -or $lnk.BaseName -match "TongYang|Customs|通洋|報關|报关"
      if ($related -and $target -ne $exe) {
        $previous = $target
        $sc.TargetPath = $exe
        $sc.WorkingDirectory = [IO.Path]::GetDirectoryName($exe)
        $sc.IconLocation = $exe
        $sc.Save()
        $rows += [pscustomobject]@{ shortcut_path=$lnk.FullName; target_path=$exe; previous_target_path=$previous; action="repaired_old_shortcut" }
      } elseif ($related -and -not $isCanonical) {
        Remove-Item -LiteralPath $lnk.FullName -Force -ErrorAction SilentlyContinue
        $rows += [pscustomobject]@{ shortcut_path=$lnk.FullName; target_path=$target; previous_target_path=$target; action="removed_duplicate_shortcut" }
      }
    } catch {}
  }
}
$rows | ConvertTo-Json -Depth 4 -Compress
'''
    env = dict(os.environ)
    env["TY_APP_EXE"] = str(exe)
    env["TY_APP_NAME"] = APP_DISPLAY_NAME
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=True,
    )
    output = completed.stdout.strip()
    if not output:
        return []
    parsed = json.loads(output)
    return parsed if isinstance(parsed, list) else [parsed]


def _cleanup_desktop_artifacts(installed_exe: Path) -> list[str]:
    removed: list[str] = []
    desktop_dirs = []
    user_profile = os.environ.get("USERPROFILE")
    public = os.environ.get("PUBLIC")
    if user_profile:
        desktop_dirs.append(Path(user_profile) / "Desktop")
    if public:
        desktop_dirs.append(Path(public) / "Desktop")

    for directory in desktop_dirs:
        if not directory.exists():
            continue
        for name in DESKTOP_ARTIFACT_NAMES:
            path = directory / name
            try:
                if not path.exists() or not path.is_file():
                    continue
                if path.resolve() == installed_exe.resolve():
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
    return removed


def _launch_app(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _write_install_log(root: Path, state: dict[str, object]) -> None:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "installer.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    silent = "--silent" in sys.argv or "--silent-update" in sys.argv
    no_launch = "--no-launch" in sys.argv
    if os.name == "nt" and not _is_admin():
        if silent:
            return 5
        _relaunch_as_admin()
        return 0

    root = _program_files_root()
    install_state = _copy_payload(root)
    permissions = _grant_runtime_permissions(root)
    shortcuts = _ensure_shortcuts(Path(install_state["exe"]))
    desktop_cleanup = _cleanup_desktop_artifacts(Path(install_state["exe"]))
    state = {
        "status": "installed",
        "root": str(root),
        "exe": install_state["exe"],
        "permissions": permissions,
        "shortcuts": shortcuts,
        "desktop_cleanup": desktop_cleanup,
        "silent": silent,
    }
    _write_install_log(root, state)
    if not no_launch:
        _launch_app(Path(install_state["exe"]))
    if not silent:
        try:
            ctypes.windll.user32.MessageBoxW(None, "通洋報關平台已安裝完成。", APP_DISPLAY_NAME, 0)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            log_path = Path(tempfile.gettempdir()) / "TongYangCustomsPlatform_Setup_error.log"
            log_path.write_text(str(exc), encoding="utf-8")
            ctypes.windll.user32.MessageBoxW(None, f"安裝失敗：{exc}", APP_DISPLAY_NAME, 0x10)
        except Exception:
            pass
        raise
