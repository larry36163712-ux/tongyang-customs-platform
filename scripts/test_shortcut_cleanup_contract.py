from __future__ import annotations

import os
import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.core.deployment import cleanup_desktop_artifacts


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def main() -> int:
    original_userprofile = os.environ.get("USERPROFILE")
    original_public = os.environ.get("PUBLIC")
    original_appdata = os.environ.get("APPDATA")
    original_programdata = os.environ.get("ProgramData")
    try:
        with tempfile.TemporaryDirectory(prefix="ty-shortcut-cleanup-") as tmp:
            root = Path(tmp)
            user_profile = root / "User"
            public = root / "Public"
            appdata = user_profile / "AppData" / "Roaming"
            program_data = root / "ProgramData"
            desktop = user_profile / "Desktop"
            public_desktop = public / "Desktop"
            start_menu = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TongYang Customs Platform"
            public_start_menu = program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TongYang Customs Platform"
            taskbar = appdata / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"
            install_exe = user_profile / "AppData" / "Local" / "TongYangCustomsPlatform" / "TongYangCustomsPlatform.exe"
            _touch(install_exe)

            os.environ["USERPROFILE"] = str(user_profile)
            os.environ["PUBLIC"] = str(public)
            os.environ["APPDATA"] = str(appdata)
            os.environ["ProgramData"] = str(program_data)

            forbidden = [
                desktop / "TongYangCustomsPlatform.exe",
                desktop / "TongYangCustomsPlatform_Setup.exe",
                desktop / "updater.exe",
                desktop / "update.bat",
                desktop / "AI_Customs_ERP_V2_update.ps1",
                desktop / "version.json",
                desktop / "SHA256.txt",
                desktop / "TongYangCustomsPlatform.update.exe",
                desktop / "TongYangCustomsPlatform.temp.exe",
                desktop / "TongYangCustomsPlatform.tmp.exe",
                desktop / "TongYangCustomsPlatform.new.exe",
                public_desktop / "TongYangCustomsPlatform.exe",
                public_desktop / "TongYangCustomsPlatform_Setup.exe",
                public_desktop / "updater.exe",
                public_desktop / "update.bat",
                public_desktop / "version.json",
                public_desktop / "SHA256.txt",
                start_menu / "TongYangCustomsPlatform.exe",
                start_menu / "TongYangCustomsPlatform_Setup.exe",
                start_menu / "version.json",
                start_menu / "SHA256.txt",
                start_menu / "TongYangCustomsPlatform_setup_update.ps1",
                public_start_menu / "TongYangCustomsPlatform.exe",
                public_start_menu / "TongYangCustomsPlatform_Setup.exe",
                public_start_menu / "version.json",
                taskbar / "TongYangCustomsPlatform_Setup.update.exe",
                taskbar / "AI_Customs_ERP_V2_update.ps1",
            ]
            for path in forbidden:
                _touch(path)

            unrelated = desktop / "客戶文件.pdf"
            _touch(unrelated)

            removed = cleanup_desktop_artifacts(install_exe)
            missing_removals = [path for path in forbidden if path.exists()]
            if missing_removals:
                raise AssertionError(f"desktop artifacts were not removed: {missing_removals}")
            if not unrelated.exists():
                raise AssertionError("unrelated desktop file was removed")
            if len(removed) < len(forbidden):
                raise AssertionError(f"expected at least {len(forbidden)} removals, got {len(removed)}")
    finally:
        if original_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = original_userprofile
        if original_public is None:
            os.environ.pop("PUBLIC", None)
        else:
            os.environ["PUBLIC"] = original_public
        if original_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = original_appdata
        if original_programdata is None:
            os.environ.pop("ProgramData", None)
        else:
            os.environ["ProgramData"] = original_programdata
    print("shortcut cleanup contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
