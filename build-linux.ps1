# Linux AppImage for Silent VPN (same UI/VPN flow as Windows PC).
# Cross-compiles Go from Windows; electron-builder --linux often needs WSL/Docker.
param(
  [string]$BootstrapVkHash = $(if ($env:BOOTSTRAP_VK_HASH) { $env:BOOTSTRAP_VK_HASH } else { '6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY' })
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host '=== Silent VPN Linux: wdtt + wireguard-go + AppImage ==='
Set-Content -Path 'src\main\buildFlags.js' -Value 'module.exports = { DEBUG_BUILD: false };' -Encoding ascii
$env:DEBUG_BUILD = $null
$env:BOOTSTRAP_VK_HASH = $BootstrapVkHash

New-Item -ItemType Directory -Force -Path 'resources\linux' | Out-Null

Write-Host '[1/4] wdtt-client (linux/amd64)...'
Push-Location wdtt-go
$env:GOOS = 'linux'
$env:GOARCH = 'amd64'
$env:CGO_ENABLED = '0'
$env:GOARM = $null
$env:GOTOOLCHAIN = 'local'
$env:GOPROXY = 'https://proxy.golang.org,direct'
go build -ldflags='-s -w -checklinkname=0' -trimpath -o '..\resources\linux\wdtt-client' .
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'wdtt linux build FAILED' }
Pop-Location

Write-Host '[2/4] wireguard-go (linux/amd64)...'
$env:GOOS = 'linux'
$env:GOARCH = 'amd64'
$env:CGO_ENABLED = '0'
$env:GOTOOLCHAIN = 'local'
$env:GOPROXY = 'https://proxy.golang.org,direct'
Remove-Item Env:GOBIN -ErrorAction SilentlyContinue
$wgOut = Join-Path (Get-Location) 'resources\linux\wireguard-go'
go get golang.zx2c4.com/wireguard@latest 2>$null
$modRoot = Join-Path (go env GOPATH) 'pkg\mod\golang.zx2c4.com'
$wgMod = Get-ChildItem $modRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'wireguard@*' } | Sort-Object Name -Descending | Select-Object -First 1
if ($wgMod) {
  Push-Location $wgMod.FullName
  go build -ldflags='-s -w' -trimpath -o $wgOut .
  Pop-Location
}
if (-not (Test-Path $wgOut)) {
  Write-Host 'WARN: wireguard-go build failed — helper will use kernel WireGuard + wg' -ForegroundColor Yellow
}

Write-Host '[2b/4] integrity hashes...'
node scripts\gen_integrity_hashes.js
if ($LASTEXITCODE -ne 0) { throw 'integrity hash gen FAILED' }

if (-not (Test-Path 'postcss.config.js')) { throw 'postcss.config.js missing' }
if (-not (Test-Path 'tailwind.config.js')) { throw 'tailwind.config.js missing' }

Write-Host '[3/4] renderer...'
Write-Host "Bootstrap hash: $env:BOOTSTRAP_VK_HASH"
if (Test-Path 'dist\renderer') { Remove-Item -Recurse -Force 'dist\renderer' }
npm run build:renderer
if ($LASTEXITCODE -ne 0) { throw 'renderer build FAILED' }

Write-Host '[4/4] electron-builder linux dir + .deb installer...'
npx electron-builder --linux dir --publish never --config electron-builder.linux.json
if ($LASTEXITCODE -ne 0) {
  Write-Host 'electron-builder --linux dir FAILED' -ForegroundColor Red
  exit 2
}

python scripts\pack_linux_deb.py
if ($LASTEXITCODE -ne 0) { throw 'pack_linux_deb FAILED' }

Write-Host '=== LINUX BUILD SUCCESS ==='
