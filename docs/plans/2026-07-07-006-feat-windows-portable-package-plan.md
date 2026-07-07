---
title: "feat: Windows 零安裝可攜式啟動包 (build-once, unzip-and-run)"
type: feat
status: active
date: 2026-07-07
---

# feat: Windows 零安裝可攜式啟動包

## Overview

目標：讓使用者拿到一個 ZIP 壓縮檔，解壓縮到任意目錄後，**不需安裝 Python、Node.js 或任何開發工具**，雙擊即可啟動 Backlink Publisher WebUI 服務，並附上從零開始的完整使用說明（首次設定 → 選擇平台 → 設定憑證 → 發布第一篇文章）。

這不是從零設計——`dist/backlink-publisher-v0.5.0-win64/` 已經有一份手動組裝的封裝雛形（`venv/`、`app/`、`scripts/`、README.md、QUICK_START.txt、ONBOARDING.md 都已存在且內容相當完整），但**沒有可重複執行的建置腳本**，而且研究過程中發現這份雛形實際上**無法在其他機器上啟動**（見下方「關鍵技術決策」與 Risks）。本計畫的核心工作是：修正這個可攜性問題、補上可重複建置的腳本，並讓文件與實際目錄結構一致。

## Problem Frame

使用者（非開發者）需要「拿到壓縮檔就能用」的體驗，但目前只有：
1. 一份給開發者用的手動安裝流程（`docs/windows-setup.md`：安裝 Python 3.11+ → 建 `.venv` → `pip install -e .[dev]`），不適合終端使用者。
2. 一份手動組裝、未納入版控（`dist/` 已被 `.gitignore`）、無建置腳本可重現的封裝產物，且其中的 `venv/` 資料夾實際上**綁定了建置機器上特定的 Python 安裝路徑**，換一台機器就無法啟動。

## Requirements Trace

- R1. 使用者解壓縮 ZIP 後，不需安裝任何開發工具，雙擊腳本即可啟動 WebUI 服務（`http://127.0.0.1:8888`，埠被占用時自動順延）。
- R2. 封裝內含完整使用說明（QUICK_START / ONBOARDING / README），涵蓋解壓縮 → 啟動 → 選擇發布平台 → 設定憑證 → 發布第一篇文章 → 常見問題，讓使用者能獨立走完「從 0 到 1」。
- R3. 封裝的產生過程可重複執行（一個建置指令），取代目前手動組裝、已知有 bug 的 `dist/` 產物；重跑建置不會產生巢狀重複目錄等雜訊。
- R4. 封裝解壓縮到與建置機器完全不同的路徑、且該機器**從未安裝過 Python** 時，仍能正常啟動 WebUI 與 CLI（可搬移 / 可重定位）。
- R5.（次要）維持既有 49 個 CLI 指令（`bp`、`plan-backlinks`、`publish-backlinks` 等，見 `pyproject.toml` `[project.scripts]`）的可用性，供進階使用者手動操作管線。

## Scope Boundaries

- 不製作 MSI / Inno Setup / NSIS 安裝程式——使用者要的是「壓縮檔」，維持可攜式 ZIP 形式。
- 不預先綁入 Playwright 瀏覽器（僅 Medium / Velog 兩個平台的瀏覽器綁定功能需要）——保留現有「選用安裝」腳本模式，避免封裝體積暴增。
- 不採用 PyInstaller / Nuitka 凍結成單一 exe——研究結論見「關鍵技術決策」，理由是動態註冊的 adapter registry 模式容易在凍結時漏掉 hidden-import，且 onefile 模式有已知的防毒誤判與冷啟動變慢問題。
- 不修改 `src/backlink_publisher` 執行期程式碼——這是純建置 / 封裝層的工作。
- 不處理 code-signing（Windows SmartScreen 對未簽章 .bat/.exe 的警告）——記錄在 Risks，作為已知的啟動摩擦，非本計畫範圍。
- 不建立 GitHub Release 或發布到任何公開通路——沿用既有 `2026-06-23-002-release-v0.5.0-prep-plan.md` 的先例，發布時機由使用者自行決定。

### Deferred to Separate Tasks

- 自動更新機制（封裝內偵測新版本並提示）：未來迭代。
- Code-signing 憑證申請與簽章流程：未來迭代，需要使用者決定是否購買憑證。
- 清理現有 `dist/backlink-publisher-v0.5.0-win64/`（含其內部意外巢狀的 `backlink-publisher-v0.5.1-win64/`）這份手動產物：完全延後處理，不在本計畫實作範圍內。Unit 5 的「先清空舊輸出」邏輯只清空**當次建置版本自己的輸出目錄**（`dist/backlink-publisher-vX.Y.Z-win64/`），不會觸碰這份舊的手動產物；待新建置流程驗證通過後，建議手動刪除舊產物，不需要另開任務追蹤。

## Context & Research

### Relevant Code and Patterns

