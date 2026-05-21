# GitHub Release Workflow

Repository:

https://github.com/larry36163712-ux/tongyang-customs-platform

## DEV Release Asset Contract

The Windows executable release asset must be named exactly:

`通洋報關平台.exe`

Do not use generated placeholder names or old executable aliases.

Generated placeholder, old alias, or romanized executable names are forbidden.

The release manifest must point to the same asset name:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/download/<tag>/%E9%80%9A%E6%B4%8B%E5%A0%B1%E9%97%9C%E5%B9%B3%E5%8F%B0.exe`

## Required Assets

Every DEV prerelease must include:

- `通洋報關平台.exe`
- `version.json`
- `SHA256.txt`

The upload pipeline must fail if GitHub returns any executable asset name other than `通洋報關平台.exe`.

## Stable Release

Stable releases are separate from DEV releases. DEV prereleases must not be marked as latest and must not overwrite stable release assets.
