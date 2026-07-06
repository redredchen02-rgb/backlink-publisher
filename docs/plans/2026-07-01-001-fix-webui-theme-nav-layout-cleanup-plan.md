---
title: "fix: WebUI 深浅主题联动 + 首页动线 + 版面一致性收尾"
type: fix
status: completed
date: 2026-07-01
claims: {}  # 主题 CSS token 补全、导航链接、表格样式类迁移、响应式抽屉 — 无需机器可验证的业务断言；由各单元 Test scenarios + Verification 表达
---

# fix: WebUI 深浅主题联动 + 首页动线 + 版面一致性收尾

## Overview

修复两个真实存在的 WebUI 缺陷、并做一轮有界的版面一致性收尾:

1. **深浅主题切换实际不生效**——Vue SPA 里点击主题按钮目前没有可见效果(比之前计划记录的"遗留 bug"更严重,见 Problem Frame)。
2. **SPA 侧栏品牌区不是首页链接**——所有 legacy Jinja 页面的品牌区都可点击回首页,SPA 侧栏的"控台"文字不行。
3. **版面一致性**——5 个仍用裸 `<table>` 的 SPA 页面未采用既有 `.data-table` 共享约定;SPA 侧栏在窄屏下完全没有响应式/折叠行为(legacy 页面有)。

本期是**有界收尾**,不是重新设计(用户决策 2026-07-01):不改配色语言、不改导航分组/信息架构、不改发布流程步数。

## Problem Frame

两个直接前置计划已 shipped/completed:
- `docs/plans/2026-06-17-001-feat-webui-console-redesign-plan.md`(shipped)——把 legacy Jinja WebUI 重做成深色控台风 + 左侧栏。
- `docs/plans/2026-06-22-002-refactor-spa-design-system-refinement-plan.md`(completed)——把 Vue SPA(`frontend/`)的设计 token 系统与 `tokens.css` 贯通,并**明确延后**两件事:亮色主题"点击退回默认态"的遗留 bug、以及任何导航/信息架构重排(该计划称其为"另一类更高杠杆的 UX 工作",本轮未选)。

本次用户请求正好承接这两处延后项。经代码研究(见 Context & Research),现状比延后计划描述的更清楚:

- **主题 bug 的根因已确认,且比"遗留 bug"框架更严重**:`frontend/src/styles/app.css:6-19` 在 2026-06-23(commit `0cbeb85`,"feat(webui): light theme…")新增了一段**无条件 `:root` 覆盖**,其注释自陈"这些规则在 main.ts 里排在 tokens.css 之后加载,所以同优先级下 `:root` 获胜"——因为它比 `tokens.css` 里正确加了 `[data-theme="light"]` 选择器限定的浅色块**晚加载且选择器优先级相同**,SPA 无论 `data-theme` 是 `dark` 还是 `light`,渲染的都是这段硬编码浅色值。**结果是:SPA 里切换主题按钮目前完全不起作用**,而不是"亮色主题不好看"这种更轻的问题。
- 即使这个覆盖被拿掉,`tokens.css` 自己的 `[data-theme="light"]` 块(`tokens.css:213-226`,208-212 行是说明注释)也只是它注释自陈的"可读性安全网"——只覆盖了 surface/text/border/glass/gradient-hero 7 组 token,遗漏了 `--primary`/`--accent-cyan`、状态色的 soft/text 变体、`--shadow-*`、`--on-primary` 等——真正切到浅色时控台的强调色、状态徽章、投影仍会是为深色背景设计的值。
- **文档评审揭出的两处规划错误(已修正,见 Key Technical Decisions)**:①`tokens.css:241-280` 的 `.alert-warning`/`.alert-danger`/`.btn-outline-secondary` 规则**不是**原计划文本所说的"已有主题感知版本"——`.btn-outline-secondary` 完全硬编码(零 `var()`),`.alert-*` 仅背景色走 `--warning-soft`/`--danger-soft`,文字色/边框色仍是硬编码深色专属字面值,且**不受任何 `[data-theme]` 限定**。直接删除 `app.css` 的 SPA-only 覆盖(该覆盖是目前 SPA 这三个类在浅色态唯一能看的样式来源)会让 SPA 回退到这段深色硬编码值,是**新增回归**而非修复;而 legacy Jinja 因为从未被 `app.css`(其注释自陈 "SPA only")覆盖过,这三个类在 legacy 浅色模式下**从一开始就是错的**,是本计划应该顺手修掉的既有 bug。②`--primary`/`--accent-cyan` 被直接当作正文文字色使用的位置(至少 `SideNav.vue:83` `color: var(--primary)`,配合浅色 `--surface-overlay:#e5e7eb`,对比度约 1.9:1,不达 WCAG 3:1 UI 组件门槛;另有 `HistoryPage.vue`/`DraftsPage.vue`/`SitesPage.vue`/`BloggerCard.vue`/`ArticleReviewRow.vue` 等页面同样直接用 `color: var(--primary)`)——"这些 token 主要用作背景色,对比风险低"的原判断不成立,Unit 1 需要给这两个 token 补浅色专属值。
- Legacy Jinja 一侧(`webui_app/static/js/theme.js`)在 2026-06-17 计划里已经把 `data-theme` 与 `data-bs-theme` 同步,吃的是 `tokens.css` 同一个 `[data-theme="light"]` 块——所以修好 `tokens.css` 这一处,SPA 和 legacy 会同时受益(单一真相源架构决策的红利)。
- **现有前端测试基线已确认非绿(文档评审实测,`npx vitest run` 于 unmodified `main`)**:`frontend/src/layout/SideNav.spec.ts` 因 `NAV_ITEMS` 现已全部迁移(零 legacy 项)导致既有"至少一个 legacy 链接"断言抛 `TypeError`——与本计划无关的既存 bug,但 Unit 2 恰好要编辑同一个测试文件,顺手修掉。`frontend/src/__tests__/token-resolution.spec.ts` 有 3 处既存违规:`KeepAlivePage.vue:21`(`background: var(--bg-primary, #1a1a2e)`,token 未定义且带字面兜底)——该文件恰是 Unit 3 的迁移目标之一;`HistoryPage.vue:64,78`(`color: var(--primary, #0d6efd)`、`color: var(--text-secondary, #6c757d)`,token 已定义但带多余字面兜底)——该页恰是 Unit 1/3 引用的"干净参照页"。三处都恰好落在本计划已经在编辑的文件范围内,顺手清掉,使 Unit 1 的回归门测试有一个真正干净的基线可比较。
- **导航动线**:SPA 每个路由都渲染在同一个持久化的 `AppShell`(`frontend/src/layout/AppShell.vue:9-20`)里,不存在真正的"死角页面"。已确认唯一的具体缺口是:SPA 侧栏品牌区(`SideNav.vue:16`,`<div class="sidenav__brand">控台</div>`)是纯文本,不是链接——不同于 legacy `base.html` 里侧栏和顶栏品牌区都是 `<a href="/">`。`/campaign/:campaignId` 页面本身已有明确的"← 返回批量任务"按钮(`CampaignProgressPage.vue:73-75`),不是导航死角,故不在本期修复范围(见 Scope Boundaries)。
- **版面一致性**:`app.css:150-193` 定义的共享 `.data-table` 约定已被 `History`/`Schedule`/`Sites` 三页采用,但另外 5 个页面(`CampaignProgress`/`EquityLedger`/`KeepAlive`/`OptimizationStatus`/`PrQueue`)仍各自用裸 `<table>`,未接入该约定。SPA 侧栏(`SideNav.vue:46-53`,固定 13rem 宽)在任何视口宽度下都没有响应式/折叠行为,而 legacy 侧栏在 ≤1024px 会折叠为抽屉。

