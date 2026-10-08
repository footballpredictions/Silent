$ErrorActionPreference = 'Stop'
$routerRoot = $PSScriptRoot
$sdkPath = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA/Android/Sdk" }
$ndkPath = Get-ChildItem -LiteralPath "$sdkPath/ndk" -Directory | Sort-Object Name -Descending | Select-Object -First 1
if (!$ndkPath) { throw 'Android NDK not found' }
$compilerRoot = "$($ndkPath.FullName)/toolchains/llvm/prebuilt/windows-x86_64/bin"
$targets = @(
    @{Abi='arm64-v8a'; Arch='arm64'; Compiler='aarch64-linux-android24-clang.cmd'},
    @{Abi='armeabi-v7a'; Arch='arm'; Compiler='armv7a-linux-androideabi24-clang.cmd'},
    @{Abi='x86'; Arch='386'; Compiler='i686-linux-android24-clang.cmd'},
    @{Abi='x86_64'; Arch='amd64'; Compiler='x86_64-linux-android24-clang.cmd'}
)
Push-Location -LiteralPath $routerRoot
$routerEnvironment = @{}
foreach ($name in @('GOOS', 'GOARCH', 'CGO_ENABLED', 'CC', 'GOARM', 'GOARM64', 'GOAMD64', 'GO386', 'GOTOOLCHAIN')) {
    $routerEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:GOOS='android'; $env:CGO_ENABLED='1'; $env:GOTOOLCHAIN='go1.26.3'
    foreach ($target in $targets) {
        $env:GOARCH=$target.Arch; $env:CC="$compilerRoot/$($target.Compiler)"
        $env:GOARM = if ($target.Arch -eq 'arm') { '7' } else { '' }
        $env:GOARM64 = if ($target.Arch -eq 'arm64') { 'v8.0' } else { '' }
        $env:GOAMD64 = if ($target.Arch -eq 'amd64') { 'v1' } else { '' }
        $env:GO386 = if ($target.Arch -eq '386') { 'sse2' } else { '' }
        $outputDirectory = Join-Path $routerRoot "../src/main/jniLibs/$($target.Abi)"
        New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
        & go build -trimpath -ldflags '-s -w' -o "$outputDirectory/libsite-router.so" .
        if ($LASTEXITCODE -ne 0) { throw "site-router build failed for $($target.Abi)" }
        Write-Output "Built site-router $($target.Abi)"
    }
} finally {
    foreach ($name in $routerEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $routerEnvironment[$name], 'Process')
    }
    Pop-Location
}
