# Release Governance System

This project treats updater compatibility as a release contract. UI, parser,
OCR, intake, audit, and feedback changes must not change release asset names,
manifest fields, or channel routing.

## Naming Policy

Stable releases use plain semantic tags:

- `v1.1.10`
- `v1.1.11`

Internal RC releases use numbered pre-release tags:

- `v1.1.10-rc.1`
- `v1.1.10-rc.2`
- `v1.1.10-rc.3`
- `v1.1.10-rc.4`

Old `-dev` release names are retired for production distribution.

## Asset Contract

Every published Stable or RC release must contain exactly these assets:

- `TongYangCustomsPlatform_Setup.exe`
- `version.json`
- `SHA256.txt`

No other release assets are allowed. In particular, do not publish naked app
EXEs, update scripts, debug logs, temporary EXEs, cache files, or test data.

## Manifest Contract

`version.json` and `dev_version.json` must contain these fields:

```json
{
  "version": "...",
  "channel": "...",
  "exe_url": "...",
  "download_url": "...",
  "release_notes": "...",
  "minimum_supported_version": "...",
  "build_id": "...",
  "build_time": "...",
  "sha256": "...",
  "app_sha256": "...",
  "package_type": "installer",
  "package_sha256": "..."
}
```

`sha256` is the installed app EXE hash and must equal `app_sha256`.
`package_sha256` is the installer package hash and must match
`TongYangCustomsPlatform_Setup.exe`.

Field names are part of the updater contract and must not be renamed.

## Channel Policy

Stable channel reads only:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json`

Stable `exe_url` must use:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/TongYangCustomsPlatform_Setup.exe`

Dev/Internal RC channel reads only:

`https://raw.githubusercontent.com/larry36163712-ux/tongyang-customs-platform/main/config/dev_version.json`

RC `exe_url` must be tag-specific:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/download/vX.Y.Z-rc.N/TongYangCustomsPlatform_Setup.exe`

RC releases must be GitHub pre-releases and must not become `/releases/latest`.
Stable releases must not be pre-releases and may become `/releases/latest`.

## Verification

`scripts/release_contract.py` verifies:

- release tag naming policy
- pre-release flag matches the channel
- release is not draft
- required assets exist
- no unexpected assets exist
- asset URLs return HTTP 2xx
- `version.json` schema is valid
- `exe_url` follows the channel policy
- `sha256` and `app_sha256` match
- `package_sha256` is a 64-character lowercase hex digest
- `SHA256.txt` contains `package_sha256`
- stable `/releases/latest` points to the expected stable tag when requested

Release workflows must fail if any check fails.

## Cleanup Safety

Cleanup must verify stable latest before deleting anything. It must never delete:

- `/releases/latest`
- active stable release
- current updater target
- required assets from a retained release

RC cleanup may delete only retired RC or legacy DEV releases when explicitly
requested by the release manager. Stable cleanup keeps the latest stable release
plus recent stable rollback versions.

## Rollback

Stable releases keep recent history so a broken stable can be replaced by
promoting a previous stable tag. RC releases are internal validation targets and
are not rollback targets for company computers on the stable channel.
