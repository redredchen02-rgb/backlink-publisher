---
title: "feat: Preview & Edit step before publish"
type: feat
status: completed
date: 2026-06-23
---

# feat: Preview & Edit step before publish

## Overview

在「已驗證」和「發布」之間插入一個強制性的預覽編輯步驟。目前流程是
`驗證 → 立即發布`，用戶沒有機會確認或修改文章內容；一旦發布錯誤，事後
修改很麻煩。

改後流程：`驗證 → 預覽/編輯（必過關卡）→ 確認發布`。「發布進行中」的
busy 面板只在用戶點擊「確認發布」後才出現。

## Problem Frame

用戶在驗證完成後直接進入同步發布，沒有機會核對 AI 生成的文章標題與正
文，也無法在發布前微調錨文字措辭。發布後若需修改則必須前往目標平台手
動操作，代價高。

## Requirements Trace

- R1. 驗證完成後顯示每篇文章的可編輯預覽（標題、正文、錨文字）
- R2. 用戶必須明確觸發「確認發布」動作，發布才開始
- R3. 用戶在預覽步驟所做的編輯，必須完整反映到實際發布的 payload
- R4. 「發布進行中，請勿關閉」的 busy 面板只在確認後才出現
- R5. 不觸碰後端——publish endpoint 不變；編輯是純前端 payload 轉換

## Scope Boundaries

- 不新增後端 API（R5）
- 不實作 Markdown 即時渲染預覽（純文字 textarea 即可；複雜渲染留未來）
- 不修改 Draft 儲存流程（draft 仍捕捉原始 validated rows；此 PR 限定
  Workbench 直接發布路徑）
- 不改動 legacy `/ce:*` Flask 路由（SPA 分支）

## Context & Research

### Relevant Code and Patterns

- `frontend/src/stores/publish.ts` — Pinia store（`Stage` 型別、`validated`、
  `runPublish()` 接受 `validated.value` 作為 plans payload）
- `frontend/src/pages/Publish/PublishWorkbench.vue` — Step 3 fieldset 顯示
  已驗證列表 + 直接出現「發布」按鈕；無編輯欄位
- `frontend/src/api/pipeline.ts` — `PlanRow = Record<string, unknown>`；
  `publishBacklinks()` 接受 `plans: PlanRow[]`
- `frontend/src/components/StateBlock.vue` — 現有 `<script setup lang="ts">`
  + scoped CSS 模式，新元件照此慣例
- `frontend/src/stores/publish.spec.ts` — Vitest + Pinia 測試慣例

### Institutional Learnings

- 前端規定：禁止 inline `on*` handler，禁止 `window.*` 全域 API，禁止
  untrusted `${…}` 注入 `innerHTML`
- `PlanRow` 的 display fields 用 `field(row, key)` 防禦性存取（返回
  `typeof v === 'string' ? v : ''`），新元件照此

## Key Technical Decisions

- **純前端 patch，不回傳後端重新驗證**：編輯後的 rows 直接作為 publish
  payload，不重新跑 validate。理由：validate 只做 URL 可達性檢查，文字
  修改不影響錨文字有效性；強制重驗會造成額外延遲且使 UX 複雜化。
- **`edits: Record<index, PlanRowPatch>` 疊加模式**：用 index 作 key 儲存
  局部 patch，`effectivePlans` computed 把 validated rows 與 patch 合併。
  優點：只儲存差異，reset 只需清空 edits；驗證結果本身保持不變，便於 debug。
- **不新增 `Stage` 列舉值**：預覽編輯是 `validated` stage 的 UI 展開，
  不是獨立 stage。Stage machine 不改（`input|planned|validated|published`），
  避免 spec 與測試的連鎖修改。
- **新元件 `ArticleReviewRow.vue`** 封裝單篇的預覽+編輯，
  `PublishWorkbench.vue` v-for 渲染；符合現有「元件化小 widget」慣例
  （參照 `ProfileSelector.vue`、`StateBlock.vue`）。
