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
    original_settings_logs_dir = settings_module.logs_dir
    try:
        settings_module.app_base_dir = lambda: work  # type: ignore[assignment]
        updater_module.local_manifest_path = lambda: local_manifest  # type: ignore[assignment]
        updater_module.logs_dir = lambda: logs  # type: ignore[assignment]
        settings_module.logs_dir = lambda: logs  # type: ignore[assignment]

        updater = V2Updater("1.0.0", UpdateSettings(enabled=True, channel="stable"))
        if updater.current_version != "1.0.2":
            raise RuntimeError(f"expected local manifest version, got {updater.current_version}")

        remote = updater_module.UpdateManifest("1.0.2", "local", "abc", "stable")
        updater._load_manifest = lambda: remote  # type: ignore[method-assign]
        result = updater.check()
        if result.status != "current":
            raise RuntimeError(f"expected current, got {result.status}")
        if result.should_show_popup:
            raise RuntimeError("equal versions must not show update popup")

        log_text = (logs / "update-debug.log").read_text(encoding="utf-8")
        required = [
            f"local_version_path={local_manifest}",
            "local_version=1.0.2",
            "remote_version=1.0.2",
            "compare result=0 should_show_popup=False",
            "update result=current should_show_popup=False",
        ]
        missing = [item for item in required if item not in log_text]
        if missing:
            raise RuntimeError(f"debug log missing: {missing}")
        version_log = (logs / "version_debug.log").read_text(encoding="utf-8")
        for item in (
            f"version_json_path={local_manifest}",
            "local_version=1.0.2",
            "remote_version=1.0.2",
            "compare_result=0",
        ):
            if item not in version_log:
                raise RuntimeError(f"version debug log missing: {item}")

        newer = updater_module.UpdateManifest("1.0.3", "local", "abc", "stable")
        updater._load_manifest = lambda: newer  # type: ignore[method-assign]
        newer_result = updater.check()
        if not newer_result.should_show_popup:
            raise RuntimeError("remote newer version should show update popup")

        older = updater_module.UpdateManifest("1.0.1", "local", "abc", "stable")
        updater._load_manifest = lambda: older  # type: ignore[method-assign]
        older_result = updater.check()
        if older_result.should_show_popup:
            raise RuntimeError("remote older version must not show update popup")

        dev_called = False
        dev_updater = V2Updater("0.0.0", UpdateSettings(enabled=True, channel="dev"))

        def fail_load() -> updater_module.UpdateManifest:
            nonlocal dev_called
            dev_called = True
            raise RuntimeError("dev channel must not load remote manifest")

        dev_updater._load_manifest = fail_load  # type: ignore[method-assign]
        dev_result = dev_updater.check()
        if dev_called:
            raise RuntimeError("dev channel attempted remote manifest load")
        if dev_result.status != "current" or dev_result.should_show_popup:
            raise RuntimeError("source dev channel must be treated as current")

        original_frozen = getattr(sys, "frozen", None)
        sys.frozen = True  # type: ignore[attr-defined]
        try:
            frozen_dev_updater = V2Updater(
                "0.0.0",
                UpdateSettings(
                    enabled=True,
                    channel="dev",
                    dev_manifest_url="https://raw.githubusercontent.com/example/repo/main/config/dev_version.json",
                ),
            )
            frozen_dev_remote = updater_module.UpdateManifest("1.0.3", "local", "abc", "dev")
            frozen_dev_updater._load_manifest = lambda: frozen_dev_remote  # type: ignore[method-assign]
            frozen_dev_result = frozen_dev_updater.check()
            if frozen_dev_result.status != "available" or not frozen_dev_result.should_show_popup:
                raise RuntimeError("frozen dev channel must compare against dev manifest")
        finally:
            if original_frozen is None:
                delattr(sys, "frozen")
            else:
                sys.frozen = original_frozen  # type: ignore[attr-defined]
    finally:
        settings_module.app_base_dir = original_app_base_dir  # type: ignore[assignment]
        updater_module.local_manifest_path = original_updater_local_manifest_path  # type: ignore[assignment]
        updater_module.logs_dir = original_updater_logs_dir  # type: ignore[assignment]
        settings_module.logs_dir = original_settings_logs_dir  # type: ignore[assignment]

    print("updater version source ok")


if __name__ == "__main__":
    main()
