# One-line installer for the undercover-driver CLI.
#
#   irm https://raw.githubusercontent.com/Reqeique/undercover-driver/main/install.ps1 | iex
#
# Binaries are attached to a public GitHub release of this repo, so no
# authentication is required.
#
# Env overrides:
#   AB_VERSION      release tag to install (default: latest)
#   AB_REPO         owner/repo (default: Reqeique/undercover-driver)
#   AB_BIN_DIR      binary install dir (default: ~/.local/bin)
$ErrorActionPreference = 'Stop'

$Repo = if ($env:AB_REPO) { $env:AB_REPO } else { 'Reqeique/undercover-driver' }
$Version = if ($env:AB_VERSION) { $env:AB_VERSION } else { 'latest' }
$BinDir = if ($env:AB_BIN_DIR) { $env:AB_BIN_DIR } else { Join-Path $HOME '.local\bin' }

# --- platform --------------------------------------------------------------
$Os = if ($IsWindows -or $env:OS -eq 'Windows_NT') { 'windows' } elseif ($IsMacOS) { 'darwin' } else { 'linux' }
$Arch = switch ($env:PROCESSOR_ARCHITECTURE) {
  'AMD64'  { 'amd64' }
  'ARM64'  { 'arm64' }
  'x86'    { 'amd64' }
  default  { $null }
}
if (-not $Arch) { throw "unsupported arch: $env:PROCESSOR_ARCHITECTURE" }
$Ext = if ($Os -eq 'windows') { '.exe' } else { '' }
$Asset = "undercover-driver-$Os-$Arch$Ext"
Write-Host "target: $Os/$Arch -> $Asset (repo $Repo, version $Version)"

# --- resolve release + asset URL -------------------------------------------
$Headers = @{ Accept = 'application/vnd.github+json' }
$RelUrl = if ($Version -eq 'latest') {
  "https://api.github.com/repos/$Repo/releases/latest"
} else {
  "https://api.github.com/repos/$Repo/releases/tags/$Version"
}
$Release = Invoke-RestMethod -Uri $RelUrl -Headers $Headers
$AssetRec = $Release.assets | Where-Object { $_.name -eq $Asset }
if (-not $AssetRec) {
  throw "asset '$Asset' not found in release '$Version'. Build it first via the .github/workflows/build-release.yml workflow."
}

# --- download + install ----------------------------------------------------
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("ab-install-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
try {
  $Dest = Join-Path $BinDir "undercover-driver$Ext"
  Write-Host "downloading $Asset ..."
  Invoke-WebRequest -Uri $AssetRec.browser_download_url -OutFile $Dest
  Write-Host "installed: $Dest"
} finally {
  Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}

# --- PATH hint -------------------------------------------------------------
if ($BinDir -notin ($env:PATH -split ';')) {
  Write-Host ""
  Write-Host "NOTE: add $BinDir to your PATH:"
  Write-Host ('  setx PATH "' + $BinDir + ';' + $env:PATH + '"   (new shells only)')
  Write-Host ('  $env:PATH = "' + $BinDir + ';' + '$env:PATH"  (this shell)')
}

Write-Host ""
Write-Host "done.  Usage:"
Write-Host ('  $env:BROWSER_URL = "https://<container>.runs.apify.net"')
Write-Host ('  $env:BROWSER_TOKEN = "<auth_token>"')
Write-Host "  undercover-driver health"
Write-Host "  undercover-driver goto https://example.com"
Write-Host "  undercover-driver snapshot"