## Requirements Trace

- R1. SPA 与 legacy 页面的亮/深主题切换必须产生真实、完整的视觉变化(而非当前 SPA 侧"切换无效"或仅有"安全网"级别覆盖的状态)。
- R2. 用户在 SPA 内任意页面都能一键点击回到操作首页(发布工作台),行为与 legacy 页面一致。
- R3. 5 个仍用裸 `<table>` 的 SPA 页面并入既有 `.data-table` 共享约定,观感与 History/Schedule/Sites 一致。
- R4. 窄屏下 SPA 侧栏可折叠为抽屉,与 legacy 响应式行为对等。

## Scope Boundaries

- 不做全面视觉/信息架构重设(导航分组、发布步数、首页选型等)——用户本轮明确选择"有界收尾",非重新设计,延续 2026-06-22 计划已排除的范围判断。
- 不新增页面密度切换(`[data-density]`)——沿用 2026-06-22 计划的延后决定,间距阶梯已为其留出空间但本期不铺钩子。
- **不修改 `/campaign/:campaignId` 的导航高亮逻辑**——该页已有明确的"← 返回批量任务"按钮,不是导航死角;为它在侧栏加合成高亮需要扩展 `NavItem` 模型(如新增 `matchNames`/`meta.navMatch`),投入产出比低,本期不做(用户已确认,见 Open Questions → Resolved During Planning)。
- 不改后端路由、API 契约、CSRF/错误信封逻辑、`StateBlock`/`classifyError` 判定逻辑。
- 不删除或替换 `theme.ts`/`theme.js`(双主题切换机制本身)——只修复它们所消费的 CSS token 是否正确响应 `data-theme` 属性。
- 不重新设计控台配色语言、不调整已验证健康的强调色取值——只补全浅色主题下缺失的 token 值。

## Context & Research

### Relevant Code and Patterns

