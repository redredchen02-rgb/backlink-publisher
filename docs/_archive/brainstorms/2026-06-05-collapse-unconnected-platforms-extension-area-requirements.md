---
date: 2026-06-05
topic: collapse-unconnected-platforms-extension-area
---

# 未串接平台收進「拓展區」— 降低平台清單認知負擔

## Problem Frame

WebUI 目前把全部 24+ 個發布平台都攤在使用者眼前(設定頁三層 tier、發布選渠道、報表等),其中大半是還沒串接、或瀏覽器操控難用的平台(Medium、Mastodon 等)。使用者每次都得在一堆「現在根本不能用」的渠道裡找出能用的那幾個,造成持續的認知負擔。

需求:把**還沒串接的平台收進一個預設折疊的「拓展區」**,主區只留下「現在馬上能用」的平台。使用者平常看不到沒串接的,但需要時能展開拓展區去新增。

> 既有基礎:設定頁已有三層折疊結構(`channel_tiers.group_channels_by_tier`),且每個平台已有連線狀態(`channel_status`:bound / unbound / expired / identity_mismatch)。本需求是改變**分組維度**——從「自動化複雜度 tier」改成「連線狀態(可用 / 未串接)」。

## 分區規則:狀態 → 落點

主區的判準是「現在能不能用」,而不是「自動化複雜度」。

| 平台狀態 | 含義 | 落點 | 標示 |
|---|---|---|---|
| `bound` | 已綁定憑證/登入態,可發 | **主區** | 正常 |
| 免綁定(`anon` tier) | 開箱即用,永遠可發(telegraph/txtfyi/rentry/notesio) | **主區** | 正常(免綁定) |
| `expired` | 曾綁定、登入態過期 | **主區** | 醒目警示「連線失效 · 需重連」 |
| `identity_mismatch` | 曾綁定、帳號對不上 | **主區** | 醒目警示「需重連」 |
| `unbound`(從未串接) | 從沒綁過(含需綁但沒綁的 API 平台、瀏覽器類沒綁的) | **拓展區**(折疊) | — |

## Requirements

**分區規則**
- R1. 主區只顯示「可用」平台:`bound` + 免綁定(`anon`)。
- R2. `expired` / `identity_mismatch`(曾可用、現失效)留在主區,但加上醒目的「需重連」狀態,不得藏進拓展區——避免使用者依賴的渠道默默消失。
- R3. 從未串接(`unbound`)的平台收進拓展區。
- R4. 分區判準是連線狀態,不是自動化 tier。原本的 tier 標籤(開箱即用 / 填憑證 / 瀏覽器登入)可保留為平台卡片上的次要資訊,但不再作為頂層分組維度。

**拓展區行為**
- R5. 拓展區預設折疊,標頭顯示未串接平台數量(例:「拓展區(18)」),讓使用者知道裡面有東西、可展開。
- R6. 展開拓展區後,使用者可對任一未串接平台執行原有的綁定 / 設定動作(Bind / Configure)——拓展區是「新增渠道」的入口,不能變成死清單。
- R7. 拓展區內可保留現有的視覺降權(例:瀏覽器登入類標示「需瀏覽器登入態 · 半自動」),但這是卡片內標示,不影響它屬於拓展區。
- R14. **冷啟動(新使用者零綁定)**:此時主區只剩免綁定平台(telegraph/txtfyi/rentry/notesio),近乎空。為避免「能用的東西被折起來」反而傷害上手,主區近空時拓展區應自動展開或顯示醒目的「去綁定第一個渠道」引導,讓綁定入口不被埋住。免綁定平台恆在主區這點同時作為主區不會真空的兜底。
- R15. **拓展區內部組織**:展開後是未串接平台的集中地(可能 15+ 個),不能是無序清單。需有穩定排序(建議按 tier 次分組:填憑證類 / 瀏覽器登入類,呼應 R4 把 tier 降為卡片次要資訊);數量超過一定門檻(如 >12)時提供搜尋/過濾,避免把「在一堆裡找」的原始痛點原封搬進拓展區。

