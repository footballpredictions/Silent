# Cross-compile Mac Go binaries from Windows. DMG itself MUST be built on a Mac:
#   ./build-mac.sh
# This script only prepares resources/mac/{wdtt-client,wireguard-go} + verifies helper.
param(
  [ValidateSet('arm64', 'amd64')]
  [string]$Arch = 'arm64',
  [string]$BootstrapVkHash = $(if ($env:BOOTSTRAP_VK_HASH) { $env:BOOTSTRAP_VK_HASH } else { '4uhJXsVypBdlEbvt6k4hPEFi3RooXUqyUwDG4lgPBDY' })
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "=== Silent VPN Mac prep (darwin/$Arch) from Windows ==="
Write-Host 'NOTE: .dmg packaging requires macOS (run build-mac.sh there).' -ForegroundColor Yellow

Set-Content -Path 'src\main\buildFlags.js' -Value 'module.exports = { DEBUG_BUILD: false };' -Encoding ascii
$env:BOOTSTRAP_VK_HASH = $BootstrapVkHash
New-Item -ItemType Directory -Force -Path 'resources\mac' | Out-Null

Write-Host "[1/3] wdtt-client (darwin/$Arch)..."
Push-Location wdtt-go
$env:GOOS = 'darwin'
$env:GOARCH = $Arch
$env:CGO_ENABLED = '0'
$env:GOTOOLCHAIN = 'local'
$env:GOPROXY = 'https://proxy.golang.org,direct'
go build -ldflags='-s -w -checklinkname=0' -trimpath -o '..\resources\mac\wdtt-client' .
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'wdtt darwin build FAILED' }
Pop-Location

Write-Host "[2/3] wireguard-go (darwin/$Arch)..."
$env:GOOS = 'darwin'
$env:GOARCH = $Arch
$env:CGO_ENABLED = '0'
$env:GOTOOLCHAIN = 'local'
$env:GOPROXY = 'https://proxy.golang.org,direct'
$wgOut = Join-Path (Get-Location) 'resources\mac\wireguard-go'
$modRoot = Join-Path (go env GOPATH) 'pkg\mod\golang.zx2c4.com'
$wgMod = Get-ChildItem $modRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'wireguard@*' } | Sort-Object Name -Descending | Select-Object -First 1
if (-not $wgMod) {
  go install golang.zx2c4.com/wireguard@v0.0.20230223 2>$null
  $wgMod = Get-ChildItem $modRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'wireguard@*' } | Sort-Object Name -Descending | Select-Object -First 1
}
if ($wgMod) {
  Push-Location $wgMod.FullName
  go build -ldflags='-s -w' -trimpath -o $wgOut .
  Pop-Location
}
if (-not (Test-Path $wgOut)) {
  # Fallback: module mode from empty dir
  $tmp = Join-Path $env:TEMP "wg-go-build-$Arch"
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  Push-Location $tmp
  go mod init tmpwg 2>$null
  go get golang.zx2c4.com/wireguard@v0.0.20230223
  go build -ldflags='-s -w' -trimpath -o $wgOut golang.zx2c4.com/wireguard
  Pop-Location
}
if (-not (Test-Path $wgOut)) { throw 'wireguard-go darwin build FAILED' }

if (-not (Test-Path 'resources\mac\silent-wg-helper')) {
  throw 'resources/mac/silent-wg-helper missing'
}

Write-Host '[3/3] integrity hashes...'
node scripts\gen_integrity_hashes.js
if ($LASTEXITCODE -ne 0) { throw 'integrity hash gen FAILED' }

Write-Host '=== MAC PREP SUCCESS (binaries only) ==='
Get-ChildItem resources\mac | Format-Table Name, Length
Write-Host ''
Write-Host 'Next on a MacBook (Apple Silicon):' -ForegroundColor Cyan
Write-Host '  cd pc'
Write-Host '  chmod +x build-mac.sh resources/mac/*'
Write-Host '  ./build-mac.sh'
Write-Host "Output: build-mac/Silent VPN Setup <version>.dmg"
