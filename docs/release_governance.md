# Release Governance System

This project treats updater compatibility as a release contract. UI, parser,
OCR, intake, and audit changes must not change release asset names, manifest
fields, or channel routing.

## Release Contract

Every published release must contain:

- `TongYangCustomsPlatform.exe`
- `version.json`
- `SHA256.txt`

`version.json` must contain these stable fields:

```json
{
  "version": "...",
  "channel": "...",
  "exe_url": "...",
  "release_notes": "...",
  "minimum_supported_version": "...",
  "build_id": "...",
  "build_time": "...",
  "sha256": "..."
}
```

Field names are part of the updater contract and must not be renamed.

## Channel Policy

Stable updater reads:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json`

Stable `exe_url` must use:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/TongYangCustomsPlatform.exe`

DEV updater reads `config/dev_version.json` from the repository raw URL. DEV
release assets are tag-specific and must not move `/releases/latest`.

## Verification

`scripts/release_contract.py` verifies:

- required assets exist
- asset URLs return HTTP 200
- `version.json` schema is valid
- `exe_url` follows the channel policy
- `sha256` exists and is 64 lowercase hex characters
- `SHA256.txt` contains the same hash and the official executable name
- stable `/releases/latest` points to the expected stable tag

Release workflows must fail if any check fails.

## Cleanup Safety

Cleanup must verify stable latest before deleting anything. It must never delete:

- `/releases/latest`
- active stable release
- current updater target
- required assets from a retained release

DEV cleanup may delete old DEV releases and tags only. Stable cleanup keeps the
latest stable release plus recent stable rollback versions.

## Rollback

Stable releases keep recent history so a broken stable can be replaced by
promoting a previous stable tag. DEV releases are not rollback targets for
company computers.
