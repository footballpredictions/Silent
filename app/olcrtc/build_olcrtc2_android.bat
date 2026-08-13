@echo off
setlocal enabledelayedexpansion
REM libolcrtc2.so = olcrtc2-cnc for Android (Telemost session-mode).
REM CGO+NDK required (same as libolcrtc / libclient).

set "APP_ROOT=%~dp0.."
set "JNI=%APP_ROOT%\src\main\jniLibs"
REM Telemost = vp8channel internals → build from vendor/olcrtc, not backend/olcrtc2 stubs.
set "OLCRTC2=%APP_ROOT%\..\..\vendor\olcrtc"
if not exist "%OLCRTC2%\cmd\olcrtc2-cnc\main.go" (
  echo Error: vendor\olcrtc\cmd\olcrtc2-cnc not found at %OLCRTC2%
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
if not exist "%CC_ARM64%" (
  echo Error: arm64 clang not found: %CC_ARM64%
  exit /b 1
)

if not exist "%JNI%\arm64-v8a" mkdir "%JNI%\arm64-v8a"
if not exist "%JNI%\armeabi-v7a" mkdir "%JNI%\armeabi-v7a"

set "GOOS=android"
set "CGO_ENABLED=1"
set "LDFLAGS=-s -w -checklinkname=0"
set "GOTOOLCHAIN=go1.26.3"

cd /d "%OLCRTC2%"

echo [1/2] arm64-v8a libolcrtc2.so...
set "GOARCH=arm64"
set "GOARM="
set "GOARM64=v8.0"
set "CC=%CC_ARM64%"
go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\arm64-v8a\libolcrtc2.so" ./cmd/olcrtc2-cnc
if errorlevel 1 exit /b 1

echo [2/2] armeabi-v7a libolcrtc2.so...
if exist "%CC_ARM32%" (
  set "GOARCH=arm"
  set "GOARM=7"
  set "GOARM64="
  set "CC=%CC_ARM32%"
  go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\armeabi-v7a\libolcrtc2.so" ./cmd/olcrtc2-cnc
  if errorlevel 1 echo Warning: armv7 failed
) else (
  echo armv7 clang missing — skip
)

echo === libolcrtc2.so BUILD SUCCESS ===
dir "%JNI%\arm64-v8a\libolcrtc2.so" "%JNI%\armeabi-v7a\libolcrtc2.so" 2>nul
endlocal
