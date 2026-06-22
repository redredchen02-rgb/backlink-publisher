---
title: "refactor: WebUI 前后端分离 — 纯 JSON API + Vue 3 SPA（单源同部署）"
type: refactor
status: active
date: 2026-06-18
deepened: 2026-06-18
claims: {}  # 结构性重构计划，无机器可验证行为断言；满足 post-2026-05-20 plan-claims gate（plan-check exit 0）
---

# refactor: WebUI 前后端分离 — 纯 JSON API + Vue 3 SPA（单源同部署）

## Overview

把 Backlink Publisher 的 WebUI 从「Flask 服务端渲染（Jinja2 模板 + 夹带业务逻辑的路由 + 零构建原生 ES 模块）」
重构为**真正的前后端分离**：

- **后端** 收敛为版本化纯 JSON API（`/api/v1`，OpenAPI 3.1 契约 + 统一错误信封）。
- **前端** 独立为 Vue 3 SPA（Vite 8 构建），消费 `/api/v1`，继承已 shipped 的深色控台 design tokens。

**运营形态 = 单源同部署（用户拍板）**：Vue SPA 构建为静态资源，仍由 Flask 在**同一源**下托管。
这是一个关键的降险决定——它让前后端在**代码与架构层面**彻底分离、前端现代化，但**不**把「持有真实发布凭证的进程」
暴露成跨源网络服务，从而**整块砍掉** CORS / BFF / SSRF / 跨源鉴权这一安全工程，保留现有 loopback + 同源 + CSRF 安全模型。

迁移用 **strangler-fig（绞杀者）逐页推进**：旧 Jinja 页与新 SPA 页单源共存、逐页 flag 门控切换、全程 CI 绿、随时可回退，
不做 big-bang 重写、不冻结功能。「与 `webui-console-redesign` 合并」的真实含义是：该视觉翻新**已 shipped**，
本计划在其已落地的深色控台设计系统**之上**做架构重构，**继承其 tokens、不重做视觉语言**。

> 本计划在写入后即做了一次 plan-level 深化（见 `deepened`），把研究中发现的「预判审计 / 已 shipped 翻新 / 测试真实爆炸面 / 单源安全模型」全部并入 Problem Frame、Key Decisions 与 Risks。

## Problem Frame

用户诉求：「整理代码库 + 进行前后端分离的运营方式 + 详细分析后重构」。经四路研究（仓库盘点 / 历史经验 / 迁移最佳实践 / 框架选型）后，需要诚实地把三个硬事实摆在最前面：

1. **仓库里已有一份针对此请求的预判审计。** `docs/solutions/architecture-health-audit-2026-06-01.md` 的触发标签正是
   「前后端分离 / 拆分模组 / 全面优化」。其结论：后端 `src/` 对 WebUI（`webui_app`）的导入数 = **0**——依赖层面早已分离干净；
   当前「进程内 API 衔接」（`webui_app/api/pipeline_api.py` 直接调用 CLI 引擎）是一个**刻意 shipped 的决定**
   （plan `2026-05-27-004-thin-webui-in-process-pipeline`）；并判定「瓶颈是执行与收敛，不是再拆模组」。
   **本计划必须正面回应这份审计**：见下方「本次重构买来的新价值」。
2. **`webui-console-redesign` 视觉翻新已 shipped（非在途）。** 它当初明确冻结了「零构建、不引框架、不动后端」这条边界。
   因此「合并」= 在一个**已完成**的设计系统之上做新重构，继承其深色控台 tokens，而非合并两个在飞计划。
3. **真正的难点不是拆代码，是边界处的纪律。** 实测：业务逻辑层（`webui_app/services/` 约 21–22 个模块 0 Flask 导入、`webui_store/` 仅 `registry.py` 用 Flask 作 DI shim）
   **已是 Flask-free 纯函数**，API 可直接调用、零重写；「~10000 测试大屠杀」是误传——量级是**几十个文件、非万级**。
   注：碰 HTTP 层的文件数随计数口径在 ~62（`test_webui_*`）/~94（含 `test_client`）/~110–259（宽松 grep）间浮动，断言裸 HTML 的在 ~20–86 间浮动；
   **U5–U7 的逐 PR 工作量须按执行时实测的口径校准，不要以最乐观的 94/20 定 PR 大小**（执行时用 `grep -l` + AST 复核）。代码分离本身可控。
   难点集中在：**API 契约不漂移、测试随路由迁移不丢业务规则、单源安全模型不被破坏**。

**本次重构买来的新价值（对审计的回应）：**
审计是对的——若目标是「网络化分离运营」，当前架构已无此需求，不该做。但本计划的目标不同：
（a）**前端可维护性与现代交互**——把 19 页、~24 个原生 ES 模块从「服务端渲染 + 字符串拼 DOM + 模板字面散落」升级为组件化、
可测试、可演进的 SPA，承接已 shipped 的控台设计系统；（b）**后端契约化**——把 all-HTTP-200 的 `{"ok":...}` 即席 JSON
收敛为版本化、可契约测试的 `/api/v1`，消灭 UI↔CLI 的派生数据漂移；（c）**单源**意味着这些价值**不需付出网络化的安全代价**。
跨源网络化运营（审计真正警告的那条路）被显式记为**带触发条件的延后阶段（R9）**，本轮不做。

## Requirements Trace

- **R1** — 后端收敛为版本化 JSON API：`/api/v1`（url_prefix blueprint）+ OpenAPI 3.1 契约 + RFC 9457 统一错误信封 + 真实 HTTP 状态码。WebUI 所需全部数据经契约暴露。
- **R2** — 前端独立为 Vue 3 SPA（Vite 8 + Vue Router 5 + Pinia + TanStack Query），单源由 Flask 托管，消费 `/api/v1`。
- **R3** — 把 6 个 context-processor 变量与现有 HTML 路由转成 API 端点；**服务端派生数据（active dofollow / 权益缝隙等）保持单一真相源**，不下放前端计算。
- **R4** — strangler-fig 逐页迁移：旧 Jinja 与新 SPA 单源共存、逐页 flag 门控、全程 CI 绿、随时回退；不 big-bang、不冻结功能。
- **R5** — 继承已 shipped 的深色控台 design tokens（`tokens.css`），保留双主题；把前端反铁律的**理由**映射到 Vue 机制（见 Key Decisions）。
- **R6** — 测试随路由迁移逐 PR 转换（特征化 → 契约测试 / 组件测试 / split），守住覆盖门、不留 E2E 真空。**⚠️ 前置修正（feasibility 审出）**：现有 `--cov-fail-under=80` 门**只测 `src/` 包，不含 `webui_app`**——删 Jinja 既不升也不降这个数，安全网对本次迁移是「装饰性」的。U1 须把 `webui_app` 纳入覆盖度量（或为前端单设 Vitest 覆盖门），否则 R6 的「80% 门」承诺无效。**注意（执行实测）：CI `ci.yml:134` 用裸 `--cov --cov-fail-under=80` 直接读 `.coveragerc` 的 source——直接把 `webui_app` 加进 source 会让 CI 立刻度量其覆盖率，若不足 80% 则当场破门。因此这一步必须先跑全量测出 `webui_app` 覆盖基线，再决定「单一门 + 爬坡」还是「webui_app 独立阈值」，不可盲目加行（首个 U1 commit 已暂缓此项以守住绿门）。**
- **R7** — 保留单源安全模型：loopback + 同源 + 全局 CSRF 守卫（守卫顺序不变量）+ origin guard；CSRF token 经端点暴露、前端每调用 fresh-read、永不缓存。
- **R8** — 仓库与文档收敛：更新 ARCHITECTURE / AGENTS / CLAUDE 反映新架构；收敛冗余 `OPTIMIZATION_*_REPORT.md`；以「有构建前端规则」正式取代「零构建铁律」并记录。
- **R9（延后，不在本轮）** — 跨源独立部署（前端上 CDN、后端作独立网络 API 服务）。带触发条件（出现真实第二客户端 / 远程多人运营需求）+ flag 门控；resume-trigger 见 Open Questions。

**继承自 redesign（已 shipped）的 UI 需求**（U4/U6 直接承接，列此以闭合可追溯性）：
- **R11** — 监控聚合看板：四类状态（保活/健康/权益/优化）汇成「今日异常优先」卡片视图 + 一键深钻 + 就地快捷操作。(see origin: redesign R11–R12)
- **R13** — 统一提醒系统：发布中断恢复 / 渠道凭证失效 / 监控异常用一致视觉语言（横幅/徽章/toast），取代散落各页的 alert。(see origin: redesign R13–R14)

### Success Criteria
- 任一**已迁移**页面在 `/app` 下由 Vue 渲染，数据全走 `/api/v1`；OpenAPI 契约 CI 门（Spectral + oasdiff + Schemathesis）绿。
- 旧 Jinja 页与新 SPA 页可共存、逐页切换、随时 flag 回退（回退 = 翻 flag，非重新部署）。
- 全量测试绿、覆盖 ≥80%；前端有 Vitest 组件测试 + 薄 Playwright E2E；迁移过程无 journey 级覆盖真空。
- 单源部署**不引入 CORS**；全局 CSRF/origin 守卫行为不变；发布凭证**不进**前端 bundle（无 `VITE_` 泄密）。
- 文档与代码现实一致；零构建铁律被新规则正式取代并记录；冗余优化报告完成收敛。

## Scope Boundaries

- **不做跨源 / 网络化暴露**（Option B）——本轮单源同部署；网络化为 R9 延后阶段。
- **不重组 `src/` Python 包结构**——这是**用户「全面重构」意图下被明确划界的取舍**（重构范围圈定在 WebUI/API/前端层）：审计判定 `src/` 对 WebUI 导入数=0、已分离干净、高 churn 低 ROI，故经用户认可后排除；不改 CLI 管线算法、adapter registry、`schema.py`。（System-Wide Impact / U9 中提到的 `python -m` smoke 仅为「万一发生包重排」的兜底检查，**不构成本轮要做包重排**。）
- **不改状态存储 schema**（`webui_store/` JSON 存储、`events.db`、`dedup.db`、checkpoint）。
- **不引入 SSR**——纯 SPA（内部运营者工具，无 SEO/首屏匿名需求）。
- **不引入 CSS-in-JS**——保留 `tokens.css` + Vue `<style scoped>` + `v-bind()`。
- **不重做视觉语言**——视觉翻新已 shipped，本轮继承其深色控台 tokens。
- **不 big-bang、不冻结功能**——strangler-fig 是硬约束。

## Context & Research

### Relevant Code and Patterns
- **后端业务层已就绪**：`webui_app/services/`（22/22 Flask-free，返回 dataclass/dict）、`webui_store/`（13/14 纯；仅 `registry.py` 用 Flask 作 DI shim）。API 直接调用即可。
- **`webui_app/api/` 不是 blueprint**，是被路由调用的服务门面（`PipelineAPI`/`DraftAPI`/`HistoryAPI`/`PipeResult`）。真正的「wire API」尚不存在，HTTP 绑定在 `routes/`。
- **路由面**（40 模块，无一用 `url_prefix`）：~24 个 HTML-only 端点需转 API、~15 个 dual-mode 需拆（去掉 HTML GET）、~43 个已 JSON-shaped。重 HTML 模块：`history.py`/`drafts.py`/`pipeline_plan.py`。
- **6 个 context-processor 变量**（`platforms`/`bound_platforms`/`csrf_token`/`asset_version`/`pro_status`+`llm_configured`/`lite_edition`）今天无 API 等价物，SPA 需要专门端点。
- **现有响应信封** `{"ok":bool, "flash_msg", "flash_type", ...}`、**全部 HTTP 200**；`PipelineAPI` 已带 `error_class`/`exit_code` 类型化错误（可作新错误信封基底）。
- **前端可移植内核**：`static/js/lib/api.js`（`readCsrf()` 每调用读 `<meta>`）、`ui/errors.js`（`classifyError`）、`ui/states.js`、`url_derive.js`（纯算法）。`tokens.css` 单一 `:root` token 源。
- **安全衔接**：`create_app()` 两个全局 `before_request` 守卫——`_global_csrf_guard`（必须是第一个，`test_webui_csrf_ordering.py` 不变量）+ `_global_origin_guard`（反 DNS-rebinding）。测试经 `disable_csrf` conftest fixture opt-out（裸改 `CSRF_ENABLED` 会触发 `test_security_toggle_mutation_gate.py`）。
- **部署**：单容器 monolith（`Dockerfile` + `docker-compose.yml`，loopback bind，进程内 APScheduler + Playwright + SQLite）。CI 无 Node 步骤——新增 JS 构建是净新增 CI 工作。`make test-js`（`node --test tests/js/*.mjs`）是现有唯一 JS 测试路径。

