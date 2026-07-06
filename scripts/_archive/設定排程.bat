@echo off
REM ================================================
REM  Windows 排程器設定腳本
REM  
REM  用途：互動式引導設定 Windows 排程器任務
REM  適用：解壓縮後的可攜式封裝版本
REM
REM  功能：
REM    - 設定每日定期執行管線
REM    - 設定定期 recheck（連結存活檢查）
REM    - 設定定期 keepalive（保活運行）
REM ================================================

title 設定 Windows 排程器

setlocal enabledelayedexpansion

echo ================================================
echo   Backlink Publisher 排程器設定
echo ================================================
echo.

REM ---- 1. 定位 ----
set "SCRIPT_DIR=%~dp0"
set "PKG_DIR=%SCRIPT_DIR%.."
set "PYTHON_CMD=%PKG_DIR%\python\python.exe"
set "APP_DIR=%PKG_DIR%\app"

if not exist "%PYTHON_CMD%" (
    echo [錯誤] 找不到 Python: %PYTHON_CMD%
    pause
    exit /b 1
)

REM ---- 2. 顯示選項 ----
echo 請選擇要設定的排程任務：
echo.
echo   [1] 每日管線執行
echo       自動執行完整管線（plan → validate → publish）
echo.
echo   [2] 定期 recheck（連結存活檢查）
echo       檢查已發布的連結是否仍然存活
echo.
echo   [3] 定期 keepalive（保活運行）
echo       保持連線活躍
echo.
echo   [4] 全部設定
echo       設定以上所有任務
echo.
echo   [0] 離開
echo.

set /p "choice=請選擇 (0-4): "

if "%choice%"=="0" goto :end
if "%choice%"=="1" goto :setup_pipeline
if "%choice%"=="2" goto :setup_recheck
if "%choice%"=="3" goto :setup_keepalive
if "%choice%"=="4" goto :setup_all

echo [錯誤] 無效的選擇
pause
goto :end

REM ---- 3. 設定每日管線 ----
:setup_pipeline
echo.
echo [設定] 每日管線執行
echo.
set /p "time=請輸入執行時間 (格式 HH:MM，例如 09:00): "

if "%time%"=="" (
    echo [錯誤] 時間不能為空
    pause
    goto :end
)

REM 建立批次檔
set "BAT_FILE=%PKG_DIR%\scripts\run-daily-pipeline.bat"
(
echo @echo off
echo title Backlink Publisher 每日管線
echo setlocal enabledelayedexpansion
echo cd /d "%APP_DIR%"
echo set "PYTHONPATH=%APP_DIR%;!PYTHONPATH!"
echo set "BACKLINK_PUBLISHER_CONFIG_DIR=%USERPROFILE%\.config\backlink-publisher"
echo.
echo echo [%date% %time%] 開始執行每日管線...
echo "%PYTHON_CMD%" -m backlink_publisher.cli.plan_backlinks --input seeds.jsonl --output planned.jsonl
echo "%PYTHON_CMD%" -m backlink_publisher.cli.validate_backlinks --input planned.jsonl --output validated.jsonl
echo "%PYTHON_CMD%" -m backlink_publisher.cli.publish_backlinks --input validated.jsonl --mode draft
echo echo [%date% %time%] 管線執行完成
) > "%BAT_FILE%"

REM 建立排程任務
schtasks /create /tn "BacklinkPublisher-DailyPipeline" /tr "\"%BAT_FILE%\"" /sc daily /st %time% /f
if %errorlevel% equ 0 (
    echo [完成] 每日管線排程已建立
    echo   執行時間: 每天 %time%
    echo   任務名稱: BacklinkPublisher-DailyPipeline
) else (
    echo [錯誤] 排程建立失敗，可能需要管理員權限
)

pause
goto :end

REM ---- 4. 設定定期 recheck ----
:setup_recheck
echo.
echo [設定] 定期 recheck（連結存活檢查）
echo.
set /p "time=請輸入執行時間 (格式 HH:MM，例如 14:00): "

if "%time%"=="" (
    echo [錯誤] 時間不能為空
    pause
    goto :end
)

set "BAT_FILE=%PKG_DIR%\scripts\run-recheck.bat"
(
echo @echo off
echo title Backlink Publisher recheck
echo setlocal enabledelayedexpansion
echo cd /d "%APP_DIR%"
echo set "PYTHONPATH=%APP_DIR%;!PYTHONPATH!"
echo set "BACKLINK_PUBLISHER_CONFIG_DIR=%USERPROFILE%\.config\backlink-publisher"
echo.
echo echo [%date% %time%] 開始 recheck...
echo "%PYTHON_CMD%" -m backlink_publisher.cli.recheck_backlinks --probe
echo echo [%date% %time%] recheck 完成
) > "%BAT_FILE%"

schtasks /create /tn "BacklinkPublisher-Recheck" /tr "\"%BAT_FILE%\"" /sc daily /st %time% /f
if %errorlevel% equ 0 (
    echo [完成] recheck 排程已建立
    echo   執行時間: 每天 %time%
    echo   任務名稱: BacklinkPublisher-Recheck
) else (
    echo [錯誤] 排程建立失敗，可能需要管理員權限
)

pause
goto :end

REM ---- 5. 設定定期 keepalive ----
:setup_keepalive
echo.
echo [設定] 定期 keepalive（保活運行）
echo.
set /p "time=請輸入執行時間 (格式 HH:MM，例如 08:00): "

if "%time%"=="" (
    echo [錯誤] 時間不能為空
    pause
    goto :end
)

set "BAT_FILE=%PKG_DIR%\scripts\run-keepalive.bat"
(
echo @echo off
echo title Backlink Publisher keepalive
echo setlocal enabledelayedexpansion
echo cd /d "%APP_DIR%"
echo set "PYTHONPATH=%APP_DIR%;!PYTHONPATH!"
echo set "BACKLINK_PUBLISHER_CONFIG_DIR=%USERPROFILE%\.config\backlink-publisher"
echo.
echo echo [%date% %time%] 開始 keepalive...
echo "%PYTHON_CMD%" -m backlink_publisher.cli.keepalive_run
echo echo [%date% %time%] keepalive 完成
) > "%BAT_FILE%"

schtasks /create /tn "BacklinkPublisher-Keepalive" /tr "\"%BAT_FILE%\"" /sc daily /st %time% /f
if %errorlevel% equ 0 (
    echo [完成] keepalive 排程已建立
    echo   執行時間: 每天 %time%
    echo   任務名稱: BacklinkPublisher-Keepalive
) else (
    echo [錯誤] 排程建立失敗，可能需要管理員權限
)

pause
goto :end

REM ---- 6. 全部設定 ----
:setup_all
call :setup_pipeline
call :setup_recheck
call :setup_keepalive
goto :end

:end
echo.
echo 排程設定完成。
echo.
echo 管理排程任務：
echo   查看: schtasks /query /tn "BacklinkPublisher-*"
echo   刪除: schtasks /delete /tn "BacklinkPublisher-DailyPipeline" /f
echo   手動執行: schtasks /run /tn "BacklinkPublisher-DailyPipeline"
echo.
pause
