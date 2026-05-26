from __future__ import annotations

import hashlib
import subprocess
import tempfile
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))

from v2.core.updater import build_replace_script


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().lower()


def run_script(script: str, path: Path) -> int:
    path.write_text(script, encoding="utf-8")
    completed = subprocess.run(["cmd", "/c", str(path)], cwd=path.parent, check=False)
    return completed.returncode


def run_script_async(script: str, path: Path) -> subprocess.Popen:
    path.write_text(script, encoding="utf-8")
    return subprocess.Popen(["cmd", "/c", str(path)], cwd=path.parent)


def main() -> None:
    work_dir = Path(tempfile.gettempdir()) / "ai_customs_v2_updater_verify"
    work_dir.mkdir(parents=True, exist_ok=True)

    old_exe = Path("C:/Windows/System32/notepad.exe")
    if not old_exe.exists():
        old_exe = DIST / "TongYangCustomsPlatform.exe"
    new_exe = DIST / "TongYangCustomsPlatform.exe"
    if not new_exe.exists():
        raise RuntimeError("dist/TongYangCustomsPlatform.exe is required")

    current = work_dir / "TongYangCustomsPlatform.exe"
    update = work_dir / "AI_Customs_ERP_V2.update.exe"
    backup = work_dir / "通洋報關平台.rollback.exe"
    log = work_dir / "update-debug.log"
    local_manifest = work_dir / "version.json"
    pending_manifest = work_dir / "version.pending.json"
    script_path = work_dir / "update-success.bat"

    current.write_bytes(old_exe.read_bytes())
    update.write_bytes(new_exe.read_bytes())
    local_manifest.write_text('{"version":"1.0.0","sha256":"old","channel":"stable"}', encoding="utf-8")
    pending_manifest.write_text('{"version":"1.0.1","sha256":"new","channel":"stable"}', encoding="utf-8")
    expected = sha256(update)
    code = run_script(
        build_replace_script(
            current,
            update,
            backup,
            log,
            expected,
            old_pid=0,
            local_manifest_path=local_manifest,
            pending_manifest_path=pending_manifest,
            restart=False,
            cleanup=False,
        ),
        script_path,
    )
    if code != 0:
        raise RuntimeError(f"success replace script failed: {code}")
    if sha256(current) != expected:
        raise RuntimeError("current exe was not replaced by update exe")
    if '"version":"1.0.1"' not in local_manifest.read_text(encoding="utf-8").replace(" ", ""):
        raise RuntimeError("pending manifest was not finalized by replace script")
    if pending_manifest.exists():
        raise RuntimeError("pending manifest was not removed by replace script")

    rollback_current = work_dir / "rollback-current.exe"
    rollback_update = work_dir / "rollback-update.exe"
    rollback_backup = work_dir / "rollback-current.rollback.exe"
    rollback_script = work_dir / "update-rollback.bat"
    rollback_current.write_bytes(old_exe.read_bytes())
    rollback_original = sha256(rollback_current)
    rollback_update.write_text("not a valid update", encoding="utf-8")
    code = run_script(
        build_replace_script(
            rollback_current,
            rollback_update,
            rollback_backup,
            log,
            expected_sha256="0" * 64,
            old_pid=0,
            restart=False,
            cleanup=False,
        ),
        rollback_script,
    )
    if code == 0:
        raise RuntimeError("rollback script unexpectedly succeeded")
    if sha256(rollback_current) != rollback_original:
        raise RuntimeError("rollback did not restore original exe")

    running_current = work_dir / "running-current.exe"
    running_update = work_dir / "running-update.exe"
    running_backup = work_dir / "running-current.rollback.exe"
    running_script = work_dir / "update-running.bat"
    running_source = Path("C:/Windows/System32/notepad.exe")
    if not running_source.exists():
        running_source = old_exe
    running_current.write_bytes(running_source.read_bytes())
    running_update.write_bytes(new_exe.read_bytes())
    running_expected = sha256(running_update)
    old_process = subprocess.Popen([str(running_current)])
    time.sleep(1)
    updater_process = run_script_async(
        build_replace_script(
            running_current,
            running_update,
            running_backup,
            log,
            running_expected,
            old_pid=old_process.pid,
            restart=False,
            cleanup=False,
        ),
        running_script,
    )
    time.sleep(2)
    if old_process.poll() is None:
        old_process.terminate()
        try:
            old_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            old_process.kill()
    code = updater_process.wait(timeout=90)
    if code != 0:
        raise RuntimeError(f"running replace script failed: {code}")
    if old_process.poll() is None:
        old_process.terminate()
        raise RuntimeError("old process was not closed")
    if sha256(running_current) != running_expected:
        raise RuntimeError("running current exe was not replaced")

    log_text = log.read_text(encoding="utf-8", errors="ignore")
    for marker in (
        "old exe path=",
        "new exe path=",
        "old process exited",
        "replace success current=",
        "progress replace start",
        "progress replace completed",
    ):
        if marker not in log_text:
            raise RuntimeError(f"update progress log missing: {marker}")

    restart_current = work_dir / "restart-current.exe"
    restart_update = work_dir / "restart-update.exe"
    restart_backup = work_dir / "restart-current.rollback.exe"
    restart_script = work_dir / "update-restart.bat"
    restart_source = Path("C:/Windows/System32/notepad.exe")
    if not restart_source.exists():
        restart_source = new_exe
    restart_current.write_bytes(old_exe.read_bytes())
    restart_update.write_bytes(restart_source.read_bytes())
    restart_expected = sha256(restart_update)
    code = run_script(
        build_replace_script(
            restart_current,
            restart_update,
            restart_backup,
            log,
            restart_expected,
            old_pid=0,
            restart=True,
            cleanup=False,
        ),
        restart_script,
    )
    if code != 0:
        raise RuntimeError(f"restart replace script failed: {code}")
    if sha256(restart_current) != restart_expected:
        raise RuntimeError("restart current exe was not replaced")
    time.sleep(3)
    log_text = log.read_text(encoding="utf-8", errors="ignore")
    if "restart pid=" not in log_text:
        raise RuntimeError("updated exe restart was not logged")
    if "progress restart start" not in log_text:
        raise RuntimeError("restart progress was not logged")
    if "restart success" not in log_text:
        raise RuntimeError("restart success was not logged")
    tasklist = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {restart_current.name}"], capture_output=True, text=True)
    if restart_current.name in tasklist.stdout:
        subprocess.run(["taskkill", "/IM", restart_current.name, "/F"], check=False, capture_output=True)

    print(f"updater workflow ok: {work_dir}")


if __name__ == "__main__":
    main()
