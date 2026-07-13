---
title: "feat: 渠道绑定状态 UI/UX 分組設計（已綁定／未綁定易讀性）"
type: feat
status: active
date: 2026-07-07
claims: {}
---

# feat: 渠道绑定状态 UI/UX 分組設計（已綁定／未綁定易讀性）

## Overview

`Settings` 頁面上的「渠道绑定状态」總覽卡（`ChannelsCard.vue`）與「渠道凭据绑定」表單卡（`ChannelBindingCard.vue`）目前都以單一平鋪列表呈現所有渠道，已綁定與未綁定渠道混雜在一起，操作者必須逐一讀取每一列的小標籤才能判斷哪些渠道仍待處理。本計畫把這兩張卡片重新設計為「未綁定優先分組」的版面，並在總覽卡加入頂部總覽計數，讓待處理項目一眼可見。

## Problem Frame

使用者要求「已綁定／未綁定的渠道需要再 UIUX 做詳細設計，讓閱讀上可以更容易」。目前兩張卡片的實作：

- `ChannelsCard.vue`（`frontend/src/pages/Settings/ChannelsCard.vue:50-67`）以 `<ul class="ch-list"><li v-for="c in channels">` 依 API 回傳順序平鋪渲染，`已绑定`/`未绑定` 只是每列裡的一個小 `<span class="tag">`。
- `ChannelBindingCard.vue`（`frontend/src/pages/Settings/ChannelBindingCard.vue:209-219`）以 `<details v-for="f in forms">` 平鋪渲染每個固定憑證渠道的表單，目前所有 `<details>` 都預設收合（沒有任何 `open` 綁定），已綁定與未綁定的表單一樣不顯眼。

這使得「還有哪些渠道沒綁」這個操作者最關心的問題，必須靠掃視整份清單才能回答。

## Requirements Trace

- R1. 操作者能在「渠道绑定状态」總覽卡與「渠道凭据绑定」表單卡中，立即區分已綁定與未綁定的渠道，而不需逐列閱讀標籤。
- R2. 「渠道绑定状态」總覽卡頂部顯示「X / Y 已绑定」總覽計數，讓整體進度一目了然。
- R3. 「渠道凭据绑定」表單卡中，未綁定渠道的表單預設展開（引導填寫），已綁定渠道的表單預設收合（減少畫面雜訊）。
- R4. 本次改動僅限表現層（分組、預設展開/收合、計數顯示）；不得變更 `GET /api/v1/settings/channels`、`GET /api/v1/settings/channels/forms` 的資料契約，也不得變更任何綁定/清除的提交行為。

## Scope Boundaries

- 僅修改 `frontend/src/pages/Settings/ChannelsCard.vue` 與 `frontend/src/pages/Settings/ChannelBindingCard.vue`（及其 `.spec.ts` 測試）。
- Medium／velog／Blogger／Notion 四張各自獨立的 OAuth／瀏覽器登入動作卡（`MediumCard.vue`、`VelogCard.vue`、`BloggerCard.vue`、`NotionCard.vue`）明確排除在外（已與使用者確認）——它們使用不同的狀態模型（各自的 liveness/oauth 狀態，非本卡的 `bound` 布林值），不在本次範圍內重新設計。
- 不涉及任何後端／API 變更；`webui_app/routes/settings*.py`、`webui_app/api/v1/schemas.py` 不需修改。
- 不引入新依賴（前端目前沒有 icon 套件，`frontend/package.json` 僅有 vue/pinia/vue-router/tanstack-query）——狀態呈現維持純 CSS/文字，沿用既有 `.tag`/`.tag--ok`/`.tag--muted`/`.tag--warn` 慣例。
- 分組內部（未綁定組、已綁定組各自內部）的排序不變，維持 API 回傳原始順序；不新增次要排序（例如按字母、按 blocker 數量）。
- `SettingsSidebar.vue` 既有的「N/M 已绑定」計數（`frontend/src/pages/Settings/SettingsSidebar.vue:31-35,45`）維持不變；本次在 `ChannelsCard.vue` 新增的計數是獨立的卡片內提示，不是取代或抽成共用 composable。

## Context & Research

### Relevant Code and Patterns

