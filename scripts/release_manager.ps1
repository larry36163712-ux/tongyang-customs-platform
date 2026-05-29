param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][ValidateSet("dev", "stable")][string]$Channel,
    [Parameter(Mandatory = $true)][string]$NotesPath,
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$VersionPath,
    [Parameter(Mandatory = $true)][string]$ShaPath,
    [string]$AssetName = ""
)

$ErrorActionPreference = "Stop"

if (-not $env:GH_TOKEN) {
    throw "GH_TOKEN is required."
}
$OfficialExeName = "TongYangCustomsPlatform_Setup.exe"
if ([string]::IsNullOrWhiteSpace($AssetName)) {
    $AssetName = $OfficialExeName
}
if ($AssetName -ne $OfficialExeName) {
    throw "Executable release asset must be $OfficialExeName."
}
$script:ReleaseCreatedByThisRun = $false

trap {
    $errorMessage = $_.Exception.Message
    if ($script:ReleaseCreatedByThisRun) {
        Write-Host "Release governance cleanup: deleting failed release $Tag because verification did not complete."
        & gh release delete $Tag --repo $Repo --yes --cleanup-tag
    }
    throw $errorMessage
}

function Invoke-Gh {
    & gh @args
    if ($LASTEXITCODE -ne 0) {
        throw "gh command failed: gh $($args -join ' ')"
    }
}

function Get-ReleaseByTag {
    param([string]$ReleaseTag)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $json = & gh release view $ReleaseTag --repo $Repo --json databaseId,tagName,isPrerelease,url 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
            return $null
        }
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    try {
        return $json | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Convert-HttpContentToText {
    param($Content)
    if ($Content -is [byte[]]) {
        return [Text.Encoding]::UTF8.GetString($Content)
    }
    if ($Content -is [array]) {
        $bytes = [byte[]]@($Content | ForEach-Object { [byte]$_ })
        return [Text.Encoding]::UTF8.GetString($bytes)
    }
    return [string]$Content
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
            if ($name -match '^v\d+\.\d+\.\d+$') {
                throw "Cleanup safety refused to delete stable-looking tag during DEV cleanup: $name"
            }
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

function Remove-OldStableReleases {
    param([string]$KeepTag, [int]$KeepCount = 3)

    if ($Channel -ne "stable") {
        return
    }

    $releases = & gh release list --repo $Repo --limit 200 --json tagName,publishedAt,isPrerelease
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to list releases for stable cleanup."
    }

    $stableReleases = @($releases | ConvertFrom-Json | Where-Object {
        ([string]$_.tagName) -match '^v\d+\.\d+\.\d+$' -and -not $_.isPrerelease
    } | Sort-Object publishedAt -Descending)

    $latest = & gh api "repos/$Repo/releases/latest" | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Cleanup safety failed to resolve /releases/latest."
    }
    $latestStableTag = [string]$latest.tag_name
    if ($latest.prerelease -or $latestStableTag -notmatch '^v\d+\.\d+\.\d+$') {
        throw "Cleanup safety refused to run stable cleanup because /releases/latest is not stable: $latestStableTag"
    }

    $keep = @($stableReleases | Select-Object -First $KeepCount | ForEach-Object { [string]$_.tagName })
    if ($keep -notcontains $KeepTag) {
        $keep += $KeepTag
    }
    if ($keep -notcontains $latestStableTag) {
        $keep += $latestStableTag
    }

    foreach ($release in $stableReleases) {
        $name = [string]$release.tagName
        if ($keep -notcontains $name) {
            if ($name -eq $latestStableTag) {
                throw "Cleanup safety refused to delete latest stable release: $name"
            }
            Write-Host "Deleting old stable release and tag: $name"
            & gh release delete $name --repo $Repo --yes --cleanup-tag
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete old stable release: $name"
            }
        }
    }
}

