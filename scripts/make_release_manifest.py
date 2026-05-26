from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--asset-name", default="")
    parser.add_argument("--output", default="version.json")
    parser.add_argument("--channel", default="stable", choices=("stable", "dev"))
    parser.add_argument("--build-time", default="")
    parser.add_argument("--release-notes", default="")
    parser.add_argument("--minimum-supported-version", default="")
    args = parser.parse_args()

    exe_path = Path(args.exe)
    digest = hashlib.sha256(exe_path.read_bytes()).hexdigest()
    asset_name = args.asset_name or exe_path.name
    encoded_name = quote(asset_name)
    build_time = args.build_time or datetime.now(timezone.utc).isoformat(timespec="seconds")
    build_id = f"{args.version.lstrip('v')}-{digest[:12]}"
    release_id = args.tag
    exe_url = f"https://github.com/{args.repo}/releases/latest/download/{encoded_name}"
    release_notes = args.release_notes or f"{args.channel.title()} release {args.tag}"
    minimum_supported_version = args.minimum_supported_version or args.version.lstrip("v")
    manifest = {
        "app_name": "通洋報關平台",
        "version": args.version.lstrip("v"),
        "channel": args.channel,
        "exe_url": exe_url,
        "download_url": exe_url,
        "sha256": digest,
        "build_id": build_id,
        "build_time": build_time,
        "release_id": release_id,
        "release_notes": release_notes,
        "notes": release_notes,
        "minimum_supported_version": minimum_supported_version,
    }
    Path(args.output).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
