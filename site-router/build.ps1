$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$oldToolchain = $env:GOTOOLCHAIN
$oldProxy = $env:GOPROXY
$oldOS = $env:GOOS
$oldArch = $env:GOARCH
$oldCgo = $env:CGO_ENABLED
try {
    $env:GOTOOLCHAIN = 'go1.26.3'
    $env:GOPROXY = 'https://proxy.golang.org,direct'
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    $env:CGO_ENABLED = '0'
    go build -trimpath -ldflags='-s -w' -o '../resources/wireguard/site-router.exe' .
    if ($LASTEXITCODE -ne 0) { throw 'site-router build failed' }
} finally {
    $env:GOTOOLCHAIN = $oldToolchain
    $env:GOPROXY = $oldProxy
    $env:GOOS = $oldOS
    $env:GOARCH = $oldArch
    $env:CGO_ENABLED = $oldCgo
    Pop-Location
}
