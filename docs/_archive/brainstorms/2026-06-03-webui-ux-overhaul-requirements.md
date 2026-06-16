---
date: 2026-06-03
topic: webui-ux-overhaul
---

# WebUI UI/UX Complete Overhaul

## Problem Frame

The WebUI is a solo-operator tool used daily for backlink publishing. It has grown organically across 10+ PRs and now shows three systemic cracks:

1. **Navigation dead-ends** — 8 pages exist (index, settings, health, schedule, equity_ledger, sites, pr_queue, result) but the only cross-page link is a "back" button; reaching any secondary page requires knowing its URL.
2. **Visual inconsistency** — Templates mix inline `style=""` attributes with CSS classes; `index.css` still contains a duplicate `:root` block despite tokens.css being the single source of truth; card hover animations (`translateY(-4px)`) feel cheap.
3. **Settings page density** — The settings page renders all channel config cards vertically in one long scroll under a 4-tab bar; with ~6+ channels and LLM config, it becomes unwieldy.

User profile: single operator, efficiency > friendliness, no onboarding needed.

## User Flow

```
  ┌───────────────── Global Nav (persistent, top bar) ────────────────────┐
  │  [发布]  [健康]  [排程]  [权益]  [站点]  [PR队列]  [设置]             │
  └────────────────────────────────────────────────────────────────────────┘
            │
            ▼ (/ index)
  ┌─────────────────────────────────────┐
  │  Mode toggle: [单笔] [批量]          │
  │  Step bar: 输入→生成→验证→发布       │
  │  Active panel (tab content)          │
  │  Copilot FAB (bottom-right)          │
  └─────────────────────────────────────┘

            │ /settings
            ▼
  ┌─────────────────────────────────────────────────────┐
  │ Left sidebar (200px)  │  Right detail pane          │
  │  ─ 綁定總覽            │  [content for selected      │
  │  ─ 发布渠道             │   section rendered here]    │
  │    ├ Medium            │                             │
  │    ├ Blogger           │                             │
  │    ├ Velog             │                             │
  │    ├ Telegraph         │                             │
  │    └ [others]          │                             │
  │  ─ 全局设置             │                             │
  │    ├ 关键词             │                             │
  │    └ 排程              │                             │
  │  ─ AI 引擎             │                             │
  └──────────────────────────────────────────────────────┘
```

## Requirements

**Global Navigation**
- R1. Add a persistent top navigation bar to `base.html` (shared by all pages) containing links to: 发布（/）、健康（/health）、排程（/schedule）、权益（/equity-ledger）、站点（/sites）、PR队列（/pr-queue）、设置（/settings）.
- R2. The active page's nav item is visually highlighted (active state distinct from hover state).
- R3. The nav bar reuses the existing `--primary` / `--gradient` design tokens; no new color values.
- R4. The nav must not break the existing Copilot FAB z-index (FAB floats above page content, not above nav).

**Settings Page Restructure**
- R5. Replace the current horizontal 4-tab bar + vertical card scroll with a two-column layout: 200px left sidebar tree + fluid right detail pane.
- R6. Sidebar tree groups: 綁定總覽 → 发布渠道（expandable, one child per registered adapter slug） → 全局设置（关键词、排程） → AI 引擎. If zero adapters are registered, 发布渠道 shows a single disabled item "（暂无渠道）" in lieu of children.
- R7. Clicking a sidebar item swaps the right pane content (JS-only, no page reload). Sidebar active item shows a distinct active style (left border accent + background tint). While the pane is swapping, a small inline spinner appears in the pane header; on error, a one-line error message replaces the spinner. No URL hash sync — solo operator has no bookmarking need.
- R8. On first load, the sidebar opens to 綁定總覽 (matching current default behavior).
- R9. The existing channel card templates (`_settings_channel_*.html`, `_settings_binding_*.html`) are reused as right-pane content — not rewritten. Only the outer scaffold changes.

