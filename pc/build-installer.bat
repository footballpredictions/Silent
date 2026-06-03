@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === Silent VPN PC: clean + wdtt + NSIS installer ===

REM Завершить зависшие процессы прошлой сборки
taskkill /F /IM makensis.exe 2>nul
taskkill /F /IM electron-builder.exe 2>nul
taskkill /F /IM "Silent VPN.exe" 2>nul

REM Всегда одна директория сборки — полная очистка перед стартом
if exist "build-output" (
  echo Cleaning build-output...
  rd /s /q "build-output" 2>nul
  timeout /t 2 /nobreak >nul
)
if exist "dist\electron" (
  rd /s /q "dist\electron" 2>nul
)

echo [1/3] wdtt-client.exe...
cd wdtt-go
go build -ldflags="-s -w -checklinkname=0" -trimpath -o "..\resources\wdtt-client.exe" .
if errorlevel 1 (
  echo wdtt build FAILED
  exit /b 1
)
cd ..

echo [2/3] renderer...
call npm run build:renderer
if errorlevel 1 exit /b 1

echo [3/3] NSIS installer -^> build-output\
call npx electron-builder --win nsis --publish never
if errorlevel 1 (
  echo electron-builder FAILED
  exit /b 1
)

for %%F in ("build-output\Silent VPN Setup *.exe") do (
  echo.
  echo OK: %%~fF
  if not exist "..\releases" mkdir "..\releases"
  copy /Y "%%~fF" "..\releases\" >nul
  echo Copied to releases\%%~nxF
)

echo === BUILD SUCCESS ===