- **發布按鈕改名**：從「發布」改為「確認並發布」，視覺語義上要求用戶
  主動確認，滿足 R2 而不用加 modal。

## Open Questions

### Resolved During Planning

- *需要重新驗證嗎？*：否。見 Key Technical Decisions。
- *是否需要 Markdown 渲染預覽？*：此 PR 不實作。純 textarea 滿足核心
  需求；渲染功能可在後續 PR 疊加。
- *draft 保存路徑是否需要捕捉 edits？*：此 PR 不涉及。Draft 目前在
  validated 完成後直接保存原始 rows，行為不改。

### Deferred to Implementation

- `PlanRow` 實際含有哪些欄位（`body_md`、`content_markdown`、`anchors`
  格式）：實作時讀 API response inspect；`field()` 防禦性存取已覆蓋不存在
  欄位。
- 錨文字展示格式（純文字 list vs. 可編輯）：實作時根據實際 `anchors` 值
  型別決定。

## High-Level Technical Design

> *此圖示意預期方向，供 review 驗證；不是要照抄的程式碼。*

```
publish store (publish.ts)
├── validated: PlanRow[]          ← 來自 /pipeline/validate（不改）
├── edits: Record<idx, Patch>     ← 新：用戶在預覽步驟的局部修改
├── effectivePlans: PlanRow[]     ← 新 computed：merge validated + edits
└── runPublish()                  ← 改：改為傳 effectivePlans

PublishWorkbench.vue — step 3 (validated stage)
├── v-for row in validated
│     └── <ArticleReviewRow :row :patch @patch="store.patchRow(i, $e)" />
└── <button @click="onPublish">確認並發布</button>   ← 確認點後才 busy

ArticleReviewRow.vue
├── props: row: PlanRow, patch: PlanRowPatch
├── emit: patch(PlanRowPatch)
├── 顯示：標題（input）、正文（textarea）、錨文字（read-only list）
└── 本地 draft state → 失焦/Enter 時 emit patch
```

## Implementation Units

- [x] **U1: 擴充 publish store — edits 狀態與 effectivePlans**

**Goal:** store 能記錄用戶編輯、合併成最終 publish payload

**Requirements:** R3, R5

**Dependencies:** 無

**Files:**
- Modify: `frontend/src/stores/publish.ts`
- Test: `frontend/src/stores/publish.spec.ts`

**Approach:**
- 新增 `type PlanRowPatch = { custom_title?: string; content_markdown?: string }`（移除 `title?`：UI 唯一編輯欄位是 `custom_title`；若 patch 含 `title` 會 spread-overwrite 原始 row 的 `title` 欄位，干擾 `rowLabel()` 邏輯）
- 新增 `edits: ref<Record<number, PlanRowPatch>>({})`
- 新增 `patchRow(idx: number, patch: PlanRowPatch)` action：**必須用物件賦值** `edits.value[idx] = { ...edits.value[idx], ...patch }` 而非 `Object.assign`，確保 U2 的 `watch(patch, ...)` shallow watch 能偵測到 reference 改變
- 新增 `effectivePlans: computed<PlanRow[]>` — map `validated` with index，若 `edits[i]` 存在則 `{ ...row, ...edits[i] }`
- 修改 `runPublish()` 的 `plans` 從 `validated.value` 改為 `effectivePlans.value`
- `reset()` 加入清空 `edits`
- `runPlan()` 亦呼叫 `clearEdits()`（緊跟 `validated.value = []` 之後），防止舊 edits 在 re-plan 但未立即 re-validate 的情況下殘留並污染下一輪 effectivePlans
- 重新 validate（`runValidate()`）成功後（在 try 內、`await` 回傳後）呼叫 `clearEdits()`，**不放 finally**——避免 validate 失敗時清除用戶已輸入的編輯
- 新增 `clearEdits()` 內部 helper（被 reset、runPlan、runValidate 成功路徑呼叫）

