@echo off
set "PYTHON="

REM Prefer the Python launcher (avoids broken venv shims first on PATH).
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3.13 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
    if not defined PYTHON for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
)

if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    set "PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
)

REM Last resort: first python.exe on PATH that has pip.
if not defined PYTHON (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PYTHON (
            "%%P" -m pip --version >nul 2>&1
            if not errorlevel 1 set "PYTHON=%%P"
        )
    )
)

if not defined PYTHON (
    echo ERROR: No usable Python found.
    echo Install Python 3 from https://www.python.org/downloads/
    echo and enable "Add python.exe to PATH", or install the py launcher.
    exit /b 1
)

exit /b 0
