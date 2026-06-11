---
title: "feat: WebUI comprehensive UX overhaul — 7-phase incremental optimization"
type: feat
status: active
date: 2026-06-11
claims:
  paths:
    - webui_app/templates/base.html
    - webui_app/static/css/tokens.css
    - webui_app/static/css/global_nav.css
    - webui_app/static/css/index.css
    - webui_app/static/css/settings.css
    - webui_app/static/js/mode_toggle.js
  shas: {}
---

# WebUI Comprehensive UX Overhaul

## Executive Summary

7-phase incremental optimization of the Backlink Publisher WebUI. Each phase is independently shippable — no big-bang rewrite. Prioritized by impact/effort ratio. Total estimated effort: **~40-50 hours** across all phases.

---

## Current State Analysis

### Architecture Facts
- **Template count**: 19 WebUI templates (base.html + 18 page/partial templates)
- **CSS files**: 6 (`tokens.css`, `global_nav.css`, `index.css`, `settings.css`, `copilot.css`, `schedule.css`)
- **JS files**: 18 modules (13 page-level, 5 shared in `lib/`)
- **Route modules**: 37+ files under `routes/`
- **Design system**: Glass morphism via CSS custom properties (`tokens.css`), Bootstrap 5.3.0 CDN
- **Nav items**: 10-12 items in flat horizontal bar (global_nav)
- **Responsive breakpoints**: Single 768px only (in `index.css`)
- **Accessibility**: Minimal — some `role="status"` and `aria-live`, no skip-nav, no keyboard shortcuts

### Pain Points (Ranked by Severity)
1. **Navigation overflow** — 10+ items don't fit on mobile; no grouping
2. **Homepage information overload** — 4-step wizard + tabs + mode toggle all on one page
3. **Settings complexity** — sidebar + 4 pane sections + 7+ channel cards, each expandable
4. **No dark mode** — all colors hardcoded in light theme
5. **No search** — no way to find settings, history items, or commands quickly
6. **Poor mobile UX** — single 768px breakpoint, no touch optimization
7. **No global notifications** — flash messages disappear, no persistent notification center

---

## Phase Priority (Impact/Effort)

| Phase | Impact | Effort | Priority |
|-------|--------|--------|----------|
| 5. Dark Mode & Themes | ★★★★★ | ★★☆ | **P0 — Highest ROI** |
| 1. Navigation Overhaul | ★★★★★ | ★★★ | **P0 — Highest ROI** |
| 7. Accessibility | ★★★★☆ | ★★☆ | **P1 — Low effort, high compliance** |
| 3. Mobile & Responsive | ★★★★☆ | ★★★ | **P1 — Critical for operators** |
| 4. Notifications & Search | ★★★★☆ | ★★★★ | **P2 — Productivity boost** |
| 2. Homepage Simplification | ★★★☆☆ | ★★★★ | **P2 — Moderate complexity** |
| 3. Settings Reorganization | ★★★☆☆ | ★★★★★ | **P3 — Lowest ROI, defer** |

---

## Phase 1: Dark Mode & Themes (P0 — Highest ROI)

**Goal**: Add dark mode using existing CSS custom property system. Zero new dependencies.

### Files to Modify

| File | Changes |
|------|---------|
| `static/css/tokens.css` | Add `[data-theme="dark"]` override block |
| `base.html` | Add theme toggle button in global nav; load theme from localStorage before paint |
| `static/css/global_nav.css` | Add dark mode overrides for nav bar |
| `static/css/index.css` | Add dark mode overrides for cards, forms, tables |
| `static/css/settings.css` | Add dark mode overrides for settings layout |
| `static/css/copilot.css` | Add dark mode overrides for copilot panel |
| `static/js/mode_toggle.js` | New file: `theme-toggle.js` (ESM) |
| `static/js/lib/dom.js` | Add `readTheme()` / `setTheme()` helpers (optional, can be inline) |

### Implementation Approach

**Step 1: Extend tokens.css with dark tokens**

```css
/* Dark mode tokens */
[data-theme="dark"] {
    --primary: #818cf8;
    --primary-dark: #6366f1;
    --secondary: #9ca3af;
    --gradient: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
    --success: #34d399;
    --danger: #f87171;
    --warning: #fbbf24;
    --info: #60a5fa;
    --light: #111827;
    --dark: #f9fafb;
    --text: #e5e7eb;
    --border: #374151;
    --glass-bg: rgba(17, 24, 39, 0.8);
    --glass-border: rgba(55, 65, 81, 0.4);
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
    --shadow-brand: 0 10px 25px -5px rgba(99, 102, 241, 0.4);
    --shadow-brand-hover: 0 15px 30px -5px rgba(99, 102, 241, 0.5);
}
```

