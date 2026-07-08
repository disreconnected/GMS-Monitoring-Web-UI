@echo off
setlocal
cd /d "%~dp0"

set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"

echo Stopping GMS Monitoring web server on port %PORT%...

powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

if errorlevel 1 (
    echo Failed to stop process on port %PORT%.
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

echo GMS Monitoring web server stopped.
exit /b 0