function Assert-ReleaseAssets {
    param([string]$ReleaseTag)

    $release = & gh api "repos/$Repo/releases/tags/$ReleaseTag" | ConvertFrom-Json
    $required = @($OfficialExeName, "version.json", "SHA256.txt")
    $assetNames = @($release.assets | ForEach-Object { $_.name })
    foreach ($name in $required) {
        if ($assetNames -notcontains $name) {
            throw "Release $ReleaseTag missing required asset: $name. Current assets: $($assetNames -join ', ')"
        }
    }

    $manifestAsset = $release.assets | Where-Object { $_.name -eq "version.json" } | Select-Object -First 1
    $exeAsset = $release.assets | Where-Object { $_.name -eq $OfficialExeName } | Select-Object -First 1
    if (-not $manifestAsset.browser_download_url) {
        throw "version.json is missing browser_download_url."
    }
    if (-not $exeAsset.browser_download_url) {
        throw "$OfficialExeName is missing browser_download_url."
    }

    $manifestResponse = Invoke-WebRequest -Method Get -Uri $manifestAsset.browser_download_url -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing
    $manifestText = Convert-HttpContentToText $manifestResponse.Content
    $manifest = $manifestText | ConvertFrom-Json
    $expectedLatestExeUrl = if ($Channel -eq "stable") {
        "https://github.com/$Repo/releases/latest/download/$OfficialExeName"
    } else {
        "https://github.com/$Repo/releases/download/$ReleaseTag/$OfficialExeName"
    }
    $manifestExeUrl = if ($manifest.exe_url) { $manifest.exe_url } else { $manifest.download_url }
    if ($manifestExeUrl -ne $expectedLatestExeUrl) {
        throw "version.json exe_url must use latest URL. manifest=$manifestExeUrl expected=$expectedLatestExeUrl"
    }
    if (-not $manifest.version) { throw "version.json missing version." }
    if (-not $manifest.channel) { throw "version.json missing channel." }
    if (-not $manifest.release_notes) { throw "version.json missing release_notes." }
    if (-not $manifest.minimum_supported_version) { throw "version.json missing minimum_supported_version." }
    if (-not $manifest.build_id) { throw "version.json missing build_id." }
    if (-not $manifest.build_time) { throw "version.json missing build_time." }
    if (-not $manifest.sha256) { throw "version.json missing sha256." }
    if ($manifest.channel -ne $Channel) { throw "version.json channel mismatch. manifest=$($manifest.channel) expected=$Channel" }
    if ($manifest.sha256 -notmatch '^[0-9a-f]{64}$') { throw "version.json sha256 is invalid: $($manifest.sha256)" }
    if ($manifest.package_type -ne "installer") { throw "version.json package_type must be installer." }
    if ($manifest.app_sha256 -notmatch '^[0-9a-f]{64}$') { throw "version.json app_sha256 is invalid: $($manifest.app_sha256)" }
    if ($manifest.package_sha256 -notmatch '^[0-9a-f]{64}$') { throw "version.json package_sha256 is invalid: $($manifest.package_sha256)" }

    Invoke-WebRequest -Method Head -Uri $manifestAsset.browser_download_url -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing | Out-Null
    Invoke-WebRequest -Method Head -Uri $exeAsset.browser_download_url -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing | Out-Null
    Invoke-WebRequest -Method Head -Uri $manifestExeUrl -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing | Out-Null
    $shaAsset = $release.assets | Where-Object { $_.name -eq "SHA256.txt" } | Select-Object -First 1
    $shaResponse = Invoke-WebRequest -Method Get -Uri $shaAsset.browser_download_url -Headers @{"User-Agent" = "TongYangReleaseManager"} -UseBasicParsing
    $shaText = Convert-HttpContentToText $shaResponse.Content
    if ($shaText -notlike "*$($manifest.package_sha256)*") {
        throw "SHA256.txt does not contain installer package_sha256. package_sha256=$($manifest.package_sha256) sha_text=$shaText"
    }
    if ($shaText -notlike "*$OfficialExeName*") {
        throw "SHA256.txt does not reference $OfficialExeName. sha_text=$shaText"
    }
}

