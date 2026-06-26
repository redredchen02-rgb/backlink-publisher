@echo off
REM run-full-pipeline.bat - Windows pipeline runner (gap -> publish)
REM Equivalent of run-full-pipeline.sh (macOS)
REM
REM Modes:
REM   gap       equity-ledger -> plan-gap -> plan-backlinks -> validate -> publish
REM   publish   validate-backlinks <stdin> -> publish-backlinks
REM
REM Env vars: BP_LANG, BP_DESIRED, BP_URL_MODE, BP_PUBLISH_MODE,
REM           BP_PLATFORM, BP_OPTIMIZE, BP_DRY_RUN, BP_MAX_ROWS
REM
REM Usage:
REM   scripts\run-full-pipeline.bat gap
REM   set BP_DRY_RUN=1 && scripts\run-full-pipeline.bat gap
REM   type seeds.jsonl | scripts\run-full-pipeline.bat publish

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "REPO_DIR=%SCRIPT_DIR%.."
set "VENV=%REPO_DIR%\.venv"
set "LOG_DIR=%REPO_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "PYTHON=%VENV%\Scripts\python.exe"
cd /d "%REPO_DIR%"

REM ---- Defaults ----
if "%BP_LANG%"=="" set "BP_LANG=zh-CN"
if "%BP_DESIRED%"=="" set "BP_DESIRED=3"
if "%BP_URL_MODE%"=="" set "BP_URL_MODE=A"
if "%BP_PUBLISH_MODE%"=="" set "BP_PUBLISH_MODE=draft"
if "%BP_OPTIMIZE%"=="" set "BP_OPTIMIZE=1"
if "%BP_DRY_RUN%"=="" set "BP_DRY_RUN=0"
if "%BP_MAX_ROWS%"=="" set "BP_MAX_ROWS=1000"

set "TIMESTAMP=%DATE:/=-%_%TIME::=-%"
set "TIMESTAMP=%TIMESTAMP: =0%"
set "PIPELINE_LOG=%LOG_DIR%\pipeline-%TIMESTAMP%.log"
copy nul "%PIPELINE_LOG%" >nul

echo [pipeline] Starting pipeline (mode=%1%)...
echo.

REM ---- do_publish: stdin -> validate -> publish ----
:do_publish
echo [pipeline] Pipeline: validate -> publish

set "VALIDATED="
for /f "delims=" %%a in (
    '"%PYTHON%" -m backlink_publisher.cli.validate_backlinks --input /dev/stdin --max-rows %BP_MAX_ROWS% 2>>"%PIPELINE_LOG%"'
) do (
    set "VALIDATED=!VALIDATED!%%a
"
)
if "!VALIDATED!"=="" (
    echo [pipeline] FAIL: validate-backlinks failed
    exit /b 1
)

set "PUB_ARGS=--mode %BP_PUBLISH_MODE% --max-rows %BP_MAX_ROWS%"
if not "%BP_PLATFORM%"=="" set "PUB_ARGS=%PUB_ARGS% --platform %BP_PLATFORM%"
if "%BP_OPTIMIZE%"=="1" set "PUB_ARGS=%PUB_ARGS% --optimize"

echo !VALIDATED! | "%PYTHON%" -m backlink_publisher.cli.publish_backlinks %PUB_ARGS% -i /dev/stdin >> "%PIPELINE_LOG%" 2>&1
if errorlevel 1 (
    echo [pipeline] FAIL: publish-backlinks failed
    exit /b 1
)
echo [pipeline] OK: Pipeline complete
exit /b 0

REM ---- do_gap: equity -> plan-gap -> plan -> validate -> publish ----
:do_gap
echo [pipeline] Pipeline: equity-ledger -> plan-gap -> plan-backlinks -> validate -> publish

echo [pipeline] Step 1/5: equity-ledger ...
set "LEDGER="
for /f "delims=" %%a in (
    '"%PYTHON%" -m backlink_publisher.cli.equity_ledger 2>>"%PIPELINE_LOG%"'
) do set "LEDGER=!LEDGER!%%a
"
if "!LEDGER!"=="" (
    echo [pipeline] FAIL: equity-ledger failed
    exit /b 1
)

echo [pipeline] Step 2/5: plan-gap (desired=%BP_DESIRED% lang=%BP_LANG%) ...
set "GAP_SEEDS="
for /f "delims=" %%a in (
    'echo !LEDGER! ^| "%PYTHON%" -m backlink_publisher.cli.plan_gap --desired %BP_DESIRED% --language %BP_LANG% --url-mode %BP_URL_MODE% --publish-mode %BP_PUBLISH_MODE% 2>>"%PIPELINE_LOG%"'
) do set "GAP_SEEDS=!GAP_SEEDS!%%a
"
if "!GAP_SEEDS!"=="" (
    echo [pipeline] No gaps to fill - all targets satisfied
    exit /b 0
)

echo [pipeline] Step 3/5: plan-backlinks ...
set "PLANS="
for /f "delims=" %%a in (
    'echo !GAP_SEEDS! ^| "%PYTHON%" -m backlink_publisher.cli.plan_backlinks --input /dev/stdin --language %BP_LANG% 2>>"%PIPELINE_LOG%"'
) do set "PLANS=!PLANS!%%a
"
if "!PLANS!"=="" (
    echo [pipeline] FAIL: plan-backlinks failed
    exit /b 1
)

echo [pipeline] Step 4/5: validate-backlinks ...
set "VALIDATED="
for /f "delims=" %%a in (
    'echo !PLANS! ^| "%PYTHON%" -m backlink_publisher.cli.validate_backlinks --input /dev/stdin --max-rows %BP_MAX_ROWS% 2>>"%PIPELINE_LOG%"'
) do set "VALIDATED=!VALIDATED!%%a
"
if "!VALIDATED!"=="" (
    echo [pipeline] FAIL: validate-backlinks failed
    exit /b 1
)

echo [pipeline] Step 5/5: publish-backlinks ...
set "PUB_ARGS=--mode %BP_PUBLISH_MODE% --max-rows %BP_MAX_ROWS%"
if not "%BP_PLATFORM%"=="" set "PUB_ARGS=%PUB_ARGS% --platform %BP_PLATFORM%"
if "%BP_OPTIMIZE%"=="1" set "PUB_ARGS=%PUB_ARGS% --optimize"

echo !VALIDATED! | "%PYTHON%" -m backlink_publisher.cli.publish_backlinks %PUB_ARGS% -i /dev/stdin >> "%PIPELINE_LOG%" 2>&1
if errorlevel 1 (
    echo [pipeline] FAIL: publish-backlinks failed
    exit /b 1
)
echo [pipeline] OK: Pipeline complete
exit /b 0

REM ---- Entry point ----
set "MODE=%1"
if "%MODE%"=="" set "MODE=gap"

if /i "%MODE%"=="gap" (
    call :do_gap
) else if /i "%MODE%"=="publish" (
    call :do_publish
) else (
    echo Usage: %0 [gap^|publish]
    echo   gap      - equity-ledger -^> plan-gap -^> plan -^> validate -^> publish (default)
    echo   publish  - validate ^<stdin^> -^> publish-backlinks
    echo.
    echo Env: BP_LANG, BP_DESIRED, BP_URL_MODE, BP_PUBLISH_MODE, BP_PLATFORM, BP_OPTIMIZE, BP_DRY_RUN, BP_MAX_ROWS
    exit /b 1
)

set "EXIT_CODE=%errorlevel%"
echo [pipeline] Done (exit %EXIT_CODE%) - see %PIPELINE_LOG%
exit /b %EXIT_CODE%
