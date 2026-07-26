@echo off
setlocal enabledelayedexpansion
REM libhev-socks5-tunnel.so — TUN→SOCKS для olcrtc (arm64 + armeabi-v7a для ТВ)

set "APP_ROOT=%~dp0.."
set "JNI=%APP_ROOT%\src\main\jniLibs"
set "HEV=%APP_ROOT%\..\..\vendor\hev-socks5-tunnel"
if not exist "%HEV%\Android.mk" (
  echo Error: vendor\hev-socks5-tunnel not found
  exit /b 1
)

if defined ANDROID_HOME (
  set "SDK_PATH=%ANDROID_HOME%"
) else if defined ANDROID_SDK_ROOT (
  set "SDK_PATH=%ANDROID_SDK_ROOT%"
) else (
  set "SDK_PATH=%LOCALAPPDATA%\Android\Sdk"
)

set "NDK_ROOT=%SDK_PATH%\ndk"
for /f "delims=" %%D in ('dir /b /ad /o-n "%NDK_ROOT%"') do (
  set "NDK_VER=%%D"
  goto :FoundNDK
)
:FoundNDK
set "NDK_BUILD=%NDK_ROOT%\%NDK_VER%\ndk-build.cmd"
echo Using NDK: %NDK_VER%

cd /d "%HEV%"
call "%NDK_BUILD%" NDK_PROJECT_PATH="%HEV%" NDK_APPLICATION_MK="%HEV%\Application.silent.mk" APP_BUILD_SCRIPT="%HEV%\Android.mk" -j4
if errorlevel 1 exit /b 1

if not exist "%JNI%\arm64-v8a" mkdir "%JNI%\arm64-v8a"
if not exist "%JNI%\armeabi-v7a" mkdir "%JNI%\armeabi-v7a"
for %%A in (arm64-v8a armeabi-v7a x86 x86_64) do (
  if not exist "%JNI%\%%A" mkdir "%JNI%\%%A"
  if exist "%HEV%\libs\%%A\libhev-socks5-tunnel.so" (
    copy /Y "%HEV%\libs\%%A\libhev-socks5-tunnel.so" "%JNI%\%%A\" >nul
  )
)
echo OK: hev → jniLibs arm64 + armeabi-v7a + x86 + x86_64
endlocal
