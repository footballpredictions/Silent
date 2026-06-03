@echo off
setlocal enabledelayedexpansion

echo === Building Go libclient for Android (cascade groups) ===

set "PROJECT_ROOT=%~dp0"
set "GO_CLIENT_DIR=%PROJECT_ROOT%wdtt-go"
set "ANDROID_JNILIBS=%PROJECT_ROOT%src\main\jniLibs"

if defined ANDROID_HOME (
  set "SDK_PATH=%ANDROID_HOME%"
) else if defined ANDROID_SDK_ROOT (
  set "SDK_PATH=%ANDROID_SDK_ROOT%"
) else if exist "%PROJECT_ROOT%local.properties" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%PROJECT_ROOT%local.properties") do (
    if "%%A"=="sdk.dir" set "SDK_PATH=%%B"
  )
  set "SDK_PATH=!SDK_PATH:\\=\!"
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
set "CC_PATH_ARM64=%TOOLCHAIN%\aarch64-linux-android29-clang.cmd"
set "CC_PATH_ARM32=%TOOLCHAIN%\armv7a-linux-androideabi29-clang.cmd"

if not exist "%CC_PATH_ARM64%" (
  echo Error: arm64 clang not found
  exit /b 1
)
if not exist "%CC_PATH_ARM32%" (
  echo Error: arm32 clang not found
  exit /b 1
)

set "GOOS=android"
set "CGO_ENABLED=1"

cd /d "%GO_CLIENT_DIR%"
go mod download
if %errorlevel% neq 0 exit /b 1

if not exist "%ANDROID_JNILIBS%\arm64-v8a" mkdir "%ANDROID_JNILIBS%\arm64-v8a"
if not exist "%ANDROID_JNILIBS%\armeabi-v7a" mkdir "%ANDROID_JNILIBS%\armeabi-v7a"

echo [1/2] arm64-v8a...
set "GOARCH=arm64"
set "GOARM="
set "CC=%CC_PATH_ARM64%"
go build -ldflags="-s -w -checklinkname=0" -trimpath -o "%ANDROID_JNILIBS%\arm64-v8a\libclient.so" .
if %errorlevel% neq 0 exit /b 1

echo [2/2] armeabi-v7a...
set "GOARCH=arm"
set "GOARM=7"
set "CC=%CC_PATH_ARM32%"
go build -ldflags="-s -w -checklinkname=0" -trimpath -o "%ANDROID_JNILIBS%\armeabi-v7a\libclient.so" .
if %errorlevel% neq 0 exit /b 1

echo === libclient.so BUILD SUCCESS ===
