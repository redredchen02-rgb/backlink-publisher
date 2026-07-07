<#
.SYNOPSIS
  Backlink Publisher WebUI 启动脚本 — Windows PowerShell 版
  等价于 launcher.command (macOS)
  
  功能：
  - 自动定位 backlink-publisher 目录
  - 端口检测 + 自动顺延
  - .venv 优先
  - 持久化 SECRET_KEY
  - 自动打开浏览器

  用法:  打开 PowerShell，cd 到项目目录，然后：
         powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1

  或者直接双击 启动WebUI.bat（推荐：更简单可靠）
#>

# 强制 UTF-8 输出，避免非 UTF-8 系统区域设置下的乱码 (Console 输出编码；
# 本文件本身另存为带 BOM 的 UTF-8，供 Windows PowerShell 5.1 在解析阶段
# 正确解码字面量中文字符串，二者缺一都无法根治乱码)。
# try/catch: 若 stdout 被重定向 (无实际 console 句柄)，此赋值会抛出
# IOException；重定向输出去排查问题的操作者不应该在这里就崩潰退出。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ---- 定位项目目录 (支持 scripts/ 和 workspace-root 两种位置) ----
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BP_DIR = $null

# Case 1: 脚本在 backlink-publisher\scripts\ 下 -> BP = ..
if (Test-Path (Join-Path $SCRIPT_DIR "..\webui.py")) {
    $BP_DIR = (Resolve-Path (Join-Path $SCRIPT_DIR "..")).Path
# Case 2: 脚本在 workspace-root\backlink-publisher\scripts\ 下 -> BP = ..\..
} elseif (Test-Path (Join-Path $SCRIPT_DIR "..\..\webui.py")) {
    $BP_DIR = (Resolve-Path (Join-Path $SCRIPT_DIR "..\..")).Path
# Case 3: 脚本在 workspace-root 下且有 backlink-publisher\webui.py
} elseif (Test-Path (Join-Path $SCRIPT_DIR "backlink-publisher\webui.py")) {
    $BP_DIR = (Resolve-Path (Join-Path $SCRIPT_DIR "backlink-publisher")).Path
} else {
    Write-Host "错误: 找不到 webui.py" -ForegroundColor Red
    Write-Host "已尝试: ..\, ..\..\, backlink-publisher\" -ForegroundColor Yellow
    Write-Host "请确认脚本在正确的位置" -ForegroundColor Yellow
    pause
    exit 1
}

Set-Location $BP_DIR
Write-Host "项目目录: $BP_DIR" -ForegroundColor Cyan

# ---- 设置 ----
$START_PORT = if ($env:PORT) { [int]$env:PORT } else { 8888 }
$BIND_HOST  = if ($env:BIND_HOST) { $env:BIND_HOST } else { "127.0.0.1" }

# ---- Python 解释器 ----
$venvPy = Join-Path $BP_DIR ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $PY = $venvPy
    Write-Host "使用虚拟环境 Python" -ForegroundColor Green
} else {
    $PY = "python"
    Write-Host "使用系统 Python（建议创建 .venv）" -ForegroundColor Yellow
}

# ---- 端口检测 ----
$port = $START_PORT
$found = $false
for ($i = 0; $i -lt 20; $i++) {
    $candidate = $START_PORT + $i
    $inUse = netstat -ano | Select-String "LISTENING" | Select-String ":$candidate\s"
    if (-not $inUse) {
        $port = $candidate
        $found = $true
        break
    }
    Write-Host "端口 $candidate 被占用，尝试下一个..." -ForegroundColor Yellow
}

if (-not $found) {
    Write-Host "错误: 连续 20 个端口都被占用" -ForegroundColor Red
    pause
    exit 1
}

# ---- 环境变量 ----
$env:PORT = "$port"
$env:BIND_HOST = $BIND_HOST
$env:PYTHONPATH = "src;$env:PYTHONPATH"
$env:FLASK_DEBUG = "0"
$env:BACKLINK_PUBLISHER_LITE = "1"
$env:BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED = "enforce"
$env:BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS = "mastodon"

# ---- SECRET_KEY ----
$configDir = if ($env:BACKLINK_PUBLISHER_CONFIG_DIR) {
    $env:BACKLINK_PUBLISHER_CONFIG_DIR
} else {
    "$env:USERPROFILE\.config\backlink-publisher"
}
$secretKeyFile = Join-Path $configDir ".webui_secret_key"
if (-not $env:SECRET_KEY) {
    if (Test-Path $secretKeyFile) {
        $env:SECRET_KEY = (Get-Content $secretKeyFile -Raw).Trim()
    } else {
        $null = New-Item -ItemType Directory -Path $configDir -Force -ErrorAction SilentlyContinue
        $newKey = [System.Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
        Set-Content -Path $secretKeyFile -Value $newKey -NoNewline
        $env:SECRET_KEY = $newKey
    }
}

$URL = "http://${BIND_HOST}:${port}"
if ($port -ne $START_PORT) {
    Write-Host "使用备用端口 $port" -ForegroundColor Yellow
}

# ---- 打开浏览器（延迟 3 秒，后台运行） ----
$null = Start-Job -ScriptBlock {
    Start-Sleep -Seconds 3
    Start-Process $using:URL
} -Name "BP-OpenBrowser"

# ---- 启动 ----
Write-Host ""
Write-Host "================================================"
Write-Host "  WebUI 启动中..."
Write-Host "  地址: $URL"
Write-Host "  关闭此窗口即可停止服务"
Write-Host "================================================"
Write-Host ""

& $PY serve.py

Write-Host "服务已停止"
pause
