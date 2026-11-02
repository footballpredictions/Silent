param([switch]$NativeOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskApp = Join-Path $taskRoot 'app'
$taskOutput = Join-Path $taskApp 'src/transportLab/jniLibs'
$taskSdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android/Sdk' }
$taskNdk = Get-ChildItem -LiteralPath (Join-Path $taskSdk 'ndk') -Directory | Sort-Object Name -Descending | Select-Object -First 1
if (!$taskNdk) { throw 'Android NDK is required' }
$taskClang = Join-Path $taskNdk.FullName 'toolchains/llvm/prebuilt/windows-x86_64/bin'
$taskTargets = @(
    @{ Abi='arm64-v8a'; Arch='arm64'; Compiler='aarch64-linux-android24-clang.cmd'; Extra='GOARM64'; Value='v8.0' },
    @{ Abi='armeabi-v7a'; Arch='arm'; Compiler='armv7a-linux-androideabi24-clang.cmd'; Extra='GOARM'; Value='7' },
    @{ Abi='x86_64'; Arch='amd64'; Compiler='x86_64-linux-android24-clang.cmd'; Extra='GOAMD64'; Value='v1' },
    @{ Abi='x86'; Arch='386'; Compiler='i686-linux-android24-clang.cmd'; Extra='GO386'; Value='sse2' }
)
$taskKeys = @('GOOS','GOARCH','GOARM','GOARM64','GOAMD64','GO386','CGO_ENABLED','CC','GOTOOLCHAIN')
$taskOriginal = @{}
foreach ($taskKey in $taskKeys) { $taskOriginal[$taskKey] = [Environment]::GetEnvironmentVariable($taskKey, 'Process') }
Push-Location (Join-Path $taskApp 'wdtt-go')
try {
    $env:GOOS = 'android'
    $env:CGO_ENABLED = '1'
    $env:GOTOOLCHAIN = 'go1.26.3'
    foreach ($taskTarget in $taskTargets) {
        foreach ($taskArchKey in @('GOARM','GOARM64','GOAMD64','GO386')) { [Environment]::SetEnvironmentVariable($taskArchKey, $null, 'Process') }
        $env:GOARCH = $taskTarget.Arch
        [Environment]::SetEnvironmentVariable($taskTarget.Extra, $taskTarget.Value, 'Process')
        $env:CC = Join-Path $taskClang $taskTarget.Compiler
        if (!(Test-Path -LiteralPath $env:CC)) { throw "Compiler missing: $($taskTarget.Abi)" }
        $taskAbiOutput = Join-Path $taskOutput $taskTarget.Abi
        New-Item -ItemType Directory -Path $taskAbiOutput -Force | Out-Null
        & go build '-ldflags=-s -w -checklinkname=0' -trimpath -o (Join-Path $taskAbiOutput 'libclient.so') .
        if ($LASTEXITCODE -ne 0) { throw "Native build failed: $($taskTarget.Abi)" }
        Get-ChildItem -LiteralPath (Join-Path $taskApp "src/main/jniLibs/$($taskTarget.Abi)") -Filter '*.so' |
            Where-Object { $_.Name -notin @('libclient.so','libolcrtc.so','libolcrtc2.so','libhev-socks5-tunnel.so') } |
            ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $taskAbiOutput $_.Name) }
        Write-Output "PASS native $($taskTarget.Abi)"
    }
} finally {
    Pop-Location
    foreach ($taskKey in $taskKeys) { [Environment]::SetEnvironmentVariable($taskKey, $taskOriginal[$taskKey], 'Process') }
}
if (!$NativeOnly) {
    Push-Location $taskApp
    try {
        & ./gradlew.bat '-PtransportLab=true' testDebugUnitTest assembleDebug
        if ($LASTEXITCODE -ne 0) { throw 'UDP tests/APK build failed' }
        $taskRelease = Join-Path $taskRoot 'releases/SilentVPN-udp-clean-1.0.171-20261102.apk'
        New-Item -ItemType Directory -Path (Split-Path $taskRelease) -Force | Out-Null
        $taskApkDirectory = Join-Path $taskApp 'build/outputs/apk/debug'
        $taskMetadata = Get-Content -LiteralPath (Join-Path $taskApkDirectory 'output-metadata.json') -Raw | ConvertFrom-Json
        if ($taskMetadata.applicationId -ne 'com.silent.vpn.transporttest' -or $taskMetadata.elements.Count -ne 1) { throw 'Unexpected APK metadata' }
        Copy-Item -LiteralPath (Join-Path $taskApkDirectory $taskMetadata.elements[0].outputFile) -Destination $taskRelease
        Get-FileHash -LiteralPath $taskRelease -Algorithm SHA256
    } finally { Pop-Location }
}
