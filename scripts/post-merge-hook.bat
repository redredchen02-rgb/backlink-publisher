@echo off
REM post-merge-hook.bat - Windows git post-merge hook for backlink-publisher
REM
REM Install:
REM   copy scripts\post-merge-hook.bat .git\hooks\post-merge
REM
REM Detects bp-* worktrees merged into main after git pull.
REM Set BACKLINK_PUBLISHER_WORKTREE_AUTOREMOVE=1 for auto-cleanup.

setlocal enabledelayedexpansion

REM Only run on main branch
for /f %%b in ('git symbolic-ref --short -q HEAD 2^>nul') do set "BRANCH=%%b"
if /i not "%BRANCH%"=="main" exit /b 0

set "REPO_ROOT="
for /f %%r in ('git rev-parse --show-toplevel 2^>nul') do set "REPO_ROOT=%%r"
if "%REPO_ROOT%"=="" exit /b 0

set "PRUNE_SCRIPT=%REPO_ROOT%\scripts\prune-stale-worktrees.sh"
if not exist "%PRUNE_SCRIPT%" exit /b 0

REM Run stale worktree check (needs Git Bash)
if exist "%PROGRAMFILES%\Git\bin\bash.exe" (
    "%PROGRAMFILES%\Git\bin\bash.exe" "%PRUNE_SCRIPT%" --dry-run 2>nul
    if errorlevel 1 (
        echo [post-merge] Stale worktrees detected. Clean up with:
        echo   bash scripts\prune-stale-worktrees.sh
    )
) else (
    REM No Git Bash, skip auto-detection
    exit /b 0
)

REM Optionally restart WebUI
call "%REPO_ROOT%\..\restart_webui.bat" 2>nul || exit /b 0