**狀態轉移(自動升降)**
- R8. 未串接平台一旦綁定成功 → 自動升入主區(無需手動操作)。
- R9. 主區平台連線失效(轉 `expired`/`identity_mismatch`)→ 留主區並切換為「需重連」警示狀態(依 R2)。
- R10. 「從未串接」與「曾串接後失效」必須區分:前者進拓展區,後者留主區。
  - 精確判準(避免實作誤判):**主區 iff** `auth_type == "anon"` **或** `status ∈ {bound, expired, identity_mismatch}`;**拓展區 iff** `status == unbound`。「曾綁過」= `status ∈ {bound, expired, identity_mismatch}`(這三態只有綁定後才到得了),**不可**只測 `bound_at` 真值,也**不可**測「紀錄是否存在」——`unbound` 紀錄也可能帶 `last_verified_at`(操作者對未綁渠道按過 Verify)。

**套用範圍**
- R11. 規則套用於使用者「挑渠道來用」的兩個畫面:**設定/控制台總覽** 與 **發布/選渠道流程**。注意這兩個畫面目前平台清單來源不同(設定頁走 `dashboard_channels`/`get_channel_status`,發布頁直接用 `registered_platforms()` 且不算連線狀態),統一接上 R13 共用判斷點是本案主要工作量,非單純查表。
- R12. CLI 管線(stdin/stdout JSONL)不在折疊範圍——那是給機器讀的資料流,沒有給人看的清單顯示。
- R13. 分區邏輯應集中在單一可重用的判斷點(輸入 channel_status → 輸出 主區/拓展區),供各畫面共用,避免每個畫面各寫一套。

## Success Criteria
- 開啟設定頁/發布流程時,主區只看到「現在能用」的平台(已綁 + 免綁 + 失效待重連),沒串接的平台預設不出現。
- 失效平台不會消失:過期/帳號對不上時,使用者在主區看得到「需重連」提示。
- 綁定一個拓展區平台後,它自動出現在主區,不需要其他操作。
- 拓展區一鍵展開即可新增/設定任何未串接平台。
- 主區可見平台數量顯著下降(以目前狀態,從 24+ 降到實際可用的少數幾個)。

## Scope Boundaries
- 不刪除、不下架任何平台或 adapter——只改 UI 的顯示/分組,後端註冊表(`registered_platforms()`)不變。
- 不改變發布邏輯、tier 健康閘門、throttle 等行為——純資訊架構/呈現層重構。
- 不在本次新增手動 pin/釘選機制(分區全自動依連線狀態)。
- **報表頁不套用折疊**:報表目的是回看「歷史發過哪些渠道」,折疊會把「從未串接但歷史上發過連結」的平台藏掉、抹掉歷史。報表維持顯示所有相關平台。
- CLI 輸出格式不變。

## Key Decisions
- **分組維度:連線狀態(可用/未串接),非自動化 tier**:直接對應「沒串接不要讓我看到」的訴求,比 tier 更貼近使用者「現在能用嗎」的心智。
- **免綁定平台算「可用」→ 留主區**:它們永遠能發,藏起來反而降低可用性。
- **失效平台留主區帶警示,不藏**:避免依賴中的渠道默默消失的踩雷風險(footgun)。
- **拓展區是入口不是墳場**:折疊但可展開、可在內綁定,維持新平台的可發現性。
- **已知取捨:連線狀態無法表達「想不想用」**:四個免綁定平台會恆駐主區、即使從沒用過;且全自動分區此版不提供手動覆寫(no pin)。代價是當系統訊號(連線狀態)與你的意圖(想看哪些)不一致時,本版沒有逃生口。接受此取捨;若日後成為痛點,再評估加入輕量「想用/置頂」訊號。
- **失效平台可能淹沒主區的風險**:瀏覽器登入類(Medium/Mastodon)過期是常態,大量同時失效會讓主區擠滿紅色「需重連」卡,與「主區清爽」目標衝突。緩解方向(留 planning 定):主區內設一個可折疊的「需重連」小節,或長期失效(>N 天未理會)降回拓展區但保留「曾失效」徽記。

