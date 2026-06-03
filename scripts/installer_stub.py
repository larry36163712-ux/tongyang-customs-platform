from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from v2.core.shortcut_manager import looks_related_shortcut, read_shortcut_target, write_shortcut


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
    "updater.exe",
    "version.json",
    "SHA256.txt",
)
DESKTOP_ARTIFACT_PATTERNS = (
    "*.update.exe",
    "*.temp.exe",
    "*.tmp.exe",
    "*.new.exe",
)
UPDATE_SCRIPT_NAMES = (
    "AI_Customs_ERP_V2_update.bat",
    "AI_Customs_ERP_V2_update.ps1",
    "TongYangCustoms_setup_update.bat",
    "TongYangCustoms_setup_update.ps1",
    "TongYangCustomsPlatform_setup_update.bat",
    "TongYangCustomsPlatform_setup_update.ps1",
    "update.bat",
)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def _program_files_root() -> Path:
    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(program_files) / APP_DIR_NAME


def _local_app_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIR_NAME
    return Path.home() / "AppData" / "Local" / APP_DIR_NAME


def _install_root(machine_install: bool = False) -> Path:
    return _program_files_root() if machine_install else _local_app_data_root()


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
    for dirname in ("logs", "cache", "config", "runtime", "parser_cache", "uploads", "exports", "database"):
        (root / dirname).mkdir(exist_ok=True)

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
    _finalize_installed_manifest(root, target_exe)
    _clear_update_state(root)

    return {"install_root": str(root), "exe": str(target_exe)}


def _clear_update_state(root: Path) -> list[str]:
    removed: list[str] = []
    config = root / "config"
    for name in (
        "version.pending.json",
        "pending_update.json",
        "update_state.json",
        "local_manifest.json",
        "updater_cache.json",
        "sha_cache.json",
        "stale_sha_cache.json",
    ):
        path = config / name
        try:
            if path.exists() and path.is_file():
                path.unlink()
                removed.append(str(path))
        except OSError:
            continue
    for dirname in ("updater_cache", "temp_update"):
        path = config / dirname
        try:
            if path.exists() and path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))
        except OSError:
            continue
    return removed


def _migrate_legacy_program_files_data(target_root: Path, machine_install: bool = False) -> dict[str, object]:
    source_root = _program_files_root()
    state: dict[str, object] = {
        "source": str(source_root),
        "target": str(target_root),
        "copied": [],
        "skipped": [],
        "errors": [],
    }
    if machine_install:
        state["status"] = "machine_install_no_migration"
        return state
    if not source_root.exists():
        state["status"] = "no_legacy_program_files_install"
        return state
    try:
        if source_root.resolve() == target_root.resolve():
            state["status"] = "same_install_root"
            return state
    except OSError:
        pass

    for dirname in ("config", "logs", "database", "parser_cache", "uploads"):
        source_dir = source_root / dirname
        if not source_dir.exists() or not source_dir.is_dir():
            continue
        destination_dir = target_root / dirname
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _arg_value(name: str) -> str:
    prefix = f"{name}="
    for index, arg in enumerate(sys.argv):
        if arg == name and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if arg.startswith(prefix):
            return arg.split("=", 1)[1]
    return ""


def _wait_for_process_exit(pid_text: str, timeout_seconds: int = 60) -> dict[str, str]:
    if not pid_text:
        return {"pid": "", "status": "not_requested"}
    try:
        pid = int(pid_text)
    except ValueError:
        return {"pid": pid_text, "status": "invalid_pid"}
    if pid <= 0:
        return {"pid": str(pid), "status": "invalid_pid"}
    if os.name != "nt":
        return {"pid": str(pid), "status": "skipped_non_windows"}

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    synchronize = 0x00100000
    process_terminate = 0x0001
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    handle = kernel32.OpenProcess(synchronize | process_terminate, False, pid)
    if not handle:
        return {"pid": str(pid), "status": "not_running_or_inaccessible"}
    try:
        result = kernel32.WaitForSingleObject(handle, timeout_seconds * 1000)
        if result == wait_object_0:
            return {"pid": str(pid), "status": "exited"}
        if result == wait_timeout:
            terminated = bool(kernel32.TerminateProcess(handle, 1))
            if terminated:
                kernel32.WaitForSingleObject(handle, 5000)
                return {"pid": str(pid), "status": "terminated_after_timeout"}
            return {"pid": str(pid), "status": "timeout_terminate_failed"}
        return {"pid": str(pid), "status": f"wait_result_{result}"}
    finally:
        kernel32.CloseHandle(handle)


