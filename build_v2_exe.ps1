$ErrorActionPreference = "Stop"

python -m PyInstaller --clean --noconfirm AI_Customs_ERP_V2.spec

$distDir = Join-Path $PSScriptRoot "dist"
$exePath = Get-ChildItem -Path $distDir -Filter "*.exe" |
    Where-Object { $_.Name -ne "default.exe" -and $_.Name -ne "release_upload.exe" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $exePath) {
    throw "V2 EXE was not produced."
}
$defaultPath = Join-Path $distDir "default.exe"
Copy-Item -Force $exePath.FullName $defaultPath
Write-Host "Built V2: $($exePath.FullName)"
