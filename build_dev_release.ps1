param(
    [string]$Version = "",
    [string]$Repo = "larry36163712-ux/tongyang-customs-platform",
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [switch]$SkipPush,
    [switch]$SkipRelease,
    [switch]$InitializeGit
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredTool {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string[]]$CommonPaths = @()
    )

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
    throw "Missing required tool: $Name. Install it and make sure it is available in PATH."
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Block
    )
    Write-Host ""
    Write-Host "==> $Name"
    & $Block
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing file: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $Data | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-NextDevVersion {
    param([Parameter(Mandatory = $true)][string]$CurrentVersion)
    $clean = $CurrentVersion -replace "-dev$", ""
    $parts = $clean.Split(".")
    if ($parts.Count -ne 3) {
        throw "Cannot auto-increment version '$CurrentVersion'. Pass -Version explicitly."
    }
    $patch = [int]$parts[2] + 1
    return "$($parts[0]).$($parts[1]).$patch-dev"
}

function Assert-ExitCode {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

$root = $PSScriptRoot
Set-Location $root

$git = Resolve-RequiredTool "git" @(
    "C:\Program Files\Git\cmd\git.exe",
    "C:\Program Files\Git\bin\git.exe",
    "C:\Program Files (x86)\Git\cmd\git.exe"
)
$gh = $null
if (-not ($SkipPush -and $SkipRelease)) {
    $gh = Resolve-RequiredTool "gh" @(
        "C:\Program Files\GitHub CLI\gh.exe",
        "$env:LOCALAPPDATA\Programs\GitHub CLI\gh.exe"
    )
}

$configVersionPath = Join-Path $root "config\version.json"
$manifest = Read-JsonFile $configVersionPath
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-NextDevVersion ([string]$manifest.version)
}
if ($Version -notmatch "^\d+\.\d+\.\d+-dev$") {
    throw "DEV version must look like 1.1.3-dev. Received: $Version"
}

$tag = "DEV-$Version"
$assetName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6YCa5rSL5aCx6Zec5bmz5Y+wLmV4ZQ=="))
$exePath = Join-Path $root "dist\$assetName"
$distVersionPath = Join-Path $root "dist\config\version.json"
$distReleaseManifestPath = Join-Path $root "dist\version.json"
$shaPath = Join-Path $root "dist\SHA256.txt"
$notesPath = Join-Path $root "dist\release-notes-$tag.md"

Invoke-Step "Preflight git working tree" {
    if (-not (Test-Path -LiteralPath (Join-Path $root ".git"))) {
        if (-not $InitializeGit) {
            throw "This folder is not a git working tree. Re-run with -InitializeGit only if you want this folder initialized and pushed to $Repo."
        }
        & $git init
        Assert-ExitCode "git init failed"
        & $git remote add $Remote "https://github.com/$Repo.git"
        Assert-ExitCode "git remote add failed"
    }
    & $git rev-parse --is-inside-work-tree | Out-Null
    Assert-ExitCode "Not inside a git working tree."

    $remoteUrl = & $git remote get-url $Remote 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($remoteUrl)) {
        & $git remote add $Remote "https://github.com/$Repo.git"
        Assert-ExitCode "git remote add failed"
    }

    & $git config user.name | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $git config user.name "TongYang DEV Release Bot"
    }
    & $git config user.email | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $git config user.email "dev-release@tongyang.local"
    }
}

if (-not ($SkipPush -and $SkipRelease)) {
    Invoke-Step "Preflight GitHub auth" {
        & $gh auth status -h github.com
        Assert-ExitCode "GitHub CLI is not authenticated. Run: gh auth login -h github.com -s repo"

        & $gh repo view $Repo --json nameWithOwner | Out-Null
        Assert-ExitCode "GitHub token cannot access $Repo. Check account, token scopes, and repository permission."

        if (-not $SkipPush) {
            & $git ls-remote "https://github.com/$Repo.git" HEAD | Out-Null
            Assert-ExitCode "git cannot access remote repository. Check credentials and remote permission."
        }
    }
}

