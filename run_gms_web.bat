@echo off
setlocal EnableExtensions
cd /d "%~dp0"

call "%~dp0_resolve_python.bat"
if errorlevel 1 (
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

echo Installing web server dependencies...
"%PYTHON%" -m pip install -r requirements_web.txt -q
if errorlevel 1 (
    echo Failed to install requirements_web.txt
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo npm not found. Install Node.js or run: cd web ^&^& npm install ^&^& npm run build
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

if not exist "web\node_modules" (
    echo Installing frontend dependencies...
    pushd web
    call npm install
    if errorlevel 1 (
        popd
        call "%~dp0_pause_on_error.bat"
        exit /b 1
    )
    popd
) else if exist "web\package-lock.json" (
    for %%F in ("web\package-lock.json") do set LOCK_TIME=%%~tF
    for %%D in ("web\node_modules") do set NODE_TIME=%%~tD
    if "%LOCK_TIME%" gtr "%NODE_TIME%" (
        echo Refreshing frontend dependencies...
        pushd web
        call npm install
        if errorlevel 1 (
            popd
            call "%~dp0_pause_on_error.bat"
            exit /b 1
        )
        popd
    )
)

echo Building current web UI...
pushd web
call npm run build
if errorlevel 1 (
    popd
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)
popd

echo.
echo Starting GMS Monitoring web server...
echo The secure dashboard URL will be printed below by the server.
echo Use that URL in your browser. After a restart, open the new URL again.
echo.
echo Optional Stormshield SNS monitoring:
echo   Pick or add the firewall in the dashboard's Firewall section (saved in gms_sns_sites.json).
echo   set GMS_SNS_PASSWORD=your-password   ^(optional: otherwise the dashboard asks once per run^)
echo   With the password set, saved sites are probed and connected automatically at startup;
echo   add --no-sns-autoconnect to skip that, or --sns-host 192.168.1.254 to force one firewall.
echo.
echo Pings, traceroute and throughput use the "Wi-Fi" adapter ^(church Wi-Fi^) only;
echo   add --source-interface "Other name" to pick another, or --source-interface "" to follow Windows.
echo.

"%PYTHON%" gms_web_server.py --source-interface "Wi-Fi" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" call "%~dp0_pause_on_error.bat"
exit /b %RC%
