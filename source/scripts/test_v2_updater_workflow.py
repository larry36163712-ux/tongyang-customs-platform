from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.core.updater import UpdateManifest, V2Updater, _hidden_process_flags  # noqa: E402
from v2.core.settings import UpdateSettings  # noqa: E402


def main() -> None:
    import v2.core.updater as updater_module

    calls: list[dict[str, object]] = []
    original_popen = updater_module.subprocess.Popen
    original_exit = updater_module.os._exit
    had_frozen = hasattr(updater_module.sys, "frozen")
    original_frozen = getattr(updater_module.sys, "frozen", None)

    def fake_popen(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": command, "kwargs": kwargs})

        class FakeProcess:
            pid = 4321

        return FakeProcess()

    try:
        updater_module.subprocess.Popen = fake_popen  # type: ignore[assignment]
        updater_module.os._exit = lambda code: (_ for _ in ()).throw(SystemExit(code))  # type: ignore[assignment]
        setattr(updater_module.sys, "frozen", True)

        setup = Path("C:/Temp/TongYangCustomsPlatform_Setup.update.exe")
        manifest = UpdateManifest(
            version="v1.1.10-rc.8",
            download_url="https://example.invalid/TongYangCustomsPlatform_Setup.exe",
            sha256="a" * 64,
            channel="dev",
            package_type="installer",
            package_sha256="b" * 64,
        )
        updater = V2Updater("v1.1.10-rc.7", UpdateSettings(enabled=True, channel="dev"))
        try:
            updater._schedule_installer(setup, manifest)
        except SystemExit as exc:
            if exc.code != 0:
                raise RuntimeError(f"schedule installer exited with unexpected code: {exc.code}")

        if len(calls) != 1:
            raise RuntimeError(f"expected one Setup process, got {len(calls)}")
        command = [str(part) for part in calls[0]["command"]]  # type: ignore[index]
        command_line = " ".join(command).casefold()
        for forbidden in ("cmd.exe", "cmd /c", "findstr", "tasklist", "powershell", ".bat", ".ps1"):
            if forbidden in command_line:
                raise RuntimeError(f"installer update command contains forbidden token: {forbidden}")
        for required in (
            str(setup),
            "--silent-update",
            "--wait-pid",
            "--expected-version",
            manifest.version,
            "--expected-sha256",
            manifest.sha256,
        ):
            if required not in command:
                raise RuntimeError(f"installer update command missing: {required}")

        flags = int(calls[0]["kwargs"].get("creationflags", 0))  # type: ignore[index, union-attr]
        if os.name == "nt" and (flags & _hidden_process_flags()) != _hidden_process_flags():
            raise RuntimeError("installer update process is not using hidden no-console flags")

        cwd = calls[0]["kwargs"].get("cwd")  # type: ignore[index, union-attr]
        if str(cwd) != str(setup.parent):
            raise RuntimeError("installer update process must run from updater temp directory")

        print("updater workflow ok: installer update uses hidden direct Setup process")
    finally:
        updater_module.subprocess.Popen = original_popen  # type: ignore[assignment]
        updater_module.os._exit = original_exit  # type: ignore[assignment]
        if had_frozen:
            setattr(updater_module.sys, "frozen", original_frozen)
        else:
            delattr(updater_module.sys, "frozen")


if __name__ == "__main__":
    main()
