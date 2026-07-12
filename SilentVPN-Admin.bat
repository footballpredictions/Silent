@echo off
:: Запуск Silent VPN от администратора + сброс сломанной службы WG (0.5.3 vs 1.1).
cd /d "%~dp0"

set "EXE="
if exist "Silent VPN.exe" set "EXE=%~dp0Silent VPN.exe"
if not defined EXE if exist "win-unpacked\Silent VPN.exe" set "EXE=%~dp0win-unpacked\Silent VPN.exe"

if not defined EXE (
  for /f "delims=" %%D in ('dir /b /ad /o-d "%~dp0build-debug-*" 2^>nul') do (
    if exist "%~dp0%%D\win-unpacked\Silent VPN.exe" (
      set "EXE=%~dp0%%D\win-unpacked\Silent VPN.exe"
      goto :found
    )
  )
)
:found

if not defined EXE (
  echo Silent VPN.exe не найден. Сначала: build-debug.bat
  pause
  exit /b 1
)

echo Закрываю Silent VPN / wdtt-client...
taskkill /F /IM "Silent VPN.exe" 2>nul
taskkill /F /IM wdtt-client.exe 2>nul
timeout /t 1 /nobreak >nul

:: Поднять UAC один раз: почистить старую службу 0.5.3 и запустить приложение.
set "PS1=%TEMP%\silent-wg-admin-launch.ps1"
(
  echo $ErrorActionPreference = 'Continue'
  echo Write-Host 'Uninstall old WireGuardTunnel$wg-turn...'
  echo $pf = 'C:\Program Files\WireGuard\wireguard.exe'
  echo $pd = 'C:\ProgramData\SilentVPN\wireguard\wireguard.exe'
  echo if ^(Test-Path $pf^) { ^& $pf /uninstalltunnelservice wg-turn 2^>^&1 | Out-Host }
  echo elseif ^(Test-Path $pd^) { ^& $pd /uninstalltunnelservice wg-turn 2^>^&1 | Out-Host }
  echo sc.exe stop 'WireGuardTunnel$wg-turn' 2^>^&1 | Out-Null
  echo sc.exe delete 'WireGuardTunnel$wg-turn' 2^>^&1 | Out-Null
  echo Start-Sleep -Milliseconds 500
  echo # Заменить залипший 0.5.3 в ProgramData на системный 1.1
  echo if ^(Test-Path $pf^) {
  echo   New-Item -ItemType Directory -Force -Path 'C:\ProgramData\SilentVPN\wireguard' | Out-Null
  echo   Copy-Item -Force $pf 'C:\ProgramData\SilentVPN\wireguard\wireguard.exe' -ErrorAction SilentlyContinue
  echo   Copy-Item -Force 'C:\Program Files\WireGuard\wg.exe' 'C:\ProgramData\SilentVPN\wireguard\wg.exe' -ErrorAction SilentlyContinue
  echo   Write-Host 'ProgramData wireguard refreshed from Program Files'
  echo }
  echo Write-Host 'Starting Silent VPN elevated...'
  echo Start-Process -FilePath '%EXE%'
) > "%PS1%"

echo Запрос UAC (очистка WG + запуск)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%PS1%'"
del "%PS1%" 2>nul