**Test scenarios:**
- Happy path: `patchRow(0, { custom_title: 'X' })` 後 `effectivePlans[0].custom_title === 'X'`，其餘 row 欄位不變
- Happy path: `runPublish()` 呼叫 `publishBacklinks` 時 plans 使用 `effectivePlans`（mock 驗證），而非原始 `validated`
- Edge case: 無 edits 時 `effectivePlans` 等於 `validated`（pure passthrough）
- Edge case: `patchRow` 只合併指定欄位，不覆蓋未提及欄位
- Edge case: `reset()` 後 `edits` 為空物件 `{}`
- Edge case: `runValidate()` 成功後 `edits` 清空（舊 patch 不殘留）
- Edge case: `runValidate()` 失敗時 `edits` 保留（用戶不需重新輸入編輯）
- Edge case: `runPlan()` 後 `edits` 清空（與 `validated` 同步清除）
- Integration: 新增 `describe('edits and effectivePlans')` 區塊（原 U4 測試，合併至此），保留現有 stage machine / loadPlatforms / reset 測試不改

**Verification:** `publish.spec.ts` 全部通過；`effectivePlans` 被 `runPublish` 使用由 mock 確認；`npx vitest run` 全綠

---

- [x] **U2: 新增 `ArticleReviewRow.vue` 元件**

**Goal:** 單篇文章的可折疊預覽＋編輯 widget

**Requirements:** R1, R2, R3

**Dependencies:** U1（`PlanRowPatch` 型別）

**Files:**
- Create: `frontend/src/components/ArticleReviewRow.vue`
- Test: `frontend/src/components/ArticleReviewRow.spec.ts`

**Approach:**
- Props: `row: PlanRow`, `patch: PlanRowPatch`（外部 controlled，反映目前已編輯狀態）
- Emit: `patch` with `PlanRowPatch` payload（統一使用 `patch`；U3 的 `@patch` 監聽與此一致）
- 顯示欄位（防禦性 `field()` 存取）：
  - **標題**：`<input>` 預填 `patch.custom_title ?? field(row, 'custom_title') ?? field(row, 'title')`
  - **正文**：`<textarea rows="8">` 預填 `patch.content_markdown ?? field(row, 'content_markdown')`
  - **目標 URL**：`<span>` 只讀
  - **錨文字**：`<ul>` 只讀列表（`field(row, 'anchors')` 若為字串則用換行分割顯示）
- 本地 `localTitle` / `localBody` ref 作為受控 input；失焦時 emit patch（避免每鍵盤事件打 store）
- 初始化：`watch(patch, handler, { immediate: true })` 同步外部 patch 到本地（`immediate: true` 確保 mount 時正確預填；支援外部重置）
- 可折疊：`<details><summary>{{ localTitle || '(無標題)' }}</summary>...編輯區</details>` — 原生 HTML，零 JS 折疊；`<summary>` 顯示 `localTitle`（即用戶編輯後的值），避免折疊後看不出哪篇已被修改；若 `localTitle !== originalTitle`，summary 加視覺標記（例如 `*`）
- 不注入 `innerHTML`；正文用 `<textarea>` 純文字

**Patterns to follow:**
- `StateBlock.vue` 的 `<script setup lang="ts">` + scoped CSS
- `PublishWorkbench.vue` 的 `field()` 防禦性存取模式

**Test scenarios:**
- Happy path: 渲染時標題 input value 等於 `field(row, 'custom_title')`
- Happy path: 用戶改標題後失焦，emit `patch` event with `{ custom_title: newValue }`
- Happy path: 若 `patch.custom_title` 已設定，input 顯示 patch 值（controlled）
- Edge case: `field(row, 'content_markdown')` 為空字串時 textarea 顯示空（不顯示 undefined）
- Edge case: 外部 patch prop 改變（v-model 重置）時，本地 state 同步更新

