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
      $related = $targetName -ieq "TongYangCustomsPlatform.exe" -or $lnk.BaseName -match "TongYang|Customs|通洋|報關"
      if ($related -and $target -ne $exe) {
        $previous = $target
        $sc.TargetPath = $exe
        $sc.WorkingDirectory = [IO.Path]::GetDirectoryName($exe)
        $sc.IconLocation = $exe
        $sc.Save()
        $rows += [pscustomobject]@{ shortcut_path=$lnk.FullName; target_path=$exe; previous_target_path=$previous; action="repaired_old_shortcut" }
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
    shortcuts = _ensure_shortcuts(Path(install_state["exe"]))
    state = {
        "status": "installed",
        "root": str(root),
        "exe": install_state["exe"],
        "shortcuts": shortcuts,
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