- `frontend/src/pages/Settings/ChannelsCard.vue:50-67` — 目前的平鋪 `<ul>` 列表，`.ch`/`.ch__head`/`.ch__meta`/`.ch__blockers` 樣式維持不動，只改變外層包裝結構與資料來源。
- `frontend/src/pages/Settings/ChannelBindingCard.vue:139-146`（`isBound()` helper）、`:209-219`（平鋪 `<details v-for>`）。
- `frontend/src/layout/SideNav.vue:107-137,156-162` — 全 SPA 中唯一現成的「同一清單內分組」前例：`<template v-for="group in GROUP_ORDER">` + `.sidenav__group-label`（純文字標籤 div，非 heading landmark，大寫/字距樣式）。本次兩張卡的分組標籤沿用此視覺語言。
- `frontend/src/pages/Settings/SettingsSidebar.vue:31-35` — 既有 `boundCount`/`totalCount` computed（同一份 `['settings','channels']` query），是 `ChannelsCard.vue` 新增卡內計數要沿用的計算方式（非抽出共用，見 Key Technical Decisions）。
- `frontend/src/components/StateBlock.vue` — 契約不變；分組/計數的 markup 完全落在其 `ready` 狀態的預設 slot 內部，不需改動 `StateBlock` 本身的 props/slots。
- `webui_app/static/css/tokens.css` — `--success`、`--warning`、`--text-secondary`、`--space-*`、`--radius-*`，兩個元件既有的 `<style scoped>` 已在使用，本次沿用不新增 token。

### Institutional Learnings

- `docs/solutions/architecture-patterns/server-side-gap-computation-2026-06-05.md` — 曾建議「操作者需要看到大量目標中缺漏/異常項目」時應由後端預先計算 gap，而非讓 UI/操作者自行推斷。本計畫評估後認為不適用：這裡的分組只是把每個渠道既有的 `bound` 布林值做二分區隔（純前端顯示順序重排），並非跨目標的聚合 gap 運算，見 Key Technical Decisions 的「拒絕」說明。
- `docs/solutions/best-practices/never-smoke-test-real-save-endpoints-2026-05-19.md` — 提醒：手動驗證時不得對真實的儲存端點做 smoke test（空 POST 會被視為合法輸入並清空既有設定）。本計畫的驗證應完全依賴既有的 mock 測試套件（`ChannelBindingCard.spec.ts` 已 mock `saveChannelCredential`/`saveChannelToken`），不得手動打真實 save API。

### External References

無需外部研究——兩個目標元件在同一份 codebase 內已有明確可依循的樣式慣例（`SideNav.vue` 分組樣式、`SettingsSidebar.vue` 計數樣式、`.tag` 系列 class），且不涉及新技術層。

## Key Technical Decisions

- **分組在前端純 computed 完成，不變更後端／API**：`bound` 布林值已存在於每個 `ChannelOverviewItem`／已透過 slug 從 `boundMap` 取得，分組只是對既有陣列做 `filter` 二分，不是新的跨渠道聚合運算——`server-side-gap-computation` 學習文件所描述的情境（需要後端預先算出「缺漏了什麼」）不適用於此處單一布林欄位的二分。
- **組內順序維持 API 原始順序**：只新增「分組」這一層，不新增次要排序邏輯，降低本次改動的測試面與審查面。
- **分組標籤視覺語言沿用 `SideNav.vue` 的 `.sidenav__group-label` 前例**（文字 label div，非新增 `<h3>` landmark），並補上最小限度的無障礙分組語意（2026-07-07 文件審查決定，見 Open Questions）：每個分組的清單/表單容器加上 `role="group"`、`aria-labelledby` 指向該組標籤的 `id`（例如 `ch-group-unbound`/`ch-group-bound`、`bind-group-unbound`/`bind-group-bound`，元件內唯一即可）——純視覺文字 div 本身無法讓螢幕報讀器使用者感知「現在進入了未綁定/已綁定分組」，而這正是 R1 可讀性目標的一部分，不只是視覺呈現，成本僅為兩個屬性。
- **`ChannelsCard.vue` 卡內計數與 `SettingsSidebar.vue` 的 `boundCount`/`totalCount` 各自獨立計算**（兩處各自 2 行 computed），不抽成共用 composable——兩個獨立用途（側欄全域導覽 vs. 卡片內即時提示）且僅兩處使用，未達到抽象化的門檻，與本 codebase 既有慣例一致（`.tag`/`.card`/`.muted` 等樣式本來就是每張卡各自複製一份，而非共用 CSS module）。
- **`ChannelBindingCard.vue` 的展開/收合狀態改為「僅在該 slug 第一次出現時播種一次，之後不隨 `isBound()` 即時重算」**（2026-07-07 文件審查決定，見 Open Questions）：原規劃的 `<details :open="!isBound(f.slug)">` 直接綁定即時 `isBound()`，會在使用者剛送出成功後（`submit()` 觸發 `['settings','channels']` 的 `invalidateQueries`，refetch 完成後 `isBound()` 翻成 `true`）讓面板立刻收合並跳到「已綁定」分組，使用者可能誤以為剛輸入的內容消失了。改為以 slug 為 key 的本地 `reactive` 狀態（例如 `openState`），在該 slug 第一次出現於 `forms` 時用當下的 `!isBound(f.slug)` 播種一次；之後即使該 slug 的 `bound` 狀態改變，已展開的表單不會被強制收合。與 `edits`/`lastSeeded` 一樣以 slug 為 key，不影響既有 dirty-tracking，也不需要計時器或延遲效果。
- **空分組直接隱藏整個標籤＋容器**（例如全部已綁定時不顯示「未綁定」標題），避免出現「0 個項目」的空段落雜訊。