- **主题 token 源**:`webui_app/static/css/tokens.css`——`:root`(5-148 行,深色默认值,`--primary`/`--accent-cyan`/状态色 soft+text 变体/`--surface-*`/`--shadow-*`/`--focus-ring`/`--on-primary`/字号-间距-圆角阶梯)+ `[data-theme="light"]`(208-226 行,仅 7 组变量,自称"安全网")。SPA(`frontend/src/main.ts:8`)与 legacy(`base.html`)共同 `import`/`link` 这一个文件——这是"单一真相源"架构决策的落点。
- **SPA 主题 store**:`frontend/src/stores/theme.ts`——`apply()`(11-13 行)只设置 `<html data-theme>`;`toggle()`(21-25 行)在 `dark`/`light` 间切换并写 `localStorage['bp-theme']`。按钮在 `frontend/src/layout/TopBar.vue:40-42`。**Dark 是默认值**(store 初始化逻辑,`theme.ts:17-18`)。
- **根因文件**:`frontend/src/styles/app.css:1-46`——无条件 `:root` 块(6-19 行)+ 无条件 `.alert-warning`/`.alert-danger`/`.btn-outline-secondary` 覆盖(21-46 行,均 `!important`),均是 2026-06-23 之后新增、且与 `tokens.css` 已有的主题感知规则(`tokens.css:241-280`,走 `--warning-soft`/`--danger-soft` 等 token)重复而更劣质(无 `[data-theme]` 限定)。这些类名确认被 5 个 SPA 页面实际使用(`CampaignProgress`/`EquityLedger`/`KeepAlive`/`OptimizationStatus`/`PrQueue`)。
- **导航模型**:`frontend/src/layout/SideNav.vue`(品牌区 16 行、`sidenav__brand` 样式 54-57 行、固定宽度 46-53 行)、`frontend/src/layout/navItems.ts`(`NavItem`/`isMigrated`/`itemsByGroup`)、`frontend/src/layout/AppShell.vue`(持久化 shell,9-20 行)。Legacy 对照:`webui_app/templates/base.html:50,91`(品牌区均为 `<a href="/">`)。
- **表格约定**:`frontend/src/styles/app.css:150-193`——`.data-table-wrap`(横向滚动容器)+ `.data-table`(密度/等宽列/截断规则,`col-id`/`col-num`/`col-date`/`col-status`/`col-url` 语义类)。已采用:`History`/`Schedule`/`Sites`。未采用但含裸 `<table>`:`CampaignProgress`/`EquityLedger`/`KeepAlive`/`OptimizationStatus`/`PrQueue`(逐一 grep 确认)。
- **响应式参照(legacy,供 Vue 化移植参考,非直接复用)**:`webui_app/static/js/nav.js` 的 `MobileDrawer` 类 + `webui_app/static/css/global_nav.css` 的 `@media (max-width:1024px)` 断点、Escape 关闭、body 滚动锁定语义。SPA 目前(`SideNav.vue`/`AppShell.vue`/`TopBar.vue`)零响应式钩子(逐一 grep 确认)。
- **既有测试守卫**:`frontend/src/__tests__/token-resolution.spec.ts`——用 `node:fs` 读源码+正则,断言 SPA 里每个 `var(--x)` 解析到 `tokens.css` 定义名、禁字面颜色兜底。同样的"读源码文本、不模拟浏览器级联"手法适用于本期 Unit 1 的回归测试。`frontend/src/layout/SideNav.spec.ts`——现有 `RouterLinkStub` mount 测试,断言迁移/legacy 链接数量与 `↪` 标记。`frontend/src/composables/useErrorToast.spec.ts` 确认 composable 测试的既有目录与写法惯例。

### Institutional Learnings

- `docs/solutions/best-practices/standalone-page-vs-retrofit-webui-2026-05-15.md`——新 UI 表面若需要"带活跃态高亮的导航栏"这类有状态共享组件,应扩展/复用既有导航而非另起一套。适用于 Unit 2(复用 `SideNav` 既有品牌区,不新建导航概念)与 Unit 4(响应式抽屉扩展既有 `SideNav`/`AppShell`,不新建平行 shell)。
- `docs/solutions/architecture-health-audit-2026-06-01.md`——此前的"前端基础层健康"审计只覆盖了 `webui_app`(legacy Jinja)的 token/base 层,**未涉及 `frontend/`(Vue SPA)**——不能把该审计的"健康"结论套用到 SPA 侧,本计划的问题正好出在审计盲区里。
- Root `CLAUDE.md` 的 zero-build 铁律(无内联 `on*`、无 `window.*` 全局、`readCsrf()` 每次读 `<meta>`)明确只约束 `webui_app`;`frontend/` 有自己的 `package.json`/`vite.config.ts`,是真实的 Vite/Vue 构建,不受该铁律字面约束,但仍应遵守 2026-06-22 计划记录的 SPA 前端约定(static 用 `var()`、reactive 用 `v-bind()`、禁字面颜色兜底,由 `token-resolution.spec.ts` 守卫)。
- `docs/solutions/architecture-patterns/server-side-gap-computation-2026-06-05.md`——派生判定服务端算好注入,前端只做状态到样式的映射。本期 Unit 3/4 不涉及派生计算,纯呈现层改动,符合该约束。

### External References

未做外部研究:本仓已有完整的本地 token/组件/测试范式(`tokens.css`、`token-resolution.spec.ts`、`.data-table` 共享约定、legacy 响应式抽屉可供参考迁移),四个单元都是在既有本地模式内的收尾工作,外部研究价值低。

## Key Technical Decisions

