@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === Silent VPN PC: DEBUG build (unpacked) ===
set DEBUG_BUILD=1

echo module.exports = { DEBUG_BUILD: true };> src\main\buildFlags.js

taskkill /F /IM "Silent VPN.exe" 2>nul
taskkill /F /IM wdtt-client.exe 2>nul
timeout /t 1 /nobreak >nul

for /f %%R in ('powershell -NoProfile -Command "Get-Random -Minimum 1000 -Maximum 999999"') do set OUT_DIR=build-debug-%%R
echo Output dir: !OUT_DIR!

echo [1/3] wdtt-client.exe...
cd wdtt-go
set GOOS=windows
set GOARCH=amd64
set CGO_ENABLED=0
go build -ldflags="-s -w -checklinkname=0" -trimpath -o "..\resources\wdtt-client.exe" .
if errorlevel 1 (
  echo wdtt build FAILED
  exit /b 1
)
cd ..

echo [2/3] renderer (debug mode)...
if exist "dist\renderer" rd /s /q "dist\renderer" 2>nul
call npx vite build --mode debug --outDir dist/renderer
if errorlevel 1 exit /b 1

echo [3/3] electron-builder dir -^> !OUT_DIR!\
set DEBUG_BUILD=1
call npx electron-builder --win dir --publish never --config.directories.output=!OUT_DIR!
if errorlevel 1 (
  echo electron-builder FAILED
  exit /b 1
)

for /d %%D in ("!OUT_DIR!\win-unpacked") do (
  echo.
  echo OK: %%~fD\Silent VPN.exe
  echo Debug build — logs, hashes and VK modes enabled.
)

echo === DEBUG BUILD SUCCESS ===
