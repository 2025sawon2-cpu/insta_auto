@echo off
rem Reconnect the already paired phone after its wireless debugging connect port changed
rem (reboot, Wi-Fi change, wireless debugging toggled). Guide: docs\PHONE_SETUP.md.
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
set "DEVICE_ID=%~1"
if not defined DEVICE_ID set "DEVICE_ID=primary"
set "PHONE_CONFIG=data\mobile-devices\%DEVICE_ID%.json"
if "%DEVICE_ID%"=="primary" set "PHONE_CONFIG=data\.mobile-device.json"
if not exist "%PHONE_CONFIG%" (
  echo No registered phone yet. Run phone-pair.cmd first.
  pause
  exit /b 1
)
echo [Phone] Wi-Fi ON, WireGuard ON, Wireless debugging ON.
echo Phone name: %DEVICE_ID%.
set /p ADB_PORT=New connect port (Wireless debugging screen, number after the colon):
"%PY%" -X utf8 -m hotpost.mobile_reels_cli --device "%DEVICE_ID%" configure --adb-port "%ADB_PORT%" || goto failed
"%PY%" -X utf8 -m hotpost.mobile_reels_cli --device "%DEVICE_ID%" connect || goto failed
echo.
echo Connected.
pause
exit /b 0

:failed
echo.
echo Failed. See the Troubleshooting section of docs\PHONE_SETUP.md.
pause
exit /b 1
