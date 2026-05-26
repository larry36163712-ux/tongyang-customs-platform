param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Tag,
    [string[]]$RequiredAssets = @("TongYangCustomsPlatform.exe", "version.json", "SHA256.txt"),
    [switch]$RequireLatest
)

$ErrorActionPreference = "Stop"

if (-not $env:GH_TOKEN) {
    throw "GH_TOKEN is required."
}

$headers = @{
    Authorization = "Bearer $env:GH_TOKEN"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "TongYangReleasePipeline"
}

$release = Invoke-RestMethod `
    -Method Get `
    -Uri "https://api.github.com/repos/$Repo/releases/tags/$Tag" `
    -Headers $headers

$assetNames = @($release.assets | ForEach-Object { $_.name })
foreach ($required in $RequiredAssets) {
    if ($assetNames -notcontains $required) {
        throw "Release $Tag is missing required asset: $required. Current assets: $($assetNames -join ', ')"
    }
}

$officialExeName = "TongYangCustomsPlatform.exe"
$exeAsset = $release.assets | Where-Object { $_.name -eq $officialExeName } | Select-Object -First 1
if (-not $exeAsset.browser_download_url) {
    throw "$officialExeName is missing browser_download_url."
}

if ($RequireLatest) {
    $latest = Invoke-RestMethod `
        -Method Get `
        -Uri "https://api.github.com/repos/$Repo/releases/latest" `
        -Headers $headers

    if ($latest.tag_name -ne $Tag) {
        throw "/releases/latest points to '$($latest.tag_name)' instead of required tag '$Tag'."
    }
}

[pscustomobject]@{
    tag = $release.tag_name
    prerelease = $release.prerelease
    latest = $release.make_latest
    assets = $assetNames
    download_url = $exeAsset.browser_download_url
}
