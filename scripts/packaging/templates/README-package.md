# Backlink Publisher — Windows 封裝版參考文件

這份文件是 Windows 免安裝封裝版（zip 解壓縮即用）的**完整參考文件**，
涵蓋目錄結構、WebUI 與 CLI 兩種使用方式、設定檔位置、排程設定與疑難
排解。如果你是第一次使用，建議先看同一個資料夾裡的 `QUICK_START.txt`
或 `ONBOARDING.md`，這份文件適合之後查閱細節用。

---

## 這是什麼

Backlink Publisher 是一套自動化「內容產生 → 驗證 → 發布到多個平台」的
工具。這個封裝版本讓你不需要安裝 Python、Node.js 或任何開發工具，
解壓縮後雙擊即可在本機執行 WebUI 服務。

---

## 目錄結構

```
backlink-publisher-vX.Y.Z-win64\
├── python-embed\                  # 官方 Python embeddable 直譯器 + 已安裝的相依套件
│   ├── python.exe                 # 內建 Python 執行檔，不需要另外安裝 Python
│   ├── python311._pth
│   └── Lib\site-packages\         # backlink_publisher 本體 + 核心相依套件
├── app\
│   ├── webui.py                   # WebUI 進入點
│   ├── webui_app\                 # Flask 應用程式（含已建置好的前端 SPA）
│   ├── webui_store\                # 狀態儲存層
│   └── config.example.toml        # 設定檔範例（首次啟動時會複製一份到使用者設定目錄）
├── scripts\
│   ├── launch-webui.bat           # 主要進入點：啟動 WebUI 服務（一般使用者只需要這個）
│   ├── launch-cli.bat             # 進階功能：開啟已設好 PATH 的命令列殼層
│   ├── setup-wizard.bat           # 互動式首次設定精靈
│   ├── setup-scheduler.bat        # Windows 工作排程器設定輔助
│   ├── install-playwright.bat     # 選用：安裝 Medium / Velog 瀏覽器綁定所需的 Chromium
│   └── cli-shims\                 # 每個 CLI 指令一支 .bat（供 launch-cli.bat 使用）
│       ├── bp.bat
│       ├── plan-backlinks.bat
│       └── ...（共 49 個，對應 pyproject.toml 的 [project.scripts]）
├── README.md                   # 完整參考文件（本身即為繁體中文，無需另外的 README.zh.md）
├── QUICK_START.txt
├── ONBOARDING.md
└── config-minimal-example.toml
```

**重要：** `python-embed\` 資料夾本身就是完整可用的 Python 環境，
內含執行本程式所需的全部相依套件。你**不需要**、也**不應該**自行安裝
系統 Python、建立 `venv`，或把這個資料夾與你電腦上其他 Python 安裝
混用。這個封裝版本的整個重點就是「不依賴建置機器以外的任何東西」——
把整個資料夾搬到任何一台 Windows 電腦上（甚至完全沒裝過 Python 的
電腦），`scripts\launch-webui.bat` 都應該能正常啟動。

---

## 使用方式一：WebUI（主要、建議一般使用者使用）

雙擊 `scripts\launch-webui.bat`：

1. 開啟一個主控台視窗（保持開啟，關閉它就是停止服務）。
2. 監聽埠預設為 `8888`；若被占用會自動依序改用 `8889`、`8890`……不需要
   手動處理，實際使用的網址會印在主控台上。
3. 約 3 秒後自動開啟預設瀏覽器，導向 `http://127.0.0.1:<實際埠號>`。
4. 首次啟動會自動：
   - 從 `app\config.example.toml` 複製一份設定檔到
     `%USERPROFILE%\.config\backlink-publisher\config.toml`（如果該路徑
     還沒有設定檔的話）。
   - 產生並持久化一組 `SECRET_KEY`，存於
     `%USERPROFILE%\.config\backlink-publisher\.webui_secret_key`，之後
     每次啟動都會重複使用，不會每次重啟就讓已登入的工作階段失效。

WebUI 涵蓋內容建立、平台憑證綁定、發布、歷史紀錄查詢、健康監控等完整
功能，是**建議所有使用者預設使用的介面**。

---

## 使用方式二：CLI（進階、次要，一般使用者不需要）

雙擊 `scripts\launch-cli.bat` 會開一個命令提示字元視窗，並把
`scripts\cli-shims\` 加進當次工作階段的 PATH，讓你可以直接輸入指令
名稱使用，例如：

```batch
bp
REM 列出所有可用指令的分組總覽

plan-backlinks --help
REM 查看單一指令的完整說明