- `dist/backlink-publisher-v0.5.0-win64/scripts/launch-webui.bat`——埠偵測（8888~8907 自動順延）、首次執行複製 `config.example.toml`、`SECRET_KEY` 持久化到 `%USERPROFILE%\.config\backlink-publisher\.webui_secret_key`、延遲 3 秒開瀏覽器：這些邏輯已經寫得很完整，可直接沿用，只需把 `venv\Scripts\python.exe` 換成新的內嵌直譯器路徑。**注意：`dist/` 已被 `.gitignore`，實作者若從乾淨 checkout 開始，這個資料夾可能不存在——上述邏輯已在本文件（Key Technical Decisions、Unit 2 Approach）中完整內嵌成文字說明，若 `dist/` 資料夾不存在，以本文件的文字描述為準，不需要依賴這個外部參考。**
- `dist/backlink-publisher-v0.5.0-win64/{QUICK_START.txt,ONBOARDING.md,README.md}`——內容完整（含平台憑證取得步驟、常見問題），可作為新文件範本的基礎，只需修正目錄結構描述（見 Unit 4）。**同樣提醒：這個資料夾可能不存在於實作者的 checkout 中；若不存在，Unit 4 應直接依據本計畫描述的內容範圍重新撰寫，而非假設有現成檔案可複製。**
- `backlink-publisher/scripts/prep-release.sh`——現有的版本發布輔助腳本（版本號替換、towncrier CHANGELOG、跑測試），可作為「編號步驟 + 清楚印出進度」的腳本風格參考，但它不處理封裝，兩者互補而非重疊。
- `webui_app/routes/spa.py`——確認 SPA 是由 Flask 以靜態檔方式服務 `webui_app/spa_dist/`，執行期完全不需要 Node.js，只有建置期需要跑一次 `npm run build`。
- `src/backlink_publisher/cli/publish_backlinks/__main__.py`、`src/backlink_publisher/cli/admin/bind_channel.py` 等部分 CLI 模組有 `if __name__ == "__main__": main()`，但**並非全部**——直接審查後發現 `cli/publish/dispatch_backlinks.py`、`cli/ops/platform_health.py`、`cli/admin/state_backup.py` 等約 10 個模組沒有這個 guard（見 Key Technical Decisions），因此封裝不能統一假設 `python -m backlink_publisher.cli.<path>` 可行，必須改用 `pyproject.toml` 記錄的精確 `module:function` 目標逐一呼叫。
- `src/backlink_publisher/cli/bp.py`——`bp` 指令本身只是列出所有指令的說明頁（`GROUPS` 常數），不是 dispatcher；49 個 `[project.scripts]` 各自獨立，因此封裝需要逐一產生對應的啟動 shim，而非只做一個入口。

### Institutional Learnings

- `docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md`（已完成）：修正了兩類 Windows 主控台 / 子行程編碼問題——(1) `subprocess` 呼叫若未明確指定 `encoding="utf-8"` 會退回系統 ANSI codepage（如 `cp950`）而在中文內容上崩潰，已有 `_util/subprocess_env.py` 的 `utf8_child_env()` 可重用；(2) `.bat`/`.ps1` 若印出非 ASCII 文字，非 UTF-8 主控台 codepage 下會亂碼，需要 `chcp 65001 >nul`（`.bat`）或包 try/catch 的 `[Console]::OutputEncoding`（`.ps1`）防護。**新的封裝啟動腳本必須延續這兩個防護，否則會重現同一個 bug。** 該計畫的 Scope Boundaries 也明確寫著「不修改 `dist/backlink-publisher-v0.5.0-win64/**`，因為這些是`封裝時`從 `scripts/` 重新產生的建置產物」——但實際上目前並沒有這個「封裝時」腳本存在，這正是本計畫要補上的缺口。
- `docs/solutions/developer-experience/per-worktree-venv-vs-pythonpath-2026-05-19.md`：`pip install -e` 的可編輯安裝會把匯入路徑綁死在建置當下的絕對路徑；本計畫確認了 `dist/backlink-publisher-v0.5.0-win64/venv/Lib/site-packages/backlink_publisher/` 是**非**可編輯安裝的完整複製（`backlink_publisher-0.5.0.dist-info` 存在），這部分沒有問題——但下面「關鍵技術決策」發現了更根本的可攜性問題出在 venv 本身，而不是套件安裝方式。

### 已驗證的關鍵發現（本計畫研究過程中直接檢查得出，非既有文件記載）

檢查 `dist/backlink-publisher-v0.5.0-win64/venv/pyvenv.cfg`：

```
home = C:\Users\user\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none
```

且 `venv/Lib/` 底下**只有 `site-packages/`，沒有任何標準函式庫檔案**。這代表這個 venv 是用 `uv` 建立的一般 Windows venv，其直譯器 / 標準函式庫在執行期會去讀取 `pyvenv.cfg` 記錄的 `home` 路徑——也就是**建置者自己機器上** `uv` 管理的 Python 安裝目錄。**任何沒有裝過那個特定 `uv` Python 的機器，這個 `venv\Scripts\python.exe` 根本無法啟動**，這是目前 `dist/` 產物完全無法達成 R4（可搬移到其他機器）的根本原因，且是一個先前未被發現、未被記錄的 bug。

### External References

