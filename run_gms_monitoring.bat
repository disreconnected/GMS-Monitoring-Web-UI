@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if /I "%~1"=="--test" (
    call "%~dp0_resolve_python.bat"
    if errorlevel 1 exit /b 1
    set GMS_BAT_TEST_CHILD=1
    "%PYTHON%" "%~dp0test_gms_monitor.py"
    if errorlevel 1 call "%~dp0_pause_on_error.bat"
    exit /b %ERRORLEVEL%
)

call "%~dp0_resolve_python.bat"
if errorlevel 1 (
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

"%PYTHON%" -c "import curses" >nul 2>&1
if errorlevel 1 (
    echo Installing windows-curses ^(required for the TUI on Windows^)...
    "%PYTHON%" -m pip install windows-curses
    if errorlevel 1 (
        echo ERROR: Failed to install windows-curses.
        call "%~dp0_pause_on_error.bat"
        exit /b 1
    )
)

REM Avoid curses ERR from a cramped console (see safe_addnstr in gms_monitor.py)
mode con: cols=120 lines=45 >nul 2>&1
chcp 65001 >nul 2>&1

"%PYTHON%" "%~dp0gms_monitor.py" %*
if errorlevel 1 call "%~dp0_pause_on_error.bat"
exit /b %ERRORLEVEL%