**Step 2: Add dark mode overrides in page CSS**

In `index.css`, add a section for dark-specific overrides:

```css
/* Dark mode overrides */
[data-theme="dark"] body {
    background: radial-gradient(circle at 10% 20%, #111827 0%, #0f172a 90%);
    color: #e5e7eb;
}
[data-theme="dark"] .card-header { background: rgba(30, 41, 59, 0.8); border-color: #374151; }
[data-theme="dark"] .form-control,
[data-theme="dark"] .form-select { background: #1e293b; border-color: #374151; color: #e5e7eb; }
/* ... etc for all hardcoded light colors */
```

**Step 3: Theme toggle in base.html nav**

```html
{# In global-nav__inner, after the Pro status pill #}
<button type="button" class="theme-toggle" data-action="toggle-theme"
        aria-label="切换深色模式" title="切换深色/浅色模式">
    <i class="bi bi-moon-fill" data-icon-light="bi-moon-fill" data-icon-dark="bi-sun-fill"></i>
</button>
```

**Step 4: Theme JS module**

```javascript
// static/js/theme-toggle.js
const STORAGE_KEY = 'bp_theme';
const html = document.documentElement;

function getPreferredTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
    html.setAttribute('data-theme', theme);
    const icon = document.querySelector('[data-action="toggle-theme"] i');
    if (icon) {
        icon.classList.toggle('bi-moon-fill', theme === 'light');
        icon.classList.toggle('bi-sun-fill', theme === 'dark');
    }
}

// Apply immediately to prevent flash
applyTheme(getPreferredTheme());

document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action="toggle-theme"]');
    if (!btn) return;
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme(next);
});

// Listen for OS theme changes
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!localStorage.getItem(STORAGE_KEY)) {
        applyTheme(e.matches ? 'dark' : 'light');
    }
});
```

**Step 5: Prevent flash of unstyled theme**

Add inline script BEFORE any CSS in `base.html` `<head>`:

```html
<script>
    (function() {
        var t = localStorage.getItem('bp_theme') || 
                (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', t);
    })();
</script>
```

### CSS Changes Summary

| File | Dark mode additions |
|------|-------------------|
| `tokens.css` | ~30 new lines: `[data-theme="dark"]` override block |
| `index.css` | ~60 lines: body, cards, forms, tables, badges, step-bar overrides |
| `settings.css` | ~40 lines: sidebar, channel cards, LLM pane overrides |
| `global_nav.css` | ~10 lines: nav bar dark background adjustment |
| `copilot.css` | ~15 lines: panel dark background overrides |

### JS Changes Summary

| File | Changes |
|------|---------|
| `base.html` | Inline theme-init script (~8 lines) + toggle button (~5 lines) |
| New: `static/js/theme-toggle.js` | ~40 lines, ESM, loaded in base.html via `{% block page_module %}` or a new `{% block theme_module %}` |

### Testing Strategy
- Manual: toggle theme on every page, verify no hardcoded colors
- Check localStorage persistence across page reloads
- Check OS preference detection works when no localStorage set
- Verify glass morphism still works (backdrop-filter in dark mode)
- Check contrast ratios meet WCAG AA in both themes

### Estimated Effort: **4-6 hours**

---

## Phase 2: Navigation Overhaul (P0 — Highest ROI)

**Goal**: Replace flat 10+ item horizontal nav with grouped, collapsible, mobile-friendly navigation.

### Files to Modify

| File | Changes |
|------|---------|
| `base.html` | Replace global-nav with grouped nav + mobile hamburger |
| `static/css/global_nav.css` | Complete rewrite: grouped items, mobile drawer, search trigger |
| New: `static/js/nav.js` | Mobile menu toggle, search trigger, keyboard shortcut |

### Implementation Approach

**Current nav items (Pro edition)**:
```
保活 | 存活率 | 发布 | 指挥 | 健康 | 批量任务 | 排程 | 权益 | 站点 | PR队列 | 设置 | [Pro pill]
```

**Proposed grouping**:

```
Group 1 (Core):     保活 | 发布 | 设置
Group 2 (Monitor):  存活率 | 健康 | 指挥
Group 3 (Advanced): 批量任务 | 排程 | 权益 | 站点 | PR队列
```

**Navigation redesign — Three-tier approach**:

1. **Desktop (>1024px)**: Horizontal nav with grouped items + separator dots + search trigger (Ctrl+K)
2. **Tablet (768-1024px)**: Condensed nav — core items visible, others in dropdown
3. **Mobile (<768px)**: Hamburger menu → full-screen slide-in drawer

