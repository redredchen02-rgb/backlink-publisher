@echo off
REM quickstart.bat - One-command dev environment setup for Windows
REM Equivalent of quickstart.sh (macOS)
REM
REM Usage: double-click or run: scripts\quickstart.bat
REM Prereq: Python 3.11+ (https://www.python.org/downloads/)

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "REPO_DIR=%SCRIPT_DIR%.."
cd /d "%REPO_DIR%"

echo === backlink-publisher quickstart (Windows) ===
echo Repo: %REPO_DIR%
echo.

REM ---- 1) Check Python version ----
python --version >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found
    echo   Install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version 2>&1 | findstr "3.1[12]" >nul
if errorlevel 1 (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
    echo ERROR: Need Python 3.11 or 3.12, got: %PY_VER%
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Python: %%v

REM ---- 2) Create venv ----
if not exist "%REPO_DIR%\.venv" (
    echo Creating .venv...
    python -m venv "%REPO_DIR%\.venv"
)

REM ---- 3) Install dev deps ----
echo Installing backlink-publisher[dev]...
"%REPO_DIR%\.venv\Scripts\python" -m pip install -e "%REPO_DIR%[dev]" -q

REM ---- 4) Playwright (optional) ----
echo.
echo Playwright browser (for channel binding)...
"%REPO_DIR%\.venv\Scripts\python" -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); p.stop()" 2>nul
if errorlevel 1 (
    echo Installing Playwright chromium...
    "%REPO_DIR%\.venv\Scripts\python" -m playwright install chromium
) else (
    echo Playwright ready
)

REM ---- 5) Config dir ----
set "CONFIG_DIR=%USERPROFILE%\.config\backlink-publisher"
if not "%BACKLINK_PUBLISHER_CONFIG_DIR%"=="" set "CONFIG_DIR=%BACKLINK_PUBLISHER_CONFIG_DIR%"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"
if not exist "%CONFIG_DIR%\config.toml" (
    if exist "%REPO_DIR%\config.example.toml" (
        echo Creating example config at %CONFIG_DIR%\config.toml
        copy "%REPO_DIR%\config.example.toml" "%CONFIG_DIR%\config.toml" >nul
    )
)

REM ---- 6) Permission check ----
echo Checking credential permissions...
"%REPO_DIR%\.venv\Scripts\python" "%SCRIPT_DIR%audit_credential_permissions.py" --fix 2>nul || echo   (audit done)

REM ---- 7) Run quick tests ----
echo.
echo Running tests (fast subset)...
cd /d "%REPO_DIR%"
set "PYTHONHASHSEED=0"
"%REPO_DIR%\.venv\Scripts\python" -m pytest tests/ -x -q --timeout=30 -k "not real_" --tb=short

echo.
echo ============ Done! ============
echo.
echo To start WebUI:
echo   Double-click start-webui.bat
echo   or run:  .venv\Scripts\python webui.py
echo.
pause
