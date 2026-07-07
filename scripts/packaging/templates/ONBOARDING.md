# Backlink Publisher — 新手上手指南（從 0 到 1）

這份文件假設你**沒有任何程式開發經驗**，帶你完成「解壓縮 → 啟動 WebUI →
選擇發布平台 → 設定憑證 → 發布第一篇文章 → 確認結果」的完整流程，
最後附上常見問題（FAQ）。

如果你只想要最短的操作步驟，看同一個資料夾裡的 `QUICK_START.txt` 就夠了；
這份文件是給想理解每一步在做什麼、或要設定 Telegraph 以外平台的人看的。

---

## 1. 解壓縮

把整個 ZIP 檔解壓縮到任意資料夾（桌面、文件、下載都可以）。**不需要**
安裝 Python、Node.js、或任何開發工具——所有需要的東西都已經包在
ZIP 裡面了。

解壓縮完成後，資料夾結構長這樣：

```
backlink-publisher-vX.Y.Z-win64\
├── python-embed\              # 內建 Python 直譯器（免安裝，程式自己會用）
├── app\                       # 程式本體（webui.py、webui_app\、webui_store\、config.example.toml）
├── scripts\
│   ├── launch-webui.bat       # ← 一般使用者最常用的就是這個：啟動 WebUI
│   ├── launch-cli.bat         # 進階功能：開啟命令列，非必要不用管
│   ├── setup-wizard.bat       # 互動式首次設定精靈
│   ├── setup-scheduler.bat    # 設定「每天自動執行一次」等排程
│   ├── install-playwright.bat # 選用：只有要用 Medium / Velog 才需要
│   └── cli-shims\             # 供 launch-cli.bat 使用的內部檔案，不需要手動點
├── README.md / README.zh.md
├── QUICK_START.txt
├── ONBOARDING.md               # 就是這份文件
└── config-minimal-example.toml
```

> `python-embed\` 資料夾裡就是完整可用的 Python，你**不需要**、也**不應該**
> 自己另外安裝 Python 或建立虛擬環境（venv）——這個封裝已經幫你做好了。

---

## 2. 啟動 WebUI

雙擊 `scripts\launch-webui.bat`。

會發生什麼事：

1. 跳出一個黑色的主控台（命令提示字元）視窗，這是正常的，**請不要關掉它**
   ——它是在背景執行 WebUI 服務，關掉它就等於把服務停掉。
2. Windows 第一次執行未簽章的 `.bat` 檔時，可能會跳出「Windows 已保護您的
   電腦」的藍色警告畫面。這是預期中的行為，不是病毒警告，做法見下方 FAQ
   的「SmartScreen 警告」一節。
3. 若是第一次執行，程式會自動幫你建立設定檔，位置在：
   `%USERPROFILE%\.config\backlink-publisher\config.toml`
   （這個路徑等同「你的使用者資料夾\.config\backlink-publisher\」）。
4. 主控台會嘗試監聽 `http://127.0.0.1:8888`；如果 8888 被其他程式占用，
   會自動改用 8889、8890……不需要你手動處理，只要看主控台印出的實際網址。
5. 大約 3 秒後，預設瀏覽器會自動開啟該網址。如果沒有自動開啟，手動在
   瀏覽器網址列輸入主控台印出的網址即可。

---

## 3. 選擇發布平台

WebUI 打開後，你會需要挑一個「發布平台」，也就是文章要發到哪裡。以下
是目前支援、且封裝內建說明涵蓋的五個平台，**難度由易到難排列**：

### Telegraph（推薦第一次使用）

- **不需要任何帳號或密碼。** 第一次對 Telegraph 發布時，程式會自動幫你
  建立一個匿名的 Telegraph 帳號並保存存取權杖（token）在
  `%USERPROFILE%\.config\backlink-publisher\telegraph-token.json`。
- 完全零設定，是驗證整個流程「能不能跑通」最快的方式。**強烈建議
  第一次先用這個平台測試。**

### dev.to（需要 API 金鑰）