**Desktop nav layout**:
```
[Logo] [保活] [发布] [设置] · [存活率] [健康] [指挥] · ··· [搜索🔍] [Pro pill]
                                                                  ↑ groups hidden behind "···"
```

**Mobile drawer**:
```
┌─────────────────────────┐
│ ☰ Backlink Publisher    │
├─────────────────────────┤
│ ★ 核心                    │
│   保活                    │
│   发布                    │
│   设置                    │
├─────────────────────────┤
│ 📊 监控                    │
│   存活率                  │
│   健康                    │
│   指挥                    │
├─────────────────────────┤
│ ⚙️ 高级                    │
│   批量任务                │
│   排程                    │
│   权益                    │
│   站点                    │
│   PR队列                  │
├─────────────────────────┤
│ [🔍 搜索 (Ctrl+K)]       │
│ [🌙 深色模式]              │
│ [Pro Status]              │
└─────────────────────────┘
```

**Implementation details**:

**base.html nav structure**:
```html
<nav class="global-nav" role="navigation" aria-label="主导航">
    <div class="global-nav__inner">
        {# Logo / brand #}
        <a href="/" class="global-nav__brand">
            <i class="bi bi-link-45deg"></i>
            <span class="global-nav__brand-text">Backlink Publisher</span>
        </a>
        
        {# Desktop nav groups #}
        <div class="global-nav__groups">
            <div class="nav-group">
                <a href="/ce:keep-alive" class="global-nav__item ..." aria-label="保活">保活</a>
                <a href="/" class="global-nav__item ..." aria-label="发布">发布</a>
                <a href="/settings" class="global-nav__item ..." aria-label="设置">设置</a>
            </div>
            <span class="nav-group-sep" aria-hidden="true">·</span>
            <div class="nav-group">
                <a href="/survival-dashboard" class="global-nav__item ..." aria-label="存活率">存活率</a>
                <a href="/ce:health" class="global-nav__item ..." aria-label="健康">健康</a>
                <a href="/ce:command-center" class="global-nav__item ..." aria-label="指挥">指挥</a>
            </div>
            {% if not lite_edition %}
            <span class="nav-group-sep" aria-hidden="true">·</span>
            <div class="nav-group nav-group--advanced">
                {# hidden on tablet, shown in drawer #}
            </div>
            {% endif %}
        </div>
        
        {# Actions bar (right side) #}
        <div class="global-nav__actions">
            <button class="global-nav__search-trigger" data-action="open-search"
                    aria-label="搜索 (Ctrl+K)" title="搜索 (Ctrl+K)">
                <i class="bi bi-search"></i>
            </button>
            <button class="global-nav__theme-toggle" data-action="toggle-theme"
                    aria-label="切换深色模式">
                <i class="bi bi-moon-fill"></i>
            </button>
            {% if not lite_edition %}
            {# Pro status pill #}
            {% endif %}
            <button class="global-nav__hamburger d-lg-none" data-action="toggle-mobile-nav"
                    aria-label="打开导航菜单" aria-expanded="false">
                <i class="bi bi-list"></i>
            </button>
        </div>
    </div>
</nav>

{# Mobile nav drawer #}
<div class="mobile-nav-overlay d-none" data-action="close-mobile-nav" aria-hidden="true"></div>
<aside class="mobile-nav-drawer d-none" role="dialog" aria-label="导航菜单">
    <div class="mobile-nav-drawer__header">
        <span class="mobile-nav-drawer__title">
            <i class="bi bi-link-45deg"></i> Backlink Publisher
        </span>
        <button class="mobile-nav-drawer__close" data-action="toggle-mobile-nav" aria-label="关闭菜单">
            <i class="bi bi-x-lg"></i>
        </button>
    </div>
    <nav class="mobile-nav-drawer__nav" aria-label="移动端导航">
        <div class="mobile-nav-group">
            <span class="mobile-nav-group__label">核心</span>
            <a href="/ce:keep-alive" class="mobile-nav-item ...">保活</a>
            <a href="/" class="mobile-nav-item ...">发布</a>
            <a href="/settings" class="mobile-nav-item ...">设置</a>
        </div>
        {# ... more groups #}
    </nav>
    <div class="mobile-nav-drawer__footer">
        <button class="mobile-nav-item" data-action="open-search">
            <i class="bi bi-search"></i> 搜索
            <kbd>Ctrl+K</kbd>
        </button>
        <button class="mobile-nav-item" data-action="toggle-theme">
            <i class="bi bi-moon-fill"></i> 深色模式
        </button>
    </div>
</aside>
```

