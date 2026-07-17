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
    if "%%A"=="sdk.dir"   set "SDK_PATH=%%B"
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
REM API 24 = Android 7.0 (minSdk). API 29+ тянет android_get_device_api_level —
REM на Android 9 (API 28) и ниже linker падает: CANNOT LINK EXECUTABLE libclient.so
set "ANDROID_API=24"
set "CC_PATH_ARM64=%TOOLCHAIN%\aarch64-linux-android%ANDROID_API%-clang.cmd"
set "CC_PATH_ARM32=%TOOLCHAIN%\armv7a-linux-androideabi%ANDROID_API%-clang.cmd"
set "CC_PATH_X86_64=%TOOLCHAIN%\x86_64-linux-android%ANDROID_API%-clang.cmd"
set "CC_PATH_X86=%TOOLCHAIN%\i686-linux-android%ANDROID_API%-clang.cmd"

if not exist "%CC_PATH_ARM64%" (
  echo Error: arm64 clang not found
  exit /b 1
)
if not exist "%CC_PATH_ARM32%" (
  echo Error: arm32 clang not found
  exit /b 1
)
if not exist "%CC_PATH_X86_64%" (
  echo Warning: x86_64 clang not found — пропуск x86_64
)
if not exist "%CC_PATH_X86%" (
  echo Warning: x86 clang not found — пропуск x86
)

set "GOOS=android"
set "CGO_ENABLED=1"
set "GO_LDFLAGS=-s -w -checklinkname=0"
REM Go 1.26.0–1.26.2: на 32-bit Android 8–10 (API 26–29) runtime пробует futex_time64,
REM zygote seccomp даёт SIGSYS → exit 159 (libclient сразу падает). Фикс в go1.26.3+.
REM https://github.com/golang/go/issues/77621
set "GOTOOLCHAIN=go1.26.3"

cd /d "%GO_CLIENT_DIR%"
go mod download
if %errorlevel% neq 0 exit /b 1

if not exist "%ANDROID_JNILIBS%\arm64-v8a" mkdir "%ANDROID_JNILIBS%\arm64-v8a"
if not exist "%ANDROID_JNILIBS%\armeabi-v7a" mkdir "%ANDROID_JNILIBS%\armeabi-v7a"
if not exist "%ANDROID_JNILIBS%\x86_64" mkdir "%ANDROID_JNILIBS%\x86_64"
if not exist "%ANDROID_JNILIBS%\x86" mkdir "%ANDROID_JNILIBS%\x86"

echo [1/4] arm64-v8a GOARM64=v8.0...
set "GOARCH=arm64"
set "GOARM="
set "GOARM64=v8.0"
set "GOAMD64="
set "GO386="
set "CC=%CC_PATH_ARM64%"
go build -ldflags="%GO_LDFLAGS%" -trimpath -o "%ANDROID_JNILIBS%\arm64-v8a\libclient.so" .
if %errorlevel% neq 0 exit /b 1

echo [2/4] armeabi-v7a GOARM=7...
set "GOARCH=arm"
set "GOARM=7"
set "GOARM64="
set "GOAMD64="
set "GO386="
set "CC=%CC_PATH_ARM32%"
go build -ldflags="%GO_LDFLAGS%" -trimpath -o "%ANDROID_JNILIBS%\armeabi-v7a\libclient.so" .
if %errorlevel% neq 0 exit /b 1

if exist "%CC_PATH_X86_64%" (
  echo [3/4] x86_64 GOAMD64=v1 baseline...
  set "GOARCH=amd64"
  set "GOARM="
  set "GOARM64="
  set "GOAMD64=v1"
  set "GO386="
  set "CC=%CC_PATH_X86_64%"
  go build -ldflags="%GO_LDFLAGS%" -trimpath -o "%ANDROID_JNILIBS%\x86_64\libclient.so" .
  if !errorlevel! neq 0 exit /b 1
) else (
  echo [3/4] x86_64 skipped
)

if exist "%CC_PATH_X86%" (
  echo [4/4] x86 GO386=sse2...
  set "GOARCH=386"
  set "GOARM="
  set "GOARM64="
  set "GOAMD64="
  set "GO386=sse2"
  set "CC=%CC_PATH_X86%"
  go build -ldflags="%GO_LDFLAGS%" -trimpath -o "%ANDROID_JNILIBS%\x86\libclient.so" .
  if !errorlevel! neq 0 exit /b 1
) else (
  echo [4/4] x86 skipped
)

echo === libclient.so BUILD SUCCESS ===
