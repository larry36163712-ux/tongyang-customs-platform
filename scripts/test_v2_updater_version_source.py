from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import v2.core.settings as settings_module
import v2.core.updater as updater_module
from v2.core.settings import UpdateSettings
from v2.core.updater import V2Updater


def main() -> None:
    work = Path(tempfile.gettempdir()) / "ai_customs_v2_version_source"
    config = work / "config"
    logs = work / "logs"
    config.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    local_manifest = config / "version.json"
    local_manifest.write_text(
        json.dumps(
            {
                "version": "1.0.2",
                "download_url": "local",
                "sha256": "abc",
                "channel": "stable",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    original_app_base_dir = settings_module.app_base_dir
    original_updater_local_manifest_path = updater_module.local_manifest_path
    original_updater_logs_dir = updater_module.logs_dir
    try:
        settings_module.app_base_dir = lambda: work  # type: ignore[assignment]
        updater_module.local_manifest_path = lambda: local_manifest  # type: ignore[assignment]
        updater_module.logs_dir = lambda: logs  # type: ignore[assignment]

        updater = V2Updater("1.0.0", UpdateSettings(enabled=True, channel="stable"))
        if updater.current_version != "1.0.2":
            raise RuntimeError(f"expected local manifest version, got {updater.current_version}")

        remote = updater_module.UpdateManifest("1.0.2", "local", "abc", "stable")
        updater._load_manifest = lambda: remote  # type: ignore[method-assign]
        result = updater.check()
        if result.status != "current":
            raise RuntimeError(f"expected current, got {result.status}")

        log_text = (logs / "update-debug.log").read_text(encoding="utf-8")
        required = [
            f"local_version_path={local_manifest}",
            "local_version=1.0.2",
            "remote_version=1.0.2",
            "compare result=0",
            "update result=current",
        ]
        missing = [item for item in required if item not in log_text]
        if missing:
            raise RuntimeError(f"debug log missing: {missing}")
    finally:
        settings_module.app_base_dir = original_app_base_dir  # type: ignore[assignment]
        updater_module.local_manifest_path = original_updater_local_manifest_path  # type: ignore[assignment]
        updater_module.logs_dir = original_updater_logs_dir  # type: ignore[assignment]

    print("updater version source ok")


if __name__ == "__main__":
    main()

