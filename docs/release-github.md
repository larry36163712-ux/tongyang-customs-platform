# GitHub Release Workflow

Repository:

https://github.com/larry36163712-ux/tongyang-customs-platform

## Release Asset Contract

The GitHub Release installer asset must be named exactly:

`TongYangCustomsPlatform_Setup.exe`

The release must also contain:

- `version.json`
- `SHA256.txt`

These three files are the only allowed release assets.

## Stable Channel

Stable releases use tags like:

`v1.1.10`

Stable releases are normal GitHub releases and may be marked as Latest.

Stable updater discovery uses:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json`

Stable `version.json` must point `exe_url` and `download_url` to:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/TongYangCustomsPlatform_Setup.exe`

## Internal RC Channel

Internal RC releases use tags like:

`v1.1.10-rc.4`

RC releases are GitHub pre-releases and must not become Latest.

Dev/Internal updater discovery uses the repository raw manifest:

`https://raw.githubusercontent.com/larry36163712-ux/tongyang-customs-platform/main/config/dev_version.json`

`dev_version.json` must point to the tag-specific RC installer:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/download/v1.1.10-rc.4/TongYangCustomsPlatform_Setup.exe`

## Required Verification

Before a release is considered usable:

1. `scripts/release_contract.py --mode published` must pass.
2. `package_sha256` must match the downloaded setup installer.
3. Stable release assets must be available through `/releases/latest/download/`.
4. RC release assets must be available through `/releases/download/<tag>/`.
5. GitHub API must report RC releases as `prerelease: true`.
6. GitHub API must report Stable releases as `prerelease: false`.
