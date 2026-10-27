@echo off
rem First-time phone registration: PC -> WireGuard -> Android wireless debugging (ADB).
rem Guide: docs\PHONE_SETUP.md. The pairing code is piped to the CLI; it is never saved
rem or put on a command line. Nothing is opened, uploaded or posted on the phone.
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
set "DEVICE_ID=%~1"
if not defined DEVICE_ID set "DEVICE_ID=primary"
if not exist "%PY%" (
  echo .venv not found. Install the repository first: docs\windows-install.md
  pause
  exit /b 1
)
"%PY%" -c "import uiautomator2, adbutils" 2>nul || "%PY%" -m pip install -r requirements-mobile.txt || goto failed
echo.
echo Phone name: %DEVICE_ID%. A new phone must use a different name, e.g. phone2 or phone3.
echo [Phone] Wi-Fi ON, WireGuard ON, then Settings ^> Developer options ^> Wireless debugging ON.
echo.
set /p PHONE_IP=Phone WireGuard IP (WireGuard app ^> tunnel ^> Addresses, e.g. 10.9.0.50):
set /p ADB_PORT=Connect port (Wireless debugging screen, number after the colon):
"%PY%" -X utf8 -m hotpost.mobile_reels_cli --device "%DEVICE_ID%" configure --phone-ip "%PHONE_IP%" --adb-port "%ADB_PORT%" || goto failed
echo.
echo [Phone] Tap "Pair device with pairing code" and keep that popup open.
set /p PAIR_PORT=Pairing port (number after the colon in the popup):
set /p CODE=6-digit Wi-Fi pairing code:
echo %CODE%| "%PY%" -X utf8 -m hotpost.mobile_reels_cli --device "%DEVICE_ID%" pair --pairing-port "%PAIR_PORT%" || goto failed
set "CODE="
"%PY%" -X utf8 -m hotpost.mobile_reels_cli --device "%DEVICE_ID%" connect || goto failed
echo.
echo Done: the phone is paired and registered. When the connect port changes later,
echo run phone-reconnect.cmd instead. Pairing is not needed again.
pause
exit /b 0

:failed
set "CODE="
echo.
echo Failed. See the Troubleshooting section of docs\PHONE_SETUP.md.
pause
exit /b 1
