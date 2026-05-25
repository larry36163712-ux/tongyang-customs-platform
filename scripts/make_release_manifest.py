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
    args = parser.parse_args()

    exe_path = Path(args.exe)
    digest = hashlib.sha256(exe_path.read_bytes()).hexdigest()
    asset_name = args.asset_name or exe_path.name
    encoded_name = quote(asset_name)
    build_time = args.build_time or datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {
        "app_name": "通洋報關平台",
        "version": args.version.lstrip("v"),
        "download_url": f"https://github.com/{args.repo}/releases/latest/download/{encoded_name}",
        "sha256": digest,
        "channel": args.channel,
        "build_time": build_time,
        "notes": f"{args.channel.title()} release {args.tag}",
    }
    Path(args.output).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
