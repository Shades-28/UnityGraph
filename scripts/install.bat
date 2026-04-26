@echo off
REM UnityGraph one-shot installer for Windows.
REM Detects Python, installs pipx if missing, installs unitygraph globally
REM via pipx so it's available on PATH everywhere.

setlocal enabledelayedexpansion

echo.
echo === UnityGraph installer (Windows) ===
echo.

REM 1. Detect Python 3.11+
set "PYTHON_CMD="
for %%P in (python python3 py) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2 delims= " %%V in ('%%P --version 2^>^&1') do (
            set "PYVER=%%V"
            for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
                if %%a geq 3 if %%b geq 11 (
                    set "PYTHON_CMD=%%P"
                    goto :got_python
                )
            )
        )
    )
)

:got_python
if "%PYTHON_CMD%"=="" (
    echo [error] Python 3.11 or newer is required but was not found on PATH.
    echo.
    echo Install Python from https://www.python.org/downloads/
    echo Be sure to check "Add Python to PATH" during install.
    exit /b 1
)

echo [ok] Found %PYTHON_CMD% (version %PYVER%)

REM 2. Make sure pip is current and pipx is installed
echo.
echo Installing pipx (Python's tool installer)...
%PYTHON_CMD% -m pip install --user --upgrade pip pipx >nul 2>&1
if errorlevel 1 (
    echo [error] pip / pipx install failed. Run "%PYTHON_CMD% -m pip install --user --upgrade pipx" manually.
    exit /b 1
)
%PYTHON_CMD% -m pipx ensurepath >nul 2>&1

REM 3. Install unitygraph
echo.
echo Installing unitygraph...
%PYTHON_CMD% -m pipx install unitygraph --force
if errorlevel 1 (
    echo [error] unitygraph install failed.
    exit /b 1
)

echo.
echo === Done. ===
echo.
echo Next:
echo   1. Restart your terminal (so the pipx PATH update takes effect)
echo   2. cd into your Unity project
echo   3. Run: unitygraph init .
echo   4. Run: unitygraph build .
echo.
echo No Unity project handy? Try the bundled demo:
echo   unitygraph init --demo my-demo
echo   cd my-demo
echo   unitygraph build .
echo   unitygraph viz graph-out\graph.json
echo.
endlocal