- 前往 [dev.to](https://dev.to) 登入你的帳號 → 右上角頭像 →
  **Settings → Extensions** → 在 **DEV Community API Keys** 區塊產生一組
  API Key。
- 回到 WebUI 的「設定 / Settings」頁面，找到 dev.to 的頻道綁定欄位，
  貼上剛剛複製的金鑰即可。金鑰會存在
  `%USERPROFILE%\.config\backlink-publisher\devto-token.json`。
- 注意：dev.to 上發布的文章連結會被平台強制加上 `nofollow`（這是
  dev.to 平台本身的政策，並非本工具的限制），適合拿來曝光內容、
  但不適合當作追求 SEO 權重傳遞的主力管道。

### Blogger（需要透過 Google Cloud Console 設定 OAuth）

- 到 [Google Cloud Console](https://console.cloud.google.com/) →
  「API 和服務」→「憑證」，建立一組 **OAuth 2.0 用戶端 ID**（類型選
  「電腦版應用程式 / Desktop app」），並在同一個專案啟用
  **Blogger API v3**。
- 把取得的 `client_id` 與 `client_secret` 填入設定檔
  `%USERPROFILE%\.config\backlink-publisher\config.toml` 的
  `[blogger.oauth]` 區塊（可參考封裝內 `app\config.example.toml` 的範例
  格式），同時在 `[blogger]` 區塊填入你的目標網站與對應的 Blogger
  部落格 ID。
- 存檔後回到 WebUI，透過「設定 / Settings」頁面的授權按鈕走一次 Google
  登入 / 授權流程即可完成綁定。

### Medium（透過內建瀏覽器登入）

- Medium 的綁定方式是「內建瀏覽器登入」：在 WebUI 的「設定 / Settings」
  頁面點選 Medium 的綁定按鈕（或使用進階的 `medium-login` 指令，見
  README-package.md），程式會另外開一個瀏覽器視窗讓你登入 Medium
  帳號，登入完成後憑證會被保存下來，之後發布不需要再重新登入。
- 這個方式需要先安裝 Playwright 瀏覽器套件，見下方 FAQ「如何安裝
  Playwright」。

### Velog（透過內建瀏覽器登入）

- 與 Medium 相同，Velog 也是「內建瀏覽器登入」模式：在 WebUI 設定頁面
  觸發綁定、或使用進階的 `velog-login` 指令，開啟瀏覽器登入 Velog
  帳號後即可，登入資訊（cookie）會被保存供之後發布使用。
- 同樣需要先安裝 Playwright（見 FAQ）。

> 建議順序：先用 **Telegraph** 確認整個流程沒問題，之後再依需求慢慢
> 加其他平台，不需要一次把五個平台都設好。

---

## 4. 發布第一篇文章

1. 在 WebUI 首頁或「草稿 / Drafts」頁面，建立一則新內容（填入標題、
   內文、目標網址等欄位）。
2. 在發布平台選單選擇 **Telegraph**（第一次建議先用它）。
3. 按下「發布 / Publish」。
4. 前往「歷史紀錄 / History」頁面，確認剛剛的項目狀態顯示為成功，並
   點開連結確認文章真的能在瀏覽器打開。

如果發布失敗，先看本文件最後 FAQ 的「發布失敗怎麼辦」一節。

---

## 5. 確認結果

- **歷史紀錄 / History** 頁面：看每一次發布的成功/失敗狀態與連結。
- **監控 / Monitor** 或健康狀態頁面：看整體管線與各平台的即時健康度。
- 之後想要「每天自動發布一次」而不用手動點擊，可以用
  `scripts\setup-scheduler.bat` 設定 Windows 工作排程器，細節見
  README-package.md。

---

## FAQ（常見問題）

### Q1：出現「Windows 已保護您的電腦」的藍色警告畫面怎麼辦？

這是 Windows SmartScreen 的機制，只要是「未經數位簽章的獨立小工具」
（不只是本工具，很多開源軟體、個人開發的 `.bat`/`.exe` 都會遇到）
第一次執行都會出現，**不代表這是病毒**。

處理方式：在警告畫面點選「**其他資訊 / More info**」，接著點選
「**仍要執行 / Run anyway**」即可繼續啟動。之後同一支程式通常就不會
再跳出這個警告。

### Q2：防毒軟體把啟動腳本「隔離」了，跟 SmartScreen 警告有什麼不一樣？

這是和 Q1 不同的狀況，需要不同的處理方式：

- Q1 的 SmartScreen 是「跳出警告視窗讓你選擇要不要繼續」——你按一下
  「仍要執行」就能繼續用。
- 這裡講的是**防毒軟體把檔案整個「隔離 / 刪除」**：如果你發現
  `scripts\launch-webui.bat`、`scripts\launch-cli.bat`，或
  `scripts\cli-shims\` 底下的某個 `.bat` 檔**憑空消失、或雙擊完全沒
  反應、沒有任何視窗跳出**，很可能是防毒軟體在背景把它偷偷隔離了，
  不會有任何警告畫面讓你點選。

處理方式：打開你的防毒軟體（Windows 內建的「Windows 安全性」或第三方
防毒軟體皆同），找到「保護記錄 / 隔離區 / Quarantine」或類似名稱的
紀錄頁面，找到被隔離的檔案，選擇「還原 / 允許 / 加入例外清單」。這一步
跟 Q1 的「其他資訊 → 仍要執行」是兩個完全不同的操作，不能互相取代。

### Q3：瀏覽器下載 ZIP 檔時被擋下來或自動刪除了怎麼辦？

有些瀏覽器（Chrome、Edge 等）對「內含 `.bat` 檔的壓縮檔」會在下載時
主動攔截或標記為危險，甚至自動刪除下載結果，這也是 Windows「網際網路
標記 / Mark-of-the-Web」機制的一部分，屬於正常現象。

處理方式：

- 到瀏覽器的「下載記錄」查看該檔案是否被攔截，通常會有「保留 / 仍要
  下載」的選項。
- 若瀏覽器設定或企業原則完全擋下下載，檢查瀏覽器的安全性設定，或改用
  另一個瀏覽器再試一次。
- 如果這是公司或學校配發的電腦（受 IT 集中管理），這類下載限制通常
  是 IT 政策設定的，請洽詢你的 IT 管理員協助允許此下載或改用其他管道
  取得檔案。

### Q4：8888 埠被占用了怎麼辦？

不需要任何動作。`launch-webui.bat` 會自動偵測埠是否被占用，並自動改用
8889、8890……依序往後嘗試，主控台視窗會印出實際使用的網址。

### Q5：怎麼停止 WebUI？

直接關閉 `launch-webui.bat` 開啟的那個黑色主控台視窗即可，服務會隨之
停止。

### Q6：設定檔在哪裡？怎麼編輯？

位置：`%USERPROFILE%\.config\backlink-publisher\config.toml`
（也就是「你的使用者資料夾\.config\backlink-publisher\config.toml」）。

第一次啟動 WebUI 時會自動從封裝內的 `app\config.example.toml` 複製出
這份設定檔。之後可以用記事本或任何文字編輯器打開修改（例如填入
Blogger 的 OAuth 憑證），存檔後重新啟動 `launch-webui.bat` 即可套用。

### Q7：怎麼安裝 Playwright（Medium / Velog 需要用到）？

雙擊 `scripts\install-playwright.bat`。只有要使用 **Medium** 或
**Velog**（兩者都是「內建瀏覽器登入」模式）才需要這一步；只用
Telegraph / dev.to / Blogger 的話不需要安裝。

### Q8：怎麼設定「每天自動跑一次」這種排程？

雙擊 `scripts\setup-scheduler.bat`，會引導你把發布流程加進 Windows
工作排程器（Task Scheduler），細節與可自訂的排程頻率見
README-package.md 的「排程」章節。

### Q9：怎麼更新到新版本？

1. 下載新版本的 ZIP，解壓縮到新的資料夾（或另一個位置）。
2. 用新版本裡的 `app\` 資料夾整個取代舊版本的 `app\` 資料夾即可完成
   更新，`python-embed\` 與 `scripts\` 通常也建議一併換成新版本的。
3. 你的設定檔與各平台的登入憑證都保存在
   `%USERPROFILE%\.config\backlink-publisher\`，**不在**解壓縮出來的
   資料夾裡，所以更新（甚至整個刪除舊版資料夾重新解壓縮新版）都不會
   遺失你的設定與已綁定的帳號。

### Q10：發布失敗怎麼辦？

依序檢查：

1. **網路連線**：確認電腦目前有連上網際網路。
2. **憑證是否正確**：回到「設定 / Settings」頁面確認該平台的 API 金鑰 /
   OAuth 授權 / 登入狀態沒有過期或打錯。
3. **目標網址是否正確**：確認你要發布連結指向的目標網址本身可以正常
   打開，沒有打錯字或該頁面已經失效。

如果以上都確認過仍然失敗，可以到「歷史紀錄 / History」頁面查看該筆
記錄的詳細錯誤訊息，或參考 README-package.md 的「疑難排解」章節。

---

需要更完整的目錄結構說明、CLI 指令列表、排程細節，請看同一個資料夾裡的
`README-package.md`。