## Dependencies / Assumptions
- 依賴既有 `webui_store/channel_status.py` 的狀態(bound/unbound/expired/identity_mismatch)與 `bound_at` 紀錄能可靠區分「從未串接」vs「曾串接後失效」。
- **狀態來源辨明(planning 須處理)**:四態列舉 enum 住在 `webui_store/channel_status`(`get_status`/`list_all`),**不是** `binding_status.get_channel_status()` 回傳的 `{bound: bool, blockers, auth_type}`。後者只看 `verify_adapter_setup` 成不成、看不出 expired vs identity_mismatch。R2/R9 要實作,分區判斷點必須額外讀 `channel_status.get_status()`。
- **API/oauth 平台的失效可能不可見(待驗證)**:`channel_status` 的記錄主要涵蓋瀏覽器綁定渠道(CHANNELS 白名單);純 API/oauth 平台可能根本沒記錄,其憑證過期會讀成 `unbound` 而誤落拓展區,使 R2 的「不讓依賴渠道消失」保證對 API 平台失效。planning 須確認涵蓋範圍。
- **legacy 資料風險**:pre-#140 寫入的 channel_status 檔可能缺 `bound_at`,使真正綁過的平台被誤判「從未串接」而折起來(R2 不涵蓋此誤記)。planning 須定 backfill/相容策略。
- 假設免綁定平台可由 `auth_type == "anon"` 穩定識別(`channel_tiers.py` 已如此分類)。
- 既有三層折疊 UI(`_settings_overview_tiers.html` + `settings.js` 折疊狀態持久化)可改造重用,不需重寫。

## Outstanding Questions

### Deferred to Planning
- [Affects R11][Technical] 發布/選渠道流程(`batch_campaign`)目前直接用 `registered_platforms()` 建 checkbox grid、不算連線狀態,且 POST 驗證失敗會重列清單;需決定折疊區在多選 checkbox grid 裡的互動形態(accordion vs 分段),並把連線狀態注入此流程。
- [Affects R4][Technical] tier 資訊降為卡片次要標示後,既有 `_settings_overview_tiers.html` 的三層 accordion 是整個換成「主區/拓展區」兩段,還是主區內仍保留 tier 分組?需看改造成本決定。
- [Affects R13][Technical] 共用判斷點應放在 `webui_app/helpers/`(如新增 `channel_partition.py`)還是擴充 `channel_tiers.py`?planning 時定。
- [Affects R5][Needs research] 拓展區折疊狀態是否沿用現有 `settings.js` 的 localStorage 持久化機制,跨畫面是否需一致?注意 `settings.js` 目前以 `.collapse[id^="tier-"]` 選取面板、key 為 `settings:collapse:`+id;改成主區/拓展區後若不換選擇器與 key,折疊記憶會靜默失效。
- [Affects R8][Technical] 綁定/重連是異步且會失敗的動作,需定義 loading / 失敗(留原區+錯誤)/ 成功(卡片從拓展區升入主區的過場,建議 toast「X 已加入可用渠道」避免無聲跳走)各狀態。
- [Affects R2/R11][User decision] 發布/選渠道流程中,「需重連」的失效平台能否被勾選發布?建議不可勾選+inline 提示與重連入口,跨畫面語義一致。
- [Affects R2/R9][Design] 「醒目警示」的具體呈現規格(置頂排序 + warning 色邊 + badge「需重連」,用 `tokens.css` 語義色而非寫死 hex)。
- [Affects R6/R13][Technical] R13「集中分區判斷」與 R6「卡片內 Bind/Configure 動作」的邊界:建議 R13 只集中分區決策,Bind/Configure 維持卡片本地。
- [Affects R13][Technical] 傾向**擴充既有 `channel_tiers.py`**(同型分組函式,只是把維度從 tier 換成連線狀態),除非該檔逼近 SLOC budget 或職責確實分裂才另立 `channel_partition.py`。判斷點應限 WebUI、不暴露給 CLI。
- [Affects R10][Technical] unbind→rebind 生命週期:使用者解綁後 `bound_at` 是保留、清空還是歸檔?影響「曾綁過」判定。
- [Affects R1][Technical] 主區/拓展區各自內部的排序維度(註冊序 / 字母序 / tier 次分組);本版不做手動 pin。

## Next Steps
→ `/ce:plan` for structured implementation planning
