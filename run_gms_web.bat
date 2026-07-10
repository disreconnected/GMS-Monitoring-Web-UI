@echo off

setlocal

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



if not exist "web\node_modules" (

    echo Installing frontend dependencies...

    where npm >nul 2>&1

    if errorlevel 1 (

        echo npm not found. Install Node.js or run: cd web ^&^& npm install ^&^& npm run build

        call "%~dp0_pause_on_error.bat"

        exit /b 1

    )

    pushd web

    call npm install

    if errorlevel 1 (

        popd

        call "%~dp0_pause_on_error.bat"

        exit /b 1

    )

    call npm run build

    if errorlevel 1 (

        popd

        call "%~dp0_pause_on_error.bat"

        exit /b 1

    )

    popd

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

"%PYTHON%" gms_web_server.py %*

if errorlevel 1 call "%~dp0_pause_on_error.bat"

