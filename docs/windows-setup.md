# Windows Setup Guide — Backlink Publisher

本文件記錄 Backlink Publisher 在 Windows 上的安裝、配置、排程和路徑差異。

## 總覽

| macOS 元件 | Windows 等價物 | 說明 |
|---|---|---|
| `launcher.command` / `启动WebUI.command` | `scripts\launcher.ps1` + `启动WebUI.bat` | PowerShell 重啟循環啟動器 |
| `restart_webui.sh` | `restart_webui.bat` | 批次重啟腳本 |
| `quickstart.sh` | `scripts\quickstart.bat` | 一鍵開發環境設置 |
| `run-full-pipeline.sh` | `scripts\run-full-pipeline.bat` | Pipeline 執行器 |
| `launchd` `.plist` 服務 | Windows 工作排程器 (Task Scheduler) | 定時任務（見下方） |
| `.venv/bin/python` | `.venv\Scripts\python.exe` | Venv Python 路徑 |
| `$HOME/.config/backlink-publisher` | `%USERPROFILE%\.config\backlink-publisher` | 配置目錄 |
| `open http://...` | `start http://...` | 開瀏覽器 |
| `lsof` | `netstat -ano` | 端口偵測 |
| `kill -9 PID` | `taskkill /F /PID` | 強制終止程序 |
| `umask 077` | 無需（Windows 預設限制 ACL） | 檔案權限控制 |

## 前置需求

