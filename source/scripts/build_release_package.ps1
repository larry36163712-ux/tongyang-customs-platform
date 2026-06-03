param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][ValidateSet("dev", "stable")][string]$Channel,
    [string]$ReleaseNotes = "",
    [string]$MinimumSupportedVersion = ""
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sourceDir = Join-Path $root "source"
$distDir = Join-Path $root "dist"
$payloadDir = Join-Path $root "installer_payload"
$appExeName = "TongYangCustomsPlatform.exe"
$setupExeName = "TongYangCustomsPlatform_Setup.exe"
$appExePath = Join-Path $distDir $appExeName
$setupExePath = Join-Path $distDir $setupExeName
$distManifestPath = Join-Path $distDir "version.json"
$runtimeManifestPath = Join-Path $distDir "config\version.json"
$payloadManifestPath = Join-Path $payloadDir "version.json"
$distShaPath = Join-Path $distDir "SHA256.txt"
$configManifestPath = Join-Path $sourceDir "config\version.json"
$devManifestPath = Join-Path $sourceDir "config\dev_version.json"
$appDisplayName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6YCa5rSL5aCx6Zec5bmz5Y+w"))

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Path
    )
    New-Item -ItemType Directory -Force -Path (Split-Path $Path) | Out-Null
    $Data | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower()
}

Set-Location $root

if ([string]::IsNullOrWhiteSpace($ReleaseNotes)) {
    $ReleaseNotes = "$($Channel.ToUpper()) release $Tag"
}
if ([string]::IsNullOrWhiteSpace($MinimumSupportedVersion)) {
    $MinimumSupportedVersion = $Version
}

$downloadUrl = if ($Channel -eq "stable") {
    "https://github.com/$Repo/releases/latest/download/$setupExeName"
} else {
    "https://github.com/$Repo/releases/download/$Tag/$setupExeName"
}

$seedManifest = if (Test-Path -LiteralPath $configManifestPath) {
    Get-Content -LiteralPath $configManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    [pscustomobject]@{}
}
$seedManifest.app_name = $appDisplayName
$seedManifest.version = $Version
$seedManifest.channel = $Channel
$seedManifest.exe_url = $downloadUrl
$seedManifest.download_url = $downloadUrl
$seedManifest.release_notes = $ReleaseNotes
$seedManifest.notes = $ReleaseNotes
$seedManifest.minimum_supported_version = $MinimumSupportedVersion
$seedManifest.package_type = "installer"
Write-JsonFile $seedManifest $configManifestPath

powershell -ExecutionPolicy Bypass -File (Join-Path $root "build_v2_exe.ps1")
if (-not (Test-Path -LiteralPath $appExePath)) {
    throw "Build did not produce expected app EXE: $appExePath"
}

$appSha = Get-Sha256 $appExePath
$buildTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
$buildId = "$Version-$($appSha.Substring(0, 12))"

$runtimeManifest = [ordered]@{
    app_name = $appDisplayName
    version = $Version
    channel = $Channel
    exe_url = $downloadUrl
    download_url = $downloadUrl
    sha256 = $appSha
    app_sha256 = $appSha
    build_id = $buildId
    build_time = $buildTime
    release_id = $Tag
    release_notes = $ReleaseNotes
    notes = $ReleaseNotes
    minimum_supported_version = $MinimumSupportedVersion
    package_type = "installer"
    package_sha256 = ""
}

if (Test-Path -LiteralPath $payloadDir) {
    Remove-Item -LiteralPath $payloadDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $payloadDir | Out-Null
Copy-Item -Force -LiteralPath $appExePath -Destination (Join-Path $payloadDir $appExeName)
Write-JsonFile $runtimeManifest $runtimeManifestPath
Write-JsonFile $runtimeManifest $payloadManifestPath
[IO.File]::WriteAllText((Join-Path $payloadDir "SHA256.txt"), "$appSha  $appExeName`n", [Text.UTF8Encoding]::new($false))

python -m PyInstaller --clean --noconfirm (Join-Path $root "TongYangCustomsPlatform_Setup.spec")
if (-not (Test-Path -LiteralPath $setupExePath)) {
    throw "Installer build did not produce expected setup EXE: $setupExePath"
}

$packageSha = Get-Sha256 $setupExePath
$releaseManifest = [ordered]@{
    app_name = $appDisplayName
    version = $Version
    channel = $Channel
    exe_url = $downloadUrl
    download_url = $downloadUrl
    sha256 = $appSha
    app_sha256 = $appSha
    build_id = $buildId
    build_time = $buildTime
    release_id = $Tag
    release_notes = $ReleaseNotes
    notes = $ReleaseNotes
    minimum_supported_version = $MinimumSupportedVersion
    package_type = "installer"
    package_sha256 = $packageSha
}

Write-JsonFile $releaseManifest $distManifestPath
Write-JsonFile $releaseManifest $runtimeManifestPath
Write-JsonFile $releaseManifest $configManifestPath
if ($Channel -eq "dev") {
    Write-JsonFile $releaseManifest $devManifestPath
}
[IO.File]::WriteAllText($distShaPath, "$packageSha  $setupExeName`n", [Text.UTF8Encoding]::new($false))

Write-Host "Release package built."
Write-Host "App EXE: $appExePath"
Write-Host "App SHA256: $appSha"
Write-Host "Setup EXE: $setupExePath"
Write-Host "Setup SHA256: $packageSha"
Write-Host "Manifest: $distManifestPath"
Write-Host "SHA256.txt: $distShaPath"
