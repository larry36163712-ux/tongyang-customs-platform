param(
    [string]$Repo = "larry36163712-ux/tongyang-customs-platform",
    [string]$Remote = "origin"
)

$ErrorActionPreference = "Continue"

function Resolve-Tool {
    param([string]$Name, [string[]]$CommonPaths = @())
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    foreach ($path in $CommonPaths) {
        $resolved = Resolve-Path $path -ErrorAction SilentlyContinue
        if ($resolved) {
            return $resolved.Path
        }
    }
    return ""
}

function Show-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $status = if ($Ok) { "OK" } else { "FAIL" }
    Write-Host "[$status] $Name - $Detail"
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$git = Resolve-Tool "git" @("C:\Program Files\Git\cmd\git.exe", "C:\Program Files\Git\bin\git.exe")
$gh = Resolve-Tool "gh" @("C:\Program Files\GitHub CLI\gh.exe", "$env:LOCALAPPDATA\Programs\GitHub CLI\gh.exe")

Show-Check "git installed" (-not [string]::IsNullOrWhiteSpace($git)) $git
Show-Check "GitHub CLI installed" (-not [string]::IsNullOrWhiteSpace($gh)) $gh
Show-Check "GH_TOKEN" (-not [string]::IsNullOrWhiteSpace($env:GH_TOKEN)) ($(if ($env:GH_TOKEN) { "present" } else { "missing" }))
Show-Check "GITHUB_TOKEN" (-not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) ($(if ($env:GITHUB_TOKEN) { "present" } else { "missing" }))
Show-Check "git working tree" (Test-Path -LiteralPath ".git") ($(if (Test-Path -LiteralPath ".git") { ".git exists" } else { ".git missing" }))

if ($git) {
    & $git --version
    if (Test-Path -LiteralPath ".git") {
        & $git remote -v
        & $git status --short
    }
}

if ($gh) {
    & $gh --version
    & $gh auth status -h github.com
    if ($LASTEXITCODE -eq 0) {
        Show-Check "gh auth" $true "authenticated"
        & $gh repo view $Repo --json nameWithOwner,viewerPermission
        Show-Check "repo access" ($LASTEXITCODE -eq 0) $Repo
    } else {
        Show-Check "gh auth" $false "run: gh auth login -h github.com -s repo"
    }
}

if ($git -and (Test-Path -LiteralPath ".git")) {
    & $git ls-remote "https://github.com/$Repo.git" HEAD
    Show-Check "remote read access" ($LASTEXITCODE -eq 0) "https://github.com/$Repo.git"
}