- **把所有浅色主题值收口进 `tokens.css` 的 `[data-theme="light"]` 块,删除 `app.css` 里的平行覆盖**——理由:`app.css` 的无条件 `:root` 块正是根因 bug,修补它(比如给它加选择器限定)只是制造第二个浅色主题真相源,违反"`tokens.css` 单一真相源"的既定架构决策;直接删除、把缺失的值补进 `tokens.css` 唯一位置,SPA 与 legacy 同时受益且不会再漂移。**修正(文档评审)**:这不能止步于扩展 token 列表——`tokens.css:241-280` 的 `.alert-*`/`.btn-outline-secondary` 规则本身也要在同一次改动里补上真正的 `[data-theme="light"]` 限定版本(见 Unit 1),否则删除 `app.css` 覆盖等于制造一个新回归。
- **浅色主题下品牌强调色(`--primary`/`--accent-cyan`)需要专属浅色值,不能"取值不变"**——**修正(文档评审,原判断有误)**:原计划认为这几个 token"主要用作背景色,对比风险低",但 `SideNav.vue:83`(`color: var(--primary)`,Unit 2 本就要改的文件)等至少 6 处直接把 `--primary` 当正文/导航文字色用,浅色态下对比度约 1.9:1,不达标。Unit 1 需要给 `--primary`/`--accent-cyan` 补浅色态专属值(在同一色相上取更深/更饱和的色阶,如向 `--primary-dark` 靠拢,具体取值留待实现时目检),同时确认 `.btn-primary` 等背景用法不受影响。状态 soft/text 变体(深色背景专用的浅粉字色放到白底上不可读)与投影(`--shadow-*` 目前的纯黑高 alpha 在浅色卡片上可能过重)同样需要浅色专属新值,判断标准统一采用 2026-06-22 计划已采用的 WCAG 2.2 AA(正文 ≥4.5:1,非文本/UI 组件 ≥3:1)。
- **首页链接用 `<RouterLink to="/">` 而非 `<a href="/">`**——理由:与其余所有已迁移导航项行为一致(SPA 内跳转、不整页刷新),避免品牌区成为该 shell 里唯一会触发整页重载的点击目标。
- **响应式侧栏做成 Vue 原生的响应式开关(一个 composable 里的 `ref`),而非直接移植 legacy `nav.js` 的 `MobileDrawer`**——理由:`nav.js` 是面向 vanilla DOM 操作的类,SPA 不应该开始依赖它;断点(1024px)与交互语义(Escape 关闭、点击遮罩关闭、body 滚动锁定)沿用 legacy 惯例以保持"感觉一致",但实现用 Vue 惯用法(composable + 响应式类绑定)。
- **5 个页面的表格迁移严格复用既有 `.data-table` 约定,不新增变体**——理由:约定(容器类+密度+语义列类)已经服务 3 个页面且经过设计精炼阶段验证,新增变体只会制造下一轮漂移。**修正(文档评审)**:这 5 个页面目前用的是 Bootstrap 的 `table table-sm table-hover align-middle mb-0` + `thead.table-light`(来自 `frontend/index.html` 的 Bootstrap CDN link,不是 npm 依赖,原计划的 Context & Research 未提及);History/Schedule/Sites 的既有做法是完全替换掉这些 Bootstrap 类而非与 `.data-table` 并存,Unit 3 需按同一方式处理,否则 Bootstrap 自带的边框/hover/内边距会和 `.data-table` 的规则打架。

## Open Questions

### Resolved During Planning

- 版面/排版收尾的深度?→ **有界收尾**(用户决策):只修复 R1-R4 列出的具体缺陷 + 有界一致性收尾,不做全面视觉/信息架构重设,不需要先走 `/ce-brainstorm`。
- 导航动线修复的具体范围?→ 经代码研究确认 SPA 内无真正的导航死角(`AppShell` 持久化 shell + 所有路由都在其内);唯一具体缺口是侧栏品牌区不可点击,`/campaign/:campaignId` 已有明确返回按钮不算死角。用户确认只修品牌区首页链接,不为该页扩展 `NavItem` 高亮模型。
- 浅色主题的"完成"标准是什么?→ 不是"看起来不难看"的模糊标准,而是:①不再有无 `[data-theme]` 限定、只对深色态成立的硬编码规则(含 `tokens.css` 自身的 `.alert-*`/`.btn-outline-secondary`);②直接做文字色使用的强调色 token 满足 WCAG 2.2 AA;③深色态(两侧默认态)视觉零回归。

### Deferred to Implementation

- `--primary`/`--accent-cyan` 浅色专属值的具体色阶(hex)——实现时在 `SideNav.vue` 等已知的 6 个直接文字色消费点上目检确认对比度达标,同时确认 `.btn-primary` 背景用法不受影响,不在计划里预先敲定精确色值。
- 状态色 soft/text 变体、`--shadow-*` 的浅色具体取值——同上,实现时在干净页(避开 settings/keep_alive/index 等重灾页)目检,以 WCAG 2.2 AA 为判定标准。
- Unit 4 抽屉的具体 ARIA 属性集(`aria-expanded`、`role`/`aria-modal`)与打开时的焦点落点(是否焦点陷阱到抽屉内)——见 Unit 4 Approach 的具体要求,实现时对照既有 modal/抽屉可访问性惯例定稿。

## Implementation Units

- [x] **Unit 1: 修复主题切换 — 删除 `app.css` 冲突覆盖 + 补全 `tokens.css` 浅色 token**

**Goal:** 让 SPA 与 legacy 页面的亮/深主题切换都产生真实、完整的视觉变化。

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `webui_app/static/css/tokens.css`(扩展 `[data-theme="light"]` 块,213-226 行;同时给 241-280 行的 `.alert-warning`/`.alert-danger`/`.btn-outline-secondary` 规则补 `[data-theme="light"]` 限定版本——见 Approach)
- Modify: `frontend/src/styles/app.css`(删除 4-46 行的无条件 `:root` 与 `.alert-*`/`.btn-outline-secondary` 覆盖,**必须与上一步同一提交**,否则 SPA 浅色态会先出现一次真实回归)
- Modify: `frontend/src/pages/KeepAlive/KeepAlivePage.vue`(21 行,移除 `var(--bg-primary, #1a1a2e)` 的未定义 token 与字面兜底,改用 `tokens.css` 里已有的等价 surface token)
- Modify: `frontend/src/pages/History/HistoryPage.vue`(64/78 行,移除 `var(--primary, #0d6efd)`/`var(--text-secondary, #6c757d)` 的多余字面兜底——两个 token 本身已在 `tokens.css` 定义,兜底纯属冗余风险)
- Modify: `frontend/src/__tests__/token-resolution.spec.ts` 或新建同目录下的主题守卫测试文件