publish-backlinks --help
```

`bp`（不加參數執行）會印出所有指令依用途分組的總覽，包含：

- **Pipeline**：`plan-backlinks`、`validate-backlinks`、`publish-backlinks`、
  `recheck-backlinks`、`dispatch-backlinks`、`spray-backlinks`、
  `phase0-seal`、`report-anchors`
- **Channel**：`bind-channel`、`velog-login`、`medium-login`、`frw-login`、
  `cull-channels`、`keepalive-run`、`keepalive-status`、
  `keepalive-reset-exhausted`
- **Analysis**：`plan-gap`、`pr-opportunities`、`weights`、
  `equity-ledger`、`footprint`、`click-track`、`generate-backlink-text`、
  `canonical-expand`、`comment`、`probe-citations`、`probe-index`、
  `probe-ranking`、`publish-metrics`、`referral-attribute`
- **Diagnostics**：`gate-probe`、`platform-health`、`health-check`、
  `audit-state`、`preflight-targets`、`canary-targets`、`canary-seed`、
  `channel-scorecard`、`plan-check`、`verify-dofollow`、
  `recheck-overlay`、`debt-report`、`decay-alert`
- **State**：`backup-state`、`restore-state`
- **Runs**：`bp-runs`、`resume`

這個 CLI 殼層是給想直接操作管線（例如批次執行 `plan-backlinks |
validate-backlinks | publish-backlinks` 這種串接流程）的進階使用者
準備的**選用能力**。**一般使用者請直接用 WebUI**，不需要學這一段。

> 每個 CLI 指令內部都是透過 `python-embed\python.exe` 呼叫對應的
> Python 函式，並自動設定好 `PYTHONPATH` 指向 `app\`，讓需要跨層匯入
> （例如讀取 `webui_store` 狀態）的指令也能正常執行，不需要額外設定。

---

## 設定檔位置

```
%USERPROFILE%\.config\backlink-publisher\config.toml
```

即「你的使用者資料夾\.config\backlink-publisher\config.toml」。

- 首次執行 `launch-webui.bat` 時，若這個位置還沒有 `config.toml`，會
  自動從封裝內的 `app\config.example.toml` 複製一份過去。
- 之後可以直接用文字編輯器修改（例如加入 Blogger 的 `[blogger.oauth]`
  憑證），存檔後重新啟動 WebUI 即可套用新設定。
- 其他平台憑證檔案也存在同一個目錄底下，例如：
  - `telegraph-token.json`（Telegraph 帳號權杖，自動產生）
  - `devto-token.json`（dev.to API 金鑰）
  - `.webui_secret_key`（WebUI 工作階段密鑰）
  - Velog / Medium 的瀏覽器登入憑證（cookie / token）

**這整個 `%USERPROFILE%\.config\backlink-publisher\` 目錄與封裝資料夾
是分開的**——更新版本、搬移或刪除封裝資料夾都不會影響這裡保存的設定
與憑證（詳見下方「更新版本」）。

---

## 發布平台總覽

| 平台 | 綁定方式 | 需要的憑證 | 適合 |
|---|---|---|---|
| Telegraph | 自動建立 | 無（免帳號） | 第一次使用、快速測試 |
| dev.to | 貼上 API 金鑰 | dev.to 帳號的 API Key | 需要曝光但不追求 dofollow 連結 |
| Blogger | OAuth（Google Cloud Console） | OAuth client_id / client_secret | 已有 Google/Blogger 帳號的使用者 |
| Medium | 內建瀏覽器登入 | Medium 帳號登入（需 Playwright） | 想在 Medium 曝光的使用者 |
| Velog | 內建瀏覽器登入 | Velog 帳號登入（需 Playwright） | 想在 Velog 曝光的使用者 |

各平台的詳細憑證取得步驟見 `ONBOARDING.md` 的「選擇發布平台」章節。

---

## 安裝 Playwright（Medium / Velog 選用功能）

Medium 與 Velog 採「內建瀏覽器登入」的綁定方式，需要 Playwright 提供
的 Chromium 瀏覽器元件。只有要用到這兩個平台才需要安裝：

```
雙擊 scripts\install-playwright.bat
```

這一步會把瀏覽器下載到 `%USERPROFILE%\.config\backlink-publisher\`
底下的持久化路徑，不會裝進封裝資料夾本身，所以之後更新封裝版本、或
把封裝資料夾搬到別的路徑，都不需要重新下載瀏覽器。

只使用 Telegraph / dev.to / Blogger 的話，完全不需要執行這一步。

---

## 排程（定時自動執行）

若想讓發布流程定時自動執行（例如每天凌晨自動跑一次），雙擊：

```
scripts\setup-scheduler.bat
```

這支腳本會引導你把想要的指令（例如完整 pipeline）加進 **Windows 工作
排程器（Task Scheduler）**。若想手動設定，也可以自行開啟「工作排程器」
應用程式，新增一個「動作」：

- 程式/指令碼：封裝資料夾內 `python-embed\python.exe` 的完整路徑
- 引數：對應要執行的模組 / 函式（可比照 `scripts\cli-shims\` 底下對應
  指令 `.bat` 的呼叫方式）
- 開始位置：封裝資料夾的完整路徑

也可以用 `schtasks` 指令建立，例如（依實際路徑調整）：

```batch
schtasks /CREATE /SC DAILY /TN "Backlink Publisher Full Pipeline" ^
  /TR "\"C:\Path\To\backlink-publisher-vX.Y.Z-win64\scripts\cli-shims\publish-backlinks.bat\"" ^
  /ST 04:00 /RL HIGHEST /F
