param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$AssetName,
    [string]$ContentType = "application/octet-stream"
)

$ErrorActionPreference = "Stop"

if (-not $env:GH_TOKEN) {
    throw "GH_TOKEN is required."
}
$RequiredExecutableName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6YCa5rSL5aCx6Zec5bmz5Y+wLmV4ZQ=="))

if (-not (Test-Path -LiteralPath $Path)) {
    throw "Asset file not found: $Path"
}
if ($AssetName -ne $RequiredExecutableName -and $Path.ToLowerInvariant().EndsWith(".exe")) {
    throw "Executable release asset must be named $RequiredExecutableName. Received: $AssetName"
}

$blockedFallbackExeName = ("default" + ".exe")

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

foreach ($asset in $release.assets) {
    if ($asset.name -eq $AssetName -or ($Path.ToLowerInvariant().EndsWith(".exe") -and $asset.name -eq $blockedFallbackExeName)) {
        Invoke-RestMethod -Method Delete -Uri $asset.url -Headers $headers | Out-Null
    }
}

$builder = [System.UriBuilder]::new("https://uploads.github.com/repos/$Repo/releases/$($release.id)/assets")
$builder.Query = "name=$AssetName"
$uploaded = Invoke-RestMethod `
    -Method Post `
    -Uri $builder.Uri `
    -Headers $headers `
    -ContentType $ContentType `
    -InFile (Resolve-Path -LiteralPath $Path).Path

if ($uploaded.name -ne $AssetName) {
    Invoke-RestMethod -Method Delete -Uri $uploaded.url -Headers $headers | Out-Null
    throw "GitHub returned asset name '$($uploaded.name)' instead of required '$AssetName'. Upload rejected to prevent invalid executable naming."
}

$uploaded
