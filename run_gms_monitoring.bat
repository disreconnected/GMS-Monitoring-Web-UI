@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if /I "%~1"=="--test" (
    set GMS_BAT_TEST_CHILD=1
    python "%~dp0test_gms_monitor.py"
    exit /b %ERRORLEVEL%
)

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Install Python 3 from https://www.python.org/downloads/ and try again.
    exit /b 1
)

python -c "import curses" >nul 2>&1
if errorlevel 1 (
    echo Installing windows-curses ^(required for the TUI on Windows^)...
    python -m pip install windows-curses
    if errorlevel 1 (
        echo ERROR: Failed to install windows-curses.
        exit /b 1
    )
)

REM Avoid curses ERR from a cramped console (see safe_addnstr in gms_monitor.py)
mode con: cols=120 lines=45 >nul 2>&1
chcp 65001 >nul 2>&1

python "%~dp0gms_monitor.py" %*
exit /b %ERRORLEVEL%