## Open Questions

### Resolved During Planning

- 分組排列順序（未綁定優先 vs. 已綁定優先 vs. 不分組只強化視覺）→ 未綁定優先分區（使用者選定）。
- 本次 UI/UX 範圍是否涵蓋 4 張 OAuth 動作卡 → 否，僅 ChannelsCard/ChannelBindingCard 兩張共用卡（使用者選定）。
- `ChannelBindingCard` 表單預設展開/收合策略 → 已綁定收合、未綁定展開（使用者選定）。
- 分組標籤視覺樣式 → 沿用 `SideNav.vue` 的 `.sidenav__group-label` 前例（規劃期推斷，風險低，審查時可直接調整微調值）。
- 【2026-07-07 文件審查】`ChannelBindingCard.vue` 的表單展開/收合狀態是否隨即時 `isBound()` 重算 → 否，改為僅在該 slug 第一次出現時播種一次，之後不隨 bound 狀態變化自動收合/移動（design-lens + feasibility 兩位審查者獨立指出同一問題後，使用者選定）——避免使用者剛送出成功就看到剛填的表單消失。
- 【2026-07-07 文件審查】分組容器是否補上 ARIA 分組語意 → 是，加上 `role="group"` + `aria-labelledby`（design-lens 指出純視覺文字標籤對螢幕報讀器不可見分組邊界後，使用者選定）。

### Deferred to Implementation

- 新增分組標籤 class 的確切 CSS 數值（padding/margin/字距）——需要實作者渲染出來後依卡片視覺節奏微調，非規劃期能精確決定。
- ~~既有「僅在已綁定時提供清除按鈕」測試在該渠道表單改為預設收合後，jsdom 的 `.trigger('click')` 是否仍能直接命中被原生 `<details>` 收合隱藏的內容~~ → 已於實作時實測：jsdom 不會因原生 `<details>` 處於收合狀態而阻擋 `find()`/`.trigger('click')`，既有測試無需修改即可通過。
- 【2026-07-07 文件審查 FYI，不強制本次處理】`ChannelsCard.vue` 頂部「X / Y 已绑定」計數會隨即時查詢資料變動，目前未規劃 `aria-live` 播報策略，螢幕報讀器使用者不會被主動告知計數變化；信心度落在 FYI 區間（非本次必須解決的判斷點），保留給未來的無障礙加強工作。
- 【2026-07-07 文件審查殘留風險，機率低不預先處理】若使用者正在某個表單欄位打字時，恰好該渠道因分組跳動被 Vue 在兩個 `v-for` 之間 destroy/remount，原生 input focus 可能遺失（欄位值本身因 `edits` 以 slug 為 key 不會遺失，只有焦點可能跳掉）；範圍極窄且發生機率低，本次不特別處理，若上線後有回報再另行修正。

## High-Level Technical Design

> 以下說明兩張卡片共用的分組結構方向，供審查用；並非最終實作規格，實作者應把它當作情境參考而非照抄的程式碼。

