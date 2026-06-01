from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


OFFICIAL_INSTALLER_NAME = "TongYangCustomsPlatform_Setup.exe"
REQUIRED_ASSETS = (OFFICIAL_INSTALLER_NAME, "version.json", "SHA256.txt")
REQUIRED_MANIFEST_FIELDS = (
    "version",
    "channel",
    "exe_url",
    "release_notes",
    "minimum_supported_version",
    "build_id",
    "build_time",
    "sha256",
)
OFFICIAL_EXE_NAME = OFFICIAL_INSTALLER_NAME


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    body: bytes = b""


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify TongYang release governance contract.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--channel", required=True, choices=("stable", "dev"))
    parser.add_argument("--token", default="")
    parser.add_argument("--mode", default="published", choices=("published", "manifest"))
    parser.add_argument("--manifest", default="")
    parser.add_argument("--require-latest", action="store_true")
    args = parser.parse_args()

    if args.mode == "manifest":
        if not args.manifest:
            raise SystemExit("--manifest is required for manifest mode")
        manifest = json.loads(open(args.manifest, "r", encoding="utf-8-sig").read())
        validate_manifest_schema(manifest, args.repo, args.tag, args.channel)
        print("release contract manifest schema ok")
        return

    release = github_json(f"https://api.github.com/repos/{args.repo}/releases/tags/{args.tag}", args.token)
    validate_tag_policy(args.tag, args.channel)
    if release.get("draft"):
        raise SystemExit(f"release must not remain draft after verification: {args.tag}")
    expected_prerelease = args.channel == "dev"
    if bool(release.get("prerelease")) != expected_prerelease:
        raise SystemExit(f"release prerelease flag mismatch for {args.tag}")

    assets = {asset.get("name"): asset for asset in release.get("assets", [])}
    missing = [name for name in REQUIRED_ASSETS if name not in assets]
    if missing:
        raise SystemExit(f"release {args.tag} missing required asset(s): {', '.join(missing)}")
    unexpected = sorted(name for name in assets if name not in REQUIRED_ASSETS)
    if unexpected:
        raise SystemExit(f"release {args.tag} has unexpected asset(s): {', '.join(unexpected)}")

    manifest_url = assets["version.json"].get("browser_download_url", "")
    exe_url = assets[OFFICIAL_INSTALLER_NAME].get("browser_download_url", "")
    sha_url = assets["SHA256.txt"].get("browser_download_url", "")
    for label, url in (("version.json", manifest_url), (OFFICIAL_INSTALLER_NAME, exe_url), ("SHA256.txt", sha_url)):
        if not url:
            raise SystemExit(f"{label} missing browser_download_url")
        status = http_head_or_get(url).status
        if status < 200 or status >= 400:
            raise SystemExit(f"{label} URL returned HTTP {status}: {url}")

    manifest_response = http_get(manifest_url)
    manifest = json.loads(manifest_response.body.decode("utf-8-sig"))
    validate_manifest_schema(manifest, args.repo, args.tag, args.channel)

    if manifest["exe_url"] != expected_exe_url(args.repo, args.tag, args.channel):
        raise SystemExit(f"manifest exe_url is invalid: {manifest['exe_url']}")

    sha_text = http_get(sha_url).body.decode("utf-8-sig").strip()
    if manifest["package_sha256"] not in sha_text:
        raise SystemExit("SHA256.txt does not contain installer package_sha256")
    if OFFICIAL_INSTALLER_NAME not in sha_text:
        raise SystemExit(f"SHA256.txt does not reference {OFFICIAL_INSTALLER_NAME}")

    if args.require_latest:
        latest = github_json(f"https://api.github.com/repos/{args.repo}/releases/latest", args.token)
        if latest.get("tag_name") != args.tag:
            raise SystemExit(f"/releases/latest points to {latest.get('tag_name')} instead of {args.tag}")
        latest_manifest = f"https://github.com/{args.repo}/releases/latest/download/version.json"
        latest_exe = f"https://github.com/{args.repo}/releases/latest/download/{OFFICIAL_INSTALLER_NAME}"
        latest_sha = f"https://github.com/{args.repo}/releases/latest/download/SHA256.txt"
        for label, url in (("latest version.json", latest_manifest), ("latest exe", latest_exe), ("latest SHA256.txt", latest_sha)):
            status = http_head_or_get(url).status
            if status < 200 or status >= 400:
                raise SystemExit(f"{label} returned HTTP {status}: {url}")

    print(json.dumps({
        "tag": args.tag,
        "channel": args.channel,
        "assets": list(REQUIRED_ASSETS),
        "manifest_url": manifest_url,
        "exe_url": manifest["exe_url"],
        "app_sha256": manifest["app_sha256"],
        "package_sha256": manifest["package_sha256"],
        "contract": "ok",
    }, ensure_ascii=False, indent=2))