Invoke-Step "Sync DEV version files" {
    $manifest.version = $Version
    $manifest.channel = "dev"
    $manifest.notes = "DEV release $tag"
    $manifest.download_url = "https://github.com/$Repo/releases/download/$tag/$([Uri]::EscapeDataString($assetName))"
    Write-JsonFile $manifest $configVersionPath

    $settingsPath = Join-Path $root "config\v2_settings.json"
    if (Test-Path -LiteralPath $settingsPath) {
        $settings = Read-JsonFile $settingsPath
        if (-not $settings.update) {
            $settings | Add-Member -MemberType NoteProperty -Name update -Value ([pscustomobject]@{})
        }
        $settings.update.channel = "dev"
        Write-JsonFile $settings $settingsPath
    }
}

Invoke-Step "Run tests" {
    python -m py_compile v2\ui\main_window.py
    python scripts\test_v2_document_workflow.py
    python scripts\test_v2_declaration_workflow.py
}

Invoke-Step "Build EXE" {
    powershell -ExecutionPolicy Bypass -File .\build_v2_exe.ps1
}

Invoke-Step "Generate assets and manifests" {
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Build did not produce expected EXE: $exePath"
    }

    python scripts\make_release_manifest.py `
        --repo $Repo `
        --tag $tag `
        --version $Version `
        --exe $exePath `
        --asset-name $assetName `
        --channel dev `
        --output $distReleaseManifestPath

    $releaseManifest = Read-JsonFile $distReleaseManifestPath
    New-Item -ItemType Directory -Force -Path (Split-Path $distVersionPath) | Out-Null
    Write-JsonFile $releaseManifest $configVersionPath
    Write-JsonFile $releaseManifest $distVersionPath

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exePath).Hash.ToLower()
    [IO.File]::WriteAllText($shaPath, "$hash  $assetName`n", [Text.UTF8Encoding]::new($false))
}

Invoke-Step "Generate release notes" {
    $commit = (& $git rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit)) {
        $commit = "pending-commit"
    }
    $buildTime = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    $notes = @"
# $tag

- Version: $Version
- Channel: dev prerelease
- Build time: $buildTime
- Git commit: $commit
- Completed modules: workflow UI, async build workflow, version sync, release asset generation
- Parser coverage: semantic-core, booking-so-parser, import DS2/INV/PKG/B/L workflow, export booking/S/O workflow
- Compare coverage: declaration/document field compare, booking/export field compare, missing document status
"@
    [IO.File]::WriteAllText($notesPath, $notes, [Text.UTF8Encoding]::new($false))
}

Invoke-Step "Commit release changes" {
    & $git add config\version.json config\v2_settings.json build_dev_release.ps1 check_github_release_auth.ps1 .github\workflows\release.yml scripts\make_release_manifest.py
    Assert-ExitCode "git add failed"

    $hasChanges = & $git status --porcelain
    if ($hasChanges) {
        & $git commit -m "chore: prepare DEV $Version release"
        Assert-ExitCode "git commit failed"
    } else {
        Write-Host "No tracked changes to commit."
    }
}

if (-not $SkipPush) {
    Invoke-Step "Push branch" {
        & $git push $Remote $Branch
        Assert-ExitCode "git push failed"
    }
}

if (-not $SkipRelease) {
    Invoke-Step "Create or update DEV prerelease" {
        & $gh release view $tag --repo $Repo *> $null
        if ($LASTEXITCODE -eq 0) {
            & $gh release edit $tag --repo $Repo --title $tag --notes-file $notesPath --prerelease --latest=false
            Assert-ExitCode "gh release edit failed"
        } else {
            & $gh release create $tag --repo $Repo --title $tag --notes-file $notesPath --prerelease --latest=false
            Assert-ExitCode "gh release create failed"
        }
        powershell -ExecutionPolicy Bypass -File .\scripts\upload_release_asset.ps1 `
            -Repo $Repo `
            -Tag $tag `
            -Path $exePath `
            -AssetName $assetName `
            -ContentType "application/octet-stream"
        & $gh release upload $tag $shaPath $distReleaseManifestPath --repo $Repo --clobber
        Assert-ExitCode "gh release upload failed"
    }
}

Write-Host ""
Write-Host "DEV release pipeline complete."
Write-Host "Version: $Version"
Write-Host "Tag: $tag"
Write-Host "EXE: $exePath"
Write-Host "SHA256: $shaPath"
Write-Host "Manifest: $distReleaseManifestPath"