**CSS for grouped nav**:

```css
/* Grouped desktop nav */
.global-nav__groups {
    display: flex;
    align-items: center;
    gap: 4px;
}
.nav-group {
    display: flex;
    align-items: center;
    gap: 2px;
}
.nav-group-sep {
    color: rgba(255,255,255,0.3);
    margin: 0 6px;
    user-select: none;
}
.nav-group--advanced {
    display: none; /* hidden on tablet, shown on desktop */
}
@media (min-width: 1200px) {
    .nav-group--advanced { display: flex; }
}

/* Mobile drawer */
.mobile-nav-overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 1040;
    backdrop-filter: blur(4px);
}
.mobile-nav-drawer {
    position: fixed; top: 0; left: 0;
    width: 280px; height: 100vh;
    background: var(--glass-bg, rgba(255,255,255,0.95));
    backdrop-filter: blur(20px);
    z-index: 1050;
    transform: translateX(-100%);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    overflow-y: auto;
}
.mobile-nav-drawer.open { transform: translateX(0); }

/* Hamburger button — visible only on mobile */
.global-nav__hamburger {
    display: none;
    background: none; border: none;
    color: white; font-size: 1.5rem;
    cursor: pointer; padding: 4px;
}
@media (max-width: 991px) {
    .global-nav__groups { display: none; }
    .global-nav__hamburger { display: inline-flex; }
}
```

**JS for mobile nav**:

```javascript
// static/js/nav.js
document.addEventListener('click', (e) => {
    const toggle = e.target.closest('[data-action="toggle-mobile-nav"]');
    if (toggle) {
        const drawer = document.querySelector('.mobile-nav-drawer');
        const overlay = document.querySelector('.mobile-nav-overlay');
        const isOpen = drawer.classList.contains('open');
        drawer.classList.toggle('open', !isOpen);
        overlay.classList.toggle('d-none', isOpen);
        document.body.style.overflow = isOpen ? '' : 'hidden';
        toggle.setAttribute('aria-expanded', !isOpen);
    }
    
    const closeOverlay = e.target.closest('[data-action="close-mobile-nav"]');
    if (closeOverlay) {
        document.querySelector('.mobile-nav-drawer')?.classList.remove('open');
        document.querySelector('.mobile-nav-overlay')?.classList.add('d-none');
        document.body.style.overflow = '';
    }
});
```

### Testing Strategy
- Test nav on desktop (1200px+), tablet (768-1024px), mobile (<768px)
- Verify hamburger opens/closes drawer
- Verify active page indicator works in both desktop and mobile
- Verify Pro status pill still visible in all layouts
- Test keyboard navigation through nav items

### Estimated Effort: **6-8 hours**

---

## Phase 3: Mobile & Responsive (P1 — Critical)

**Goal**: Add proper responsive breakpoints and touch-friendly interactions.

### Files to Modify

| File | Changes |
|------|---------|
| `static/css/tokens.css` | Add responsive spacing tokens |
| `static/css/index.css` | Add 480px, 768px, 1024px, 1200px breakpoints |
| `static/css/settings.css` | Mobile settings layout (stack sidebar below content) |
| `static/css/global_nav.css` | Mobile nav (covered in Phase 2) |
| Templates (various) | Fix inline `style="max-width:..."` hardcoded values |

### Breakpoint System

```css
/* tokens.css — responsive tokens */
:root {
    --bp-sm: 480px;
    --bp-md: 768px;
    --bp-lg: 1024px;
    --bp-xl: 1200px;
    
    /* Spacing scales with viewport */
    --space-xs: 8px;
    --space-sm: 12px;
    --space-md: 16px;
    --space-lg: 24px;
    --space-xl: 32px;
}

/* index.css — replace single 768px breakpoint */
/* Mobile first: 480px */
@media (min-width: 480px) {
    body { padding: 12px; }
    .card-body { padding: 16px; }
}

/* Small tablets: 768px */
@media (min-width: 768px) {
    body { padding: 16px; }
    .container-fluid { padding: 0 16px; }
}

/* Tablets: 1024px */
@media (min-width: 1024px) {
    body { padding: 20px; }
    .container-fluid { max-width: 1000px; margin: 0 auto; }
}

/* Desktop: 1200px */
@media (min-width: 1200px) {
    .container-fluid { max-width: 1100px; }
}

/* Mobile-specific overrides */
@media (max-width: 767px) {
    .btn-group-actions { flex-direction: column; }
    .btn-group-actions .btn { width: 100%; }
    .step-bar { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .step-label { display: none; } /* show only circles on mobile */
    .url-item { flex-direction: column; align-items: stretch; }
    .url-badge { align-self: flex-start; }
    .meta-info { flex-direction: column; gap: 4px; }
    .navbar { flex-direction: column; gap: 8px; }
    .nav-actions { width: 100%; justify-content: flex-end; }
    .editor-container { padding: 12px; }
    .link-table { font-size: 12px; }
    .link-table th, .link-table td { padding: 8px; }
    .filter-bar { gap: 4px; }
}
```