```
// 兩張卡共用的形狀（各自獨立實作，不抽共用函式）：
unboundItems = items.filter(item => !isBound(item))   // 保留原始順序
boundItems   = items.filter(item =>  isBound(item))   // 保留原始順序

render:
  if unboundItems.length:
    <div class="group-label" id="...-group-unbound">未绑定 · {{ unboundItems.length }}</div>
    <ul-or-details-list role="group" aria-labelledby="...-group-unbound" :items="unboundItems" />
  if boundItems.length:
    <div class="group-label" id="...-group-bound">已绑定 · {{ boundItems.length }}</div>
    <ul-or-details-list role="group" aria-labelledby="...-group-bound" :items="boundItems" />
```

（`role="group"` + `aria-labelledby` 為 2026-07-07 文件審查後新增的無障礙分組語意，id 前綴依元件區分，如 `ch-group-*`／`bind-group-*`，元件內唯一即可。）

`ChannelsCard.vue` 額外在卡片標題下方加一行摘要（沿用 `SettingsSidebar.vue:33-34` 的 `boundCount`/`totalCount` 計算方式）：

```
<p class="ch-summary">{{ boundCount }} / {{ totalCount }} 已绑定</p>
```

`ChannelBindingCard.vue` 的展開/收合狀態改為一次性播種、不隨即時 `isBound()` 重算（2026-07-07 文件審查後決定，見 Key Technical Decisions）：

```
const openState = reactive<Record<string, boolean>>({})
watch(forms, (list) => {
  for (const f of list) {
    if (!(f.slug in openState)) openState[f.slug] = !isBound(f.slug)
  }
}, { immediate: true })
```

```
<details :open="openState[f.slug]"> ... </details>
```

## Implementation Units

- [x] **Unit 1: `ChannelsCard.vue` 分組與總覽計數**

**Goal:** 把「渠道绑定状态」總覽卡從單一平鋪列表改為「未綁定」「已綁定」兩個分區（未綁定在前），並在卡片標題下方加入「X / Y 已绑定」總覽計數。

**Requirements:** R1, R2, R4

**Dependencies:** 無

**Files:**
- Modify: `frontend/src/pages/Settings/ChannelsCard.vue`
- Test: `frontend/src/pages/Settings/ChannelsCard.spec.ts`

**Approach:**
- 新增 `boundCount`/`totalCount` computed（沿用 `SettingsSidebar.vue:33-34` 的計算方式），在 `<h2>` 下方渲染成一行摘要文字。
- 把目前單一 `channels` computed 的消費方式，改為兩個 computed：`unboundChannels = channels.filter(c => !c.bound)`、`boundChannels = channels.filter(c => c.bound)`，兩者都保留原陣列順序。
- 渲染兩個條件區塊（先未綁定、後已綁定），每個區塊前面加一個分組標籤（沿用 `SideNav.vue` 的 `.sidenav__group-label` 視覺語言，加上 `id`），區塊本身的清單容器加上 `role="group"`、`aria-labelledby` 指向該標籤 `id`（2026-07-07 文件審查決定，見 Key Technical Decisions）；區塊內部沿用既有 `.ch-list`/`.ch` markup 不變；只有非空分組才渲染其標籤＋容器。
- 每列本身的內容（`dofollowLabel`、`identity`、`blockers`）不變，只改變外層分組結構與資料來源。

**Patterns to follow:**
- `frontend/src/layout/SideNav.vue:107-162`（分組標籤＋逐組清單的結構與樣式）
- `frontend/src/pages/Settings/SettingsSidebar.vue:31-35`（`boundCount`/`totalCount` 計算方式）

**Test scenarios:**
- Happy path：給定 1 個已綁定 + 1 個未綁定渠道，兩個分組標題都渲染、且順序為「未綁定」在前、「已綁定」在後；頂部摘要顯示「1 / 2 已绑定」（更新既有「renders a row per channel…」測試，把 `rows[0]` 改為未綁定渠道、`rows[1]` 改為已綁定渠道，以符合新順序）。
- Happy path：兩個渠道都已綁定時，摘要顯示「2 / 2 已绑定」。
- Happy path：每個分組容器帶有 `role="group"` 且 `aria-labelledby` 指向該組標籤元素的 `id`，兩者的 `id` 互相對應且不與頁面上其他 id 衝突。
- Edge case：全部已綁定 → 只渲染「已绑定」分組，DOM 中不出現「未绑定」的標題或容器。
- Edge case：全部未綁定 → 只渲染「未绑定」分組。
- Edge case：`channels` 為空陣列 → `StateBlock` 的 `empty` 狀態渲染如常，不出現任何分組標題或摘要（既有「shows the empty state」測試的迴歸保護）。