```

管理已建立的排程：

```batch
REM 列出所有 Backlink Publisher 排程
schtasks /QUERY /TN "Backlink Publisher*" /V

REM 立即執行一次
schtasks /RUN /TN "Backlink Publisher Full Pipeline"

REM 停止 / 刪除
schtasks /END /TN "Backlink Publisher Full Pipeline"
schtasks /DELETE /TN "Backlink Publisher Full Pipeline" /F
```

---

## 更新到新版本

1. 下載新版本的 ZIP 並解壓縮（可以先解到另一個資料夾，確認沒問題後
   再取代舊版）。
2. 用新版本的 `app\`（以及通常建議一併更新的 `python-embed\`、
   `scripts\`）取代舊版本的對應資料夾。
3. **不需要**特別備份設定：你的設定檔與各平台登入憑證都保存在
   `%USERPROFILE%\.config\backlink-publisher\`，這個位置**不在**封裝
   資料夾裡，所以即使你整個刪除舊版封裝資料夾、重新解壓縮新版，之前
   的設定與已綁定的帳號都會維持不變、不需要重新設定。

---

## 疑難排解

### Windows SmartScreen「Windows 已保護您的電腦」警告

第一次雙擊 `scripts\` 底下任何 `.bat` 檔時可能出現。這是 Windows 對
「未經數位簽章的小工具」的標準警告，不代表有病毒。點選「其他資訊」→
「仍要執行」即可繼續。目前這個封裝版本尚未申請程式碼簽章憑證（屬於
已知的既定摩擦點，非本次封裝範圍）。

### 防毒軟體把某個 .bat 檔「隔離」了（不同於上面的 SmartScreen 警告）

如果 `launch-webui.bat`、`launch-cli.bat`，或 `cli-shims\` 底下某個
指令的 `.bat` 檔**憑空消失，或雙擊完全沒有任何反應、連警告視窗都沒
跳出**，這通常代表防毒軟體已經在背景把它「隔離」了，跟 SmartScreen
的點擊確認警告是不同的失敗模式，需要不同的處理方式：打開防毒軟體的
「隔離區 / Quarantine / 保護記錄」，找到該檔案並選擇還原、或把封裝
資料夾加入防毒軟體的允許清單（allowlist）。

### 瀏覽器下載 ZIP 時被封鎖或自動刪除

部分瀏覽器對「內含 `.bat` 的壓縮檔」會在下載時攔截或標記為危險（屬於
Windows「網際網路標記 / Mark-of-the-Web」與瀏覽器下載防護的正常行為）。
到瀏覽器的下載記錄查看是否有「保留 / 仍要下載」的選項；若是公司或
學校的受管理電腦，這類限制通常是 IT 政策設定，請洽詢你的 IT 管理員。

### 8888 埠已被占用

不需要處理，`launch-webui.bat` 會自動改用 8889、8890……主控台會印出
實際使用的網址。

### 怎麼停止 WebUI

關閉 `launch-webui.bat` 開啟的主控台視窗即可。

### 找不到設定檔 / 想知道設定檔在哪

見上方「設定檔位置」章節：`%USERPROFILE%\.config\backlink-publisher\config.toml`。

### `python-embed\python.exe` 找不到 / 封裝不完整

代表 ZIP 解壓縮不完整或封裝資料夾結構被破壞，請重新解壓縮整個 ZIP，
不要只複製部分資料夾。

### 發布失敗

依序排查：

1. 網路連線是否正常。
2. 該平台的憑證（API 金鑰 / OAuth 授權 / 登入狀態）是否正確、是否過期。
3. 目標網址本身是否可正常打開、網址是否打錯。

若排查後仍失敗，到 WebUI 的「歷史紀錄 / History」頁面查看該筆記錄的
詳細錯誤訊息。

### 如何安裝 Playwright（Medium / Velog）

雙擊 `scripts\install-playwright.bat`，見上方「安裝 Playwright」章節。

### 如何設定排程自動執行

雙擊 `scripts\setup-scheduler.bat`，見上方「排程」章節。

---

## 更多資訊

（本檔案 `README.md` 就是最完整的參考文件；以下是同一個資料夾裡的其他文件）

- 新手完整「從 0 到 1」教學：`ONBOARDING.md`
- 最短操作步驟：`QUICK_START.txt`
- 想從原始碼自行建置（開發者向）：見專案原始碼倉庫根目錄的 `README.md` / `AGENTS.md`（不隨此封裝版本一起提供）
