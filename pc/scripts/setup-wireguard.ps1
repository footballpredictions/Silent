$dest = Join-Path $PSScriptRoot "..\resources\wireguard"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$wgExe = Join-Path $dest "wireguard.exe"
if (-not (Test-Path $wgExe)) {
    $sys = "C:\Program Files\WireGuard\wireguard.exe"
    if (Test-Path $sys) {
        Copy-Item $sys $wgExe -Force
        Copy-Item "C:\Program Files\WireGuard\wg.exe" (Join-Path $dest "wg.exe") -Force -ErrorAction SilentlyContinue
    }
}

$wintun = Join-Path $dest "wintun.dll"
if (-not (Test-Path $wintun)) {
    $zip = Join-Path $env:TEMP "wintun.zip"
    Invoke-WebRequest -Uri "https://www.wintun.net/builds/wintun-0.14.1.zip" -OutFile $zip
    $extract = Join-Path $env:TEMP "wintun_extract"
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    Copy-Item (Join-Path $extract "wintun\bin\amd64\wintun.dll") $wintun -Force
}

Get-ChildItem $dest
