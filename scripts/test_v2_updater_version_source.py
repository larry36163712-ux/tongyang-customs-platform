from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import v2.core.settings as settings_module
import v2.core.updater as updater_module
from v2.core.settings import UpdateSettings
from v2.core.updater import V2Updater, _compare_versions


def main() -> None:
    work = Path(tempfile.gettempdir()) / "ai_customs_v2_version_source"
    if work.exists():
        shutil.rmtree(work)
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
        updater_log_text = (logs / "updater.log").read_text(encoding="utf-8")
        required = [
            "local exe sha matches remote; forcing current state and syncing manifest",
            "local_version=1.0.2",
            "remote_version=1.0.2",
            "local manifest synced",
            "update result=current sha_match should_show_popup=False",
            "local_sha256=abc remote_sha256=abc",
        ]
        missing = [item for item in required if item not in log_text]
        if missing:
            raise RuntimeError(f"debug log missing: {missing}")
        missing = [item for item in required if item not in updater_log_text]
        if missing:
            raise RuntimeError(f"updater log missing: {missing}")
        version_log = (logs / "version_debug.log").read_text(encoding="utf-8")
        for item in (
            f"version_json_path={local_manifest}",
            "local_version=1.0.2",
            "remote_version=1.0.2",
            "compare_result=0",
            "sha_match=True",
            "should_show_popup=False",
        ):
            if item not in version_log:
                raise RuntimeError(f"version debug log missing: {item}")

        newer = updater_module.UpdateManifest("1.0.3", "local", "abc", "stable")
        updater._load_manifest = lambda: newer  # type: ignore[method-assign]
        newer_result = updater.check()
        if newer_result.should_show_popup:
            raise RuntimeError("remote newer version with same local sha must not show update popup")
        finalized_same_sha = json.loads(local_manifest.read_text(encoding="utf-8"))
        if finalized_same_sha["version"] != "1.0.3":
            raise RuntimeError("same sha newer version should sync local manifest")

        older = updater_module.UpdateManifest("1.0.1", "local", "abc", "stable")
        updater._load_manifest = lambda: older  # type: ignore[method-assign]
        older_result = updater.check()
        if older_result.should_show_popup:
            raise RuntimeError("remote older version must not show update popup")

        local_manifest.write_text(
            json.dumps({"version": "1.0.2", "download_url": "local", "sha256": "abc", "channel": "stable"}, indent=2),
            encoding="utf-8",
        )
        same_version_new_sha = updater_module.UpdateManifest("1.0.2", "local", "def", "stable")
        updater._load_manifest = lambda: same_version_new_sha  # type: ignore[method-assign]
        same_version_new_sha_result = updater.check()
        if same_version_new_sha_result.status != "available" or not same_version_new_sha_result.should_show_popup:
            raise RuntimeError("same version with different remote sha256 should update")

        local_manifest.write_text(
            json.dumps({"version": "1.0.2", "download_url": "local", "sha256": "def", "channel": "stable"}, indent=2),
            encoding="utf-8",
        )
        pending = config / "version.pending.json"
        pending.write_text(
            json.dumps(
                {
                    "version": "1.0.3",
                    "download_url": "local",
                    "sha256": "def",
                    "channel": "stable",
                    "build_id": "1.0.3-def",
                    "build_time": "2026-05-26T00:00:00+00:00",
                    "exe_url": "local",
                    "release_notes": "test",
                    "minimum_supported_version": "1.0.0",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        updater._load_manifest = lambda: updater_module.UpdateManifest("1.0.3", "local", "def", "stable")  # type: ignore[method-assign]
        pending_result = updater.check()
        if pending_result.status != "current" or pending_result.should_show_popup:
            raise RuntimeError("pending finalized update must not show update popup after restart")
        finalized = json.loads(local_manifest.read_text(encoding="utf-8"))
        if finalized["version"] != "1.0.3":
            raise RuntimeError("pending manifest was not finalized into local version.json")
        if pending.exists():
            raise RuntimeError("pending manifest was not cleaned up")

        if _compare_versions("v1.2.3", "1.2.3") != 0:
            raise RuntimeError("v prefix must be normalized")
        if _compare_versions("refs/tags/v1.2.4", "1.2.3") <= 0:
            raise RuntimeError("release tag version normalization failed")

        debug = updater.debug_state()
        for key in ("executable_path", "local_version", "local_sha", "remote_version", "remote_sha", "pending_sha", "update_state", "finalize_state", "cache_state"):
            if key not in debug:
                raise RuntimeError(f"debug state missing: {key}")

        dirty_files = [
            config / "pending_update.json",
            config / "update_state.json",
            config / "local_manifest.json",
            config / "updater_cache.json",
            config / "sha_cache.json",
            config / "stale_sha_cache.json",
        ]
        for path in dirty_files:
            path.write_text("dirty", encoding="utf-8")
        cache_dir = config / "updater_cache"
        temp_update_dir = config / "temp_update"
        cache_dir.mkdir(exist_ok=True)
        temp_update_dir.mkdir(exist_ok=True)
        (cache_dir / "github.json").write_text("dirty", encoding="utf-8")
        (temp_update_dir / "old.exe").write_text("dirty", encoding="utf-8")
        updater._load_manifest = lambda: updater_module.UpdateManifest("1.0.3", "local", "def", "stable")  # type: ignore[method-assign]
        reset_state = updater.reset_state()
        if reset_state.get("update_state") != "current_sha_match":
            raise RuntimeError(f"reset should be current by sha, got {reset_state.get('update_state')}")
        if reset_state.get("local_version") != "1.0.3" or reset_state.get("local_sha") != "def":
            raise RuntimeError("reset did not rebuild a clean synced manifest")
        for path in dirty_files:
            if path.exists():
                raise RuntimeError(f"dirty updater state was not removed: {path}")
        if cache_dir.exists() or temp_update_dir.exists():
            raise RuntimeError("dirty updater cache directories were not removed")

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
                    stable_manifest_url="https://github.com/example/repo/releases/latest/download/version.json",
                ),
            )
            frozen_dev_remote = updater_module.UpdateManifest("1.0.3", "local", "abc", "dev")
            frozen_dev_updater._load_manifest = lambda: frozen_dev_remote  # type: ignore[method-assign]
            frozen_dev_result = frozen_dev_updater.check()
            if frozen_dev_result.status != "available" or not frozen_dev_result.should_show_popup:
                raise RuntimeError("frozen dev channel must compare against latest manifest")
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