**Settings mobile layout**:

```css
/* settings.css — mobile settings */
@media (max-width: 767px) {
    .settings-layout { flex-direction: column; }
    .settings-sidebar {
        width: 100%;
        border-right: none;
        border-bottom: 1px solid var(--border, #e5e7eb);
        display: flex;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        padding: 0;
        gap: 0;
    }
    .sidebar-group { display: flex; margin-bottom: 0; }
    .sidebar-group__label { display: none; }
    .sidebar-item {
        border-left: none;
        border-bottom: 3px solid transparent;
        white-space: nowrap;
        padding: 10px 14px;
    }
    .sidebar-item.active { border-bottom-color: var(--primary); }
    .settings-pane-host { padding: 16px; }
}
```

**Touch-friendly improvements**:
- Minimum 44px touch targets for all interactive elements
- Add `touch-action: manipulation` on buttons to eliminate 300ms delay
- Use `@media (pointer: coarse)` to increase padding on touch devices

```css
/* Touch device adjustments */
@media (pointer: coarse) {
    .global-nav__item { padding: 8px 16px; min-height: 44px; }
    .btn { padding: 14px 28px; min-height: 44px; }
    .sidebar-item { padding: 12px 16px; min-height: 44px; }
    .filter-chip { padding: 8px 14px; min-height: 44px; }
}
```

### Testing Strategy
- Test on iPhone SE (375px), iPhone 14 (390px), iPad (768px), iPad Pro (1024px)
- Verify touch targets are at least 44px
- Verify horizontal scroll on step-bar works on mobile
- Verify settings sidebar scrolls horizontally on mobile
- Test orientation changes

### Estimated Effort: **5-7 hours**

---

## Phase 4: Notifications & Search (P2 — Productivity Boost)

**Goal**: Replace flash messages with persistent notification center; add Ctrl+K command palette.

### Files to Modify

| File | Changes |
|------|---------|
| `base.html` | Add notification bell + dropdown, search modal |
| New: `static/js/notifications.js` | Notification center logic |
| New: `static/js/search.js` | Command palette / search modal |
| `static/css/global_nav.css` | Notification badge styles |
| New: `static/css/notifications.css` | Notification center styles |
| New: `static/css/search.css` | Search modal styles |
| `webui_app/__init__.py` | Add `/api/notifications` endpoint (optional) |
| `webui_app/routes/main.py` | Return notifications in context (optional) |

### Notification Center

**Design**: Bell icon in nav → dropdown panel with recent notifications, grouped by type.

```
┌──────────────────────────────┐
│ 通知 (3)                      │
├──────────────────────────────┤
│ 🔵 发布完成                    │
│    2 篇文章已发布到 Medium      │
│    2 分钟前                    │
├──────────────────────────────┤
│ ⚠️ 绑定过期                    │
│    Velog Cookie 已过期         │
│    1 小时前                    │
├──────────────────────────────┤
│ ✅ 系统正常                    │
│    所有渠道运行正常             │
│    30 分钟前                   │
└──────────────────────────────┘
```

**Implementation**:

```html
{# In global-nav__actions, before theme toggle #}
<div class="notification-bell" data-action="toggle-notifications">
    <button type="button" aria-label="通知" aria-expanded="false">
        <i class="bi bi-bell"></i>
        <span class="notification-badge d-none" id="notif-count">0</span>
    </button>
    <div class="notification-panel d-none" role="dialog" aria-label="通知中心">
        <div class="notification-panel__header">
            <h3>通知</h3>
            <button data-action="clear-notifications" class="btn btn-sm btn-ghost">全部清除</button>
        </div>
        <div class="notification-panel__list" id="notif-list">
            {# Dynamic content from JS #}
        </div>
        <div class="notification-panel__empty d-none">
            暂无通知
        </div>
    </div>
</div>
```

**Notification storage**: Use localStorage for client-side notifications + optional server endpoint.