**Approach:**
- 删除 `app.css` 里那段自陈"因加载顺序同优先级取胜"的无条件 `:root` 块,以及同样无条件的 `.alert-warning`/`.alert-danger`/`.btn-outline-secondary` 覆盖。**文档评审修正**:原计划以为 `tokens.css:241-280` 已有这三个类的"主题感知版本"可以接手——核实后发现只有 `.alert-*` 的**背景色**走了 `--warning-soft`/`--danger-soft`,文字色/边框色仍是硬编码深色专属字面值(如 `color: #fcd34d !important`);`.btn-outline-secondary` 三条属性**全部**是硬编码字面值,零 `var()`。这三条规则本身也不受任何 `[data-theme]` 限定。因此必须在 `tokens.css` 里同时给这三个类补 `[data-theme="light"]` 限定的版本(文字色/边框色改用浅色安全值,或改写为消费新增的浅色 token),否则删除 `app.css` 的覆盖后,SPA 在浅色态会从"能看"退化为"深色硬编码值",而 legacy Jinja(`app.css` 的覆盖本来就是 "SPA only"、从未覆盖到 legacy)在浅色态下这三个类**从一开始就是错的**,借这次改动一并修好。
- 在 `tokens.css` 的 `[data-theme="light"]` 块里补上目前缺失、但在浅色背景下有意义的 token:`--primary`/`--accent-cyan`(**需要浅色专属值,不是"取值不变"**——见 Key Technical Decisions 的修正,`SideNav.vue:83` 等至少 6 处直接把 `--primary` 当文字色用,现状对比度不达标)、状态 soft 变体(`--*-soft`,评估现有 rgba alpha 在白底上是否仍读作淡色块)、状态 text 变体(`--*-text`,当前深色背景专用的浅粉色在白底上不可读,需要专属浅色值——最简方案是直接复用 `--success`/`--danger`/`--warning`/`--info` 基础色本身作为浅底上的文字色)、`--shadow-*`(评估现有纯黑高 alpha 投影在浅色卡片上是否过重,需要则调轻)、`--on-primary`(需确认在 `--primary` 新浅色值上仍保持对比度)。判定标准统一用 WCAG 2.2 AA(正文 ≥4.5:1,非文本/UI 组件 ≥3:1)。
- 值只新增/覆盖到 `[data-theme="light"]` 选择器下,不改动 `:root` 里的深色默认值——保证深色模式(SPA 与 legacy 均默认深色)零回归。
- 顺手清理 `token-resolution.spec.ts` 当前在 unmodified `main` 上就已暴露的 3 处既存违规(`KeepAlivePage.vue:21` 未定义 token `--bg-primary` 且带字面兜底;`HistoryPage.vue:64,78` 两处冗余字面兜底)——这两个文件恰好落在本计划的编辑范围/参照范围内(`KeepAlivePage.vue` 是 Unit 3 的迁移目标,`HistoryPage.vue` 是本计划多处引用的"干净参照页"),顺手修掉让 Unit 1 的回归门测试有一个真正干净的基线可比较。

**Execution note:** characterization-first——改动前用浏览器实测当前 SPA 在 dark/light 两种 `data-theme` 属性下的实际渲染(确认"切换无效"的具体现象),并跑一次 `npx vitest run` 记录 `token-resolution.spec.ts`/`SideNav.spec.ts` 当前的既存失败(两者在 unmodified `main` 上均不通过),作为修复后的对比基线——不要把这两个既存失败误判为本单元引入的新回归。

**Patterns to follow:** `tokens.css` 现有 `[data-theme="light"]` 块的选择器结构;`token-resolution.spec.ts` 的"读源码文本断言"手法(不模拟浏览器级联)。

**Test scenarios:**
- Happy path: `tokens.css` 的 `[data-theme="light"]` 块包含 `--primary`/`--accent-cyan`/四个状态色 text 变体/`--shadow-sm` 等新增键。
- Error path(回归门): `frontend/src/styles/app.css` 源码里不再出现无条件的 `:root {` 块或未加 `[data-theme]` 限定的 `.alert-warning`/`.alert-danger`/`.btn-outline-secondary` 规则(静态源码断言,同 `token-resolution.spec.ts` 手法)。
- Error path(回归门): `tokens.css` 里 241-280 行的 `.alert-*`/`.btn-outline-secondary` 规则新增了 `[data-theme="light"]` 限定版本,不再是无条件硬编码。
- Error path(既存违规清零): `npx vitest run src/__tests__/token-resolution.spec.ts` 全绿——不再有 `KeepAlivePage.vue`/`HistoryPage.vue` 的未定义 token 或字面兜底违规。
- Integration: 手动在浏览器里对 SPA 与至少一个 legacy 深色页切换主题,确认两侧都从深色完整过渡到浅色(强调色、状态徽章、`.alert-*`/`.btn-outline-secondary`、投影都随之变化),而非只变了背景/文字色。
- Integration: `SideNav.vue` 浅色态下,导航激活项文字(`color: var(--primary)`)在 `--surface-overlay` 背景上通过 WCAG 3:1 UI 组件对比度门槛。

**Verification:**
- 浏览器手测:SPA 与 legacy 页面切换主题均产生完整视觉变化,无遗留深色专属硬编码残留在浅色态下,`.alert-*`/`.btn-outline-secondary` 在两侧浅色态下都可读(而非白底白字/低对比度)。
- 静态守卫测试通过(`app.css` 无无条件覆盖残留;`tokens.css` 浅色块补全;`token-resolution.spec.ts` 全绿,不再有既存违规)。
- 深色模式(默认态)视觉零回归。

- [x] **Unit 2: SPA 侧栏品牌区改为首页链接**

**Goal:** SPA 侧栏的"控台"品牌区点击后回到操作首页(发布工作台),与 legacy 页面行为一致。

**Requirements:** R2

**Dependencies:** None

