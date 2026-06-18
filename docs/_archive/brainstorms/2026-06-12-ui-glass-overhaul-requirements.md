---
date: 2026-06-12
topic: ui-glass-overhaul
---

# WebUI 全面視覺升級 — Glass / Gradient 現代感

## Problem Frame

目前 WebUI 的 `tokens.css` 和 `index.css` 已有 glass-bg、backdrop-filter blur 的雛形，
但整體視覺停留在「淺灰底 + 輕描邊卡片」，缺乏 Glass/Gradient 風格的核心張力：
豐富的漸層背景、強 blur 毛玻璃卡片、明確的深度層次感。
四個頁面（主頁 pipeline、Batch、History、Settings）視覺語言不統一，部分頁面完全未套用 glass 元素。

## Requirements

**設計 Token 升級**
- R1. 更新 `tokens.css`：body 背景改為深度漸層（如 `#0f0c29 → #302b63 → #24243e` 或品牌紫藍），
  `--glass-bg` 改為 `rgba(255,255,255,0.10)`，`--glass-border` 改為 `rgba(255,255,255,0.18)`，
  `--glass-blur` 新增 `blur(20px)`，`--shadow-glass` 新增帶色彩的柔陰影。
- R2. 新增 `--gradient-hero` token（全版面用漸層）與 `--gradient-accent`（CTA 按鈕用）。

**Pipeline Wizard（主頁）**
- R3. Step bar 升級：當前步驟圓圈加上 `--gradient-accent` 光暈脈衝動畫（CSS keyframe），
  已完成步驟顯示綠色 checkmark，待辦步驟半透明。
  所有 keyframe 動畫必須包裹在 `@media (prefers-reduced-motion: no-preference) { … }` 中。
- R4. 每個 wizard 卡片改為強 glass card：backdrop-filter blur(20px)、白色半透明底、
  白色細邊框、帶色彩柔陰影；hover：`translateY(-2px)`，transition `200ms ease-out`；
  active/pressed：`translateY(0px)` + 陰影縮減 10%，提供觸感回饋。
  所有 glass 元件的標準 blur 深度為 `blur(20px)`，除非特別說明。
- R5. 「一鍵生成並發布」CTA 按鈕改為漸層色 + 微光 shine 動畫（CSS ::after pseudo 掃過）。
  按鈕需具備 `position: relative; overflow: hidden` 作為前置樣式。
  shine keyframe 動畫必須包裹在 `@media (prefers-reduced-motion: no-preference) { … }` 中。
- R6. 成功狀態（發布結果卡）背景改為綠色漸層 glass，失敗改為紅色漸層 glass，視覺反差明顯。
  卡片標題區必須包含圖示（成功 ✓，失敗 ✕ 或 ⚠），不得僅靠顏色區分（WCAG 1.4.1）。

**Batch 批量發布**
- R7. Batch 輸入區（大文字框、URL 清單）改為 glass card 包覆，與主頁視覺語言統一。
- R8. Batch 批量進度顯示加入進度條動畫：玻璃底條（always-visible，opacity 0.3）+ 漸層填充條；
  初始狀態填充寬度 0%，完成時填充色過渡到成功綠漸層持續 1s；進度條動畫同樣遵守 prefers-reduced-motion。
  注意：R8 僅適用於 Batch 頁面內的進度條元件，不適用於 `campaign_progress` 獨立頁面（後者在本次範圍外）。

**History 歷史記錄**
- R9. 歷史記錄表格行改為交替半透明 glass row，hover 行高亮為白色輕量 glass。
- R10. 狀態標籤（published / drafted / failed）改用顏色語義明確的 pill badge，
  含對應色彩的微光暈（box-shadow colored glow）；badge 必須保留文字標籤，glow 僅為視覺強化（WCAG 1.4.1）。

**Settings**
- R11. Settings sidebar（`_settings_sidebar.html`）改為左側 glass panel，
  active 項目加上 `--gradient-accent` 左側高亮條。
- R12. 各設定分區卡片統一套用 glass card（同 R4），取代目前的白底卡片。

**全局基礎**
- R13. `base.html` body 套用 `--gradient-hero` 背景，並在 `<body>` 內插入一個
  `<div class="bg-orbs" aria-hidden="true">` 元素（不使用 `::before` 偽元素，以避免
  backdrop-filter 疊合脈絡衝突）。該元素使用 `position: fixed; z-index: -1;
  pointer-events: none` 包含 2-3 個 `border-radius:50%` 的裝飾色塊（不帶 filter/blur 自身），
  靠背景漸層色製造景深，不干擾任何互動。同時在 `:root` 中設定 `color-scheme: dark`
  使瀏覽器 scrollbar / autofill 配合深色主題。