```javascript
// notifications.js
const NOTIF_KEY = 'bp_notifications';
const MAX_NOTIFS = 50;

export function addNotification(type, title, body) {
    const notifs = JSON.parse(localStorage.getItem(NOTIF_KEY) || '[]');
    notifs.unshift({
        id: Date.now(),
        type, // 'success' | 'warning' | 'info' | 'error'
        title,
        body,
        timestamp: new Date().toISOString(),
        read: false
    });
    if (notifs.length > MAX_NOTIFS) notifs.length = MAX_NOTIFS;
    localStorage.setItem(NOTIF_KEY, JSON.stringify(notifs));
    updateBadge();
}

export function getNotifications() {
    return JSON.parse(localStorage.getItem(NOTIF_KEY) || '[]');
}

function updateBadge() {
    const notifs = getNotifications();
    const unread = notifs.filter(n => !n.read).length;
    const badge = document.getElementById('notif-count');
    if (badge) {
        badge.textContent = unread;
        badge.classList.toggle('d-none', unread === 0);
    }
}
```

### Command Palette (Ctrl+K)

**Design**: Modal overlay with search input + categorized results.

```
┌─────────────────────────────────────┐
│ 🔍 搜索命令、页面、设置...              │
├─────────────────────────────────────┤
│ 页面                                 │
│   📝 发布 — /                        │
│   ⚙️ 设置 — /settings                │
│   📊 健康 — /ce:health               │
│                                      │
│ 操作                                 │
│   🔄 重置配置 — POST /ce:clear        │
│   📋 复制配置路径                      │
│                                      │
│ 历史                                 │
│   搜索最近发布记录...                  │
└─────────────────────────────────────┘
```

**Implementation**:

```javascript
// search.js
const COMMANDS = [
    { type: 'page', icon: 'bi-file-text', label: '发布', path: '/', keywords: 'publish home' },
    { type: 'page', icon: 'bi-gear', label: '设置', path: '/settings', keywords: 'settings config' },
    { type: 'page', icon: 'bi-heart-pulse', label: '健康', path: '/ce:health', keywords: 'health status' },
    { type: 'page', icon: 'bi-clipboard-data', label: '存活率', path: '/survival-dashboard', keywords: 'survival rate' },
    { type: 'page', icon: 'bi-command', label: '指挥中心', path: '/ce:command-center', keywords: 'command center' },
    { type: 'page', icon: 'bi-kanban', label: '批量任务', path: '/batch-campaign', keywords: 'batch' },
    { type: 'page', icon: 'bi-calendar', label: '排程', path: '/schedule', keywords: 'schedule' },
    { type: 'page', icon: 'bi-shield-check', label: '保活', path: '/ce:keep-alive', keywords: 'keep alive' },
    { type: 'page', icon: 'bi-globe', label: '站点', path: '/sites', keywords: 'sites domains' },
    { type: 'page', icon: 'bi-list-task', label: 'PR队列', path: '/pr-queue', keywords: 'pr queue' },
    { type: 'action', icon: 'bi-arrow-counterclockwise', label: '重置配置', action: 'reset-config' },
    { type: 'action', icon: 'bi-clipboard', label: '复制配置路径', action: 'copy-config-path' },
];

// Keyboard shortcut
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        toggleSearch();
    }
    if (e.key === 'Escape') closeSearch();
});
```

### Testing Strategy
- Test Ctrl+K opens search modal on all pages
- Test search filters commands as you type
- Test keyboard navigation in search results (arrow keys + Enter)
- Test notification bell shows/hides dropdown
- Test notifications persist across page reloads
- Test notification badge count updates correctly

### Estimated Effort: **8-10 hours**

---

## Phase 5: Homepage Simplification (P2 — Moderate Complexity)

**Goal**: Reduce cognitive load on the index page; improve information hierarchy.

### Files to Modify

| File | Changes |
|------|---------|
| `templates/index.html` | Simplify layout, move secondary info below fold |
| `templates/_tab_new.html` | Restructure wizard steps, collapsible sections |
| `templates/_tab_history.html` | Add quick filters, better card layout |
| `templates/_tab_batch.html` | Cleaner batch upload interface |
| `static/css/index.css` | Simplified card layouts, better spacing |
| `static/js/index.js` | Lazy-load non-critical sections |

### Implementation Approach

**Current problem**: Index page shows 4-step wizard + tabs + mode toggle + health bar + flash messages + Pro nudge all at once.

**Proposed layout — Progressive disclosure**:

```
┌─────────────────────────────────────────┐
│ [Logo] [导航...]            [🔍] [🌙] [Pro] │
├─────────────────────────────────────────┤
│ ⚠️ 未完成任务 (if any)                    │
│ ─────────────────────────────────────── │
│ 📊 系统健康 (collapsed, green = hidden)   │
├─────────────────────────────────────────┤
│ [单笔] [批量]  ← mode toggle             │
│ ─────────────────────────────────────── │
│                                          │
│  ┌ Step 1: 输入网址 ──────────────────┐ │
│  │  (collapsed if step > 1)           │ │
│  │  [URL input fields]                │ │
│  │  [分析连结]                         │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌ Step 2: 配置参数 ──────────────────┐ │
│  │  (collapsed if step > 2)           │ │
│  │  [Config selects + buttons]        │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌ Step 3: 文章预览 ──────────────────┐ │
│  │  (collapsed if step > 3)           │ │
│  │  [Plan cards with actions]         │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌ Step 4: 发布结果 ──────────────────┐ │
│  │  (shown after publish)             │ │
│  └────────────────────────────────────┘ │
│                                          │
│ ─── 历史记录 ────────────────────────── │
│ [最新] [全部] [成功] [失败]  ← quick filters │
│ [History item cards...]                  │
└─────────────────────────────────────────┘
```

**Key changes**:

1. **Collapse completed steps** — Already done via wizard chips; ensure they're compact
2. **Move health bar to header** — Small green/yellow dot in nav instead of full-width bar
3. **Progressive step display** — Show only current step + previous summaries
4. **Simplify step 2** — Group related selects in a card layout, not a long form
5. **History as footer** — Move history below the fold, make it collapsible

### Testing Strategy
- Test 4-step flow from empty state through publish
- Verify collapsed steps show correct summary
- Test quick filters in history section
- Verify batch mode still works correctly
- Test on mobile — ensure single-step-at-a-time UX

### Estimated Effort: **6-8 hours**

---

## Phase 6: Settings Reorganization (P3 — Lowest ROI, Defer)

**Goal**: Improve settings page navigation and reduce cognitive load.

**Note**: Settings already has a two-column layout with sidebar navigation. The main improvements are:
1. Better grouping of settings sections
2. Status dashboard at top
3. Search within settings
4. Keyboard shortcuts for settings navigation

### Files to Modify

| File | Changes |
|------|---------|
| `templates/settings.html` | Add search bar, reorganize sections |
| `templates/_settings_sidebar.html` | Add icons, badges, search filter |
| `static/css/settings.css` | Improve section spacing, add search styles |
| `static/js/settings.js` | Add sidebar search filter |

### Implementation Approach

**Current settings layout**: Sidebar (4 items) + Content (4 sections, each with multiple subsections).

**Proposed improvements**:

1. **Settings search bar** at top of sidebar:
```html
<div class="settings-search">
    <input type="text" placeholder="搜索设置..." 
           data-action="filter-settings" aria-label="搜索设置">
</div>
```

2. **Status dashboard cards** at top of content area:
```html
<div class="settings-status-grid">
    <div class="status-card">
        <span class="status-dot ok"></span>
        <span>Blogger</span>
        <span class="badge ok">已授权</span>
    </div>
    <div class="status-card">
        <span class="status-dot err"></span>
        <span>Velog</span>
        <span class="badge err">未绑定</span>
    </div>
    {# ... for each channel #}
</div>
```

3. **Keyboard navigation**: Arrow keys to move between sidebar items, Enter to select

### Estimated Effort: **5-7 hours**

---

## Phase 7: Accessibility (P1 — Low Effort, High Compliance)

**Goal**: Meet WCAG AA standards; add keyboard navigation, ARIA labels, skip-nav.

### Files to Modify

| File | Changes |
|------|---------|
| `base.html` | Add skip-nav link, landmark roles, ARIA labels |
| `templates/index.html` | Add ARIA labels to all interactive elements |
| `templates/settings.html` | Add ARIA labels, improve focus management |
| `static/css/global_nav.css` | Focus visible styles |
| `static/css/index.css` | Focus visible styles, skip-nav styles |
| New: `static/js/keyboard.js` | Global keyboard shortcuts, focus trapping |

### Implementation Approach

**1. Skip Navigation Link**

```html
{# Add as first child of <body> in base.html #}
<a href="#main-content" class="skip-nav">跳到主要内容</a>
```

```css
.skip-nav {
    position: absolute;
    top: -40px;
    left: 0;
    background: var(--primary);
    color: white;
    padding: 8px 16px;
    z-index: 10000;
    transition: top 0.3s;
}
.skip-nav:focus {
    top: 0;
}
```

**2. ARIA Labels on All Interactive Elements**