**Verification:** Vitest component tests pass；元件在 Workbench 中 mount 時各欄位正確顯示

---

- [x] **U3: 更新 `PublishWorkbench.vue` — 插入預覽編輯區**

**Goal:** Step 3（validated）展示每篇文章的可編輯預覽，發布按鈕改名以強調確認

**Requirements:** R1, R2, R4

**Dependencies:** U1, U2

**Files:**
- Modify: `frontend/src/pages/Publish/PublishWorkbench.vue`

**Approach:**
- Step 3 fieldset (`v-if="store.validated.length"`)：
  - 移除簡單 `<ul>` 列表
  - 換成 `v-for (row, i) in store.validated` 渲染 `<ArticleReviewRow>`，
    binding `:row="row"` `:patch="store.edits[i] ?? {}"` `@patch="store.patchRow(i, $event)"`
  - 保留 busy panel（publish-busy）和 spinner——位置不動，仍在按鈕上方
  - 發布按鈕文字改為「確認並發布」（`store.publishing ? '發布進行中…' : '確認並發布'`）
  - **Step 3 fieldset 條件改為 `v-if="store.validated.length && !store.publishResult"`**，確保 Step 4（結果卡）出現後 Step 3 自動隱藏，避免編輯區與結果卡同時可見造成混亂
- Steps 指示列（`<ol class="steps">`）：legend 文字可改為「3 · 預覽/確認」但
  不新增 step（避免 stage machine 改動；見 Key Technical Decisions）
- Import `ArticleReviewRow`；繼承現有 `onPublish()` 邏輯不動（R4 已自動滿足
  因為 busy 只在 `store.publishing` 為 true 時出現，而 `store.publishing` 只在
  `runPublish()` 呼叫後翻轉）

**Test scenarios:**
- Integration: `v-if="store.validated.length"` 條件 — validated 空時不渲染編輯區
- Integration: 渲染 N 篇文章時出現 N 個 `ArticleReviewRow`（v-for key 正確）
- Integration: 點擊「確認並發布」後 `store.publishing` 變 true，busy panel 出現

**Verification:** Dev server (`python webui.py`) 手動確認：驗證完成後能看到每篇文章可編輯；改標題後點「確認並發布」，publish payload 包含修改後的標題

## System-Wide Impact

- **互動圖**：`effectivePlans` 是純 computed，不改 API contract；publish endpoint
  收到的仍是 `PlanRow[]` ——後端零影響
- **Draft 路徑**：Draft 儲存在 `DraftsPage` 中由獨立按鈕觸發（目前 Workbench
  無 Save Draft 按鈕），此 PR 不涉及
- **重新計劃（runPlan）**：`runPlan()` 呼叫 `clearEdits()` 與 `validated.value = []` 同步執行，確保即使用戶 re-plan 後未立即 validate，stale edits 也不會殘留
- **不變的不變量**：`Stage` 型別不改（`input|planned|validated|published`）；
  `/api/v1/pipeline/publish` endpoint 不改；`validated` ref 語義不改

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `content_markdown` 欄位名稱與實際 PlanRow 不一致 | 實作時先 `console.log(validated[0])` 確認欄位名；`field()` 防禦存取保證不 crash |
| `ArticleReviewRow` watch(patch) 造成循環更新 | watch 用 `{ deep: false }`，emit 只在失焦時觸發，不在 watch 內 emit |
| 大量文章時（>10 篇）UI 過長 | `<details>` 折疊預設收起（不帶 `open` attr）；用戶按需展開 |

## Sources & References

- Related code: `frontend/src/stores/publish.ts`, `frontend/src/pages/Publish/PublishWorkbench.vue`
- Related code: `frontend/src/api/pipeline.ts` (`PlanRow`, `publishBacklinks`)
- Pattern: `frontend/src/components/StateBlock.vue` (Vue 3 setup + scoped CSS)
- Pattern: `frontend/src/stores/publish.spec.ts` (Vitest + Pinia mock pattern)