function Assert-LatestRelease {
    param([string]$ReleaseTag)

    $latest = & gh api "repos/$Repo/releases/latest" | ConvertFrom-Json
    if ($latest.tag_name -ne $ReleaseTag) {
        throw "/releases/latest points to '$($latest.tag_name)' instead of '$ReleaseTag'."
    }
}

function Assert-LocalReleaseFiles {
    foreach ($path in @($ExePath, $VersionPath, $ShaPath)) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Release preflight failed. Missing local asset: $path"
        }
    }
    if ((Split-Path -Leaf $ExePath) -ne $OfficialExeName) {
        throw "Release preflight failed. EXE must be named $OfficialExeName."
    }
    $manifest = Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($field in @("version", "channel", "exe_url", "release_notes", "minimum_supported_version", "build_id", "build_time", "sha256")) {
        if (-not $manifest.$field) { throw "Release preflight failed. version.json missing field: $field" }
    }
    if ($manifest.channel -ne $Channel) {
        throw "Release preflight failed. version.json channel mismatch: $($manifest.channel) != $Channel"
    }
    if ($manifest.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Release preflight failed. version.json sha256 is invalid."
    }
    if ($manifest.package_type -ne "installer") {
        throw "Release preflight failed. version.json package_type must be installer."
    }
    if ($manifest.app_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Release preflight failed. version.json app_sha256 is invalid."
    }
    if ($manifest.sha256 -ne $manifest.app_sha256) {
        throw "Release preflight failed. version.json sha256 must equal app_sha256 for SHA-first app comparison."
    }
    if ($manifest.package_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Release preflight failed. version.json package_sha256 is invalid."
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExePath).Hash.ToLower()
    if ($actualHash -ne $manifest.package_sha256) {
        throw "Release preflight failed. Installer package SHA256 mismatch. actual=$actualHash manifest=$($manifest.package_sha256)"
    }
    $shaText = Get-Content -LiteralPath $ShaPath -Raw -Encoding UTF8
    if ($shaText -notmatch [regex]::Escape($manifest.package_sha256)) {
        throw "Release preflight failed. SHA256.txt does not contain installer package_sha256."
    }
    if ($shaText -notmatch [regex]::Escape($OfficialExeName)) {
        throw "Release preflight failed. SHA256.txt does not reference $OfficialExeName."
    }
}

Assert-LocalReleaseFiles
$release = Get-ReleaseByTag $Tag
if ($release) {
    Invoke-Gh release edit $Tag --repo $Repo --title $Tag --notes-file $NotesPath
} else {
    if ($Channel -eq "dev") {
        Invoke-Gh release create $Tag --repo $Repo --title $Tag --notes-file $NotesPath --prerelease
    } else {
        Invoke-Gh release create $Tag --repo $Repo --title $Tag --notes-file $NotesPath --latest
    }
    $script:ReleaseCreatedByThisRun = $true
    $release = Get-ReleaseByTag $Tag
}

if (-not $release) {
    throw "Release was not created or found: $Tag"
}

if ($Channel -eq "dev") {
    Invoke-Gh api --method PATCH "repos/$Repo/releases/$($release.databaseId)" -F prerelease=true -F make_latest=false
} else {
    Invoke-Gh api --method PATCH "repos/$Repo/releases/$($release.databaseId)" -F prerelease=false -F make_latest=true
}

.\scripts\upload_release_asset.ps1 `
    -Repo $Repo `
    -Tag $Tag `
    -Path $ExePath `
    -AssetName $AssetName `
    -ContentType "application/octet-stream" | Out-Null

Invoke-Gh release upload $Tag $ShaPath $VersionPath --repo $Repo --clobber

Remove-OldDevReleases -KeepTag $Tag
Remove-OldStableReleases -KeepTag $Tag -KeepCount 3
Assert-ReleaseAssets -ReleaseTag $Tag
if ($Channel -eq "stable") {
    Assert-LatestRelease -ReleaseTag $Tag
}

Write-Host "Release manager completed."
Write-Host "Channel: $Channel"
Write-Host "Tag: $Tag"
Write-Host "Latest URL: https://github.com/$Repo/releases/tag/$Tag"
$script:ReleaseCreatedByThisRun = $false