def _finalize_installed_manifest(root: Path, target_exe: Path) -> None:
    manifest_path = root / "config" / "version.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if isinstance(manifest, dict):
            manifest["sha256"] = _sha256(target_exe)
            manifest["app_sha256"] = manifest["sha256"]
            if getattr(sys, "frozen", False):
                manifest["package_sha256"] = _sha256(Path(sys.executable))
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except Exception:
        return


def _verify_installed_update(root: Path, target_exe: Path, expected_version: str, expected_sha256: str) -> dict[str, str]:
    result = {
        "expected_version": expected_version,
        "expected_sha256": expected_sha256.lower(),
        "actual_version": "",
        "actual_sha256": "",
        "status": "not_required",
    }
    expected_version = expected_version.strip()
    expected_sha256 = expected_sha256.strip().lower()
    if not expected_version and not expected_sha256:
        return result
    if not target_exe.exists():
        raise RuntimeError(f"Installed EXE missing: {target_exe}")

    actual_sha256 = _sha256(target_exe).lower()
    result["actual_sha256"] = actual_sha256
    manifest_path = root / "config" / "version.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Installed manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Installed manifest is invalid")
    actual_version = str(manifest.get("version", "")).strip()
    manifest_sha256 = str(manifest.get("sha256", "")).strip().lower()
    result["actual_version"] = actual_version

    if expected_version and actual_version != expected_version:
        raise RuntimeError(f"Installed version mismatch: actual={actual_version} expected={expected_version}")
    if expected_sha256 and actual_sha256 != expected_sha256:
        raise RuntimeError(f"Installed EXE SHA mismatch: actual={actual_sha256} expected={expected_sha256}")
    if expected_sha256 and manifest_sha256 != expected_sha256:
        raise RuntimeError(f"Installed manifest SHA mismatch: actual={manifest_sha256} expected={expected_sha256}")
    result["status"] = "verified"
    return result


def _grant_runtime_permissions(root: Path) -> list[dict[str, str]]:
    if not _is_program_files_path(root):
        return [{"path": str(root), "returncode": "0", "status": "not_required_per_user_install"}]
    rows: list[dict[str, str]] = []
    # Builtin Users SID avoids localized group-name issues on Chinese Windows.
    users_sid = "*S-1-5-32-545"
    writable_dirs = ("logs", "cache", "config", "runtime", "parser_cache", "uploads", "exports", "database")
    for path in (root / dirname for dirname in writable_dirs):
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
                timeout=20,
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


def _is_program_files_path(path: Path) -> bool:
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    for root in roots:
        if not root:
            continue
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def _desktop_dir() -> Path | None:
    user_profile = os.environ.get("USERPROFILE")
    return Path(user_profile) / "Desktop" if user_profile else None


def _start_menu_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TongYang Customs Platform" if appdata else None


def _taskbar_pinned_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar" if appdata else None


def _canonical_shortcut_paths() -> list[Path]:
    paths: list[Path] = []
    desktop = _desktop_dir()
    start_menu = _start_menu_dir()
    if desktop:
        paths.append(desktop / f"{APP_DISPLAY_NAME}.lnk")
    if start_menu:
        paths.append(start_menu / f"{APP_DISPLAY_NAME}.lnk")
    return paths