**Files:**
- Modify: `frontend/src/layout/SideNav.vue`(16 行 `<div class="sidenav__brand">` → `<RouterLink to="/">`)
- Modify: `frontend/src/layout/SideNav.spec.ts`(补充品牌区断言)

**Approach:**
- 把纯文本 `<div class="sidenav__brand">控台</div>` 换成 `<RouterLink to="/" class="sidenav__brand">控台</RouterLink>`,保留现有 class 与视觉样式(54-57 行样式块基本不需要改,`RouterLink` 渲染为 `<a>`)。
- 加一个可读的 `aria-label`(如"返回操作首页")或 `title`,让屏幕阅读器用户也能识别这是一个返回首页的操作,而不仅是品牌文字。
- **文档评审修正,两处需要修正而非只是新增断言**:①`SideNav.spec.ts` 现有 `expect(w.findAllComponents(RouterLinkStub).length).toBe(migratedCount)` 断言只数导航项,品牌区变成 `RouterLink` 后会让实际渲染数比 `migratedCount` 多一,必须把该断言改为排除品牌区(如按 `.sidenav__link` 选择器过滤)或显式 `+1`,不能只加一条新断言而放着旧断言不改,否则会带着一个可预期但未处理的失败提交。②`SideNav.spec.ts` 目前在 unmodified `main` 上就已经因为 `NAV_ITEMS` 全部迁移(零 legacy 项)导致 `legacyLinks[0]` 为 `undefined` 而抛 `TypeError`——与本单元无关的既存 bug,但本单元恰好要编辑同一个测试文件,顺手把这条断言改为对"零 legacy 项时不作 legacy 相关断言"的分支处理(或更新为反映当前全迁移状态的断言),避免自己的改动被这个无关的既存失败掩盖。

**Patterns to follow:** 同文件里已有的 `RouterLink` 用法(21-30 行,`isMigrated` 分支)。

**Test scenarios:**
- Happy path: `SideNav` 渲染后,品牌区是指向 `/` 的 `RouterLink`(而非纯文本 `div`)。
- Integration: 点击品牌区触发 SPA 内路由跳转(非整页刷新),落地页为发布工作台。
- Error path(既存违规清零): 修正后的 `SideNav.spec.ts` 在 `npx vitest run` 下全绿——既不因品牌区新增的 `RouterLinkStub` 导致计数断言失败,也不因零 legacy 项导致 `TypeError`。

**Verification:**
- `SideNav.spec.ts` 全部断言(含修正后的既有断言)通过。
- 浏览器手测:在任意 SPA 页面点击左上角品牌区,回到发布工作台且无整页刷新。

- [x] **Unit 3: 5 个页面迁移到共享 `.data-table` 约定**

**Goal:** `CampaignProgress`/`EquityLedger`/`KeepAlive`/`OptimizationStatus`/`PrQueue` 五个页面的裸 `<table>` 并入既有 `.data-table` 共享约定,观感与 `History`/`Schedule`/`Sites` 一致。

**Requirements:** R3

**Dependencies:** None

**Files:**
- Modify: `frontend/src/pages/CampaignProgress/CampaignProgressPage.vue`
- Modify: `frontend/src/pages/EquityLedger/EquityLedgerPage.vue`
- Modify: `frontend/src/pages/KeepAlive/KeepAlivePage.vue`
- Modify: `frontend/src/pages/OptimizationStatus/OptimizationStatusPage.vue`
- Modify: `frontend/src/pages/PrQueue/PrQueuePage.vue`
- Create: `frontend/src/__tests__/data-table-adoption.spec.ts`(静态源码断言,见 Approach)

**Approach:**
- 逐页给 `<table>` 套上 `.data-table-wrap`(横向滚动容器)、表格本身加 `.data-table` 类;ID/计数/日期/状态/URL 列按现有语义加 `col-id`/`col-num`/`col-date`/`col-status`/`col-url` 类(参照 `History`/`Schedule`/`Sites` 的既有用法)。
- **文档评审修正**:这 5 个页面目前的 `<table>` 用的是 Bootstrap 的 `table table-sm table-hover align-middle mb-0` + `thead.table-light`(来自 `frontend/index.html` 的 Bootstrap CDN link),不是空白裸表格。History/Schedule/Sites 的既有做法是**完全替换掉**这些 Bootstrap 类而不是与 `.data-table` 并存(如迁移后是 `<table class="data-table">` 而非 `<table class="table table-sm data-table">`)——本单元同样要整个替换掉,否则 Bootstrap 自带的边框/hover 背景/内边距会和 `.data-table` 的密度规则打架,达不到"观感与 History/Schedule/Sites 一致"的目标。
- 每个文件里若有与 `.data-table` 重复或冲突的页面本地 `<style>` 表格规则(密度、边框、字号),先删除再套用共享类,避免两套规则并存导致的样式漂移——逐文件检查,不假设都没有。
- **新增静态回归门(文档评审建议,成本低、Unit 1 已示范同一手法)**:仿照 `token-resolution.spec.ts` 的"读源码文本 + 正则"手法,新增一个测试断言这 5 个页面文件都引用了 `.data-table`/`.data-table-wrap`,且不再包含裸的 `table table-sm table-hover align-middle mb-0` Bootstrap 类组合——比纯手工目检更能防止未来有人改动这几个页面时悄悄退回裸表格。

**Execution note:** 纯样式/class 改动,无行为变化;逐页目检确认与 History/Schedule/Sites 观感一致。

