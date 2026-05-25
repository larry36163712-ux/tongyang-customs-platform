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

Every DEV release must include:

- `TongYangCustomsPlatform.exe`
- `version.json`
- `SHA256.txt`

The upload pipeline must fail if GitHub returns any executable asset name other than `TongYangCustomsPlatform.exe`.

## DEV and Stable Latest Rules

Stable releases are separate from DEV releases.

DEV keeps exactly one active release: `vX.X.X-dev`. The Release Manager updates that release, marks it as latest, uploads the required assets, and deletes older DEV releases/tags such as `DEV-*` and `vX.X.X-dev.N`.

Stable releases are normal releases, use stable `vX.X.X` tags, and may keep historical versions.

Updater discovery must use:

`https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json`