- Python 官方 embeddable 套件已知限制：`python3XX._pth` 預設關閉 `import site`（因此關閉 pip / site-packages），必須在建置期手動取消註解並加入 `Lib\site-packages` 路徑（[cpython#102169](https://github.com/python/cpython/issues/102169)）。
- venv 的「relocatable」支援已被官方認定為不可靠 / 已棄用（[Python Discourse 討論](https://discuss.python.org/t/making-venvs-relocatable-friendly/96177)）——呼應上面直接驗證到的 `pyvenv.cfg home=` 問題，排除「直接複製 venv 資料夾」作為封裝方式。
- PyInstaller onefile 模式有記錄在案的防毒軟體誤判問題（[pyinstaller#6754](https://github.com/pyinstaller/pyinstaller/issues/6754)），且動態 `importlib` 匯入（本專案的 adapter registry 模式）在凍結時容易漏收 hidden-import。

## Key Technical Decisions

- **改用 Python 官方 embeddable 套件（`python-3.11.x-embed-amd64.zip`）取代複製 `venv/` 資料夾**：理由見上方「已驗證的關鍵發現」——venv 依賴建置機器的 base Python 路徑，不可搬移；embeddable 套件本身就是設計給「內嵌到別的應用程式裡發布」用的獨立直譯器。
- **依賴套件安裝方式：在 embeddable 直譯器上 `pip install --target <embed>\Lib\site-packages .`（非 editable）**：只在建置機器上執行一次 pip，產出的資料夾本身不再需要 pip / venv / 任何 Python 安裝即可執行；`backlink_publisher` 本身以及 `[project.dependencies]` 列出的核心依賴（純 Python + 預編譯 wheel，無需編譯器）全部裝入同一個 `site-packages`。
- **不使用 pip 產生的 console-script `.exe`（如現有 `bp.exe`、`audit-state.exe`），也不能假設 `python -m <module>` 對所有指令都可行**：console-script exe 會把絕對直譯器路徑寫死在 shebang 裡，解壓縮到不同路徑就會失效；而直接審查原始碼發現，49 個 `[project.scripts]` 裡至少有約 10 個模組（如 `cli/publish/dispatch_backlinks.py`、`cli/ops/platform_health.py`、`cli/admin/state_backup.py` 等）**沒有** `if __name__ == "__main__":` guard，`python -m <module>` 對這些指令會靜默匯入模組後直接結束、不呼叫任何函式——沒有錯誤、沒有輸出，使用者會誤以為指令成功執行（`backup-state`/`restore-state` 更是同一個模組對應兩個不同函式，`-m` 完全無法區分該呼叫哪一個）。改為建置腳本讀取 `pyproject.toml` 的 `[project.scripts]` 精確的 `module:function` 目標，逐一產生用 `%~dp0` 相對路徑呼叫 `python-embed\python.exe -c "from <module> import <function>; <function>()"` 的 `.bat` shim——這正是 setuptools 自己產生 console-script 時使用的呼叫方式，對全部 49 個指令一體適用，不依賴 `__main__` guard 是否存在，也天然解決一個模組對應多個函式的問題。
- **所有 CLI shim 與 WebUI 啟動腳本都設定 `PYTHONPATH=<pkg_dir>\app`**：直接審查原始碼發現 `dispatch_backlinks.py` 等 CLI 模組在檔案最上層就 `from webui_store.channel_status import channel_status_store`，而 `webui_store` 只存在於封裝的 `app\` 底下、不在 site-packages 裡。若只有 `launch-webui.bat` 設定 `PYTHONPATH` 而 CLI shim 沒有，透過 `launch-cli.bat` 呼叫這類指令會直接 `ModuleNotFoundError`。因此建置腳本產生的每一個 `cli-shims/*.bat` 都比照 `launch-webui.bat` 設定同樣的 `PYTHONPATH`，不只是 WebUI 進入點需要。
- **SPA 前端在建置機器上先跑 `npm run build`，把 `webui_app/spa_dist/` 一起封裝進去**：確認 `webui_app/routes/spa.py` 只是把 `spa_dist/` 當靜態檔案送出，執行期完全不需要 Node.js。
- **Playwright 維持選用（不預設封裝）**：延續現有 `install-playwright.bat` 的選用安裝模式；瀏覽器下載目標改指向 `%USERPROFILE%\.config\backlink-publisher\` 底下的持久化路徑（而非解壓縮出來的暫時目錄），避免使用者之後更新封裝或搬移目錄時要重新下載。
- **既有啟動腳本的 UTF-8 防護必須原封保留**：所有新／修改的 `.bat` 都要有 `chcp 65001 >nul`，子行程呼叫沿用 `utf8_child_env()` 慣例，避免重現 `2026-07-03-001` 修過的編碼崩潰。
- **建置腳本以 Python 撰寫（`backlink-publisher/scripts/packaging/build_windows_package.py`）而非純 `.bat`**：下載 embeddable zip、修改 `._pth`、跑 pip、產生 shim、組裝目錄、打包 zip 這些步驟用 Python 處理錯誤與跨步驟狀態比 batch script 可靠，且與現有 `scripts/*.py` 慣例一致（`optimize_static.py`、`webwright_scaffold.py`）。
- **建置期供應鏈完整性防護**：（1）`python-3.11.x-embed-amd64.zip` 與 `get-pip.py` 下載後都比對建置腳本內硬編碼的預期 SHA-256，不符就中止建置——`get-pip.py` 是一個會以建置程序權限執行的任意腳本，先前的計畫草稿只驗證了 embeddable zip、沒驗證 `get-pip.py`，是不一致的防護缺口。（2）`[project.dependencies]` 在封裝建置時精確釘選版本（而非沿用 `pyproject.toml` 的開放區間），並在安裝完成後對 `site-packages` 跑一次 `pip-audit`（已是 `dev` extra 的一部分），發現已知 CVE 就中止建置——避免每次建置時日不同、PyPI 上游套件被置換或出現惡意版本而不自知，同時讓 Unit 5 的「兩次建置輸出應完全相同」冪等性測試不會因為版本區間造成假性失敗。（3）`pip install --target` 執行時加上 `--ignore-installed`（或等效的 `PYTHONNOUSERSITE=1`），避免啟用 `import site` 之後，pip 因為建置機器自己裝過同名套件而跳過複製，導致封裝結果隨建置機器環境而異、無法重現。
- **封裝資料檔案的明確涵蓋**：`backlink_publisher` 有非 `.py` 的封裝資料（例如 `publishing/adapters/catalog/*.yaml`，供 `txtfyi` 等平台的目錄載入器讀取），但 `pyproject.toml` 目前沒有宣告 `package_data`/`include_package_data`——直接建置一份 wheel 驗證後發現，一般 `pip install --target` 會**靜默漏掉**這些資源檔，而目錄載入器對空目錄不會拋例外，只會悄悄註冊零筆資料，使封裝出去的應用程式少了一個平台且毫無錯誤訊息。建置腳本需新增 `package_data`/`include_package_data` 宣告（屬於封裝中繼資料，不算「修改 `src/backlink_publisher` 執行期程式碼」，不違反本計畫的 Scope Boundaries）或明確的複製步驟，並在安裝完成後斷言資源檔確實存在，斷言失敗就中止建置。

## Output Structure

建置出的 ZIP 內容（`backlink-publisher-vX.Y.Z-win64/`）：

```
backlink-publisher-vX.Y.Z-win64/
├── python-embed/                  # 官方 embeddable 直譯器 + 已安裝依賴（建置產物，免安裝）
│   ├── python.exe
│   ├── python311._pth             # 已修改：啟用 site-packages
│   └── Lib/site-packages/         # backlink_publisher 本體 + 核心依賴（非 editable 安裝）
├── app/
│   ├── webui.py
│   ├── webui_app/
│   ├── webui_store/
│   ├── webui_app/spa_dist/        # 建置期先跑過 npm run build 的 SPA 產物
│   └── config.example.toml
├── scripts/
│   ├── launch-webui.bat           # 主要進入點：啟動 WebUI 服務
│   ├── launch-cli.bat             # 開一個已設好 PATH 的殼層，可直接輸入 49 個 CLI 指令
│   ├── setup-wizard.bat           # 互動式首次設定精靈（沿用既有邏輯）
│   ├── setup-scheduler.bat        # Windows 工作排程器設定輔助
│   ├── install-playwright.bat     # 選用：安裝 Medium/Velog 瀏覽器綁定所需的 Chromium
│   └── cli-shims/                 # 建置期自動產生，每個 [project.scripts] 一個 .bat
│       ├── bp.bat
│       ├── plan-backlinks.bat
│       └── ...（共 49 個）
├── README.md / README.zh.md
├── QUICK_START.txt
├── ONBOARDING.md
└── config-minimal-example.toml
```

建置腳本自身新增的原始碼位置（在 `backlink-publisher/` 內，版控追蹤）：

```
backlink-publisher/scripts/packaging/
├── build_windows_package.py       # 主要建置腳本，單一進入點
└── templates/
    ├── launch-webui.bat.tmpl
    ├── launch-cli.bat.tmpl
    ├── QUICK_START.txt
    ├── ONBOARDING.md
    └── README-package.md
```

> 此目錄樹是範圍宣告，非絕對限制——實作時若發現更好的檔案劃分，可調整；各 Unit 的 **Files** 清單以其內容為準。

## Implementation Units

- [ ] **Unit 1: 建置期取得並準備獨立 Python 直譯器**

**Goal:** 產生一個不依賴任何主機 Python 安裝、可直接搬移的 `python-embed/` 目錄，內含 `backlink_publisher` 本體與核心依賴。

**Requirements:** R1, R4

**Dependencies:** None

**Files:**
- Create: `backlink-publisher/scripts/packaging/build_windows_package.py`（本 Unit 先實作其中的 interpreter-provisioning 部分）
- Test: `backlink-publisher/tests/packaging/test_build_windows_package.py`

**Approach:**
- 下載指定版本的 `python-3.11.x-embed-amd64.zip`，比對建置腳本內硬編碼的預期 SHA-256（版本號與 `pyproject.toml` 的 `requires-python` 對齊，精確釘選到某個 3.11.x patch 版本，避免依賴 wheel 相容性漂移）；不符就中止建置。
- 解壓縮後修改 `python311._pth`：取消 `import site` 的註解、加入 `Lib\site-packages` 路徑。
- 下載 `get-pip.py`，比對建置腳本內硬編碼的預期 SHA-256（比照上面 embeddable zip 的校驗方式）；核對通過才用該內嵌直譯器執行它 bootstrap pip（僅建置期使用，不隨封裝出貨）。
- 執行 `python-embed\python.exe -m pip install --no-cache-dir --ignore-installed --target python-embed\Lib\site-packages <repo_root>`（非 editable，安裝 `[project.dependencies]` 的**精確釘選版本**，不含 `dev`/`browser` extras；`--ignore-installed` 確保安裝結果不受建置機器本身已安裝套件影響）。
- 為 `publishing/adapters/catalog/*.yaml` 等非 `.py` 封裝資料新增 `package_data`/`include_package_data` 宣告（或建置腳本的明確複製步驟），安裝完成後斷言這些資源檔確實存在於 `site-packages` 裡，斷言失敗就中止建置。
- 對安裝完成的 `site-packages` 執行一次 `pip-audit`，發現任何已知 CVE 就中止建置。

**Test scenarios:**
- Happy path：對一個乾淨的暫存目錄執行整個流程後，`python-embed\python.exe -c "import backlink_publisher, flask, waitress"` 成功且 exit code 0；`publishing/adapters/catalog/txtfyi.yaml` 確實存在於安裝結果的 `site-packages` 底下。
- Error path：embeddable zip 或 `get-pip.py` 下載失敗、checksum 不符 → 腳本印出清楚錯誤訊息並以非 0 結束，不留下半成品目錄。
- Error path：pip install 因某個依賴沒有對應 wheel 而失敗，或 `pip-audit` 發現已知 CVE → 腳本立即中止並回報是哪個套件失敗，而非繼續產生一個壞掉或有已知漏洞的 site-packages。
- Error path：安裝完成後找不到預期的 `catalog/*.yaml` 資源檔 → 斷言失敗，建置中止，而非產生一個 `txtfyi` 平台被靜默移除的封裝。
- Integration：`python-embed/` 目錄搬移到另一個路徑（模擬「解壓縮到不同位置」）後，`python.exe -c "import backlink_publisher"` 仍然成功——直接驗證 R4 要解決的可攜性問題。
- Integration：在一台已對某個核心依賴執行過 `pip install --user` 的建置機器上執行整個流程，確認 `--ignore-installed` 讓最終 `site-packages` 仍完整包含該依賴，而非因為建置機器本身已有該套件而跳過複製。

**Verification:**
- 在一台（或一個乾淨的暫存帳號 / 容器）**從未安裝過 Python** 的 Windows 環境重現同樣的匯入測試，確認不依賴任何主機環境。

---

- [ ] **Unit 2: 從 pyproject.toml 產生 CLI shim 與更新 WebUI/CLI 啟動腳本**

**Goal:** 讓 49 個 `[project.scripts]` 指令與 WebUI 都能透過相對路徑呼叫內嵌直譯器啟動，不依賴 pip 產生的 console-script exe。

**Requirements:** R1, R4, R5

**Dependencies:** Unit 1（需要 `python-embed/` 的位置慣例已定案）

**Files:**
- Create: `backlink-publisher/scripts/packaging/templates/launch-webui.bat.tmpl`
- Create: `backlink-publisher/scripts/packaging/templates/launch-cli.bat.tmpl`
- Modify: `backlink-publisher/scripts/packaging/build_windows_package.py`（新增 shim 產生邏輯）
- Test: `backlink-publisher/tests/packaging/test_cli_shim_generation.py`

**Approach:**
- 解析 `pyproject.toml` 的 `[project.scripts]`（`name = "module.path:function"`），為每一項在 `scripts/cli-shims/<name>.bat` 產生一個呼叫 `"%~dp0..\..\python-embed\python.exe" -c "from <module.path> import <function>; <function>()" %*` 的 shim——直接用 `module:function` 目標，不依賴 `__main__` guard 是否存在，同時解決 `backup-state`/`restore-state` 共用同一模組兩個函式的問題。每個 shim 都設定 `PYTHONPATH=<pkg_dir>\app`（見 Key Technical Decisions），避免呼叫到會匯入 `webui_store` 的指令（如 `dispatch-backlinks`）時發生 `ModuleNotFoundError`。建置腳本產生完 shim 後，對每個 `[project.scripts]` 目標執行一次「能否解析 `module:function`」的存在性檢查，檢查失敗就中止建置，而非產生一個呼叫必定失敗的 shim。
- `launch-webui.bat` 沿用 `dist/backlink-publisher-v0.5.0-win64/scripts/launch-webui.bat` 已驗證過的邏輯（埠偵測 8888~8907、首次執行複製 `config.example.toml`、`SECRET_KEY` 持久化、3 秒後開瀏覽器），只把 Python 路徑換成 `python-embed\python.exe`，並設定 `PYTHONPATH` 指向 `app\`（給 `webui_app`/`webui_store` 用；`backlink_publisher` 已經是 site-packages 裡的真安裝，不需要 PYTHONPATH）——CLI shim 也需要同樣的 `PYTHONPATH` 設定，見上一點。將原本的 `cd /d "%PKG_DIR%"` 改為 `pushd "%PKG_DIR%"`（`cd /d` 不支援 UNC / 網路磁碟機路徑作為工作目錄，`pushd` 會自動對應一個暫時磁碟機代號），確保封裝解壓縮到公司網路共用磁碟機等 UNC 路徑時仍可啟動。
- `launch-cli.bat` 開一個 `cmd.exe`，把 `scripts\cli-shims\` 加進當次工作階段的 `PATH`，讓使用者可以直接輸入 `bp`、`plan-backlinks --help` 等指令；同樣使用 `pushd` 而非 `cd /d`。
- 兩個腳本都保留 `chcp 65001 >nul` 防護（延續 `2026-07-03-001` 的修復）。

**Test scenarios:**
- Happy path：執行 `launch-webui.bat` 後，`http://127.0.0.1:8888` 可連線且回傳 200；預設瀏覽器在 ~3 秒後自動開啟。
- Edge case：8888 被占用時，自動改用 8889 並在主控台印出提示，使用者不需手動介入。
- Error path：`python-embed\python.exe` 不存在（封裝不完整）時，腳本印出明確錯誤訊息並暫停，而非丟出不知所云的 Windows 錯誤視窗。
- Integration：從 `launch-cli.bat` 開的殼層直接輸入 `plan-backlinks --help`，能看到對應 CLI 的說明輸出（證明 shim + PATH 設定正確串接到內嵌直譯器與已安裝套件）。
- Integration：呼叫一個匯入 `webui_store` 的指令（如 `dispatch-backlinks --help`）不會出現 `ModuleNotFoundError`，證明 shim 的 `PYTHONPATH` 設定正確涵蓋 CLI 模組的跨層匯入。
- Integration：呼叫一個原本沒有 `__main__` guard 的指令（如 `platform-health --help` 或 `restore-state --help`）能正確執行對應函式並產生輸出，而不是靜默無輸出結束。
- Edge case：把封裝解壓縮到 UNC 路徑（例如 `\\server\share\backlink-publisher\`）後執行 `launch-webui.bat`，`pushd` 能成功切換工作目錄並正常啟動。

**Verification:**
- 對照 `pyproject.toml` 目前 49 個 `[project.scripts]` 條目，確認 `scripts/cli-shims/` 底下產生的 `.bat` 數量與名稱一一對應，沒有遺漏或多餘。

---

- [ ] **Unit 3: 建置 SPA 前端並組裝完整封裝目錄樹**

**Goal:** 一個指令完成「建置 SPA → 複製後端程式碼 → 組合成 Output Structure 描述的目錄樹」，取代目前手動複製組裝的流程。

**Requirements:** R1, R3

**Dependencies:** Unit 1, Unit 2

**Files:**
- Modify: `backlink-publisher/scripts/packaging/build_windows_package.py`（新增組裝階段）
- Test: `backlink-publisher/tests/packaging/test_package_assembly.py`

**Approach:**
- 建置腳本在 `frontend/` 執行 `npm ci && npm run build`（產出 `webui_app/spa_dist/`），失敗就整個中止，不允許「靜默沿用舊的/不存在的 spa_dist」。
- 複製 `webui.py`、`webui_app/`（含剛建好的 `spa_dist/`）、`webui_store/`、`config.example.toml` 到封裝的 `app/` 底下。
- 從 `pyproject.toml` 讀出版本號，決定輸出資料夾名稱 `backlink-publisher-vX.Y.Z-win64`。
- 開始組裝前，若目標輸出路徑已存在就整個刪除重建（避免重現目前 `dist/` 產物裡巢狀重複資料夾的問題）。

**Test scenarios:**
- Happy path：全新執行一次，產出的目錄樹與「Output Structure」章節描述的結構完全吻合（用檔案樹比對）。
- Error path：`npm run build` 失敗（例如語法錯誤）時，建置腳本整個中止且不產生任何輸出目錄，不會留下缺 `spa_dist` 的半成品封裝。
- Edge case：重跑建置指令兩次（模擬使用者重新打包同一版本）→ 第二次執行不會在輸出目錄裡巢狀出現第一次的殘留（直接對應目前 `dist/backlink-publisher-v0.5.0-win64/backlink-publisher-v0.5.1-win64/` 這個已知 bug）。
- Integration：組裝完成後啟動 `launch-webui.bat`，瀏覽 `/app` 能看到 Vue SPA 畫面（不是 404 或空白頁），證明 `spa_dist` 確實被正確複製並被 `webui_app/routes/spa.py` 讀到。

**Verification:**
- 目錄樹快照比對 + 一次完整的 `launch-webui.bat` 啟動並訪問 `/` 與 `/app` 兩個路徑都成功。

---

- [ ] **Unit 4: 修正並產出封裝內的使用說明文件**

**Goal:** README / QUICK_START / ONBOARDING 內容與封裝的實際目錄結構一致（修正目前文件寫 `python\` 但實際是 `venv\` 的落差），並涵蓋「從 0 到 1」的完整使用流程。

**Requirements:** R2

**Dependencies:** None（可與 Unit 1-3 平行進行，最後在 Unit 5 一起打包）

**Files:**
- Create: `backlink-publisher/scripts/packaging/templates/QUICK_START.txt`
- Create: `backlink-publisher/scripts/packaging/templates/ONBOARDING.md`
- Create: `backlink-publisher/scripts/packaging/templates/README-package.md`

**Approach:**
- 若 `dist/backlink-publisher-v0.5.0-win64/{QUICK_START.txt,ONBOARDING.md,README.md}` 存在於實作者的 checkout 中，以其現有內容為基礎（涵蓋 Telegraph/dev.to/Blogger/Medium/Velog 的憑證取得步驟、常見問題，內容品質已經不錯），全面校對並把所有提到目錄結構的地方（`python\` → `python-embed\`，移除已不存在的 `venv\` 描述）改成與 Unit 3 的 Output Structure 一致；`dist/` 已被 `.gitignore`，若該資料夾不存在（例如乾淨 checkout），直接依本計畫描述的內容範圍（本 Approach 段落 + Output Structure）重新撰寫，不假設有現成檔案可複製。
- 新增一段說明 `launch-cli.bat` 的用法（現有文件只提到 WebUI，CLI shim 是本計畫新增的能力）。
- 保留原文件已有的「Windows SmartScreen / 防毒警示」常見問題雛形，若沒有就新增一則（對應 Risks 表的已知摩擦點）。

**Test expectation:** none — 純文件內容變更，正確性由 Unit 5 的自動化字串檢查與人工校對確保。

**Verification:**
- 人工通讀一次，確認一個完全沒用過本專案的人能照著 QUICK_START 走完「解壓縮 → 啟動 → 發布第一篇文章」而不卡關。

---

- [ ] **Unit 5: 建置腳本主流程整合、冪等清理、打包與可搬移性驗收**

**Goal:** 提供單一指令 `python scripts/packaging/build_windows_package.py` 串起 Unit 1-4，輸出 `dist/backlink-publisher-vX.Y.Z-win64.zip` 與對應的 `.sha256` 校驗檔，並驗證封裝在「換路徑、換機器」情境下仍可運作。

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** Unit 1, Unit 2, Unit 3, Unit 4

**Files:**
- Modify: `backlink-publisher/scripts/packaging/build_windows_package.py`（主流程 orchestration：呼叫前面各階段、清理、壓縮、輸出 checksum）
- Test: `backlink-publisher/tests/packaging/test_build_windows_package_e2e.py`

**Approach:**
- 執行前先清空 `dist/backlink-publisher-vX.Y.Z-win64/`（若存在），避免任何殘留造成巢狀重複。
- 依序呼叫 Unit 1（直譯器）→ Unit 2（shim/launcher）→ Unit 3（SPA + 組裝）→ 複製 Unit 4 的文件模板進最終目錄。
- 產生 zip（`shutil.make_archive` 或等效），並寫出 `.sha256` 供使用者核對下載完整性。
- 每個步驟印出編號進度（風格比照 `scripts/prep-release.sh` 的 `1/4`、`2/4`），失敗時中止並保留失敗前的診斷輸出，不留下看起來完整但其實壞掉的 zip。

**Test scenarios:**
- Happy path：從乾淨 checkout 執行一次完整建置，產出的 zip 可以被解壓縮，解壓縮出的目錄樹與 Unit 3 驗證過的結構一致。
- Error path：任一子階段失敗時，最終不會產生 `.zip`（避免使用者誤下載一個半成品）。
- Integration / 可搬移性驗收（對應 R4，直接回應本計畫研究階段發現的核心 bug）：把建好的 zip 解壓縮到一個**與建置機器完全不同、過去從未存在過**的路徑（例如換一個磁碟機代號或一台乾淨的 Windows VM），執行 `launch-webui.bat`，確認能成功啟動並可在瀏覽器開啟 `/` 與 `/app`；再開 `launch-cli.bat` 確認至少一個 CLI 指令（如 `plan-backlinks --help`）可執行。
- Edge case：把同一份 zip 解壓縮到 UNC / 網路共用磁碟機路徑後重複上述驗收，確認 `pushd` 讓啟動腳本仍可正常切換工作目錄並啟動。
- Idempotency：對同一個版本號連續執行兩次建置（依賴版本已精確釘選，見 Unit 1），兩次的輸出目錄結構逐檔比對應完全相同（排除時間戳等預期差異），且不會有巢狀殘留。

**Verification:**
- 上述「可搬移性驗收」情境必須實際跑過一次並記錄結果，而不是只靠原機器上的測試——這是本計畫要解決的原始 bug 的直接反證。

## System-Wide Impact

- **互動圖譜：** 本計畫只新增建置期工具（`scripts/packaging/`）與封裝產物，不改動 `webui_app`/`webui_store`/`src/backlink_publisher` 的執行期程式碼或路由；唯一的執行期介面變化是新增的 `.bat` 啟動腳本如何呼叫既有的 `webui.py` / CLI 模組進入點（呼叫方式改變，被呼叫的程式碼不變）。
- **錯誤傳播：** 建置腳本任何階段失敗都必須以非 0 結束並清楚印出原因，不得產生「看起來完整但實際壞掉」的封裝（見各 Unit 的 Error path 情境）。
- **狀態生命週期風險：** 封裝內的 `python-embed/` 與 `app/` 每次重新建置都是全新產生（見 Unit 5 的先清空邏輯），使用者機器上的 `%USERPROFILE%\.config\backlink-publisher\`（設定檔、`SECRET_KEY`、Playwright 瀏覽器路徑）維持不受影響、跨版本更新持續存在——這是刻意設計，讓使用者「替換 app 資料夾」就能更新而不遺失設定。
- **不變的既有介面：** WebUI 的 API 路由、CSRF 機制、`BACKLINK_PUBLISHER_SPA` 旗標、`_util.errors` 例外分類、adapter registry 的 `register()` 慣例——全部不受本計畫影響，本計畫是純建置 / 發布層的新增工作。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| venv 不可搬移的問題直到本計畫研究階段才被發現，可能還有其他未知的環境依賴 | Unit 5 的「可搬移性驗收」情境明確要求在與建置機器不同的路徑 / 機器上實測，而不只是原機器自測 |
| 封裝體積可能偏大（embeddable Python + 核心依賴 + SPA 靜態檔） | 只安裝 `[project.dependencies]`（核心），排除 `dev`/`browser` extras；Playwright 維持選用安裝，不預設打包 |
| Windows Defender SmartScreen 對未簽章 `.bat`/zip 顯示警告，嚇退新使用者 | 記錄在 ONBOARDING.md 常見問題（Unit 4），提示「更多資訊 → 仍要執行」；code-signing 列為 Deferred to Separate Tasks |
| `pyproject.toml` 的 `[project.scripts]` 未來新增/刪除指令時，忘記同步封裝邏輯 | Unit 2 的 shim 直接從 `pyproject.toml` 解析產生，非手寫清單，天然不會漂移 |
| 內嵌 Python 版本與依賴 wheel 相容性（例如某天某依賴不再提供對應 patch 版本的 wheel） | Unit 1 精確釘選一個已驗證可用的 3.11.x patch 版本；pip install 失敗會讓建置立即中止並指出是哪個套件 |
| 現有 `dist/backlink-publisher-v0.5.0-win64/` 手動產物與新建置腳本的產出目錄若混淆，可能誤把舊的、壞掉的封裝發給使用者 | Unit 5 建置前清空目標目錄；建議舊的手動產物在新流程驗證通過後刪除（已列入 Deferred to Separate Tasks，不阻塞本計畫） |

## Documentation / Operational Notes

- 建置完成後應把 `dist/*.zip` 排除在 Git 版控外（`dist/` 已在 `.gitignore`），只把 `scripts/packaging/` 底下的建置腳本與範本納入版控。
- 建議在完成後用 `/ce-compound` 記錄本次發現的 venv 不可搬移問題與其修法，避免下次封裝又從零踩坑（`docs/solutions/` 目前完全沒有這類記錄）。

## Deferred / Open Questions

### From 2026-07-07 review

- **Deferring code-signing may leave the core "frictionless first use" promise unmet** — Scope Boundaries / Risks & Dependencies (P1, product-lens, confidence 0.85)

  The plan's entire value proposition is that a non-developer can unzip and double-click their way to a working WebUI. But the very first action a user takes — double-clicking an unsigned `.bat` inside a downloaded zip — is exactly the trigger for Windows Defender SmartScreen's full-screen "Windows protected your PC" warning, which the plan itself acknowledges will scare off new users. A non-technical user with no prior trust in the publisher is disproportionately likely to abandon at this screen rather than click through "More info -> Run anyway," meaning the promised onboarding flow never actually begins for a meaningful share of the target audience. Resolving this with only a FAQ entry in ONBOARDING.md treats the single most likely drop-off point as documentation debt rather than a cost/benefit decision (e.g. evaluating a low-cost code-signing certificate now) worth making before shipping to the stated non-technical persona.

  <!-- dedup-key: section="scope boundaries  risks  dependencies" title="deferring codesigning may leave the core frictionless first use promise unmet" evidence="the plans entire value proposition is that a nondeveloper can unzip and doubleclick their way to a working webui" -->

## Sources & References

- 相關程式碼：`dist/backlink-publisher-v0.5.0-win64/`（本計畫要取代的手動產物，含具體可重用的 `.bat` 邏輯）
- `backlink-publisher/scripts/prep-release.sh`（版本發布輔助腳本，風格參考）
- `backlink-publisher/docs/windows-setup.md`（既有開發者向 Windows 安裝文件，與本計畫的終端使用者向封裝互補而非取代）
- `backlink-publisher/docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md`（必須延續的 UTF-8 防護修復）
- `backlink-publisher/docs/plans/2026-06-23-002-release-v0.5.0-prep-plan.md`（前次發布準備計畫，Scope 界定方式參考）
- External: [cpython#102169](https://github.com/python/cpython/issues/102169)、[Python Discourse: venv relocatability](https://discuss.python.org/t/making-venvs-relocatable-friendly/96177)、[pyinstaller#6754](https://github.com/pyinstaller/pyinstaller/issues/6754)
