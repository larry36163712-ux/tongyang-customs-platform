$ErrorActionPreference = "Stop"

$configVersion = Join-Path $PSScriptRoot "config\version.json"
$configSettings = Join-Path $PSScriptRoot "config\v2_settings.json"
if (-not (Test-Path -LiteralPath $configVersion)) {
    throw "Missing canonical version source: $configVersion"
}

python -m PyInstaller --clean --noconfirm AI_Customs_ERP_V2.spec

$distDir = Join-Path $PSScriptRoot "dist"
$distConfigDir = Join-Path $distDir "config"
$legacyDistVersion = Join-Path $distDir "version.json"
$exeName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6YCa5rSL5aCx6Zec5bmz5Y+wLmV4ZQ=="))
$exePath = Get-ChildItem -Path $distDir -Filter "*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $exePath) {
    throw "V2 EXE was not produced."
}
$targetPath = Join-Path $distDir $exeName
if ($exePath.FullName -ne $targetPath) {
    Move-Item -Force -LiteralPath $exePath.FullName -Destination $targetPath
    $exePath = Get-Item -LiteralPath $targetPath
}

New-Item -ItemType Directory -Force -Path $distConfigDir | Out-Null
Copy-Item -Force -LiteralPath $configVersion -Destination (Join-Path $distConfigDir "version.json")
if (Test-Path -LiteralPath $configSettings) {
    Copy-Item -Force -LiteralPath $configSettings -Destination (Join-Path $distConfigDir "v2_settings.json")
}
if (Test-Path -LiteralPath $legacyDistVersion) {
    Remove-Item -Force -LiteralPath $legacyDistVersion
}
Write-Host "Built V2: $($exePath.FullName)"
Write-Host "Canonical version source: $configVersion"
Write-Host "Runtime version source: $(Join-Path $distConfigDir "version.json")"