**Verification:**
- `ChannelsCard.spec.ts` 全部通過（含更新後的順序斷言）；`npm run typecheck`、`npm run build`（frontend workspace）成功。

- [x] **Unit 2: `ChannelBindingCard.vue` 分組與預設展開/收合**

**Goal:** 把「渠道凭据绑定」表單卡改為與 Unit 1 一致的「未綁定」「已綁定」分組（未綁定在前），並讓未綁定渠道的表單預設展開、已綁定渠道的表單預設收合。

**Requirements:** R1, R3, R4

**Dependencies:** Unit 1（視覺一致性上應同批落地，非硬性程式相依）

**Files:**
- Modify: `frontend/src/pages/Settings/ChannelBindingCard.vue`
- Test: `frontend/src/pages/Settings/ChannelBindingCard.spec.ts`

**Approach:**
- 沿用既有 `isBound()` helper，對 `forms` 建立 `unboundForms`/`boundForms` 兩個 computed，各自保留原陣列順序。
- 分組渲染方式與 Unit 1 相同的分組標籤樣式＋`role="group"`/`aria-labelledby`（僅在該組非空時渲染）。
- 新增以 slug 為 key 的 `openState` reactive 狀態；`forms` 的 watch（沿用既有 `edits`/`lastSeeded` 的 seed-on-first-appearance 寫法）在每個 slug 第一次出現時，用當下的 `!isBound(f.slug)` 播種 `openState[slug]` 一次；每個 `<details>` 綁定 `:open="openState[f.slug]"`，之後不隨 `isBound()` 即時重算（2026-07-07 文件審查決定，見 Key Technical Decisions）——避免使用者剛送出成功就看到剛填的表單被收合、跳到「已綁定」分組。
- 表單欄位、submit/clear handler、422 inline error 顯示邏輯完全不變。

**Patterns to follow:**
- Unit 1 的分組標籤 markup／class／ARIA 屬性（視覺與語意需與 Unit 1 一致）
- `frontend/src/pages/Settings/ChannelBindingCard.vue:139-146`（`isBound()`）
- `frontend/src/pages/Settings/ChannelBindingCard.vue:109-124`（`edits`/`lastSeeded` 的 seed-on-first-appearance watch 寫法，`openState` 的播種邏輯應是同樣的形狀）

**Test scenarios:**
- Happy path：未綁定渠道的 `<details>` 渲染時帶有 `open` 屬性；已綁定渠道的 `<details>` 渲染時不帶 `open`。
- Happy path：表單依「未綁定」（前）/「已綁定」（後）分組，順序與 Unit 1 一致；每個分組容器帶有 `role="group"` 且 `aria-labelledby` 指向該組標籤的 `id`。
- Edge case：預設 mock（`getChannels: []`，即目前 `beforeEach` 的預設值）→ 所有表單皆為未綁定 → 只渲染「未绑定」分組，不出現空的「已绑定」標題。
- Integration：延伸既有「W2: a newly-appearing channel form does not itself count as a dirty edit」測試，額外斷言新streaming 進來的表單落在正確分組，且 `dirtyStore.anyDirty` 仍為 `false`。
- Integration：新增測試模擬 `['settings','channels']`（overview query）比 `['settings','channel-forms']` 更晚 resolve 的情境——斷言使用者已輸入但未送出的欄位值（`edits`）在該渠道之後被判定為已綁定、移動到「已绑定」分組時，仍完整保留不遺失。
- Integration（2026-07-07 文件審查新增）：模擬一個未綁定渠道被使用者成功送出憑證（`saveChannelCredential` resolve 成功、`['settings','channels']` 被 invalidate 並 refetch 回傳 `bound: true`）——斷言該渠道的 `<details>` 在 `isBound()` 翻成 `true` 之後仍維持 `open`（不會自動收合），即使它已經在下一次渲染中移動到「已綁定」分組。
- Regression：既有「offers a Clear button only when the channel is bound」測試（`ChannelBindingCard.spec.ts:100-119`）在該已綁定渠道的 `<details>` 改為預設收合後，需確認 jsdom 的 `.trigger('click')` 是否仍可直接命中；若不行，測試需先明確展開該 `<details>`（見 Open Questions → Deferred to Implementation）。

