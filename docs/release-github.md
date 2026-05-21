# GitHub Release Workflow

Repository:

https://github.com/larry36163712-ux/tongyang-customs-platform

## DEV Release Asset Contract

The GitHub Release executable asset must be named exactly:

`TongYangCustomsPlatform.exe`

This only affects the GitHub Release asset filename. UI text, window title, product name, and company name remain `通洋報關平台`.

Do not use generated placeholder names or old executable aliases.

The release manifest must point to the same asset name:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/download/<tag>/TongYangCustomsPlatform.exe`

## Required Assets

Every DEV prerelease must include:

- `TongYangCustomsPlatform.exe`
- `version.json`
- `SHA256.txt`

The upload pipeline must fail if GitHub returns any executable asset name other than `TongYangCustomsPlatform.exe`.

## Stable Release

Stable releases are separate from DEV releases. DEV prereleases must not be marked as latest and must not overwrite stable release assets.