### Institutional Learnings
- `docs/solutions/architecture-health-audit-2026-06-01.md` — 见 Problem Frame #1。**计划必须开篇回应**。
- `docs/solutions/best-practices/app-level-csrf-guard-makes-blueprint-csrf-dead-code-2026-05-27.md` — app 级 CSRF 守卫先跑，per-blueprint CSRF 是死代码；要更多保护用**正交**守卫（origin/rebinding）。
- `docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md` — 复用 `PipeResult`/`error_class`/`exit_code` 作 JSON 错误 schema，不要另起炉灶。
- `docs/solutions/architecture-patterns/server-side-gap-computation-2026-06-05.md` — 「每个判断服务端算好再注入，不外包给客户端」；移派生逻辑入 SPA 会让 UI↔CLI 漂移。**R3 的硬约束**。
- `docs/solutions/best-practices/standalone-page-vs-retrofit-webui-2026-05-15.md` + `monolith_budget.toml`/`complexity_budget.toml` — monolith god-constant 的痛驱动了 sibling-page + blueprint 拆分 + SLOC 门。**强烈支持逐页迁移**而非大爆改；超 budget 需同 PR 写 ≥80 字 rationale。
- `docs/solutions/logic-errors/python-m-needs-main-module-after-package-split-2026-05-19.md` — 任何包重排后 `python -m` 会断（仅 CI smoke 抓），`tests/test_cli_layout.py` 有预防检查。
- auto-memory `user-doc-convergence-pref` / `v050-core-convergence` — 用户偏好**收敛现有文档、抗拒新路线图、用数据决策**；R8 必须用「distill 而非加 roadmap」的姿态。

