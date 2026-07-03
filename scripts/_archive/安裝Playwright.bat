@echo off
REM ================================================
REM  Playwright 瀏覽器安裝腳本
REM  
REM  用途：安裝 Chromium 瀏覽器（用於 Medium/Velog 等瀏覽器綁定功能）
REM  適用：解壓縮後的可攜式封裝版本
REM
REM  注意：
REM    - 僅需要 Medium 和 Velog 的瀏覽器綁定功能
REM    - API 模式的平台（Blogger、Telegraph 等）不需要此步驟
REM    - 安裝大小約 200MB
REM ================================================

title 安裝 Playwright 瀏覽器

setlocal enabledelayedexpansion

echo ================================================
echo   安裝 Playwright Chromium 瀏覽器
echo ================================================
echo.

REM ---- 1. 定位 ----
set "SCRIPT_DIR=%~dp0"
set "PKG_DIR=%SCRIPT_DIR%.."
set "PYTHON_CMD=%PKG_DIR%\python\python.exe"

if not exist "%PYTHON_CMD%" (
    echo [錯誤] 找不到 Python: %PYTHON_CMD%
    pause
    exit /b 1
)

REM ---- 2. 檢查是否已安裝 ----
echo [檢查] 測試 Playwright 是否已就緒...
"%PYTHON_CMD%" -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); p.stop()" 2>nul
if %errorlevel% equ 0 (
    echo [完成] Playwright Chromium 已安裝！
    echo.
    echo 你可以關閉此視窗。
    pause
    exit /b 0
)

REM ---- 3. 安裝 ----
echo [安裝] Playwright 未就緒，開始安裝 Chromium...
echo [安裝] 這可能需要幾分鐘，請耐心等待...
echo.

"%PYTHON_CMD%" -m playwright install chromium

if %errorlevel% neq 0 (
    echo.
    echo [錯誤] 安裝失敗！
    echo   請檢查網路連線後重試。
    pause
    exit /b 1
)

REM ---- 4. 安裝系統依賴（Windows 可能需要） ----
echo.
echo [安裝] 安裝系統依賴...
"%PYTHON_CMD%" -m playwright install-deps chromium 2>nul

echo.
echo ================================================
echo   安裝完成！
echo ================================================
echo.
echo   Chromium 瀏覽器已安裝完成。
echo   現在可以使用 Medium 和 Velog 的瀏覽器綁定功能。
echo.
pause
