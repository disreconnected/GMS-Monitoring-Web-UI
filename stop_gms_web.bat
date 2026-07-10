@echo off
setlocal
cd /d "%~dp0"

set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"

echo %PORT%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo Invalid port: %PORT%. Provide a numeric port, e.g. stop_gms_web.bat 8765
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

echo Stopping GMS Monitoring web server on port %PORT%...

powershell -NoProfile -Command ^
  "$port = %PORT%;" ^
  "$stopped = 0;" ^
  "Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |" ^
  "Select-Object -ExpandProperty OwningProcess -Unique |" ^
  "ForEach-Object {" ^
  "  $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_) -ErrorAction SilentlyContinue;" ^
  "  if ($proc -and $proc.CommandLine -like '*gms_web_server.py*') {" ^
  "    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue;" ^
  "    $stopped++;" ^
  "  }" ^
  "};" ^
  "if ($stopped -eq 0) { exit 2 } else { exit 0 }"

if errorlevel 2 (
    echo No gms_web_server.py process found on port %PORT%.
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

if errorlevel 1 (
    echo Failed to stop process on port %PORT%.
    call "%~dp0_pause_on_error.bat"
    exit /b 1
)

echo GMS Monitoring web server stopped.
exit /b 0