**Visual Consistency**
- R10. All inline `style=""` attributes in `index.html`, `settings.html`, `base.html` moved to CSS classes (in the relevant `.css` file or tokens.css). Inline styles permitted only for data-driven values that cannot be expressed as static CSS (e.g., progress bar widths set by JS).
- R11. Duplicate `:root` block in `index.css` (lines 3–16) removed; `index.css` consumes `var(--…)` from `tokens.css` only.
- R12. Card hover transition changed from `transform: translateY(-4px)` to `box-shadow` deepening only (no layout shift): `box-shadow: 0 8px 24px -8px rgba(0,0,0,0.12)` on hover.
- R13. Navbar hover animation (`translateY(-2px)`) removed from `.navbar:hover` — navbars don't float.
- R14. Button inline styles in `index.html` navbar (the "设置", "重置", Blogger token badge) extracted to named classes in `index.css`.

**Main Page Workflow Polish**
- R15. Step bar connectors use a CSS transition so a step turning "done" animates smoothly (opacity + color, 200ms ease).
- R16. ~~Removed~~ (no problem driver; `<template>` loading element is not a source of any reported issue).
- R17. Flash message auto-dismisses after 4 seconds via JS (removes need to manually click ×).

**Copilot Panel**
- R18. The Copilot FAB moves to the bottom-right of the viewport (fixed position), clear of the new global nav. Current placement already bottom-right; verify z-index remains above nav (z-index: 1050 or higher).
- R19. FAB label "优化建议" shown at ≥1280px viewport width; at narrower widths the label hides and the `✦` icon remains. Panel open behavior is unchanged at all widths (slides in from the right, overlays page content, does not push the global nav).

## Success Criteria

- Navigating from index → health → schedule → settings requires zero URL typing.
- Settings page: reaching any channel config requires ≤2 clicks from page load.
- Zero inline `style=""` on layout/color/spacing in index.html and settings.html after the change (data-driven JS exceptions allowed).
- Card hover produces no layout shift (no translateY).
- All existing tests pass (no route/template regressions).

## Scope Boundaries

- **Out**: Dark mode — adds significant token complexity, low ROI for single operator.
- **Out**: Mobile responsiveness overhaul — operator uses desktop only.
- **Out**: Rewriting channel card templates (`_settings_channel_*.html`) — content is correct, only the scaffold wrapper changes.
- **Out**: New pages or new features — this is purely visual/IA work.
- **Out**: Replacing Bootstrap 5 — too large a carrying cost.
- **Out**: Removing Google Fonts CDN — acceptable latency for single-operator local/VPS use.

## Key Decisions

- **Left-sidebar for settings, not accordion**: Accordion hides options below the fold; sidebar keeps all sections scannable at a glance. Low additional carrying cost for a single-page JS swap.
- **Global nav in base.html**: All pages extend base.html already; one change propagates everywhere.
- **Reuse channel templates as-is**: The sub-templates are already correct; the refactor buys a better scaffold with zero content risk.
- **No URL hash sync for settings sidebar**: Solo operator has no bookmarking need; hash sync would add ESM interaction risk (double-init) with zero benefit.
- **No page reload for settings sidebar**: JS pane-swap is ~30 lines of vanilla JS; server-side route per section would add 6+ new routes with no added capability.

## Dependencies / Assumptions

- All 8 pages extend `base.html` — confirmed from template inspection.
- Registered adapter slugs are available to the settings route via `registered_platforms()` — confirmed from architecture notes.
- The settings route already passes `dashboard_channels` to the template; sidebar channel list can be derived from the same data.

## Outstanding Questions

### Resolve Before Planning
_(none — all product decisions resolved)_

### Deferred to Planning

- [Affects R7][Technical] How does the settings sidebar JS interact with the existing `settings.js` ESM entry? Verify no double-initialization risk when the right pane swaps content that includes `<script>` tags or data-attributes.
- [Affects R5][Technical] Does the current `settings.css` assume full-width layout? Check for any `max-width` or `width: 100%` rules that would break inside a `calc(100% - 200px)` right pane.
- [Affects R1][Needs research] Confirm the exact URL paths for health, equity-ledger, pr-queue routes — they may differ from the display names used above.

## Next Steps

→ `/ce:plan` for structured implementation planning