def _shortcut_scan_dirs() -> list[Path]:
    candidates: list[Path] = []
    user_profile = os.environ.get("USERPROFILE")
    public = os.environ.get("PUBLIC")
    appdata = os.environ.get("APPDATA")
    program_data = os.environ.get("ProgramData")
    if user_profile:
        candidates.append(Path(user_profile) / "Desktop")
    if public:
        candidates.append(Path(public) / "Desktop")
    if appdata:
        candidates.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TongYang Customs Platform")
        candidates.append(Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar")
    if program_data:
        candidates.append(Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TongYang Customs Platform")
    return [path for path in candidates if path.exists()]


def _ensure_shortcuts(exe: Path) -> list[dict[str, str]]:  # type: ignore[no-redef]
    exe = exe.resolve()
    rows: list[dict[str, str]] = []
    canonical_paths = _canonical_shortcut_paths()
    for shortcut_path in canonical_paths:
        previous = read_shortcut_target(shortcut_path)
        try:
            target = write_shortcut(shortcut_path, exe, working_dir=exe.parent, icon_path=exe)
            rows.append(
                {
                    "shortcut_path": str(shortcut_path),
                    "target_path": target or str(exe),
                    "previous_target_path": previous,
                    "action": "created_or_repaired",
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "shortcut_path": str(shortcut_path),
                    "target_path": "",
                    "previous_target_path": previous,
                    "action": f"error: {exc}",
                }
            )

    canonical_resolved = {str(path.resolve()).casefold() for path in canonical_paths if path.parent.exists()}
    taskbar_dir = _taskbar_pinned_dir()
    for directory in _shortcut_scan_dirs():
        is_taskbar = taskbar_dir is not None and directory.resolve() == taskbar_dir.resolve()
        for shortcut_path in directory.glob("*.lnk"):
            try:
                target = read_shortcut_target(shortcut_path)
                if not looks_related_shortcut(shortcut_path, target, APP_DISPLAY_NAME):
                    continue
                is_canonical = str(shortcut_path.resolve()).casefold() in canonical_resolved
                if not is_canonical and not is_taskbar:
                    shortcut_path.unlink(missing_ok=True)
                    rows.append(
                        {
                            "shortcut_path": str(shortcut_path),
                            "target_path": target,
                            "previous_target_path": target,
                            "action": "removed_duplicate_shortcut",
                        }
                    )
                elif target and Path(target).resolve() != exe:
                    before = target
                    repaired_target = write_shortcut(shortcut_path, exe, working_dir=exe.parent, icon_path=exe)
                    rows.append(
                        {
                            "shortcut_path": str(shortcut_path),
                            "target_path": repaired_target or str(exe),
                            "previous_target_path": before,
                            "action": "repaired_old_shortcut",
                        }
                    )
            except Exception as exc:
                rows.append(
                    {
                        "shortcut_path": str(shortcut_path),
                        "target_path": "",
                        "previous_target_path": "",
                        "action": f"error: {exc}",
                    }
                )
    return rows


def _cleanup_desktop_artifacts(installed_exe: Path) -> list[str]:
    removed: list[str] = []
    desktop_dirs = []
    user_profile = os.environ.get("USERPROFILE")
    public = os.environ.get("PUBLIC")
    appdata = os.environ.get("APPDATA")
    program_data = os.environ.get("ProgramData")
    if user_profile:
        desktop_dirs.append(Path(user_profile) / "Desktop")
    if public:
        desktop_dirs.append(Path(public) / "Desktop")
    if appdata:
        desktop_dirs.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TongYang Customs Platform")
        desktop_dirs.append(Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar")
    if program_data:
        desktop_dirs.append(Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TongYang Customs Platform")

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
        for pattern in DESKTOP_ARTIFACT_PATTERNS:
            for path in directory.glob(pattern):
                try:
                    if not path.is_file() or path.resolve() == installed_exe.resolve():
                        continue
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
    silent_update = "--silent-update" in sys.argv
    no_launch = "--no-launch" in sys.argv
    machine_install = "--machine" in sys.argv or "--program-files" in sys.argv
    wait_state = _wait_for_process_exit(_arg_value("--wait-pid")) if "--wait-pid" in sys.argv else {"pid": "", "status": "not_requested"}
    expected_version = _arg_value("--expected-version")
    expected_sha256 = _arg_value("--expected-sha256")
    if os.name == "nt" and machine_install and not _is_admin():
        if silent:
            return 5
        _relaunch_as_admin()
        return 0

    root = _install_root(machine_install)
    install_state = _copy_payload(root)
    verification = _verify_installed_update(
        root,
        Path(install_state["exe"]),
        expected_version=expected_version,
        expected_sha256=expected_sha256,
    )
    migration = _migrate_legacy_program_files_data(root, machine_install=machine_install)
    permissions = _grant_runtime_permissions(root)
    shortcuts = [] if silent_update else _ensure_shortcuts(Path(install_state["exe"]))
    desktop_cleanup = _cleanup_desktop_artifacts(Path(install_state["exe"]))
    state = {
        "status": "installed",
        "root": str(root),
        "exe": install_state["exe"],
        "permissions": permissions,
        "migration": migration,
        "shortcuts": shortcuts,
        "desktop_cleanup": desktop_cleanup,
        "silent": silent,
        "install_scope": "machine" if machine_install else "per_user",
        "wait_for_process": wait_state,
        "verification": verification,
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
            if "--silent" not in sys.argv and "--silent-update" not in sys.argv:
                ctypes.windll.user32.MessageBoxW(None, f"安裝失敗：{exc}", APP_DISPLAY_NAME, 0x10)
        except Exception:
            pass
        raise