def validate_manifest_schema(manifest: dict, repo: str, tag: str, channel: str) -> None:
    validate_tag_policy(tag, channel)
    if not isinstance(manifest, dict):
        raise SystemExit("version.json must be a JSON object")
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if not str(manifest.get(field, "")).strip()]
    if missing:
        raise SystemExit(f"version.json missing required field(s): {', '.join(missing)}")
    if str(manifest["channel"]).strip() != channel:
        raise SystemExit(f"version.json channel mismatch: {manifest['channel']} != {channel}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest["sha256"]).strip().lower()):
        raise SystemExit("version.json sha256 must be a 64-character lowercase hex digest")
    if str(manifest["sha256"]).strip().lower() != str(manifest.get("app_sha256", "")).strip().lower():
        raise SystemExit("version.json sha256 must equal app_sha256 for SHA-first app comparison")
    if str(manifest.get("package_type", "")).strip() != "installer":
        raise SystemExit("version.json package_type must be installer")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("app_sha256", "")).strip().lower()):
        raise SystemExit("version.json app_sha256 must be a 64-character lowercase hex digest")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("package_sha256", "")).strip().lower()):
        raise SystemExit("version.json package_sha256 must be a 64-character lowercase hex digest")
    if not str(manifest["exe_url"]).endswith(f"/{OFFICIAL_INSTALLER_NAME}"):
        raise SystemExit(f"version.json exe_url must point to {OFFICIAL_INSTALLER_NAME}")
    if str(manifest["exe_url"]) != expected_exe_url(repo, tag, channel):
        raise SystemExit(
            "version.json exe_url violates channel policy: "
            f"{manifest['exe_url']} expected {expected_exe_url(repo, tag, channel)}"
        )


def validate_tag_policy(tag: str, channel: str) -> None:
    if channel == "stable":
        if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            raise SystemExit(f"stable release tag must look like v1.1.10. Received: {tag}")
        return
    if not re.fullmatch(r"v\d+\.\d+\.\d+-rc\.\d+", tag):
        raise SystemExit(f"RC/dev release tag must look like v1.1.10-rc.4. Received: {tag}")


def expected_exe_url(repo: str, tag: str, channel: str) -> str:
    if channel == "stable":
        return f"https://github.com/{repo}/releases/latest/download/{OFFICIAL_INSTALLER_NAME}"
    return f"https://github.com/{repo}/releases/download/{tag}/{OFFICIAL_INSTALLER_NAME}"


def github_json(url: str, token: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "TongYangReleaseGovernance"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return json.loads(http_get(url, headers=headers).body.decode("utf-8"))


def http_get(url: str, headers: dict[str, str] | None = None) -> HttpResult:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "TongYangReleaseGovernance"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return HttpResult(url, response.status, response.read())
    except urllib.error.HTTPError as exc:
        return HttpResult(url, exc.code, exc.read())


def http_head_or_get(url: str) -> HttpResult:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "TongYangReleaseGovernance"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return HttpResult(url, response.status)
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 405}:
            return http_get(url)
        return HttpResult(url, exc.code, exc.read())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"release contract failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
