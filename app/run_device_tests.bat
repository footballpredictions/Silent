@echo off
setlocal
set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
set RUNNER=com.silent.vpn.debug.test/com.silent.vpn.HiltTestRunner

if not exist "%ADB%" (
  echo adb not found: %ADB%
  exit /b 1
)

"%ADB%" devices
if errorlevel 1 exit /b 1

echo.
echo === All device tests (safe, no VPN reconnect) ===
"%ADB%" shell am instrument -w %RUNNER%

endlocal