**Patterns to follow:** `frontend/src/pages/History/HistoryPage.vue`、`frontend/src/pages/Schedule/SchedulePage.vue`、`frontend/src/pages/Sites/SitesPage.vue` 里 `.data-table` 的既有用法(含它们如何完全替换 Bootstrap 表格类,而非叠加)。

**Test scenarios:**
- Happy path(静态回归门): 新增的 `data-table-adoption.spec.ts` 断言 5 个目标页面文件均包含 `.data-table`/`.data-table-wrap` 引用。
- Error path(静态回归门): 同一测试断言 5 个文件不再包含 Bootstrap 的 `table table-sm table-hover align-middle mb-0`/`table-light` 类组合。
- Test expectation(视觉层面): none — 密度/对齐/截断的视觉正确性无法靠静态断言覆盖,由 Verification 的逐页目检覆盖。

**Verification:**
- 5 个页面的表格密度、等宽列对齐、长文本截断观感与 History/Schedule/Sites 一致,无 Bootstrap 表格类残留造成的样式冲突。
- 每页原有的本地表格样式冲突已清理,无残留双重样式。
- 页面原有功能(排序、操作按钮、轮询刷新等)零回归。
- 新增的静态断言测试通过。

- [x] **Unit 4: SPA 侧栏窄屏响应式(折叠为抽屉)**

**Goal:** SPA 侧栏在窄屏下可折叠为抽屉,与 legacy 响应式行为对等(汉堡键打开、Escape/遮罩关闭、body 滚动锁定)。

**Requirements:** R4

**Dependencies:** None(可与 Unit 2 并行;若顺序执行,建议在 Unit 2 之后,因为顶栏汉堡键与品牌区在小屏下的布局需要一起过目检)

**Files:**
- Create: `frontend/src/composables/useSidenavDrawer.ts`(抽屉开关状态)
- Create: `frontend/src/composables/useSidenavDrawer.spec.ts`
- Modify: `frontend/src/layout/AppShell.vue`(挂载抽屉状态、遮罩层)
- Modify: `frontend/src/layout/SideNav.vue`(抽屉展开/收起的 class 绑定、断点样式)
- Modify: `frontend/src/layout/TopBar.vue`(窄屏下显示汉堡按钮,触发 composable 的 toggle)

**Approach:**
- `useSidenavDrawer` composable 暴露一个 `isOpen` 响应式状态 + `open`/`close`/`toggle` 方法,供 `TopBar`(汉堡按钮)与 `SideNav`/`AppShell`(抽屉本体+遮罩)共享。
- 断点沿用 legacy 的 `@media (max-width: 1024px)`;宽屏下汉堡按钮隐藏、侧栏保持常驻(现状不变)。
- 交互语义对齐 legacy `MobileDrawer`:Escape 键关闭、点击遮罩关闭、抽屉打开时 body 滚动锁定、关闭后焦点回到汉堡按钮(参照 legacy `webui_app/static/js/nav.js` 的无障碍处理,但用 Vue 的 `onMounted`/`onUnmounted` 生命周期钩子注册/清理事件监听,而非直接复用该文件)。
- 侧栏 `nav` landmark 与 `aria-current` 等既有无障碍属性(SideNav.vue 已有)在抽屉模式下保持不变。
- **文档评审补充,原计划遗漏的具体无障碍要求**:①**打开时的焦点落点** ——抽屉打开时焦点应移入抽屉内(如第一个导航项或关闭按钮),而不是停留在汉堡按钮上,否则键盘用户 Tab 会直接穿过视觉上隐藏的抽屉进入背后的主内容区;②**Tab 焦点陷阱**——抽屉打开期间 Tab/Shift+Tab 应在抽屉内循环,不应跳到抽屉外的背景内容;③**明确的 ARIA 属性集**——汉堡按钮需要 `aria-expanded`(随 `isOpen` 同步)+ `aria-controls` 指向抽屉;抽屉容器需要恰当的 `role`(如 `dialog`)与状态属性,不能只在 Verification 里写"无障碍属性达标"这种未列出具体属性的笼统说法。
- **窄屏下调整视口宽度跨越断点时的行为**:若抽屉打开时视口从窄屏变宽跨过 1024px 断点(如平板旋转、开发者工具调整),抽屉应自动关闭且释放 body 滚动锁定,不能停留在"打开态"但侧栏已经变成宽屏常驻布局的不一致状态。

**Execution note:** test-first——`useSidenavDrawer` 的开关/Escape/清理行为先写测试再实现,composable 本身无 DOM 依赖,适合纯单元测试。

**Patterns to follow:** legacy `webui_app/static/js/nav.js` 的 `MobileDrawer`(交互语义参照,非直接复用)与 `webui_app/static/css/global_nav.css` 的断点值;`frontend/src/composables/useErrorToast.ts` 的 composable 文件组织与测试写法。

**Test scenarios:**
- Happy path: 点击汉堡按钮 → `isOpen` 变为 `true`,侧栏获得展开态 class,`aria-expanded` 同步为 `true`。
- Happy path: 再次点击或点击遮罩 → 关闭,`isOpen` 变为 `false`,焦点回到汉堡按钮。
- Edge case: 按 Escape 键 → 关闭抽屉(仅在打开状态下监听,关闭后应移除监听避免残留)。
- Edge case: 抽屉打开时 body 滚动被锁定;关闭后恢复。
- Edge case: 抽屉打开时焦点先移入抽屉内(而非停留在汉堡按钮),Tab/Shift+Tab 在抽屉内循环,不跳到背景内容。
- Edge case: 抽屉打开期间视口从窄屏调整到 >1024px → 抽屉自动关闭、body 滚动锁定释放,侧栏恢复宽屏常驻布局。
- Integration: 宽屏(>1024px)下汉堡按钮不可见、侧栏保持宽屏原有的常驻布局,不回归 Unit 2 的品牌区首页链接可点击性。

