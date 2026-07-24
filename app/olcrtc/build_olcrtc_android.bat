@echo off
setlocal
set "APP_ROOT=%~dp0.."
set "JNI=%APP_ROOT%\src\main\jniLibs"
set "OLCRTC=%APP_ROOT%\..\..\vendor\olcrtc"
if not exist "%OLCRTC%\cmd\olcrtc" (
  echo Error: vendor\olcrtc not found at %OLCRTC%
  exit /b 1
)
if not exist "%JNI%\arm64-v8a" mkdir "%JNI%\arm64-v8a"
if not exist "%JNI%\armeabi-v7a" mkdir "%JNI%\armeabi-v7a"

set "CGO_ENABLED=0"
set "GOOS=android"
set "LDFLAGS=-s -w -checklinkname=0"

echo [1/2] arm64-v8a libolcrtc.so...
set "GOARCH=arm64"
set "GOARM="
cd /d "%OLCRTC%"
go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\arm64-v8a\libolcrtc.so" ./cmd/olcrtc
if errorlevel 1 exit /b 1

echo [2/2] armeabi-v7a libolcrtc.so...
set "GOARCH=arm"
set "GOARM=7"
go build -trimpath -ldflags "%LDFLAGS%" -o "%JNI%\armeabi-v7a\libolcrtc.so" ./cmd/olcrtc
if errorlevel 1 (
  echo Warning: armv7 build failed — arm64-only OK for most devices
) else (
  echo armv7 OK
)

echo === libolcrtc.so BUILD SUCCESS ===
dir "%JNI%\arm64-v8a\libolcrtc.so"
endlocal
