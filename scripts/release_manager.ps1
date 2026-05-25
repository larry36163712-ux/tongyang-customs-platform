param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][ValidateSet("dev", "stable")][string]$Channel,
    [Parameter(Mandatory = $true)][string]$NotesPath,
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$VersionPath,
    [Parameter(Mandatory = $true)][string]$ShaPath,
    [string]$AssetName = "TongYangCustomsPlatform.exe"
)

$ErrorActionPreference = "Stop"

if (-not $env:GH_TOKEN) {
    throw "GH_TOKEN is required."
}
if ($AssetName -ne "TongYangCustomsPlatform.exe") {
    throw "Executable release asset must be TongYangCustomsPlatform.exe."
}

function Invoke-Gh {
    & gh @args
    if ($LASTEXITCODE -ne 0) {
        throw "gh command failed: gh $($args -join ' ')"
    }
}

function Get-ReleaseByTag {
    param([string]$ReleaseTag)
    $json = & gh release view $ReleaseTag --repo $Repo --json databaseId,tagName,isPrerelease,url 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
        return $null
    }
    return $json | ConvertFrom-Json
}

function Remove-OldDevReleases {
    param([string]$KeepTag)

    if ($Channel -ne "dev") {
        return
    }

    $releases = & gh release list --repo $Repo --limit 200 --json tagName,isDraft,isPrerelease
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to list releases for DEV cleanup."
    }

    foreach ($release in ($releases | ConvertFrom-Json)) {
        $name = [string]$release.tagName
        $isDevTag = $name -match '^DEV-' -or $name -match '^v\d+\.\d+\.\d+-dev(\.\d+)?$'
        if ($isDevTag -and $name -ne $KeepTag) {
            Write-Host "Deleting old DEV release: $name"
            & gh release delete $name --repo $Repo --yes --cleanup-tag
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete old DEV release: $name"
            }
        }
    }

    $refs = & gh api "repos/$Repo/git/matching-refs/tags" --jq '.[].ref'
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to list git tags for DEV cleanup."
    }

    foreach ($ref in $refs) {
        $name = $ref -replace '^refs/tags/', ''
        $isDevTag = $name -match '^DEV-' -or $name -match '^v\d+\.\d+\.\d+-dev(\.\d+)?$'
        if ($isDevTag -and $name -ne $KeepTag) {
            Write-Host "Deleting old DEV tag: $name"
            & gh api --method DELETE "repos/$Repo/git/refs/tags/$name" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete old DEV tag: $name"
            }
        }
    }
}

function Assert-ReleaseAssets {
    param([string]$ReleaseTag)

    $release = & gh api "repos/$Repo/releases/tags/$ReleaseTag" | ConvertFrom-Json
    $required = @("TongYangCustomsPlatform.exe", "version.json", "SHA256.txt")
    $assetNames = @($release.assets | ForEach-Object { $_.name })
    foreach ($name in $required) {
        if ($assetNames -notcontains $name) {
            throw "Release $ReleaseTag missing required asset: $name. Current assets: $($assetNames -join ', ')"
        }
    }

    $manifestAsset = $release.assets | Where-Object { $_.name -eq "version.json" } | Select-Object -First 1
    $exeAsset = $release.assets | Where-Object { $_.name -eq "TongYangCustomsPlatform.exe" } | Select-Object -First 1
    if (-not $manifestAsset.browser_download_url) {
        throw "version.json is missing browser_download_url."
    }
    if (-not $exeAsset.browser_download_url) {
        throw "TongYangCustomsPlatform.exe is missing browser_download_url."
    }

    $manifest = Invoke-RestMethod -Uri $manifestAsset.browser_download_url -Headers @{"User-Agent" = "TongYangReleaseManager"}
    $expectedLatestExeUrl = "https://github.com/$Repo/releases/latest/download/TongYangCustomsPlatform.exe"
    $manifestExeUrl = if ($manifest.exe_url) { $manifest.exe_url } else { $manifest.download_url }
    if ($manifestExeUrl -ne $expectedLatestExeUrl) {
        throw "version.json exe_url must use latest URL. manifest=$manifestExeUrl expected=$expectedLatestExeUrl"
    }
    if (-not $manifest.version) { throw "version.json missing version." }
    if (-not $manifest.channel) { throw "version.json missing channel." }
    if (-not $manifest.release_notes) { throw "version.json missing release_notes." }
    if (-not $manifest.minimum_supported_version) { throw "version.json missing minimum_supported_version." }

    Invoke-WebRequest -Method Head -Uri $manifestAsset.browser_download_url -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing | Out-Null
    Invoke-WebRequest -Method Head -Uri $exeAsset.browser_download_url -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing | Out-Null
    Invoke-WebRequest -Method Head -Uri $manifestExeUrl -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing | Out-Null
}

function Assert-LatestRelease {
    param([string]$ReleaseTag)

    $latest = & gh api "repos/$Repo/releases/latest" | ConvertFrom-Json
    if ($latest.tag_name -ne $ReleaseTag) {
        throw "/releases/latest points to '$($latest.tag_name)' instead of '$ReleaseTag'."
    }
}

$release = Get-ReleaseByTag $Tag
if ($release) {
    Invoke-Gh release edit $Tag --repo $Repo --title $Tag --notes-file $NotesPath --latest
} else {
    Invoke-Gh release create $Tag --repo $Repo --title $Tag --notes-file $NotesPath --latest
}

.\scripts\upload_release_asset.ps1 `
    -Repo $Repo `
    -Tag $Tag `
    -Path $ExePath `
    -AssetName $AssetName `
    -ContentType "application/octet-stream" | Out-Null

Invoke-Gh release upload $Tag $ShaPath $VersionPath --repo $Repo --clobber

Remove-OldDevReleases -KeepTag $Tag
Assert-ReleaseAssets -ReleaseTag $Tag
Assert-LatestRelease -ReleaseTag $Tag

Write-Host "Release manager completed."
Write-Host "Channel: $Channel"
Write-Host "Tag: $Tag"
Write-Host "Latest URL: https://github.com/$Repo/releases/tag/$Tag"