1. **Python 3.11+** — 從 [python.org](https://www.python.org/downloads/) 下載安裝，安裝時勾選 **"Add Python to PATH"**
2. **PowerShell 5.1+** — Windows 10/11 內置
3. **Git for Windows** — 從 [git-scm.com](https://git-scm.com/download/win) 下載 (選 Git Bash + Git from the command line)

> 如需使用 Playwright 瀏覽器綁定功能，首次執行 `scripts\quickstart.bat` 時會自動安裝 chromium。

## 快速開始

### 方式 A：一鍵設置

雙擊 `backlink-publisher\scripts\quickstart.bat` 或執行：

```batch
cd backlink-publisher
scripts\quickstart.bat
```

此腳本會自動：
1. 檢查 Python 版本 (需 3.11 或 3.12)
2. 建立 `.venv` 虛擬環境
3. 安裝 `.[dev]` 依賴
4. 安裝 Playwright Chromium（如需要）
5. 建立範例配置 `%USERPROFILE%\.config\backlink-publisher\config.toml`
6. 執行快速測試

### 方式 B：手動安裝

```batch
cd backlink-publisher
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m playwright install chromium
```

## 啟動 WebUI

### 雙擊啟動（推薦）

雙擊 workspace 根目錄的 `启动WebUI.bat`。

### 命令列啟動

```batch
cd backlink-publisher
.venv\Scripts\python webui.py
```

默認埠 `8888`，訪問 http://127.0.0.1:8888

### 帶 crash-restart 循環的完整啟動器

```batch
cd backlink-publisher
powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1
```

功能：
- 自動定位專案目錄
- 端口衝突檢測與自動順延（+20 埠）
- 60 秒內最多 3 次 restart
- 持久化 `SECRET_KEY`（存於 `%USERPROFILE%\.config\backlink-publisher\.webui_secret_key`）
- 首次啟動自動打開瀏覽器

## 路徑差異

### Python 解釋器

| 系統 | 啟用 venv | 執行程式 |
|---|---|---|
| macOS | `source .venv/bin/activate` | `.venv/bin/python` |
| Windows | `.venv\Scripts\activate` 或直接 | `.venv\Scripts\python.exe` |

### 配置目錄

| 系統 | 默認路徑 | 環境變數 |
|---|---|---|
| macOS | `~/.config/backlink-publisher/` | `BACKLINK_PUBLISHER_CONFIG_DIR` |
| Windows | `%USERPROFILE%\.config\backlink-publisher\` | `BACKLINK_PUBLISHER_CONFIG_DIR` |

### PYTHONPATH

| 系統 | 分隔符 |
|---|---|
| macOS | `:` (冒號) |
| Windows | `;` (分號) |

設定範例：
```batch
set PYTHONPATH=src;%PYTHONPATH%
```

## Pipeline 執行

### 完整 gap→publish 流程

```batch
cd backlink-publisher
scripts\run-full-pipeline.bat gap
```

### 自指定種子發布

```batch
type seeds.jsonl | scripts\run-full-pipeline.bat publish
```

### 環境變數

```batch
set BP_LANG=zh-CN
set BP_DESIRED=3
set BP_PUBLISH_MODE=draft
set BP_DRY_RUN=1
scripts\run-full-pipeline.bat gap
```

## 排程任務（取代 launchd）

macOS 使用 `launchd` `.plist` 做定時任務。Windows 使用 **工作排程器 (Task Scheduler)**。

### 建立 Pipeline 定時任務（每日 04:00）

1. 打開 **工作排程器** (Task Scheduler)
2. 右鍵 **工作排程器程式庫** → **建立工作…**
3. **一般** 標籤：
   - 名稱: `Backlink Publisher Full Pipeline`
   - 勾選 **不論使用者登入與否均執行**
   - 勾選 **以最高權限執行**
4. **觸發程序** 標籤 → **新增…**：
   - 開始工作: 依排程執行
   - 設定: 每日 / 04:00
5. **動作** 標籤 → **新增…**：
   - 動作: 啟動程式
   - 程式/指令碼: `C:\Path\To\backlink-publisher\.venv\Scripts\python.exe`
   - 引數: `-m backlink_publisher.cli.pipeline_orchestrator`
   - 開始位置: `C:\Path\To\backlink-publisher`
6. 設定環境變數（可選，在「設定」區改為手動編輯工作 → 編輯 XML… 或使用 `schtasks` 命令）：

```batch
schtasks /CREATE /SC DAILY /TN "Backlink Publisher Full Pipeline" /TR "'.venv\Scripts\python.exe' -m backlink_publisher.cli.pipeline_orchestrator" /ST 04:00 /RL HIGHEST /F
```

### 其他定時工作對應

| macOS `.plist` | Windows 排程建議 |
|---|---|
| `com.dex.bp-full-pipeline` (每日 04:00) | 每日觸發，執行 `.venv\Scripts\python.exe -m backlink_publisher.cli.pipeline_orchestrator` |
| `com.dex.bp-pipeline` (每 4 小時) | 每 4 小時觸發一次 |
| `com.dex.bp-optimization` | 每 2 小時觸發 `.venv\Scripts\python.exe -m backlink_publisher.cli.optimize_weights` |
| `com.dex.bp-recheck` | 每 12 小時觸發一次 |
| `com.dex.bp-keepalive` | 每 5 分鐘觸發一次 |
| `com.dex.bp-weights` (每週) | 每週觸發 |
| `com.dex.bp-citations` | 每天觸發 |

### 管理排程任務

```batch
REM 列出所有 BP 任務
schtasks /QUERY /TN "Backlink Publisher*" /V

REM 立即執行
schtasks /RUN /TN "Backlink Publisher Full Pipeline"

REM 停止
schtasks /END /TN "Backlink Publisher Full Pipeline"

REM 刪除
schtasks /DELETE /TN "Backlink Publisher Full Pipeline" /F
```

## WebUI 重啟

```batch
restart_webui.bat
```

Idempotent：不管是否已有 WebUI 在執行，都會先 kill 再啟動新實例。

## Git Hooks

macOS 使用 `scripts/install-post-merge-hook.sh` 安裝 git post-merge hook。
Windows 上等同操作：

```batch
REM 手動安裝 post-merge hook
copy scripts\post-merge-hook.bat .git\hooks\post-merge
```

> 注意：`scripts/install-post-merge-hook.sh` 使用了 `bash` 特有語法，
> Windows 上需要透過 **Git Bash** 執行，或在 PowerShell 中手動複製 hook 文件。

## 常見問題

### Q: 執行 `.ps1` 時出現執行原則錯誤

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Q: `netstat` 命令找不到

請以管理員身分執行命令提示字元，或確認 `C:\Windows\System32` 在 `PATH` 中。

### Q: 端口被佔用

啟動器 (`launcher.ps1`) 會自動嘗試順延埠，從 `PORT` (預設 8888) 開始依次嘗試到 `PORT + 20`。

手動檢查：
```batch
netstat -ano | findstr "8888"
tasklist /FI "PID eq 12345"
```

### Q: `wmic` 命令找不到

Windows 11 (24H2 以上) 預設不安裝 `wmic`。請改用 PowerShell：
```powershell
Get-CimInstance Win32_Process -Filter "CommandLine like '%webui.py%'"
```

## 參考

- macOS 原始啟動器: `docs/plans/2026-05-20-014` (啟動器架構設計)
- macOS 對應文件: `scripts/launcher.command`, `restart_webui.sh`
- 所有 Windows 新增文件:
  - `scripts/launcher.ps1` — PowerShell 重啟循環啟動器
  - `启动WebUI.bat` — 雙擊啟動包裝
  - `restart_webui.bat` — 批次重啟腳本
  - `scripts/quickstart.bat` — 一鍵環境設置
  - `scripts/run-full-pipeline.bat` — Pipeline 執行器