**Verification:**
- `ChannelBindingCard.spec.ts` 全部通過；`npm run typecheck`、`npm run build`（frontend workspace）成功。

## System-Wide Impact

- **Interaction graph：** 無新增事件、callback 或跨元件訊號；兩張卡仍各自獨立讀取同一份 `['settings','channels']` query cache。
- **Error propagation：** 不變——`StateBlock` 的 loading/empty/error 處理邏輯不受影響。
- **State lifecycle risks：** `ChannelBindingCard.vue` 中，分組（未綁定/已綁定）仍是即時依 `isBound()` 計算，所以無論是 overview query 比 forms query 更晚 resolve、或使用者剛送出成功觸發的 refetch，某個渠道都可能在該事件後把視覺分組從「未綁定」移到「已綁定」——這是分組本身刻意保持即時反映最新狀態的設計，不是缺陷。2026-07-07 文件審查決定把「展開/收合」狀態（`openState`）與分組解耦：`openState` 只在 slug 第一次出現時播種一次，之後不隨 `isBound()` 重算，所以分組移動不會連帶把使用者剛填、剛送出的表單強制收合；`edits`/`lastSeeded` 同樣以 slug 為 key，不受分組移動影響，資料不會遺失（見 Unit 2 Test scenarios 的對應測試）。
- **API surface parity：** 無——不涉及新端點；4 張排除在外的 OAuth 卡不適用本次改動。
- **Integration coverage：** 由 Unit 2 新增的「overview query 延遲 resolve」與「新表單 streaming 進來」測試涵蓋。
- **Unchanged invariants：** `GET /api/v1/settings/channels`、`GET /api/v1/settings/channels/forms`、`saveChannelCredential`、`saveChannelToken` 的契約與行為不變；`SettingsSidebar.vue` 既有的「N/M 已绑定」計數不變。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `ChannelsCard.spec.ts` 既有測試依賴 API 回傳順序做位置斷言，分組後順序改變會直接讓測試失敗 | Unit 1 的 Test scenarios 明確要求更新該測試的 `rows[0]`/`rows[1]` 斷言以符合未綁定優先順序 |
| `ChannelBindingCard.vue` 中 overview query 比 forms query 晚 resolve、或使用者剛送出成功時，渠道會在分組間跳動、`<details>` 在兩個 `v-for` 之間重新掛載 | `edits`/`lastSeeded` 以 slug 為 key，不受 DOM 分組位置影響；`openState` 同樣以 slug 為 key 且只播種一次、不隨分組移動重算，剛填寫/剛送出的表單不會被強制收合（2026-07-07 文件審查決定）；新增專門測試驗證延遲 resolve 與送出成功兩種情境下欄位值與展開狀態都不遺失 |
| 既有「Clear 按鈕」測試互動的渠道，現在預設收合，jsdom 是否仍可直接觸發按鈕點擊未知 | 列為 Deferred to Implementation；實作時實測，若失敗則在測試中先明確展開該 `<details>` |
| 空分組（全部已綁定或全部未綁定）若忘記隱藏標題，會出現「0 個項目」的空段落雜訊 | Key Technical Decisions 明確規定：分組標籤＋容器只在該組非空時渲染，兩個 Unit 的 Test scenarios 都涵蓋此邊界情況 |
| `role="group"` + `aria-labelledby` 是本 SPA 中首次出現的分組 ARIA 語意，若 id 命名不慎可能與頁面上其他 id 衝突 | 使用元件內唯一、有前綴的 id（如 `ch-group-*`／`bind-group-*`），兩個 Unit 的 Test scenarios 都新增斷言驗證 `aria-labelledby` 正確對應 |

## Sources & References

- Related code: `frontend/src/pages/Settings/ChannelsCard.vue`, `frontend/src/pages/Settings/ChannelBindingCard.vue`, `frontend/src/layout/SideNav.vue`, `frontend/src/pages/Settings/SettingsSidebar.vue`, `frontend/src/components/StateBlock.vue`
- Institutional learnings: `docs/solutions/architecture-patterns/server-side-gap-computation-2026-06-05.md`, `docs/solutions/best-practices/never-smoke-test-real-save-endpoints-2026-05-19.md`