- R14. 所有 `<button>` focus ring 改為品牌色 glow（`box-shadow: 0 0 0 3px rgba(99,102,241,0.4)`）。
- R15. 全部 CSS 變更保持零 Node/bundler 依賴，純 CSS + 原生 ES Module。

## User Flow

```
[body: gradient-hero bg + 裝飾光球]
        │
   ┌────▼────────────────────────────────────────┐
   │  Navbar (gradient bar)                      │
   └────┬────────────────────────────────────────┘
        │
   ┌────▼────────────────────────────────────────┐
   │  Step Bar: ①(pulse glow) ─ ② ─ ③ ─ ④     │
   └────┬────────────────────────────────────────┘
        │
   ┌────▼────────────────────────────────────────┐
   │  Glass Card (blur 20px, white 10% bg)       │
   │  ┌── URL 輸入 ──────────────────────────┐   │
   │  │  paste-to-derive input              │   │
   │  │  main / category / work URL rows    │   │
   │  └─────────────────────────────────────┘   │
   │  [分析連結]  [一鍵生成▶shine CTA]           │
   └─────────────────────────────────────────────┘
        │ 成功
   ┌────▼────────────────────────────────────────┐
   │  Glass Card — 生成預覽                      │
   │  [AI 生成 badge] 標題 · 字數 · 外鏈數       │
   │  [重新生成] [編輯]                          │
   │  [驗證] [發布 ▼ 草稿/正式]                  │
   └─────────────────────────────────────────────┘
        │ 發布完成
   ┌────▼────────────────────────────────────────┐
   │  Green Glass 成功卡 / Red Glass 失敗卡       │
   │  文章連結按鈕 + URL 顯示                     │
   └─────────────────────────────────────────────┘
```

## Success Criteria

- 任何新使用者開啟主頁，第一眼感受到「現代 SaaS 工具」而非「Bootstrap 表單」
- Step bar 在當前步驟有明確視覺脈衝，用戶不需要閱讀文字就能看出進度
- 四個頁面視覺語言統一（同一套 glass token），對比度符合 WCAG AA（4.5:1 以上）
- 零新外部依賴引入（無 Tailwind、無 Alpine.js、無 bundler）

## Scope Boundaries

- 不重構路由或後端邏輯，純前端 CSS/HTML 改動
- 不改變任何表單 `name`、API 路由、CSRF 機制
- 不引入 dark mode toggle（本次目標是單一深色漸層主題；工具為內部操作者使用，不需多主題）
- `campaign_progress`、`equity_ledger`、`seo_viz` 等獨立輔助頁面本次不納入新視覺設計；
  但 `tokens.css` / `base.html` 的全局改動會影響這些頁面，需在 QA 階段做視覺冒煙測試以確認無破版
- 瀏覽器最低支援：Chrome 100+、Safari 15.4+、Firefox 103+。
  須在 `backdrop-filter` 使用處加 `@supports (backdrop-filter: blur(1px))` guard，
  fallback 使用 `rgba(30,27,75,0.85)` 純色背景

## Key Decisions

- **深色漸層底 vs 淺色白底**：選深色，因為 glass card 在深色底才能展現最大視覺張力；現有白底 glass 效果幾乎不可見
- **改 tokens.css 而非新增 CSS 檔**：避免 specificity 衝突，讓所有頁面共享同一 token 更新
- **裝飾光球用 CSS ::before 偽元素**：零 DOM 影響，CSS `pointer-events: none`，不干擾任何交互

## Dependencies / Assumptions

- 現有 `tokens.css` 已被 `base.html` 在所有頁面 link，升級 token 即全局生效
- 字型 `Outfit` 已 import，無需額外字型

## Outstanding Questions

### Deferred to Planning

- [Affects R4][Needs research] `--glass-bg: rgba(255,255,255,0.10)` 在最暗漸層色 `#0f0c29` 上的合成文字對比度需實測；建議工具：WebAIM Contrast Checker，量測文字 token `rgba(255,255,255,0.92)` 對合成底色。
- [Affects R7][Technical] Batch 頁面 `_tab_batch.html` 中「大文字框 + URL 清單」的確切 HTML 結構需先確認，才能決定 glass card 的包覆層級。

## Next Steps

→ `/ce:plan` for structured implementation planning