### External References（2026，含来源）
- Strangler-fig / branch-by-abstraction（外到内、逐路由、flag 回退）：[Fowler](https://martinfowler.com/bliki/StranglerFigApplication.html)、[Azure](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)。
- 契约优先 + OpenAPI 3.1（`nullable` 已移除）：[OpenAPI 3.0→3.1](https://learn.openapis.org/upgrading/v3.0-to-v3.1.html)；错误信封 [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html)（branch on `type` 不 branch on `title`）。
- Flask 契约工具：**apiflask 3.1**（Pydantic v2 / OpenAPI 3.1 / 纯 WSGI，推荐）或 flask-smorest 0.47（marshmallow）。契约门：[Spectral](https://github.com/stoplightio/spectral)（lint）+ oasdiff（破坏性变更 fail）+ [Schemathesis](https://schemathesis.io/)（一致性 fuzz）+ [Prism](https://stoplight.io/open-source/prism)（前端先行 mock）。
- 前端框架选型：**Vue 3.5 Composition API**（不上 3.6 Vapor beta）+ [Vite 8](https://vite.dev/blog/announcing-vite8) + Vue Router 5 + Pinia + TanStack Query（`refetchInterval` 轮询）。runner-up Svelte 5。来源见 Sources。
- 单源/部署：Vite `server.proxy`（`changeOrigin:true` 让 Flask origin guard 看到同源）→ `build.outDir` 给 Flask 托管；`index.html` `no-cache`、hashed 资源 `immutable`；`VITE_` 变量会烘进 public bundle，**禁放密钥**。
- 测试：特征化/golden-master（[approvaltests](https://pypi.org/project/approvaltests/) / syrupy，先 scrub CSRF/时间戳等非确定项）；分流决策树；前端 Vitest + Testing Library；薄 [Playwright](https://playwright.dev/python/)（有 Python binding）；[MSW](https://mswjs.io/) 从同一 OpenAPI spec 生成前端 mock。

## Key Technical Decisions

- **单源同部署**：Flask catch-all 在 `/app/*` 服务 SPA `index.html`，Vite `build.outDir → webui_app/static/spa/`。理由：保留同源安全模型，砍掉网络化的整块安全工程；契合「内部运营者工具」定位（见研究：内部工具单源更简单）。
- **API 框架 = apiflask（Pydantic v2 / OpenAPI 3.1）**，`/api/v1` url_prefix blueprint。理由：从 typed schema 生成契约、纯 WSGI 不需 ASGI 迁移。runner-up flask-smorest（marshmallow）——执行 U1 时一锤定。
- **错误信封 = RFC 9457 `application/problem+json`**，构建在现有 `PipeResult.error_class`/`exit_code` 之上（复用而非重造）；把 all-HTTP-200 改为真实状态码。SPA 只 branch on `type`，不 branch on `title`/`detail`。
- **契约即真相**：OpenAPI 3.1 spec 作 linchpin，CI 门 = Spectral（lint，强制 snake_case/描述）+ oasdiff（破坏性变更 fail，对 merged-base）+ Schemathesis（live 一致性 fuzz）；Prism mock 让前端先行；MSW 从同一 spec 生成前端测试 mock —— 一份 spec 同时喂后端一致性 + 前端 mock，结构性防漂移。
- **版本化 = URL path `/api/v1`，additive-only**（同 major 内只加不改/不删）。wire 用 **snake_case**、时间戳 **RFC 3339 UTC**、**string ID**（避 JS `Number` 精度）、集合用对象信封（**永不裸顶层数组**）、大/可变列表用 **cursor 分页**。
- **前端栈 = Vue 3.5 Composition API（`<script setup>`）+ Vite 8 + Vue Router 5 + Pinia + TanStack Query**；纯 SPA。理由见研究：从 Jinja+vanilla 心智跳跃最短、原生对接 tokens.css/主题、官方全家桶、密集表格生态最好。**不上 Vue 3.6 Vapor（仍 beta）**。
- **反铁律「理由」→ Vue 机制映射**（语法变、理由不变）：
  - `window.*` 全局 API（静默 no-op）→ **Pinia store / `emit`**（显式、可 devtools 检视）。
  - 不可信 `${…}` 入 `innerHTML`（XSS 边界）→ **Vue 默认转义**；`v-html` 是显式可 grep 的 opt-in。
  - `readCsrf()` 每调用读 `<meta>`（轮换 token 否则 403）→ **fetch 拦截器每次现读、永不缓存进 store**。
  - `asset_version`（mtime 防陈旧）→ **Vite content-hash 文件名**；处理 `vite:preloadError`。
- **迁移 = strangler-fig 外到内**：先立单源入口 → 抽 API 契约（让现有 Jinja 视图也消费同一 API，杜绝双真相）→ 迁 shell → 逐页迁移（flag 门控）→ 删 Jinja 路由+模板（删除即兑现价值）。
- **服务端派生数据保持单一真相源**：gap/dofollow/set-difference 判定留服务端（沿用 server-side-gap learning），SPA 只显示不重算。
- **测试随路由迁移逐 PR**：每个路由 cutover PR 同时带（a）路由改动（b）旧 HTML 断言的删除/转换（c）新契约测试（d）新前端组件测试 —— 套件全程绿、迁移路由覆盖不掉。决策树：view-only → 组件测试后删；业务规则经 HTML → 转契约测试；both → **split（永不折叠成 delete）**；纯逻辑 → 不动。

## Open Questions

### Resolved During Planning
- 运营形态？→ **单源同部署**（用户拍板；砍掉跨源安全工程）。
- 前端框架？→ **Vue 3**（用户拍板；研究首选）。
- `src/` 是否重组？→ **否**（审计判定已分离干净 + 收敛偏好 + 高 churn 低 ROI）。
- 测试真实规模？→ ~94 文件碰 HTTP、~20 裸 HTML、~490 纯逻辑不动（实测，非万级重写）。
- 「合并 redesign」含义？→ redesign 已 shipped，本轮**继承其 tokens**、不重做视觉。

### Deferred to Implementation
- **apiflask vs flask-smorest** 最终取舍——执行 U1 时按团队 schema 偏好（Pydantic v2 vs marshmallow）一锤。
- ~~**publish 是否暴露可轮询 task-id 进度端点**~~ — **U5 已决（降级忙碌态）**：实测后端单笔 publish 是同步阻塞（300s 超时）、无 task-id（只有批量 campaign 另有 `/api/campaign/<id>/status` 轮询）。加 task-id 须改持有真实凭证的发布路径（redesign 当初判定高风险未做），故采保守先例：`POST /api/v1/pipeline/publish` 保持同步、partial→200、total-failure→problem+json；前端走降级忙碌态分支（提交控件 in-flight 禁用防 `dedup.db` 单飞重复提交 + 软超时文案「仍在进行，可能已完成，请勿重复提交」+ 完成回填）。task-id 进度端点若日后需要，按本格式重启。
- ~~**监控聚合看板数据源**~~ — **U6 已决（复用既有聚合）**：实测后端已有 `command_center._collect_subsystem_status()` + `_build_anomaly_cards()` 聚合 + `/api/monitor-hub` JSON（redesign U5 落地），equity/optimization 也已有 `/api/*` JSON 孪生。故 U6 不重算、不新建聚合逻辑——在 `/api/v1/monitor/summary` 做薄绑定复用同一对函数（gap/severity/排序留服务端，R3 单一真相源），前端只显示（按服务端已排好的 danger→warning→ok→info 序）。fail-open：子系统级降级卡 + 聚合级 `degraded` 空载 200，永不拖垮整页。前端 TanStack Query `keepPreviousData` 轮询防闪白。
- **密集 ledger 表**——off-the-shelf grid（AG Grid / TanStack Table）vs 手写组件；窄屏卡片化断点。影响个别组件依赖，迁移时定。
- **R9 跨源网络化 resume-trigger**——当出现「真实第二客户端」或「远程/多人运营」需求时，按 deferral 格式（status + rationale + trigger）重启，届时执行研究中的安全清单（每端点鉴权 + 授权 + CORS allowlist + BFF + SSRF allowlist + 密钥管理 + TLS/HSTS + ASVS 验收）。

## High-Level Technical Design

> *以下示意「单源 strangler-fig + 契约 linchpin」的整体形态，是供评审验证方向的指引性草图，不是实现规范。实现代理应将其视为上下文，而非照抄的代码。*

迁移期的单源请求路由 + 契约作为前后端唯一耦合点：

```mermaid
flowchart TB
  Browser["浏览器（同源）"] --> Flask["Flask（单进程 / loopback）"]
  Flask -->|"/app/* + flag on"| SPA["Vue SPA index.html<br/>(webui_app/static/spa/)"]
  Flask -->|"未迁移路径 / flag off"| Jinja["旧 Jinja2 模板（逐页退役）"]
  SPA -->|"fetch（同源, 带 CSRF header）"| APIv1["/api/v1（apiflask blueprint）"]
  Jinja -->|"迁移期也消费同一 API（杜绝双真相）"| APIv1
  APIv1 --> Svc["services/ + webui_store/<br/>（已 Flask-free 纯逻辑, 零重写）"]
  Spec["OpenAPI 3.1 spec（linchpin）"] -.->|"Spectral lint / oasdiff 破坏门"| CI["CI 契约门"]
  Spec -.->|"Schemathesis 一致性 fuzz"| APIv1
  Spec -.->|"Prism mock（前端先行）/ MSW（前端测试）"| SPA
  CSRF["全局 CSRF 守卫(第一)+origin 守卫"] -.->|"不变量保持"| Flask
```

> **图是「重构后的目标态」，不是 day-1 现状（coherence 审出）。** 「旧 Jinja 视图也消费同一 `/api/v1`」是 U1→U2→…→U7 逐步达成的*目标*——当前 Jinja 路由仍各自调 `services/`，双真相在迁移完成前并未被杜绝。把它当现状会误判风险已消除。

关键不变量：**唯一耦合点 = OpenAPI 契约**；**唯一源 = 同一 Flask origin**（dev 用 Vite `server.proxy` 镜像 prod，浏览器全程只见相对 `/api` 路径；注意 prod 是 Flask 直接托管静态文件、无 proxy，`changeOrigin:true` 仅是 dev 让 origin 守卫看到同源的权宜，prod 同源天然成立）；**安全模型不变**（CSRF 守卫仍第一、origin 守卫仍在、凭证仍仅服务端——但见上方「单源威胁模型」对 GET bootstrap 面的补强）。

## Implementation Units

> 4 阶段、9 单元，依赖序见下图。每个 cutover 单元都遵守 strangler-fig：套件全程绿、可 flag 回退。

```mermaid
flowchart TB
  U1["U1 /api/v1 契约骨架 + CI 门"] --> U2["U2 暴露 context + 已JSON端点"]
  U1 --> U3["U3 脚手架 Vue+Vite + 单源托管 + 内核移植"]
  U2 --> U4["U4 迁移全局 shell"]
  U3 --> U4
  U4 --> U5["U5 迁移核心发布工作台"]
  U4 --> U6["U6 迁移监控聚合看板"]
  U5 --> U7["U7 逐页迁移其余页 + 转 HTML/dual 路由"]
  U6 --> U7
  U7 --> U8["U8 退役 Jinja 服务端渲染路径"]
  U8 --> U9["U9 文档/仓库收敛 + 部署/CI 固化"]
```

**迁移期 UX 连续性约定（design-lens 审出，U3 立基、U4–U7 引用）：** 服务端渲染页数据随 HTML 一次到位、没有加载态；转 fetch 后**每页新增了加载/失败/空/陈旧四态**，这是回归风险点，须统一约定而非逐人发挥：
- **四态矩阵**（U3 把 `ui/states.js` 移植为单一源）：加载（skeleton/spinner 阈值）、空（图示+文案+主行动）、错误（页级 fetch 失败就地重试 vs 动作失败 toast，按 `classifyError` 分类）、陈旧（轮询用 TanStack Query keep-previous-data，监控看板每次轮询不要闪白）。
- **双栈导航寻路**（U4）：迁移期侧栏须同时列已迁移（Vue/`/app`）与未迁移（Jinja）页；点未迁移项是整页跳出 SPA（in-flight toast/轮询/store 态会丢，须明确为预期），且 `data-theme` 主题须跨边界保留（Jinja 页从 storage/服务端重置）；明确「是否给操作者标注新旧页」的决定。
- **flash→Toast 桥**（U4）：未迁移 Jinja 页仍服务端发 `{flash_msg,flash_type}`；须定义 `flash_type`→Toast 严重度映射，并明确跨边界后服务端 flash 的呈现/不重放行为，避免动作反馈静默消失。
- **a11y / 响应式基线**（U4）：SPA 路由切换移焦点到页标题 + aria-live 播报；Toast store 渲染进 aria-live 区（即「订阅契约」的 a11y 半边）；密集表用语义 `<table>`+表头关联；桌面优先、声明侧栏折叠断点与多列→单列堆叠断点。若决定延后完整 a11y，须作为显式 Scope Boundary 带触发条件记录，而非静默省略。

### Phase 0 — 契约与脚手架（无用户可见切换）

- [x] **U1：建立 `/api/v1` 契约骨架与 CI 契约门**

**Goal:** 引入 apiflask，建立 `/api/v1` url_prefix blueprint、RFC 9457 错误信封（构建于 `PipeResult`）、OpenAPI 3.1 spec 生成、CI 契约门（Spectral + oasdiff + Schemathesis）。这是 branch-by-abstraction 的 API 缝。

**Requirements:** R1, R7

**Dependencies:** 无

**Files:**
- Create: `webui_app/api/v1/__init__.py`（blueprint, `url_prefix="/api/v1"`）、`webui_app/api/v1/errors.py`（problem+json handler）、`webui_app/api/v1/schemas.py`（Pydantic DTO 基类 + 错误模型）
- Create: `openapi/backlink-api.yaml`（生成产物）、`.spectral.yaml`（lint 规则）、`.github/workflows/api-contract.yml`（或扩 `ci.yml`：spectral/oasdiff/schemathesis lane）
- Modify: `webui_app/__init__.py`（注册 v1 blueprint；**确保 `_global_csrf_guard` 仍是第一个 `before_request`**）
- Test: `tests/test_api_v1_contract.py`、`tests/test_api_v1_error_envelope.py`

**Approach:**
- blueprint `url_prefix="/api/v1"`；错误 handler 输出 `application/problem+json`，把 `PipeResult.error_class`/`exit_code` 映射为 `type`（稳定 URI）/`status`/`detail`/`errors[]`。
- 真实 HTTP 状态码（取代 all-200）；spec 从 Pydantic 生成；CI：spectral lint → oasdiff vs merged-base（破坏性变更 fail）→ schemathesis 对 live app fuzz。
- apiflask vs flask-smorest 在此一锤（见 Open Questions）。

**Patterns to follow:** `webui_app/api/pipeline_api.py` 的 `PipeResult` 错误契约；CSRF 守卫顺序（`test_webui_csrf_ordering.py` 不变量）；`docs/solutions/.../typed-error-envelope-...md`。

**Test scenarios:**
- Happy path：OpenAPI spec 通过 Spectral lint；schemathesis 对首批端点一致性绿。
- Error path：已知 `error_class` → `problem+json`（含正确 `type`/`status`，非 200）。
- Integration：注册 v1 blueprint 后 `_global_csrf_guard` 仍第一个执行（顺序不变量）。
- Edge：oasdiff 对 additive 变更通过、对删字段/改类型 fail。

**Verification:** `/api/v1` 挂载；OpenAPI spec 产出且 lint 绿；CI 契约门作为 required check 绿。

- [x] **U2：暴露 context 变量 + 已 JSON 化端点为首批 `/api/v1` 端点**

**Goal:** 把 6 个 context-processor 变量 + ~43 个已 JSON-shaped 端点纳入 `/api/v1`，直接调用既有纯 services/stores，契约锁定。

**Requirements:** R1, R3

**Dependencies:** U1

**Files:**
- Create: `webui_app/api/v1/app_config.py`（`/api/v1/app-config`、`/platforms`、`/bound-platforms`、`/pro-status`、`/csrf-token`）、按资源拆 `webui_app/api/v1/<resource>.py`
- Modify: 复用 `webui_app/services/*`、`webui_store/*`（不改其逻辑）
- Test: `tests/test_api_v1_app_config.py`、各资源契约测试

**Approach:** 薄 HTTP 绑定覆盖纯 service；snake_case wire、RFC3339 UTC、string ID、对象信封、history/ledger 用 cursor 分页。**派生数据（active dofollow / gap）仍服务端单一真相源计算**。

**Patterns to follow:** `webui_app/services/copilot_advisor.py`（返回 dataclass）；`docs/solutions/.../server-side-gap-computation-...md`。

**Test scenarios:**
- Happy path：每端点返回 spec 文档化的 schema；`/csrf-token` 返回 fresh token。
- Edge：cursor 分页在中途插入新记录后不跳/不重。
- Integration：pro/lite gating 在 `/api/v1/app-config` 正确反映；`active dofollow` 经服务端 helper 计算（与 CLI 同源，不漂移）。

**Verification:** SPA 所需全部 bootstrap 数据经 `/api/v1` 可得；契约门绿。

- [x] **U3：脚手架 Vue 3 + Vite 前端 + 单源托管 + 可移植内核移植**

**Goal:** 在 `frontend/` 建 Vue 3.5 + Vite 8 工程；dev proxy → Flask；build → `webui_app/static/spa/`；Flask catch-all 在 `/app/*`（flag 门控）服务 `index.html`，与 Jinja 共存；移植可复用内核；引入 `tokens.css` + 已 shipped 控台设计系统；CI 加 Node build/test lane。

**Requirements:** R2, R5, R7

**Dependencies:** U1（dev 时调 `/api/v1`）

**Files:**
- Create: `frontend/package.json`、`frontend/vite.config.ts`、`frontend/src/main.ts`、`frontend/src/api/client.ts`（CSRF 拦截器，移植 `lib/api.js`）、`frontend/src/router/`、`frontend/src/stores/`、`frontend/src/lib/`（移植 `ui/errors.js`/`ui/states.js`/`url_derive.js`）、`frontend/src/styles/`（import `tokens.css`）
- Create: `webui_app/routes/spa.py`（`/app/<path:p>` catch-all → `static/spa/index.html`，flag 门控）
- Modify: `Dockerfile`（多阶段：Node build → 拷 dist）、`.dockerignore`、`.gitignore`（`node_modules`、`frontend/dist`）、`.github/workflows`（node build + vitest lane）
- Test: `frontend/src/**/*.spec.ts`（vitest）、`tests/test_spa_catchall.py`

**Approach:** 纯 SPA；Vite `server.proxy` `/api → :8888`（`changeOrigin:true` 让 origin guard 看到同源）；`build.outDir = webui_app/static/spa`；`index.html` `no-cache`、hashed 资源 `immutable`；CSRF 拦截器每调用读 token、**永不缓存**；主题用 `data-theme` + 小 Pinia store；无 CSS-in-JS；处理 `vite:preloadError`。

**⚠️ U3 三个执行前必须先拍板的衔接点（feasibility 审出，否则一开工就卡）：**
- **`asset_version` 走查碰撞**：`_compute_asset_version()` 递归 `os.walk(static_folder)`；dist 落在 `webui_app/static/spa/` 会被这个开机走查遍历、且对已带 content-hash 的 SPA 资源毫无意义。U3 起 dist 与旧 mtime 缓存机制就并存（到 U8 才退役 `asset_version`）——须**把 `static/spa` 排除出走查或改 outDir 位置**。
- **catch-all 与 Flask 自带 `/static` 路由 + Vite `base` 的优先级**：Flask 默认注册 `/static/<path>`；新 `/app/<path>` catch-all 必须既不吞 `/api` 404、也不让 SPA 自身的 JS/CSS 资源请求落到 catch-all 拿到 `index.html`（经典 SPA fallback bug）。须先定 Vite `base` + 路由优先级。
- **Dockerfile 是净新增 Node 阶段不是「Modify」**：现 Dockerfile 是纯 Python builder+runtime、无 Node；CI 当前零 Node 引用。U3 要加 Node base image + `npm ci` + `vite build` + 拷 dist，并把 `node_modules`/`frontend/dist` 加进 `.dockerignore`/`.gitignore`。工作量按净新增基建估，别按一行 Modify 估。
- **`tokens.css` 双主题落地**：须确认 redesign 的 `tokens.css` 是已含明/暗两套变量、还是只有暗色——决定 SPA 是直接 import 还是要另搭 `data-theme` 覆盖层（R5）。

**Patterns to follow:** `static/js/lib/api.js`（`readCsrf` 每调用）；`static/css/tokens.css`；framework 研究的「`tokens.css` 原样保留」结论。

**Test scenarios:**
- Happy path（vitest）：移植的 fetch 拦截器每调用现读 CSRF（不缓存）；`ui/states`/`url_derive` 行为等价旧实现。
- Integration：`npm run build` 产 dist 被 Flask 在 `/app` 服务；dev proxy 命中真实 Flask；主题切换翻 `data-theme`。
- Edge：深链刷新 `/app/<sub>` 仍返回 `index.html`（SPA fallback，且不吞 `/api` 的真实 404）。
- 反铁律：无 `window.*` API；Vue 默认转义生效。

**Verification:** `/app` 显示带主题的 SPA shell；dev/prod 单源一致；CI Node lane 绿。

### Phase 1 — Shell + 最高价值页面

- [x] **U4：迁移全局 shell（侧栏/顶栏/主题/Pro/通知）到 Vue**

**Goal:** 把全局 shell 迁入 Vue，消费 `/api/v1/app-config`；用 Vue 组件 + Pinia 事件 store **取代** `notifications.js`（该 700 行层违反反铁律：`innerHTML` 拼接 + `window.notifications` 全局、且无订阅契约）；规划 z-index（含 copilot 浮层）。

**Requirements:** R2, R5, R13（继承自 redesign）

**Dependencies:** U2, U3

**Files:** Create `frontend/src/layout/*`、`frontend/src/stores/notifications.ts`、`frontend/src/components/Toast.vue`、`frontend/src/components/SideNav.vue`（`/app` 下）

**Approach:** `emit`/Pinia 取代 `window.*`；Toast/通知中心提供订阅契约；侧栏体现 pipeline 心智模型 + 活跃态；继承 redesign 的深色控台观感。

**Patterns to follow:** redesign plan `2026-06-17-001` 的 shell/z-index 规划；现有 `nav.js`/`theme.js` 行为。

**Test scenarios:**
- Happy path（组件）：侧栏活跃态随路由更新；主题持久化（reload 保留）。
- Edge：toast 生命周期（出现/堆叠/消失）；通知订阅多消费者不漏。
- Integration（E2E smoke）：`/app` shell 导航在单源下渲染、CSRF header 随 fetch 带出。

**Verification:** `/app` 全局 shell 由 Vue 渲染、观感统一控台风、通知走新订阅契约。

- [x] **U5：迁移核心发布工作台（plan/generate/validate/preview/publish）**

**Goal:** 迁移最高 churn/价值的单笔发布四阶段工作台；把其路由转 `/api/v1`（**特征化先行**）；承接 redesign 的单页分步 + 长任务进度（TanStack Query `refetchInterval` 轮询）。

**Requirements:** R1, R2, R4, R6

**Dependencies:** U4

**Files:**
- Modify→Convert: `webui_app/routes/pipeline_plan.py`、`pipeline_publish.py`、`pipeline.py` → `/api/v1/pipeline/*` 端点
- Create: `frontend/src/pages/Publish/*`
- Test: `tests/test_api_v1_pipeline.py`（契约）、`frontend/src/pages/Publish/*.spec.ts`（组件）、`tests/e2e/publish_journey.py`（Playwright）

**Execution note:** 特征化先行——对现有路由建 golden master（scrub CSRF/时间戳），抽 API 于其下、保持 Jinja 渲染在上验证行为保持，再翻 JSON、退役 HTML golden master。

**Approach:** publish task-id 进度按后端实况决定（小改加 task-id 或降级忙碌态，见 Open Questions）；错误经 problem+json → `classifyError` 分类 UI。**两个分支的 UX 内容都须先定义、再让后端决定走哪支（design-lens 审出，列为 Success Criterion 防静默丢失）**：task-id 分支 = 复用 redesign 阶段反馈语言的逐阶段标签 + 已耗时 + 取消入口；降级忙碌分支 = 明确文案「发布进行中，请勿关闭此页—完成后自动刷新」+ 动态指示器 + 软超时后转「仍在进行/可能已完成，请勿重复提交」而非看似卡死 + **禁用提交控件防止违反 `dedup.db` 单飞的重复提交**。

**Patterns to follow:** `webui_app/api/pipeline_api.py`（in-process 调用 + subprocess publish）；redesign 的阶段反馈语言。

**Test scenarios:**
- Happy path：plan→validate→preview→publish 全程契约绿；进度轮询渲染阶段文案。
- Error path：publish 失败 → problem+json（正确 `type`/status）→ 分类错误 UI + 重试。
- Edge：取消进行中 publish（若后端支持）；空输入/校验拒绝。
- Integration（E2E）：单源下完成一次发布全程不跳出工作台。

**Verification:** 核心发布全程在 `/app` Vue 工作台完成；契约 + 组件 + E2E 三层绿。

- [x] **U6：迁移监控聚合看板（keep_alive/health/equity/optimization）**

**Goal:** 迁移 redesign 的「今日异常优先」聚合看板；`equity`/`optimization` 当前仅 HTML → 转 JSON；决定数据源（聚合四路由 vs 新 `/api/v1/monitor/summary`）。

**Requirements:** R1, R2, R3, R11（继承）

**Dependencies:** U4

**Files:** Convert `webui_app/routes/equity_ledger.py`、`optimization_status.py`、`keep_alive.py`（`health.py` 已 JSON）；可能 Create `webui_app/api/v1/monitor.py`；Create `frontend/src/pages/Monitor/*`；Test 对应契约 + 组件。

**Approach:** 异常按优先级排序 + 就地快捷操作链接既有路由；**权益缝隙服务端单一真相源计算**（不前端重算）。

**Test scenarios:**
- Happy path：四类状态汇成卡片、异常优先排序。
- Integration：equity gap 由服务端 helper 算（与 CLI 同源）；一键深钻跳对应页。
- Edge：全绿（无异常）空态引导。

**Verification:** 监控异常一眼可见、一键深钻；`equity`/`optimization` 已 JSON 化、契约绿。

### Phase 2 — 其余页面 + 退役 Jinja

- [ ] **U7：逐页迁移其余页面 + 转换剩余 HTML / dual-mode 路由**（进行中——逐页 PR）

> **U7 进度（逐页迁移）**：✅ **历史页**（`/api/v1/history*` + Vue `/history`）✅ **草稿队列**（`/api/v1/drafts*` + Vue `/drafts`，旧 `?tab=draft` → 独立页）✅ **站点配置**（`/api/v1/sites*` 6 路由 + Vue `/sites`）。站点抽 `SitesAPI` facade（`webui_app/api/sites_api.py`，复用既有 `url_meta`/`config` 派生原语）；**核心页范围**：配置表单（①②③ 含服务端 TDK/sitemap 派生 + 422 字段级 `errors[]`）+ Autopilot 表（④ toggle/间隔，scheduler-sync 失败→502 回滚）+ Plan-Gap/citation 只读 widgets。**⑥ 批量操作表（`batch_sites.py`）刻意不迁——归属独立「batch」单元**。旧 `/ce:*`/Jinja 路由加法式保留待 U8 退役（旧 `routes/sites.py` 未动，计划已许可迁移窗双真相）。
> ✅ **排程**（`/api/v1/schedule` 只读 + Vue `/schedule`，复用 `scheduled_api.list_scheduled`，fail-soft 空列表）。
> ✅ **批量发布活动**（`CampaignAPI` facade + `/api/v1/campaigns/form|create` + Vue `/batch-campaign`；seeds≤10/平台/mode/cap/delay 校验 + 422 字段 `errors[]`；成功后 SPA 全导航出至旧 `/campaign/<id>` 进度页——进度页是独立未迁路由，dual-stack）。
> ✅ **profiles CRUD**（`/api/v1/profiles` list/save/delete，复用 `profiles_store`）——**仅后端**：SPA 今天无 profiles 消费者（活消费者是 `settings.js`），前端选择器随 **Settings 单元** 落地，现在建 SPA 页属投机，故不建。
> 🟰 **batch（`/ce:batch` + `/ce:publish-real`）= 无新工作**：经核已被 U5 `/api/v1/pipeline/plan|validate|publish`（接受 `urls[]` 即批量）完整覆盖；`_tab_batch.html` 仅存在于旧 `index.html`，旧路由待 U8 随 `/ce:*` 退役。
> 🔴 **Settings（独立硬子单元，进行中——安全核心已落地）**：用户拍板「安全核心优先」。
> - ✅ **凭证写安全核心**（`/api/v1/settings/channels/<ch>/token` + `/api/v1/settings/notion-token`，`webui_app/api/v1/settings_credentials.py`）。这是**威胁3 面**（写 `0600` 密钥文件）：新 api_v1 blueprint **不继承** `bind.py` 的 `before_request`，故守卫**内联在每个 view**（`_refuse_when_allow_network` + `_check_bind_origin_or_abort`，按 CSRF 配置 gate，同 `bind.py`）。所有密钥写**复用 `credential_service`/`save_notion_token`**（单源 0600 原子写），旧 `token_paste.py` 未动。**传输层安全回归**（`tests/test_webui_api_v1_settings_credentials.py`）：伪造 Origin→403、`ALLOW_NETWORK=1`→403、文件仍 `0600`、未知渠道→422、clear 删文件。两路由并入 `_GUARDED_ROUTES`（内联守卫层）→ csrf-only 快照仍 **90**（按 view 源 grep 排除）+ 白嫖伪造 Origin 覆盖。`spec.py` ceiling 640→**700**（SLOC 693）。
> - ✅ **通用凭证写 facade 抽取**（`channel_bind_save` 注册表驱动 5-way dispatch：anon/token/token_fields/paste_blob/userpass + SSRF/blob/hostname 校验）。按计划要求**单源 facade 抽取（搬移，非复制）**：dispatch + 全部校验**搬进** `webui_app/api/channel_bind_api.py::ChannelBindAPI`，返回**中性 `BindSaveResult`**（`level`/`error_class`/`cleared`/`fragment`），旧 `/settings/save-channel-credential` 路由改薄成 HTML 绑定（365→**21 SLOC**），新 `/api/v1/settings/channels/<ch>/credential` 绑定 JSON/problem。**零行为漂移**由既有 `test_channel_bind_save.py`（57 测试）当安全网证明全过；SSRF patch 目标 + `_SKIP_CHANNELS` import 跟随搬移更新。新 v1 端点同样**内联守卫**（同 settings_credentials），传输回归 `tests/test_webui_api_v1_channel_bind.py`（18 测试：伪造 Origin→403、`ALLOW_NETWORK=1`→403、五种 auth_type 0600 round-trip、SSRF/域名拒绝、clear、secret 不泄漏）。并入 `_GUARDED_ROUTES` → csrf-only 快照仍 **90**（view 源内联字面量排除）。`spec.py` ceiling 700→**730**（SLOC 724）。
> - ✅ **有状态浏览器绑定流 facade 抽取**（`bind`：start/poll/identity-mismatch keep+replace）。**单源搬移**进 `webui_app/api/bind_api.py::BindAPI`（含 PR#83 的 identity_mismatch TOCTOU 409 守卫、keep 的原子 `_restore` 闭包「bound→kept / 缺文件→expired 而非破坏性 replace / 状态变更→noop」、replace 的 artifact 擦除），返回中性 `BindResult`；旧 `bind.py` 改薄 151→**52 SLOC**（start/poll 仍 jsonify、keep/replace 仍 redirect），新 `/api/v1/settings/channels/<ch>/bind*` 四路由转 JSON/problem。**关键安全细节**：新 api_v1 bp 不继承 bind bp 的 `before_request` loopback 检查，故每 view 内联 `remote_addr` loopback 守卫——尤其 **GET poll**（无 `_refuse_when_allow_network`，remote_addr 是 `ALLOW_NETWORK=1` 下唯一 loopback 防线）；mutating 路由额外内联 Origin/network 守卫。**零行为漂移**：既有 `test_webui_bind_routes.py`+`_security.py`（53 测试）全过；新 `tests/test_webui_api_v1_bind.py`（16 测试）。keep/replace 并入 `_GUARDED_ROUTES`（start 跳过=loopback POST 会启真子进程；poll 跳过=remote_addr 非 Origin 守卫）→ 快照仍 **90**。`spec.py` ceiling 730→**820**（SLOC 819）。
> - ✅ **OAuth 凭证管理 facade 抽取**（`oauth.py` 的 clear-medium + save-blogger）。**单源搬移**进 `webui_app/api/oauth_api.py::OAuthAPI`（含 blank-secret 保留 stored 规则），旧两路由改薄委托，新 `/api/v1/settings/{blogger-oauth, medium-oauth/clear}` 转 JSON/problem。**刻意不迁**：blogger `oauth-start`→Google→`oauth-callback` 重定向握手对——callback 是 Google 顶层浏览器回跳、必须 302 回 `/settings`，**不可能是 JSON**，且 start 携带最敏感的 Flow/session/OAUTHLIB-transport/OAuth-CSRF-state 代码 + 最重 mock 耦合，整对保留 legacy 浏览器导航（SPA 的「Google 登入」按钮直接导航到 legacy start，标准 OAuth UX）。**零行为漂移**：`test_webui_routes_oauth.py`+`test_oauth_service.py`（37 测试）全过；mock 路径跟随搬移（save-blogger 的 load/save_config + clear 的 os.remove 改指 `api.oauth_api.*`，oauth-start 的 patch 保持不动）；新 `test_webui_api_v1_oauth.py`（7 测试）。**守卫**：匹配 legacy posture——无内联守卫（config 写非 0600），csrf 快照 90→**92**（+2，全局 origin guard 运行时覆盖）。`spec.py` ceiling 820→**860**（SLOC 855）。**Settings 后端至此完成**（所有凭证写 + bind 流 + oauth 凭证）。
> - ✅ **profiles 前端选择器**（2026-06-22，用户选「① profiles 前端选择器」，小而独立）。`frontend/src/api/profiles.ts`（getProfiles/saveProfile/deleteProfile 接 `/api/v1/profiles`）+ **解耦受控组件** `components/ProfileSelector.vue`（props `current:{platform,language,publishMode}` + emit `apply`，载入/存为预设/删除，TanStack Query + setQueryData 刷新 + notify toast）+ 集成进 **PublishWorkbench** config 区（`@apply` 填 `store.config`）。**消费者确认**：profile 字段（platform/language/url_mode/publish_mode）= 发布工作台 config（旧 `lib/profiles.js::loadProfile/saveProfilePrompt` 的活宿主是 `index.js` 发布台，非 settings——settings 里那套 DEAD）。url_mode 工作台无控件→存时省略、后端默认兜底。`ProfileSelector.spec.ts`（5 测试）+ PublishWorkbench.spec 补 VueQueryPlugin/mock profiles；全前端 79 测试 + vue-tsc 全绿。
> - ✅ **LLM 设定保存 facade 抽取**（`llm.py` 的 save-llm-config）。**单源搬移**进 `webui_app/api/llm_settings_api.py::LlmSettingsAPI`（clear-to-defaults / https endpoint 双闸 / blank-secret 保留 / AI 封面 image-gen 校验 / **0600 写 llm-settings.json（api_key 长期密钥）** / 同步 image-gen 进 pipeline `Config.image_gen` 桥），返回中性 `LlmSaveResult`；旧路由 277→**141 SLOC**，新 `/api/v1/settings/llm-config` 转 JSON/problem。**关键**：(1) checkbox 跨传输语义差异——form 用「键存在」=勾选、JSON 用真 bool，`_truthy_flag` 桥接；(2) 因写 0600 密钥→归**内联守卫凭证写家族**（同 credential，gated on CSRF，THREAT-3 安全回归：伪造 Origin→403/ALLOW_NETWORK=1→403/0600）；快照排除→仍 **92**。**零行为漂移**：`test_webui_llm_settings_save.py`（10 测试，真文件+flash 断言、**零内部 patch→零涟漪**）全过；新 `test_webui_api_v1_llm.py`（7 测试）。`spec.py` ceiling 860→**880**。test-connection/test-generation **未迁**（已是 JSON，且 SSRF 内部 patch 重耦合 7 处，留下一轮单独处理更安全）。
> - ✅ **LLM 诊断对 facade 抽取**（`llm.py` 的 test-llm-connection + test-llm-generation）。**单源搬移**进 `webui_app/api/llm_diagnostics_api.py::LlmDiagnosticsAPI`（SSRF-guarded 连接探针 guard→/models→/chat/completions fallback + best-effort last-known-health 持久化 + 重定向拒绝的 `_safe_get_json` + article/anchor 生成预览），返回中性 `DiagnosticResult(payload, http_status)`；旧 `llm.py` 141→**23 SLOC**（全薄），新 `/api/v1/settings/llm/{test-connection,test-generation}` 转 JSON（**返回诊断 envelope `{status,message,models}` 非 problem+json**——失败探针是成功调用、SPA 按 status 分支，同 legacy 契约）。**关键涟漪处理**：`import requests` + `_guard_llm_endpoint`/`_safe_post_json`/`_safe_get_json` re-export **保留在 routes.llm**——因 unit3 SSRF 测试 patch `routes.llm.requests.{get,post}`（**全局 requests 模块 handle**，搬 helper 后仍生效）+ lift-parity 测试断言 re-export；故 unit3/lift-parity **零改动**，只 3 个 persist 测试的 helper-name patch 改指 facade。**零行为漂移**：`test_webui_unit3_security`+`test_llm_client`+`test_webui_llm_test_persist`+`test_webui_core_routes`（100 测试）全过 + 新 `test_webui_api_v1_llm_diagnostics`（5）。守卫匹配 legacy posture（诊断无内联守卫）→ 快照 92→**94**。`spec.py` ceiling 880→**930**。**LLM 后端至此全部完成**（save + connection + generation）。⚠️ 移植中发现 legacy candidates 路径有 pre-existing bug（`LLMAnchorRequest(domain=...)` 该类不接受 domain→status error）；**忠实保留不改**（移植不 fix bug）。
> - ✅ **image-gen 诊断对 facade 抽取**（`image_gen.py` 的 test-image-gen + generate-sample-image）。**单源搬移**进 `webui_app/api/image_gen_diagnostics_api.py::ImageGenDiagnosticsAPI`（OpenAI `/models` 探针 + FRW native `/balance` 探针 + provider dispatch + 真实生成→base64 data-URL），**复用** llm 诊断的中性 `DiagnosticResult`；旧 `image_gen.py` 198→**35 SLOC**（全薄），新 `/api/v1/settings/image-gen/{test-connection,generate-sample}` 转 JSON（**envelope `{"ok": bool, ...}` 非 problem+json，恒 200**——同 legacy + llm 诊断契约）。**关键涟漪处理**：`http_client` import **保留在 routes.image_gen**——lift-parity 测试 patch `routes.image_gen.http_client.get`（**共享单例对象的 `.get`**，搬 probe 后仍生效，同 round-6 requests 洞察）；故 `test_webui_image_gen`（17 测试，真文件 + 真探针 patch）**零改动**全过。**无 SSRF gate**（endpoint 读自 config.toml `[image_gen]` 非用户输入，`allow_private=True`），守卫匹配 legacy posture（无内联守卫）→ 快照 94→**96**。新 `test_webui_api_v1_image_gen`（5：no-section ok=False / OpenAI 成功 model_count / FRW credits + X-Api-Key / generate no-section / generate 成功 data-URL）。`spec.py` ceiling 930→**970**。
> - ✅ **medium 浏览器登录 facade 抽取**（`medium_login.py` 的 launch/probe/clear-browser-login，**有状态似 bind**）。**单源搬移**进 `webui_app/api/medium_login_api.py::MediumLoginAPI`（dispatch + 结果分类 + DependencyError/ExternalServiceError 映射），返回中性 `MediumLoginResult(level, message, session_op, logged_in, fragment)`；旧 `medium_login.py` 105→**78 SLOC**（薄路由：apply session + flash render），新 `/api/v1/settings/medium/{launch,probe,clear}-browser-login` 回 **envelope `{level,message,logged_in}` 非 problem+json、恒 200**。**关键有状态语义**：`session["medium_probe_logged_in"]` 发布门控 flag 不进 facade（传输层），facade 回 `session_op` *决策*（set/clear/keep）由各传输 apply（似 BindAPI outcome 捕获）。**安全**：派生浏览器进程 + 删 profile→**内联守卫**（gated `_transport_guards_active()`，似 bind；伪造 Origin→403/ALLOW_NETWORK=1→403）→ 全被 csrf 快照排除→**快照仍 96**（不进 `_GUARDED_ROUTES`：launch/probe 会派生真浏览器、clear 删 profile，似 bind-start 排除，由专测 + global sweep 覆盖）。**搬移涟漪**：3 个 sanitization 测试 patch `routes.medium_login.{launch_login_window,probe_login_status,clear_browser_profile}`→`api.medium_login_api.*`（dispatch 名字绑定改指 facade，路由仍经 `_safe_flash_redirect` 消毒 facade 产出的 message）。零漂移：`test_medium_login_routes`（全套，含 PW 生命周期 + CRLF 消毒）全过 + 新 `test_webui_api_v1_medium_login`（7：launch/probe-in/probe-out/clear 成功 + DependencyError warning + evil-origin 403 + ALLOW_NETWORK 403）。`spec.py` ceiling 970→**1000**。
> - ✅ **全局关键词/排程保存 facade 抽取**（`settings_basic.py` 的 save-target-keywords + schedule，**Settings 后端最后一块**）。**单源搬移**进 `webui_app/api/global_settings_api.py::GlobalSettingsAPI`（keyword 池：strip/去空/>60 拒绝/域内去重 + `save_config(target_anchor_keywords=)`；schedule：解析/clamp(>=0.5h,>=0min) + `_save_schedule_settings`），返回中性 `GlobalSettingsResult(level, message, error_class, fragment)`；旧两路由改薄（form-indexed 解析→facade→flash），新 `/api/v1/settings/{keywords,schedule}` 转 JSON/problem（invalid_request→422 / persistence_failure→502）。**单源边界**：facade 收中性 `pools: {域名: [原始关键词行]}`（form textarea splitlines vs JSON list 由各路由适配），校验/去重/落盘单源。**无内联守卫**（全局 config 写 config.toml/schedule-settings.json，非 0600 凭证，同 oauth/诊断姿态）→ 快照 96→**98**。零漂移：`test_webui_settings_routes`（302 redirect parity，不 patch 内部→零涟漪）全过 + 新 `test_webui_api_v1_global_settings`（6：keywords ok/去重/>60→422/空 noop + schedule ok/非数→422）。`spec.py` ceiling 1000→**1040**。⚠️ 注意 `save_config` 规范化域名 key（去尾斜杠），契约测试断言值非 key。**Settings 后端至此全部完成**（凭证/bind/oauth/llm/image-gen/medium/全局配置）。
> - 🔨 **Settings 整页 SPA（进行中，逐段攒）**：`/settings`（21 分片/2537 行模板 + 696 行 settings.js）太大、单轮不可审→**逐段建 Vue 页，navItem 暂留 legacy `href`（无 UX 回退：旧页仍全），攒够 section 再 flip `to`**。
>   - ✅ **段 1：页骨架 + 全局配置段**（keyword 池 + 排程）。后端补 **GET hydration**：`GlobalSettingsAPI.{get_keywords,get_schedule}` + `GET /api/v1/settings/{keywords,schedule}`（keyword GET 回 `{targets, pools}`——targets = blog-id ∪ 已配置池域名，同 legacy `all_targets`；schedule GET 复用 request schema）。前端 `frontend/src/api/settings.ts`（getKeyword/saveKeyword/getSchedule/saveSchedule）+ `pages/Settings/SettingsPage.vue`（StateBlock 四态 + useQuery hydrate→reactive 本地副本 + save→toast + 422 detail→warning toast）+ router `/settings`（**navItem 未 flip**）。`spec.py` ceiling 1040→**1060**（GET 加入，SLOC 1054）；快照 **98 不变**（GET 非 mutating）。验证：后端 131 + 宽扫 2180 + 新 `test_webui_api_v1_global_settings`（8，含 GET 往返）；前端 vitest **83**（新 `SettingsPage.spec` 4）+ vue-tsc exit 0。
>   - ✅ **段 2：AI 整合卡**（LLM + image-gen，一表单一 save）。后端补**唯一缺口=redaction-safe GET hydration**：`LlmSettingsAPI.get_config()` + `GET /api/v1/settings/llm-config`——**两个密钥（api_key/image_gen_api_key）只回 `has_*` bool、绝不回 key**（PR#139 P3：blank-preserve 配套），其余 save/4 诊断后端早齐。前端 `settings.ts` 加 llm get/save/clear + 4 诊断 wrapper（`diagnostic()` 吞 LLM test-connection 的 400 SSRF envelope→当失败探针显示而非 toast 传输错）+ 独立组件 `pages/Settings/LlmSettingsCard.vue`（连接配置+功能开关 article/image-gen+进阶 temperature/prompt+保存/清除+test-connection/test-generation/image-test/generate-sample 内联结果+图预览）。`spec.py` ceiling 1060→**1070**（SLOC 1068）；快照 **98 不变**（GET 非 mutating；诊断 POST 早已计入）。验证全绿：后端 132（新 GET redaction 测试断言 key 不出现在 body 任何处）+ 宽扫 2190；前端 vitest **88**（新 `LlmSettingsCard.spec` 5）+ vue-tsc exit 0。
>   - 🔨 **段 3：渠道段（逐子刀）**——最大最难，分子刀建。**✅ 子刀 1=渠道状态总览（只读）**：后端 `ChannelOverviewAPI.list_channels()`（`registered_platforms()` − `hidden_from_ui()` ∘ `get_channel_status` + `auth_type` + `app_meta.display_name`，逐渠道 guard）+ `GET /api/v1/settings/channels`（回 `{channels:[{slug,display_name,auth_type,bound,identity,dofollow,last_verify_result,blockers}]}`，无 secret→无内联守卫）。前端 `settings.ts` `getChannels` + 只读组件 `pages/Settings/ChannelsCard.vue`（StateBlock + 每渠道 bound/identity/dofollow/blockers 徽章），SettingsPage 顶部渲染。`spec.py` ceiling 1070→**1090**（SLOC 1088）；快照 **98 不变**。验证全绿：后端新 `test_webui_api_v1_channels`（3，含「无凭证字段泄漏」断言）+ 宽扫 2645；前端 vitest **90**（新 ChannelsCard.spec 2）+ vue-tsc 0。⚠️ 顺手修了**无关的 pre-existing budget drift**（`keepalive_job.py` 被外部缩到 394 SLOC 但 ceiling 仍 450→headroom 56>50，按 policy ratchet 450→430；非本切片功能）。
>   - ✅ **子刀 2=binding 表单（固定凭据 4 型 token/token_fields/paste_blob/userpass）**：核心洞察——credential 写端点 `POST …/<channel>/credential`（ChannelBindAPI 全派发+全校验）**早齐**，前端缺的只是**渲染表单的字段元数据**（label/type/help 原仅存于 Jinja）。后端新 `webui_app/binding_forms.py`（展示元数据；字段 NAME 不在此——从 `credential_service` 派发表读，单一来源，parity 测试钉死）+ `webui_app/api/channel_forms_api.py` `ChannelFormsAPI.list_forms()`（`registered_platforms` − `hidden_from_ui` − `_SKIP_CHANNELS{devto,ghpages,notion}`，仅固定 4 型）+ `GET /api/v1/settings/channels/forms`（**纯静态 schema**：`{forms:[{slug,display_name,auth_type,supports_clear,fields:[{name,label,type,placeholder,help,secret}]}]}`，无状态探测/无 secret/无内联守卫；前端按 slug join 总览的 bound）。实际有表单的 10 渠道：hackmd/mataroa/qiita(token)·gitlabpages/hatena/tumblr/wordpresscom/zenn(token_fields)·substack(paste_blob)·livejournal(userpass)。前端 `settings.ts` `getChannelForms`+`saveChannelCredential` + 通用组件 `pages/Settings/ChannelBindingCard.vue`（按 `type` 渲 input/textarea，secret 永不预填、留空保留；绑定/更新/清除按钮；成功→toast+清空 secret+invalidate 双 query；422→warning 带 detail），SettingsPage 总览卡下渲染。`spec.py` ceiling 1090→**1140**（SLOC 1108=`round_up_to_10(1108+30)`）；快照 **98 不变**（GET 非 mutating）。验证全绿：后端新 `test_webui_api_v1_channel_forms`（7：字段名 parity vs credential_service·无 secret 值·oauth/browser/skip 渠道缺席）+ 宽扫 3092；前端 vitest **95**（新 ChannelBindingCard.spec 5）+ vue-tsc 0。⚠️ Jinja `_settings_binding_token_fields` 仍留自己的 label 副本（U8 删）——字段 NAME 单源 parity 已护，label 为展示性短期重叠。
>   - ✅ **子刀 3=Medium 卡（渠道动作，非凭据表单）**：核心洞察——浏览器登录三动作（launch/probe/clear）+ OAuth-token 清除的写端点**早齐**（第 8 轮迁 medium 浏览器登录 + OAuthAPI clear-medium），唯一缺口=状态 GET。后端 `MediumLoginAPI.status(probe_logged_in)`（**flask-free**：session 旗标由传输传入，似 session_op seam；复用 `_get_medium_browser_status` + `load_medium_token`）+ `GET /api/v1/settings/medium/status`（回 `{browser:{state,playwright_installed,profile_has_cookies,cookies_age_days,singleton_lock_present,logged_in},oauth_token_exists}`，纯文件/import 读、无 secret、无内联守卫；action POST 保留内联守卫）。前端 `settings.ts` `getMediumStatus`+`launch/probe/clearMediumLogin`+`clearMediumOauth` + `pages/Settings/MediumCard.vue`（状态徽章 + 三动作 → `level`→toast severity（danger→error）+ refetch；OAuth-token 存在 → 清除（window.confirm）；**Integration-Token 块留 legacy 页**——Medium 停发新 token、不值得再迁两个写端点）。`spec.py` SLOC 1108→**1128**（ceiling **1140 不变**，headroom 12）；快照 **98 不变**（GET 非 mutating）。验证全绿：后端 `test_webui_api_v1_medium_login` +4（状态 shape·session 旗标·无守卫·无 token 值泄漏）= 11 + 宽扫 2358；前端 vitest **100**（新 MediumCard.spec 5）+ vue-tsc 0。
>   - ✅ **子刀 4=velog 卡（渠道动作）**：legacy `/api/velog/{login,status}` 早已 JSON（非 Jinja），但未版本化——按「搬移非复制」迁到 `/api/v1/settings/velog/*`。后端新 `webui_app/api/velog_login_api.py` `VelogLoginAPI`（spawn `velog-login` detached 子进程 + `error_code`→`_MESSAGES` 映射**搬出 legacy 路由**；`status()` 委托单源 `_get_velog_status`）+ legacy `/api/velog/login` 路由改薄委托（保 200/500 契约）+ 新 `/api/v1/settings/velog/{status(GET 无守卫),login(POST 内联守卫——派生进程似 medium)}`（login 回 `{ok,message,error_code,log_path}` envelope **恒 200**）。前端 `settings.ts` `getVelogStatus`+`velogLogin` + `pages/Settings/VelogCard.vue`（6 态徽章 err/warn/ok/fresh/cap_reached/permission_denied + guide 提示 + 配额 count/cap + 绑定/重新绑定→spawn→`ok`?success:warning+refetch），SettingsPage 渲染。`spec.py` ceiling 1140→**1200**（SLOC 1166=`round_up_to_10(1166+30)`）；快照 **98 不变**（login 内联守卫排除、status GET 非 mutating）。验证全绿：后端新 `test_webui_api_v1_velog`（6：状态 shape·无守卫·envelope·失败 200+error_code·forged-origin 403·ALLOW_NETWORK 403）+ legacy parity（3）保留 + 宽扫 2303；前端 vitest **104**（新 VelogCard.spec 4）+ vue-tsc 0。⚠️ `spawn_browser_login` 用 lazy import 故 legacy 测试 patch `services.browser_login.spawn_browser_login` 仍生效。
>   - ✅ **子刀 5=blogger 卡（OAuth 凭据半）**：复用既有 `OAuthAPI`（save_blogger 已迁），扩 `revoke_blogger()`（删 token 文件，**搬出** legacy `settings_basic.py` revoke 路由→改薄委托）+ `blogger_status()`（authorized/client_id/client_secret_set/callback_uri，**client_id 非密、secret 只回 bool**）。新 `GET /api/v1/settings/blogger/status`（无守卫）+ `POST /api/v1/settings/blogger/revoke`（无内联守卫，同既有 oauth 写姿态——config/文件 op 非 0600）。前端 `settings.ts` `getBloggerStatus`+`saveBloggerOauth`+`revokeBlogger` + `pages/Settings/BloggerCard.vue`（状态徽章 + callback_uri 提示 + Client ID/Secret 表单：**确认绑定**=JSON save（留 SPA，secret 留空保留+422→warning）·**使用 Google 帐号登入**=`createElement` 真表单全页 POST 到 **legacy** `/settings/blogger/oauth-start`（OAuth 握手+callback 必 302 留 legacy，带 `csrfToken()` 的 csrf_token）·**撤销**=revoke（confirm））。`spec.py` ceiling 1200→**1240**（SLOC 1205）；快照 98→**99**（revoke 无内联守卫计入；status GET 非 mutating）。验证全绿：后端 `test_webui_api_v1_oauth` +5（状态无 secret 泄漏·revoke 删文件/缺文件/502·literal）=12 + legacy revoke parity（302）保留 + 宽扫 2173；前端 vitest **110**（新 BloggerCard.spec 6）+ vue-tsc 0。⚠️ BloggerCard 加 form 移位了 SettingsPage 的 `findAll('form')[0/1]`→给 keyword/schedule form 加 `data-test` 锚点修稳。
>   - ✅ **子刀 6=Blog ID 映射编辑器（渠道段收尾）**：新 `webui_app/api/blogger_settings_api.py` `BloggerSettingsAPI`（`get_blog_ids()` 回 `cfg.blogger_blog_ids`；`save_blog_ids(mapping)` strip/去空/域去重→`save_config(extra_blogger_ids={})`——清洗规则**搬出** legacy `save-blog-ids` 路由，单源）。专属 facade（blog-ID 路由 ≠ OAuth 凭据）。新 `GET/POST /api/v1/settings/blogger/blog-ids`（POST 无内联守卫，同 blogger 写姿态；复用 oauth.py `_render`），legacy 路由改薄委托（`domain[]`/`blog_id[]` 表单 list→dict→facade，保 302）。前端 `settings.ts` `getBlogIds`+`saveBlogIds` + `pages/Settings/BlogIdsCard.vue`（动态增删行：每行 domain+blog_id，新增/删除/保存；存时客户端也丢空行，服务端再清洗）。`spec.py` SLOC 1238（**ceiling 1240 不变**，headroom 2）；快照 99→**100**（POST blog-ids 无内联守卫计入；GET 非 mutating）。验证全绿：后端新 `test_webui_api_v1_blog_ids`（6：round-trip·strip/去空·替换·清空·缺 body）+ legacy save-blog-ids parity（302×2）保留 + 宽扫 2310；前端 vitest **115**（新 BlogIdsCard.spec 5）+ vue-tsc 0。**🎉 渠道段（段 3）全部 6 子刀完成**：总览·binding 表单·Medium·velog·blogger OAuth·blog-ids。
>   - ✅ **段 4=页面 chrome（侧栏导航 + 概览摘要）**：legacy 用「侧栏+pane 切换」布局，SPA 是滚动卡片页、功能已齐——chrome 真正需要的是**长页可导航 + 顶部概览**，非逐像素复刻 tier 分组/cold-start（onboarding 锦上添花，跳过）/banner（image-gen 快照，与 LlmSettingsCard 重叠，跳过）。新 `pages/Settings/SettingsSidebar.vue`（sticky 左栏：概览摘要 `N/M 渠道已绑定` + 有阻断项警示，**复用** `['settings','channels']` query 零额外请求；9 个分区 jump 链接 `scrollIntoView`）。SettingsPage 改 2 列 grid（180px + 1fr，窄屏栈叠+隐藏侧栏）+ 各区加锚点 id（`sec-channels/binding/medium/velog/blogger/blogids/keywords/schedule/ai`）+ 页头文案改为「全部在此页管理」+ keyword 空态指向页内 Blog ID 区（不再指旧页）。**纯前端、零后端、复用既有 GET**。验证全绿：前端 vitest **118**（新 SettingsSidebar.spec 3：分区链接·概览计数·scrollIntoView spy）+ vue-tsc 0。
>   - ✅ **段 5=flip + 收尾**：`navItems.ts` 的 `设置` 从 legacy `href:'/settings'`→migrated `to:'/settings'`（移入 migrated 块）→设置页正式成主入口（RouterLink，不刷新；SPA 路由早建可达）。收尾去除翻后过期/变错的页内指回提示：`ChannelsCard`「绑定/改凭证暂在旧设置页，正逐段迁入」→「见下方凭据绑定及动作卡」；`ChannelBindingCard`「Blogger·Medium·velog 暂在旧设置页」（**已变错**——三卡就在本页下方）→「见下方各自动作卡」；`SettingsPage`/`router` 头注释改「已完成·现为主入口」。**刻意保留** `MediumCard` 的 Integration Token→旧页提示（真·未迁移 legacy-only 功能，旧 `/settings` U8 前仍在，正当逃生口）。**纯前端、零后端、零 spec/快照改动**；两测试（navItems/SideNav 动态计数 migrated/legacy）flip 后仍有 3 个 legacy 项（健康/权益账本/保活），照过。验证全绿：前端 vitest **118**（26 文件不变）+ vue-tsc 0。**↓ 下一步=U8 退役 `/ce:*`+Jinja**（含 legacy `/settings` 21 分片 + settings.js + 已改薄的 legacy 路由 + `asset_version`/旧 mtime 缓存），再 U9 文档收敛。
> 已迁导航页（8）：发布工作台 `/`、监控 `/monitor`、历史 `/history`、草稿 `/drafts`、站点 `/sites`、排程 `/schedule`、批量 `/batch-campaign`（+ 全局 shell）。Settings 页 UI 待下一轮。
>
> **U7 两处一级护栏（随页推进维护）**：(1) `webui_app/api/v1/spec.py` 声明式 OpenAPI 契约按端点组线性增长，越 500 canary；`monolith_budget.toml` ceiling 现 **1240**（452→1205 SLOC，已含 sites/schedule/campaigns/profiles + **Settings 后端全部**：凭证写 channel-token/notion/通用 channel-credential + bind 四路由 + oauth 两路由 + blogger status/revoke/blog-ids + llm-config + llm 诊断对 + image-gen 诊断对 + medium 浏览器登录三路由+状态 + velog 状态+登录 + 全局 keywords/schedule 两路由 POST + SPA settings 页读侧 GET hydration（keywords/schedule/llm-config redaction-safe + 渠道绑定状态总览 + 渠道 binding-form schema + medium 卡状态 + velog 卡状态 + blogger 卡状态 + blog-ids）；受 `SEED_HEADROOM_MAX=50` 约束，后续 settings section 补 GET 会再 bump）。(2) `test_csrf_only_route_count_snapshot` 71→**100**：U5–U7 的 `/api/v1` mutating 路由（pipeline 5 + history 4 + drafts 5 + sites 2 + campaigns 1 + profiles 2 + oauth-credential 2 + blogger-revoke 1 + blogger-blog-ids 1 + llm 诊断 2 + image-gen 诊断 2 + 全局 keywords/schedule 2）计入（自 U5 潜伏 stale，因 gating lane 非该 full-suite 安全单测）。**非新漏洞**：全由 app 级 `_global_origin_guard` 运行时覆盖（`test_global_guard_covers_every_mutating_route` 绿）、且为 config/state JSON 写或操作员配置探针，非 `0600` 凭证写。**内联守卫家族**（0600 凭证写 channel-token/notion/channel-credential/bind + **medium 浏览器登录三路由 + velog 登录**——派生进程/删 profile）保留 inline `_check_bind_origin_or_abort`→被快照排除（故未计入）。

**Goal:** 逐页（或小簇）迁移 history/drafts/settings/sites/batch/batch_campaign/schedule/profiles 等；把剩余 ~24 HTML-only + ~15 dual-mode 路由转 `/api/v1`；测试随路由按决策树迁移。

**Requirements:** R1, R2, R4, R6

**Dependencies:** U5, U6

**Files:** 多——每页一 PR：Convert 对应 `routes/*.py`、Create `frontend/src/pages/<page>/*`、迁移/拆分对应 `tests/test_webui_*.py`

**Execution note:** 每页特征化先行；每 cutover PR 同带「路由改 + 旧断言转换/删 + 新契约测试 + 新组件测试」，套件全程绿。**⚠️ U7 是按权重严重欠拆的最大单元（adversarial 审出）**：模板实为 ~44 个 `.html` = ~19 页 + **~25 个 settings 分片/宏**（`_settings_*.html`、`_channel_card_macro.html` 等）。Settings 是十几个互相依赖的分片 + 文档化的「Jinja macro 不继承 context → CSRF 绑定 403」陷阱，**是最难的单页、不是收尾扫尾项**——应把 Settings 拆为 U7 的独立子单元/独立 PR，并把 macro/CSRF 绑定隐患列为一级风险（**在传输层测**，不靠 Jinja render 测试）。

**Approach:** 高 churn 页先（已在 U5/U6）、稳定页后；追踪「% 路由已迁移」作一级指标，每个 Jinja 路由删除是有主、有期的交付。

**Test scenarios:**
- 每页 Happy path：契约 + 组件测试。
- Error/Edge：settings 绑定 CSRF 在传输层验证（403 不回归）；表单校验拒绝转契约测试。
- 决策树：view-only 断言迁组件测试后删；业务规则断言转契约测试；both 必 split。

**Verification:** 所有页面在 `/app` 由 Vue 渲染、数据全走 `/api/v1`；覆盖 ≥80%。

- [ ] **U8：退役 Jinja 服务端渲染路径**

**Goal:** 所有页 100% 落 SPA 后，删除 Jinja 模板 + 服务端渲染路由 + `asset_version` + Bootstrap head 脚本 + `page_data` islands；SPA 成默认 UI（`/` → SPA）；移除 flag 门控；删除已迁移的 HTML golden-master 测试。

**Requirements:** R4

**Dependencies:** U7

**Files:** Delete 大部分 `webui_app/templates/*`、`base.html`；Prune `webui_app/routes/*` 的渲染路由；Modify `webui.py`（根服务 SPA）；更新 `monolith_budget.toml`/`complexity_budget.toml`（移除模板相关项，同 PR 写 rationale）

**Approach:** 删除即兑现价值；确认无业务规则丢失（规则已在 U5–U7 转契约测试）。

**Test scenarios:**
- Integration：全量套件绿、覆盖 ≥80%（业务规则全在契约/组件测试存活）。
- Edge：根路径 `/` 直达 SPA；旧 Jinja 路由 404/移除无残链。
- 反向验证：grep 确认无 `render_template` 残留于业务路由。

**Verification:** 无 Jinja 渲染路径残留；SPA 为默认；budget 测试绿。

> **U8 进度（逐段退，用户拍板「先退 legacy 设置页」+「3 逃生口现在迁入 SPA、不留极简逃生页」）：**
> - **退役盘点（3 探子实测）**：flip 后 navItems 仍剩 3 legacy 项（健康/权益账本/保活，仅 `/monitor` 只读聚合、无替身详情页+动作）+ 站外 command-center/optimization/survival/pipeline-dashboard/pr-queue/campaign-progress 均未迁——**「全退 Jinja」现做不到（丢功能）**，故逐段。删 legacy `/settings` 前要补的 SPA 凭据覆盖：**devto·ghpages·notion（v1 后端全齐）+ medium-IT（无 v1、Medium 停发）**；Blogger OAuth 按钮 SPA 已有（全页 POST），删页那轮只需把 `oauth-callback` 重定向从 `/settings`→SPA。必保留：`base.html`+共享层（lib/ui/css）、CSRF/Origin 守卫（E3 顺序）、`spa.py`。会破测试：`test_settings_binding_partial`/`test_history_template_rendering`/`test_webui_regen_body`/`test_webui_health_geo_panel`（render legacy 分片/断言 `/ce:*`）。
> - ✅ **U8 子刀 1=Notion 凭据卡**（2026-06-22）：token-paste 逃生口里最独立的一个。**后端唯一缺口=状态 GET**（写端点 `POST /api/v1/settings/notion-token` U7 安全核心早齐）：`GET /api/v1/settings/notion/status` 复用 `config.tokens.load_notion_token`，回 `{configured:bool, database_id}`——**integration_token 绝不回**（redaction，测试钉死），非密 `database_id` 回供显示；无 secret→无内联守卫。前端 `settings.ts` `getNotionStatus/saveNotionToken/clearNotionToken`（复用 `CredentialSaveResult`）+ 新 `pages/Settings/NotionCard.vue`（状态徽章 + 双字段表单：integration_token 密文不预填 + database_id 非密预填；**Notion 无 blank-preserve**——两字段都必填、留空→422 warning，同 legacy；确认绑定/清除（confirm）→toast+invalidate notion-status&channels 双 query）。SettingsPage 加 `sec-notion`（Blogger 后 BlogIds 前）+ SettingsSidebar SECTIONS 加 Notion（9→10）。`spec.py` ceiling 1240→**1290**（SLOC 1258=`round_up_to_10(1258+30)`，headroom 32）；快照 **100 不变**（status 是 GET、notion-token POST 早已计入）。⚠️ **openapi 必须用 `PYTHONPATH=src python scripts/gen_openapi.py` 重生成**——裸 python 的 `app_version()` 读到 0.5.0、测试/CI 环境读 0.3.0，版本号会漂导致 `test_committed_openapi_spec_is_not_stale` 失败。全绿：后端新 `test_webui_api_v1_notion`（4：未配置·配置往返·无 integration_token 泄漏·GET 无守卫）+ api_v1 宽扫 196；前端 vitest **123**（新 NotionCard.spec 5）+ vue-tsc 0。
> - ✅ **U8 子刀 2=devto/ghpages 折进 SPA**（2026-06-22）：这俩在 `ChannelBindAPI._SKIP_CHANNELS`（其不派发、走专属 token-paste 路由 `/channels/<ch>/token`），但 auth_type（devto=token、ghpages=token_fields-单字段）正是 ChannelBindingCard 已会渲的型——**唯一差别是 save 端点**，故**折进同卡**而非新卡。后端 `channel_forms_api.list_forms()` 不再跳过整个 `_SKIP_CHANNELS`、改只跳 `_DEDICATED_CARD_CHANNELS={notion}`（notion 有专属 NotionCard），并给每 form 加 `save_via` 判别符（=`"token" if slug in (_SKIP_CHANNELS−{notion})={devto,ghpages} else "credential"`）。**陷阱**：不能用 `_PASTE_ROUTE_CHANNELS` 当判别符——它含**所有** token 渠道（hackmd/mataroa/qiita 也在内），会把已正常走 `/credential` 的渠道误翻到 token 路由；正确源是 `_SKIP_CHANNELS−{notion}`。`binding_forms.py` 加 ghpages 的 GitHub PAT presentation（devto 用通用 `token` 项）。`schemas.py` `ChannelFormSchema` 加 `save_via`（→openapi 重生成，**仍须 `PYTHONPATH=src`**）。前端 `settings.ts` `ChannelBindingForm` 加 `save_via` + 新 `saveChannelToken`（同 body 形，端点读 `token`/`clear` 忽略多余 `auth_type`）；`ChannelBindingCard.submit()` 按 `save_via` 选 `saveChannelToken` vs `saveChannelCredential`（一行三元）。**零新路由**（复用既有 token 端点）→快照 100 不变、spec.py SLOC 未动→budget 不变。全绿：后端 `test_webui_api_v1_channel_forms` 更新（absent 去 devto/ghpages 留 notion + 新增 save_via=token/credential 断言）+ binding 宽扫 132；前端 vitest **124**（ChannelBindingCard.spec +1：token-route 渠道走 saveChannelToken）+ vue-tsc 0。
> - ✅ **U8 子刀 3=medium Integration-Token 弃用**（2026-06-22，**用户拍板「弃用：删 UI、不建后端」**）：关键事实——medium-IT 是 `config.toml` 明文字段 `cfg.medium_integration_token`（`save_config(cfg, medium_token=)`，**非 0600 密钥**），Medium 2023-03-02 归档 API/停发 token，**发布路径仍读已存在的值**（`helpers/contexts.py`：`token = _it_val or cfg.medium_integration_token`）→ 删 UI 不影响老 token 继续发布。删 legacy `/settings/{save,clear}-medium-token` 两路由（settings_basic.py）+ legacy 片段 `_settings_channel_medium.html` 的 Block 3（IT `<details>`，保留 Block 4 OAuth 说明）+ SPA `MediumCard.vue` 指回提示。**零后端新建**。测试：删 `test_webui_settings_routes` 3 个 medium-token 测试 + `test_webui_request_cache` 2 个 spec + `test_webui_core_routes::test_settings_html_contract` 去 form_action_urls 2 条（12→10）/medium_urls 2 条/dom_ids（mediumTokenInput·eyeIcon）/js_handlers（toggle-token，4 个）。**快照 100→98**（删 2 条 unguarded legacy config-write 路由；断言是 `<=`，收紧上限保持精确 + 减量注释）。settings.js 里 toggleToken/mediumTokenInput 裸引用是 dead code，随 settings.js 在子刀 4 删。全绿：后端受影响 116 passed + medium/settings 宽扫 337；前端 vitest **124**（MediumCard 提示+样式删，无 spec 改）+ vue-tsc 0。
> - **⚠️ 阻断点发现（删 legacy 前必读）**：SPA 是 **flag-gated**（`BACKLINK_PUBLISHER_SPA` 默认 `"0"`）→ 默认配置下 `/app/*` 404、整个 SPA inert、用户看 legacy Jinja（含 legacy 导航）；那次 navItems flip 只改 SPA 内部导航、仅 flag ON 可见。`/`、`/settings` 等 legacy 路由无条件渲染，无「SPA 成默认」机制，`spa_dist` 是 6/18 旧构建（已过期）。**故删 legacy 设置页前必须先让 SPA 成默认 UI**（plan U8 写的「移除 flag 门控」）。**用户拍板「先翻 SPA 成默认（独立一步），下轮再删」**。
> - ✅ **U8 子刀 4=翻 SPA 成默认（flag）**（2026-06-22）：`spa.py::_spa_enabled()` 默认 `"0"`→**默认 ON**（`os.environ.get(...,"1") != "0"`，`=0` 为 opt-out）→ `/app/*` 默认服务 SPA，legacy 页留在各自 URL 作 dual-stack 逃生口。**`/`→SPA 落地重定向刻意不做**（15 个测试文件 GET `/` 取 legacy index，重定向破一大片、属删除阶段）。SPA 蓝图路由始终注册（flag 只 gate view 行为）→ 路由计数/快照不变。唯一受影响测试 `test_webui_spa_catchall::test_app_404_when_flag_off`→改 `test_app_404_when_flag_explicitly_off`（显式 `=0`）+ 新增 `test_app_serves_by_default_without_the_flag`。全绿：webui 宽扫 683。**⚠️ deploy 必须 rebuild `spa_dist`（`cd frontend && npm run build`）**——否则默认服务 6/18 旧 bundle（缺 Notion/devto/ghpages 等近期卡）；spa_dist 是构建产物、不在 agent 改动面，未提交重建。
> - **↓ U8 剩余=子刀 5=删 legacy 设置页**（SPA 已默认 ON，可删）：删 `settings.html`+~20 分片+`settings.js`+3 classic JS（bind_channel/channel-binding/fetch_json）+`settings.css`+superseded `/settings/*` 旧路由（保留 blogger `oauth-start`/`oauth-callback` 握手）+ 把 `oauth-callback` 重定向 `/settings`→SPA（`/app/settings`）+ 删会破的 legacy-render 测试（`test_settings_html_contract`/`test_settings_binding_partial` 等）+ 清 settings 专用 context-processor。**大、不可逆→先列精确删除清单给用户确认再删**。再后续：`/`→SPA 落地重定向（连同退 legacy index）、退监控类未迁页（健康/权益账本/保活/command-center 等）、清 `asset_version`。

### Phase 3 — 仓库/文档/运营收敛（用户要的「整理」）

- [ ] **U9：文档与仓库收敛 + 部署/CI 固化**

**Goal:** 更新 `ARCHITECTURE.md`/`AGENTS.md`/`webui_app/AGENTS.md`/`CLAUDE.md` 反映 API + SPA 新架构；以「有构建前端规则 + 反铁律→Vue 映射」**正式取代**「零构建铁律」；收敛冗余 `OPTIMIZATION_*_REPORT.md`（4 份 → distill/归档）；记录 R9 延后触发条件。

**Requirements:** R8, R9

**Dependencies:** U8

**Files:** Modify `ARCHITECTURE.md`、`AGENTS.md`、`webui_app/AGENTS.md`、`CLAUDE.md`；Archive/distill `OPTIMIZATION_REPORT.md`/`OPTIMIZATION_COMPLETE_REPORT.md`/`OPTIMIZATION_PHASE3_REPORT.md`/`FINAL_OPTIMIZATION_REPORT.md`；Create `docs/solutions/` 一条本次重构的 learning（含 R9 trigger）

**Execution note:** 这是用户要的「整理」——用收敛姿态（distill 而非加 roadmap，遵循 `user-doc-convergence-pref`）。任何 `src/` 包重排（本轮非目标）若发生，跑 `python -m` smoke（`tests/test_cli_layout.py`）。

**Patterns to follow:** `v050-core-convergence` 的收敛做法；`2026-06-05-lite-accepted-deferrals.md` 的 deferral 格式。

**Test scenarios:** Test expectation: none —— 文档/收敛单元，无行为变化；唯一硬约束是模板移除后 `monolith`/`complexity` budget 测试与全量套件保持绿。

**Verification:** 文档与代码现实一致；零构建铁律已被新规则取代并记录；冗余报告完成收敛；R9 trigger 入库。

## System-Wide Impact

- **Interaction graph:** `create_app()` 的 6 个 context-processor + 2 个 `before_request` 守卫是跨切面核心。新增 v1 blueprint 不得改 CSRF 守卫顺序（`test_webui_csrf_ordering`）；`asset_version` 在 U8 退役（被 Vite content-hash 取代）。
- **Error propagation:** CLI subprocess（`publish-backlinks`）的 `__BLP_ERR__` 类型化信封 → `PipeResult.error_class`/`exit_code` → `/api/v1` problem+json → 前端 `classifyError` 分类 UI。这条链是错误传播主干，迁移须保持端到端。
- **State lifecycle risks:** 进程内 APScheduler + Playwright + SQLite（`events.db`/`dedup.db`）仍归后端单实例所有——单源不改这点；publish 幂等（`dedup.db` 单飞语义）是正确性关键，迁移不得旁路。
- **API surface parity:** 迁移期旧 Jinja 视图也消费同一 `/api/v1`（杜绝双真相）；`make test-js` 的 7 个 `.mjs` 测试在 JSON 契约稳定时存活。
- **Integration coverage:** 单源 CSRF/origin 守卫、publish 进度轮询、监控派生数据单一真相源——这些跨层行为靠契约测试 + 薄 Playwright E2E 守，不靠组件 mock。
- **Unchanged invariants（蓝图爆炸半径保证）:** `src/backlink_publisher/` CLI 管线、adapter registry、`schema.py`、状态存储 schema、全局 CSRF/origin 守卫语义、loopback 默认 bind、凭证仅服务端——**本计划显式不改**。新 API 是这些不变量之上的新表达层。

## 单源威胁模型（Single-origin Threat Model）

> security-lens 审出：原计划把安全叙事完全寄托在「单源砍掉跨源安全工程」，把整张安全清单推给 R9——但**单源模型自身有三个本轮就存在的暴露面**，必须显式列入并在对应单元加验收，不能只当成「守卫顺序别破」。

- **威胁 1（最可能）— bundle XSS 驱动凭证/发布 POST。** 从 Jinja 字符串拼 DOM 转到 Vite 打包的 JS 依赖树，新增供应链 + `v-html` 执行面；而 SPA 的 fetch 会自动带 CSRF header，一旦 XSS 即可发起 bind/publish。**缓解（入 U3 + Documentation）**：SPA `index.html` 下发 CSP（至少 `default-src 'self'; script-src 'self'; frame-ancestors 'none'`）+ `X-Frame-Options: DENY` + `X-Content-Type-Options: nosniff`（**注意：本仓当前零安全响应头，这是净新增**）；锁 lockfile + CI `npm audit` 门。
- **威胁 2（最高影响）— DNS-rebinding 经未守卫的 bootstrap GET 读 CSRF token。** 现有 `_global_origin_guard` **只检查 POST/PUT/PATCH/DELETE**；而 SPA 的 `index.html`、`/api/v1/app-config`、新增的 **`/api/v1/csrf-token`（GET）** 都走 GET，守卫不覆盖。新的 token-披露 GET 端点是本轮净新增暴露面。**缓解（入 U2 + 立为不变量，与 CSRF-ordering 并列）**：对敏感 GET 端点（`/api/v1/csrf-token`、`/api/v1/app-config`）加 GET 时的 origin/Host 校验，并加一条「rebinding 页无法跨源 GET 读取 bootstrap/token」的测试。
- **威胁 3（最隐蔽）— HTML→JSON 转换时静默丢失 per-route 凭证守卫。** `token_paste` / `channel_bind_save` / `bind`（写 `0600` 凭证文件、`bind.py` 自带 `_enforce_loopback` / `_refuse_when_allow_network`）在 U5/U7 转 `/api/v1` 时，契约测试只验 schema、**不验这些守卫还在**。**缓解（入 U7 Execution note）**：凭证写端点转换后加安全回归测试——伪造 Origin 仍 403、`ALLOW_NETWORK=1` 仍拒、文件仍 `0600`。
- **CI 隔离（U1）**：Schemathesis live-fuzz **不得**打到带真实凭证/可联网/真状态库的实例——须对临时实例跑（无凭证、`BACKLINK_NO_FETCH_VERIFY`/断网、抛弃式 state store），否则可能触发真实发布或把密钥泄进 CI 日志。
- **测试盲点（feasibility）**：`_global_origin_guard` 在 pytest 下被禁用——上述 origin/rebinding 不变量**无法靠 Python 单测验证**，须由 Playwright E2E（真 Origin header）覆盖。

## Risks & Dependencies

| 风险 | 缓解 |
|------|------|
| 与审计「分离已健康、瓶颈是收敛」冲突——做了高成本低 ROI 的事 | 单源选择砍掉网络化成本；价值锚定在前端可维护性 + 契约化（非网络化）；R9 网络化显式延后带 trigger；Problem Frame 正面回应审计 |
| 契约漂移（服务端测实现不测契约，SPA 突然崩） | OpenAPI 3.1 单一 spec + Spectral/oasdiff（破坏门）/Schemathesis（一致性）作 required CI check；前端 MSW 从同一 spec 生成 |
| 测试迁移误删编码业务规则的 HTML 断言 | 决策树强制 both→split、永不折叠成 delete；特征化 golden master 先 pin 行为；每 cutover PR 套件全程绿、覆盖不掉 |
| 单源 CSRF/origin 守卫被破坏（守卫顺序 / 每调用现读 token） | 保留全局守卫 + 顺序不变量测试；CSRF 拦截器每调用读、永不缓存进 store；Vite `changeOrigin:true` 让 dev 也走同源 |
| budget 天花板批量击穿（模板删除 / 新文件） | 逐页增量（非大爆改）天然分散；超 budget 同 PR 写 ≥80 字 rationale；U8 集中处理模板移除的 budget 调整 |
| 迁移「永不收尾」（双栈双维护拖长） | 追踪「% 路由已迁移」一级指标；每个 Jinja 路由删除是有主、有期、flag 门控的交付；strangler 不冻结功能 |
| 版本偏移（旧 SPA bundle 调到已变 API） | additive-only + `/api/v1`；单源 + content-hash + 保留旧 hashed 资源；后端先部署 |
| publish 无 task-id 致进度反馈降级 | U5 时按后端实况：小改加 task-id 或降级忙碌态（沿用 redesign 先例），并记入计划 |
| 净新增 Node/Vite 构建 + CI lane 对小团队的运维负担 | 单源 Flask 托管 dist（一个部署目标）；契约门自动化；R9 之前不引第二部署面 |

## Phased Delivery

- **Phase 0（U1–U3）**：契约骨架 + 前端脚手架。无用户可见切换，纯基座；可独立验收（契约门绿 + `/app` shell 起得来）。
- **Phase 1（U4–U6）**：迁 shell + 最高价值两块（发布工作台 + 监控看板）。这是价值兑现的拐点——核心流程已在新前端。
- **Phase 2（U7–U8）**：逐页清扫 + 退役 Jinja。`/app` 成默认、服务端渲染路径消失。
- **Phase 3（U9）**：文档/仓库/运营收敛（用户要的「整理」），并把 R9 网络化以 trigger 入库。

**收敛护栏（adversarial 审出，防双栈无限期拖延）：** strangler-fig 在 U3–U8 期间是「双栈双维护、代码比现在更复杂」的状态。设一个 **Phase 1 完成后的检查点**：到点要么承诺推进至 U8 完成，要么把双栈**有意冻结在一个稳定边界**（明确「可接受的永久部分迁移」长什么样、停在哪条路由边界），不让停滞静默变成无限期双维护。「% 路由已迁移」只是度量、不是收敛机制。

## Documentation / Operational Notes

- `CLAUDE.md`/`AGENTS.md` 的「零构建铁律」在 U9 被「有构建前端规则」取代——这是面向未来贡献者的关键文档变更，须显式记录新旧映射，避免后续 agent 误用已废规则。
- 部署：单容器多阶段（Node build dist → Python 运行）；`index.html` `no-cache`、hashed 资源 `immutable`；`VITE_` 变量禁放密钥。
- 可观测性：跨 SPA↔API 传 correlation id（W3C `traceparent`），API 响应回带，便于把前端错误对到后端请求。
- R9（跨源网络化）resume-trigger 入 `docs/solutions/`：出现真实第二客户端 / 远程多人运营时重启，届时执行安全清单。

## Sources & References

- 触发请求：用户 `/ce:plan`「前后端分离 + 整理 + 重构」；决策经两轮澄清（单源同部署 + Vue 3 + 全面重构但 `src/` 不重组）。
- 关联代码：`webui_app/`（routes/api/services/templates/static）、`webui_store/`、`webui.py`、`create_app()`。
- 关联已 shipped 计划：`docs/plans/2026-06-17-001-feat-webui-console-redesign-plan.md`（继承其 tokens）；`docs/plans/2026-06-18-001-feat-v050-core-convergence-plan.md`（收敛姿态）。
- 关键 learning：`docs/solutions/architecture-health-audit-2026-06-01.md`（预判审计，必读）、`server-side-gap-computation-2026-06-05.md`、`typed-error-envelope-over-stderr-truncation-2026-05-27.md`、`app-level-csrf-guard-makes-blueprint-csrf-dead-code-2026-05-27.md`、`standalone-page-vs-retrofit-webui-2026-05-15.md`、`python-m-needs-main-module-after-package-split-2026-05-19.md`。
- 外部：[Strangler-fig (Fowler)](https://martinfowler.com/bliki/StranglerFigApplication.html)、[RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html)、[OpenAPI 3.0→3.1](https://learn.openapis.org/upgrading/v3.0-to-v3.1.html)、[apiflask](https://apiflask.com/)、[Schemathesis](https://schemathesis.io/)、[Vite 8](https://vite.dev/blog/announcing-vite8)、[Vite server.proxy](https://vite.dev/config/server-options)、[Vue Router 5 (InfoQ)](https://www.infoq.com/news/2026/03/vue-router-5/)、[Vue SFC CSS / v-bind()](https://vuejs.org/api/sfc-css-features.html)、[MSW](https://mswjs.io/)、[Playwright Python](https://playwright.dev/python/)。
