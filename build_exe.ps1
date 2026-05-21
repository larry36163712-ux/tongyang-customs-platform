$ErrorActionPreference = "Stop"

$pythonRoot = python -c "import sys; print(sys.base_prefix)"
$env:TCL_LIBRARY = Join-Path $pythonRoot "tcl\tcl8.6"
$env:TK_LIBRARY = Join-Path $pythonRoot "tcl\tk8.6"

python -m PyInstaller --clean --noconfirm TongYangCustoms.spec

$distDir = Join-Path $PSScriptRoot "dist"
$exePath = Join-Path $distDir "通洋報關平台.exe"
Write-Host "Built: $exePath"
