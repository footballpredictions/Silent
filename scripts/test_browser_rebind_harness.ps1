param(
    [string]$SourcePath = "",
    [string]$SdkRoot = "",
    [string]$GradleCache = ""
)
$ErrorActionPreference = "Stop"
$androidRoot = (Resolve-Path "$PSScriptRoot/..").Path
$harnessRoot = "$PSScriptRoot/browser-rebind-harness"
if (-not $SourcePath) { $SourcePath = "$androidRoot/app/src/main/kotlin/com/silent/vpn/vpn/BrowserScopedTunnel.kt" }
if (-not $GradleCache) {
    $gradleUserCache = if ($env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME } else { "$env:USERPROFILE/.gradle" }
    $GradleCache = "$gradleUserCache/caches/modules-2/files-2.1"
}
if (-not $SdkRoot) {
    $SdkRoot = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA/Android/Sdk" }
}

# Runs the real production Kotlin start/stop logic. Android services/logging are
# doubles; no VPN service, native process, physical network, or account is used.
# A living fake Process plus identical semanticKey reproduces the stale-socket
# no-op. The forced call must stop that Process and enter real reinitialization.
function CachedJar([string]$module, [string]$version = "") {
    $target = "$GradleCache/$module"
    if ($version) { $target = "$target/$version" }
    $found = Get-ChildItem -LiteralPath $target -Recurse -Filter '*.jar' | Select-Object -Last 1
    if (-not $found) { throw "Missing cached dependency $module $version; build the Android app once before this harness" }
    return $found.FullName
}

$java = (Get-Command java.exe).Source
$compilerClasspath = @(
    (CachedJar 'org.jetbrains.kotlin/kotlin-compiler-embeddable' '2.0.21'),
    (CachedJar 'org.jetbrains.kotlin/kotlin-stdlib' '2.0.21'),
    (CachedJar 'org.jetbrains.kotlin/kotlin-script-runtime' '2.0.21'),
    (CachedJar 'org.jetbrains.kotlin/kotlin-reflect'),
    (CachedJar 'org.jetbrains.intellij.deps/trove4j'),
    (CachedJar 'org.jetbrains/annotations'),
    (CachedJar 'org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm')
) -join ';'
$stdlib = CachedJar 'org.jetbrains.kotlin/kotlin-stdlib' '2.0.21'
$annotations = CachedJar 'org.jetbrains/annotations'
$sdkJar = "$SdkRoot/platforms/android-35/android.jar"
if (-not (Test-Path -LiteralPath $sdkJar)) {
    $sdkJar = (Get-ChildItem -LiteralPath "$SdkRoot/platforms" -Filter android.jar -Recurse | Select-Object -Last 1).FullName
}
if (-not $sdkJar) { throw "No Android SDK platform jar in $SdkRoot/platforms" }
$outputRoot = "$androidRoot/build/browser-rebind-harness"
$classes = "$outputRoot/classes"
New-Item -ItemType Directory -Path $classes -Force | Out-Null
$wireGuardJar = "$outputRoot/wireguard-classes.jar"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$aar = Get-ChildItem -LiteralPath "$GradleCache/com.wireguard.android/tunnel" -Recurse -Filter '*.aar' | Select-Object -Last 1
if (-not $aar) { throw "WireGuard dependency is not cached; build the Android app once before this harness" }
$zip = [System.IO.Compression.ZipFile]::OpenRead($aar.FullName)
try { [System.IO.Compression.ZipFileExtensions]::ExtractToFile($zip.GetEntry('classes.jar'), $wireGuardJar, $true) }
finally { $zip.Dispose() }
$runtime = "$stdlib;$annotations;$sdkJar;$wireGuardJar"
$sources = @((Get-ChildItem -LiteralPath $harnessRoot -Filter '*.kt' | ForEach-Object { $_.FullName }),
    $SourcePath, "$androidRoot/app/src/main/kotlin/com/silent/vpn/vpn/RouterProcessOutput.kt") | ForEach-Object { $_ }
& $java -cp $compilerClasspath org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect -jvm-target 17 -classpath $runtime -d $classes @sources
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $java -cp "$classes;$runtime" recovery.harness.BrowserRebindHarnessKt
exit $LASTEXITCODE
