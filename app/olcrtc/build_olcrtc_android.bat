@echo off
setlocal enabledelayedexpansion
REM libolcrtc.so с CGO+NDK — на Android 11+ net.Interfaces() = netlinkrib denied.
REM Нужен getifaddrs через pionnet_android.go (cgo), как у libclient.
REM ABI: arm64, armv7 (ТВ), x86, x86_64 (эмулятор).

set "APP_ROOT=%~dp0.."
set "JNI=%APP_ROOT%\src\main\jniLibs"
set "OLCRTC=%APP_ROOT%\..\..\vendor\olcrtc"
if not exist "%OLCRTC%\cmd\olcrtc" (
  echo Error: vendor\olcrtc not found at %OLCRTC%
  exit /b 1
)

if defined ANDROID_HOME (
  set "SDK_PATH=%ANDROID_HOME%"
) else if defined ANDROID_SDK_ROOT (
  set "SDK_PATH=%ANDROID_SDK_ROOT%"
) else if exist "%APP_ROOT%\local.properties" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%APP_ROOT%\local.properties") do (
    if "%%A"=="sdk.dir" set "SDK_PATH=%%B"
  )
  set "SDK_PATH=!SDK_PATH:\\=\!"
  set "SDK_PATH=!SDK_PATH:C\:\=C:\!"
) else (
  set "SDK_PATH=C:\Users\silent27\AppData\Local\Android\Sdk"
)

set "NDK_ROOT=%SDK_PATH%\ndk"
if not exist "%NDK_ROOT%" (
  echo Error: NDK not found at %NDK_ROOT%
  exit /b 1
)
for /f "delims=" %%D in ('dir /b /ad /o-n "%NDK_ROOT%"') do (
  set "NDK_VER=%%D"
  goto :FoundNDK
)
:FoundNDK
echo Using NDK: %NDK_VER%
set "TOOLCHAIN=%NDK_ROOT%\%NDK_VER%\toolchains\llvm\prebuilt\windows-x86_64\bin"
set "ANDROID_API=24"
set "CC_ARM64=%TOOLCHAIN%\aarch64-linux-android%ANDROID_API%-clang.cmd"
set "CC_ARM32=%TOOLCHAIN%\armv7a-linux-androideabi%ANDROID_API%-clang.cmd"
set "CC_X86=%TOOLCHAIN%\i686-linux-android%ANDROID_API%-clang.cmd"
set "CC_X64=%TOOLCHAIN%\x86_64-linux-android%ANDROID_API%-clang.cmd"
if not exist "%CC_ARM64%" (
  echo Error: arm64 clang not found: %CC_ARM64%
  exit /b 1
)

for %%A in (arm64-v8a armeabi-v7a x86 x86_64) do (
  if not exist "%JNI%\%%A" mkdir "%JNI%\%%A"
)

set "GOOS=android"
set "CGO_ENABLED=1"
set "LDFLAGS=-s -w -checklinkname=0"
set "GOTOOLCHAIN=go1.26.3"

cd /d "%OLCRTC%"

echo [1/4] arm64-v8a...
set "GOARCH=arm64"
set "GOARM="
set "GOARM64=v8.0"
set "CC=%CC_ARM64%"
go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\arm64-v8a\libolcrtc.so" ./cmd/olcrtc
if errorlevel 1 exit /b 1

echo [2/4] armeabi-v7a...
if exist "%CC_ARM32%" (
  set "GOARCH=arm"
  set "GOARM=7"
  set "GOARM64="
  set "CC=%CC_ARM32%"
  go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\armeabi-v7a\libolcrtc.so" ./cmd/olcrtc
  if errorlevel 1 echo Warning: armv7 failed
) else (
  echo armv7 clang missing — skip
)

echo [3/4] x86...
if exist "%CC_X86%" (
  set "GOARCH=386"
  set "GOARM="
  set "GOARM64="
  set "GOAMD64="
  set "GO386=sse2"
  set "CC=%CC_X86%"
  go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\x86\libolcrtc.so" ./cmd/olcrtc
  if errorlevel 1 echo Warning: x86 failed
) else (
  echo x86 clang missing — skip
)

echo [4/4] x86_64...
if exist "%CC_X64%" (
  set "GOARCH=amd64"
  set "GOARM="
  set "GOARM64="
  set "GOAMD64=v1"
  set "GO386="
  set "CC=%CC_X64%"
  go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\x86_64\libolcrtc.so" ./cmd/olcrtc
  if errorlevel 1 echo Warning: x86_64 failed
) else (
  echo x86_64 clang missing — skip
)

echo === libolcrtc.so CGO BUILD SUCCESS ===
dir "%JNI%\arm64-v8a\libolcrtc.so" "%JNI%\armeabi-v7a\libolcrtc.so" "%JNI%\x86\libolcrtc.so" "%JNI%\x86_64\libolcrtc.so" 2>nul
endlocal