**Verification:**
- 三种宽度(桌面/平板/手机)下侧栏行为符合预期;窄屏抽屉可用;`aria-expanded`/`aria-controls`/抽屉 `role` 等具体无障碍属性存在且正确,焦点顺序(打开时移入、关闭时归位)、Tab 陷阱、Escape、锁滚动均达标。
- 宽屏行为(现状)零回归;视口跨断点变化时抽屉状态与布局保持一致。

## System-Wide Impact

- **Interaction graph:** `tokens.css` 是 SPA(`main.ts:8`)与 legacy(`base.html`)共同的父依赖——Unit 1 改动会同时影响两侧处于浅色态的页面(深色态默认值不变,零影响面已在 Approach 里限定)。`AppShell.vue`/`SideNav.vue`/`TopBar.vue` 是所有 14 个 SPA 路由共同的持久化 shell,Unit 2/4 改动理论上影响全部页面——但改动本身局限于品牌区标记和新增的响应式钩子,不触及路由内容区。
- **Error propagation:** 本期四个单元均不涉及错误处理路径,`StateBlock`/`classifyError` 逻辑不变。
- **State lifecycle risks:** Unit 4 新增的抽屉开关状态是纯前端 UI 状态(无持久化、无网络请求),关闭时机不当只会导致视觉残留,不会产生数据不一致或重复提交风险。
- **API surface parity:** 无——四个单元均为纯前端改动,不涉及后端契约。
- **Integration coverage:** 需要跨表(SPA + legacy)手测浅色主题切换效果(Unit 1);需要在实际浏览器里验证响应式抽屉与既有 Ctrl+K 搜索框、Pro 状态徽章(`TopBar.vue`)在窄屏汉堡按钮加入后的布局不冲突(Unit 4)。
- **Unchanged invariants:** 深色模式(两侧默认态)视觉不变;`theme.ts`/`theme.js` 的切换逻辑与 localStorage key 不变;`NavItem`/`isMigrated`/路由表结构不变(仅 `SideNav` 品牌区标记改动);`.data-table` 共享约定定义本身(`app.css:150-193`)不变,只扩大采用范围;后端路由/API 契约不变。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| 浅色主题补全后仍有未预见的低对比度点(SPA 组件里残留字面色值) | `token-resolution.spec.ts` 既有守卫已禁止字面颜色兜底;Unit 1 完成后对 5 个使用 `.alert-*`/`.btn-outline-secondary` 的页面逐一目检 |
| 删除 `app.css` 无条件覆盖后,`tokens.css` 已有的主题感知 `.alert-*` 规则视觉与之前不完全一致 | 目检确认改动前后视觉差异是否可接受(预期应更接近深色控台风统一观感,而非退步) |
| Unit 3 迁移时页面本地表格样式与 `.data-table` 冲突未被发现 | 逐文件检查 `<style>` 块,迁移前先确认并清理冲突规则,不假设无冲突 |
| Unit 4 是 SPA 侧全新响应式行为,复杂度高于其余三个单元 | 断点值与交互语义直接对齐 legacy 已验证过的模式,不发明新方案;test-first 覆盖 composable 核心逻辑 |
| Unit 2/4 都触碰 `SideNav.vue`,若并行执行可能产生合并冲突(Unit 1 不改 `SideNav.vue`,原表格曾误列) | 二者逻辑上独立(品牌区标记 vs 响应式 class),但同文件改动建议顺序执行或改动前 `git status` 核对,而非严格并行 |
| 现有前端测试基线本身非绿(`token-resolution.spec.ts`/`SideNav.spec.ts` 在 unmodified `main` 上已失败),容易把既存失败误判为本计划引入的新回归 | Unit 1 Execution note 要求实现前先跑一次 `npx vitest run` 记录既存失败;Unit 1/2 分别把各自涉及的既存违规清零,而非在报告里含糊带过 |

## Documentation / Operational Notes

- 无数据库迁移、无 rollout 开关、无后端契约变化;纯前端 CSS token + 少量组件改动,SPA 侧走 Vite 热更新即可预览。
- `docs/solutions/` 目前没有覆盖 Vue SPA 主题/导航/响应式的既有条目(已确认,见 Institutional Learnings)——建议本期完成后用 `/ce-compound` 补一条,记录"`tokens.css` 单一真相源 + `app.css` 不应再引入平行的无条件主题覆盖"这一具体教训,避免下一次同样的漂移。

## Sources & References

- **既有计划**:[2026-06-17-001 控台重设(shipped)](docs/plans/2026-06-17-001-feat-webui-console-redesign-plan.md)、[2026-06-22-002 SPA 设计系统精炼(completed,本期承接其延后项)](docs/plans/2026-06-22-002-refactor-spa-design-system-refinement-plan.md)
- 关键代码:`webui_app/static/css/tokens.css`、`frontend/src/styles/app.css`、`frontend/src/stores/theme.ts`、`frontend/src/layout/{SideNav,TopBar,AppShell}.vue`、`frontend/src/layout/navItems.ts`、`frontend/src/router/index.ts`、`frontend/src/__tests__/token-resolution.spec.ts`
- 机构经验:`docs/solutions/best-practices/standalone-page-vs-retrofit-webui-2026-05-15.md`、`docs/solutions/architecture-health-audit-2026-06-01.md`、`docs/solutions/architecture-patterns/server-side-gap-computation-2026-06-05.md`
