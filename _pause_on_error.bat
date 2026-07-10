@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if defined CI goto :skip_pause
if defined GMS_BAT_TEST_CHILD goto :skip_pause
echo.
echo Press any key to close...
pause >nul
:skip_pause