```html
{# Navigation #}
<nav class="global-nav" role="navigation" aria-label="主导航">

{# Search trigger #}
<button aria-label="搜索命令 (Ctrl+K)">

{# Theme toggle #}
<button aria-label="切换深色模式">

{# Mode toggle #}
<div class="mode-toggle-bar" role="tablist" aria-label="发布模式">
    <button role="tab" aria-selected="true" aria-controls="newPanel">单笔</button>
    <button role="tab" aria-selected="false" aria-controls="batchPanel">批量</button>
</div>

{# Form fields #}
<label for="derive_source">粘贴 URL 自动派生</label>
<input id="derive_source" aria-describedby="derive-help">

{# Cards with expandable content #}
<details>
    <summary aria-expanded="false">HTML 内容预览</summary>
    ...
</details>
```

**3. Focus Visible Styles**

```css
/* global_nav.css — add focus visible */
.global-nav__item:focus-visible {
    outline: 2px solid white;
    outline-offset: 2px;
    border-radius: 8px;
}

/* index.css — add focus visible */
.btn:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
}
.form-control:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 1px;
}
.sidebar-item:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
}
```

**4. Keyboard Shortcuts Module**

```javascript
// keyboard.js
const SHORTCUTS = {
    'ctrl+k': () => toggleSearch(),
    'ctrl+/': () => toggleShortcutsHelp(),
    'Escape': () => closeAllModals(),
    '1': { modifier: 'ctrl', action: () => navigateTo('/') },      // 发布
    '2': { modifier: 'ctrl', action: () => navigateTo('/settings') }, // 设置
    '3': { modifier: 'ctrl', action: () => navigateTo('/ce:health') }, // 健康
};

document.addEventListener('keydown', (e) => {
    for (const [key, handler] of Object.entries(SHORTCUTS)) {
        // ... match and execute
    }
});
```

**5. Color Contrast Fixes**

Audit all text colors against backgrounds:
- `#374151` on `#f9fafb` → contrast ratio 7.2:1 ✓
- `#6b7280` on `#f9fafb` → contrast ratio 4.6:1 ✓ (AA for normal text)
- `#9ca3af` on `#f9fafb` → contrast ratio 3.1:1 ✗ (fails AA) → change to `#6b7280`
- `#9ca3af` on `#e5e7eb` → contrast ratio 2.0:1 ✗ (fails AA) → change to `#6b7280`

### Testing Strategy
- Test with keyboard only (Tab, Shift+Tab, Enter, Escape)
- Test with screen reader (VoiceOver on macOS)
- Verify all interactive elements are reachable via keyboard
- Verify focus indicators are visible on all elements
- Run axe-core accessibility audit
- Test skip-nav link works
- Verify color contrast ratios meet WCAG AA

### Estimated Effort: **4-6 hours**

---

## Implementation Order (Recommended)

```
Phase 7 (Accessibility)  → 4-6h  ← Start here, foundation for everything
Phase 1 (Dark Mode)      → 4-6h  ← Highest impact, self-contained
Phase 2 (Navigation)     → 6-8h  ← Depends on Phase 1 (theme toggle)
Phase 3 (Mobile)         → 5-7h  ← Depends on Phase 2 (mobile nav)
Phase 4 (Notifications)  → 8-10h ← Depends on Phase 2 (search in nav)
Phase 5 (Homepage)       → 6-8h  ← Can be done in parallel
Phase 6 (Settings)       → 5-7h  ← Lowest priority, defer
```

**Total estimated: 38-52 hours**

**Recommended shipping order**:
1. **Sprint 1** (Phase 7 + Phase 1): Accessibility foundation + Dark mode = immediate visible improvement
2. **Sprint 2** (Phase 2 + Phase 3): Navigation overhaul + Mobile responsive = transforms mobile UX
3. **Sprint 3** (Phase 4 + Phase 5): Notifications + Search + Homepage = productivity features
4. **Sprint 4** (Phase 6): Settings reorganization = polish pass

---

## Anti-Rot Rules Compliance

All changes must follow existing conventions:
- **No inline `on*` handlers** — use `data-action` + delegated listeners
- **No `window.*` globals as API** — use ES module imports
- **No untrusted `${…}` into innerHTML** — use `esc()` or `textContent`
- **`readCsrf()` reads `<meta>` per call** — never cache
- **Bootstrap stays classic non-defer head script**
- **Bump `asset_version`** for all new/modified static files
- **CSS custom properties from `tokens.css`** — no local `:root` blocks

---

## Claims

```yaml
claims:
  paths: []
  shas: []
```

(No code claims — this is a design plan, not an implementation plan.)
