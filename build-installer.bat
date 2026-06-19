@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === Silent VPN PC: clean + wdtt + NSIS installer ===

REM Уникальная папка сборки, чтобы electron-builder не пытался удалять заблокированный app.asar из прошлых прогонов.
for /f %%R in ('powershell -NoProfile -Command "Get-Random -Minimum 1000 -Maximum 999999"') do set OUT_DIR=build-release-v141-%%R
echo Output dir: !OUT_DIR!

REM Завершить запущенное приложение и процессы прошлой сборки
echo Stopping running processes...
taskkill /F /IM "Silent VPN.exe" 2>nul
taskkill /F /IM wdtt-client.exe 2>nul
taskkill /F /IM makensis.exe 2>nul
taskkill /F /IM electron-builder.exe 2>nul
timeout /t 2 /nobreak >nul

if exist "build-output" (
  echo Cleaning build-output...
  rd /s /q "build-output" 2>nul
  timeout /t 2 /nobreak >nul
)
if exist "dist\electron" (
  rd /s /q "dist\electron" 2>nul
)
if exist "build-output-v41" (
  rd /s /q "build-output-v41" 2>nul
)
if exist "build-output-old-locked" (
  rd /s /q "build-output-old-locked" 2>nul
)

echo [1/3] wdtt-client.exe...
cd wdtt-go
go build -ldflags="-s -w -checklinkname=0" -trimpath -o "..\resources\wdtt-client.exe" .
if errorlevel 1 (
  echo wdtt build FAILED
  exit /b 1
)
cd ..

if not exist "postcss.config.js" (
  echo ERROR: postcss.config.js missing - UI will break without Tailwind
  exit /b 1
)
if not exist "tailwind.config.js" (
  echo ERROR: tailwind.config.js missing - UI will break without Tailwind
  exit /b 1
)

echo [2/3] renderer...
if exist "dist\renderer" rd /s /q "dist\renderer" 2>nul
call npm run build:renderer
if errorlevel 1 exit /b 1

for %%F in (dist\renderer\assets\*.css) do (
  if %%~zF LSS 8000 (
    echo ERROR: CSS too small ^(%%~zF bytes^) - Tailwind did not compile. Aborting.
    exit /b 1
  )
  echo OK: renderer CSS %%~nxF ^(%%~zF bytes^)
)

echo [3/3] NSIS installer -^> !OUT_DIR!\
call npx electron-builder --win nsis --publish never --config.directories.output=!OUT_DIR!
if errorlevel 1 (
  echo electron-builder FAILED
  exit /b 1
)

for %%F in ("!OUT_DIR!\Silent VPN Setup *.exe") do (
  echo.
  echo OK: %%~fF
  if not exist "..\releases" mkdir "..\releases"
  copy /Y "%%~fF" "..\releases\" >nul
  echo Copied to releases\%%~nxF
)

echo Removing old build-release folders (keeping !OUT_DIR!)...
for /d %%D in (build-release*) do (
  if /I not "%%~nxD"=="!OUT_DIR!" (
    echo Removing %%D...
    rd /s /q "%%D" 2>nul
  )
)

echo === BUILD SUCCESS ===
