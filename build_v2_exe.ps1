$ErrorActionPreference = "Stop"

python -m PyInstaller --clean --noconfirm AI_Customs_ERP_V2.spec

$distDir = Join-Path $PSScriptRoot "dist"
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
Write-Host "Built V2: $($exePath.FullName)"
