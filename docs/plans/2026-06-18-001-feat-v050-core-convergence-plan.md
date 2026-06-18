---
title: "feat: v0.5.0 core convergence — Track A + governance closeout"
type: feat
status: shipped
date: 2026-06-18
origin: docs/brainstorms/2026-06-18-v050-core-convergence-requirements.md
deepened: 2026-06-18
claims: {}  # explicit opt-out — convergence/governance round, no path/SHA locking; satisfies post-2026-05-20 plan-claims gate (plan-check exit 0)
---

# feat: v0.5.0 core convergence — Track A + governance closeout

## Overview

把现役 75 份 brainstorm/plan（43 brainstorm + 32 plan）收敛为「保留 ~7 份 + 归档 ~68 份」，并做完
v0.5.0 真正剩下的工作。分两轨：**Track A（R1–R4 + R10）= 决定能否切版本的代码工作**；
**Track B（R6–R9）= 文档治理，永不阻塞发版**。R5（索引性桥接）已由数据定为延后，不在本轮。

> **plan-level review（2026-06-18）后修正**：原计划把 R1 当作"写新 catalog YAML"——验码证伪。本仓
> 扩 dofollow 平台的真实机制是**对现有 `uncertain` adapter 跑 canary 翻牌**（见 U1）。R1 因此重写，
> 并对 U5 发版做诚实解耦（U1 不足则 dofollow 扩充延 v0.5.1）。

## Problem Frame

项目瓶颈不是缺想法、不是缺修复（技术债登记表 9/10 resolved、~537 test files、CI 覆盖门 80%），而是
**文档堆积与代码现实脱节、未收敛成可发布版本**。本计划把"真正剩下什么"落成可执行单元，切出 v0.5.0。
（see origin: docs/brainstorms/2026-06-18-v050-core-convergence-requirements.md）

## Requirements Trace

**Track A（ship-blocking）**
- **R1** — 扩 ≥2 个 dofollow 平台：**对现有 `uncertain` adapter 跑 OUR-pipeline canary 翻牌 ≥2 个为 dofollow=true**（非"写新 YAML"，见 U1 修正）。
- **R2** — index / settings 接入统一空态首次引导 CTA（区分三种"空"成因）。
- **R3** — token 一致性收尾 + 验收门（**仅核心流程页** allowlist：裸 Bootstrap 颜色类收口到 `tokens.css`）。
- **R4** — 加载 / 空 / 错误三态一致（统一组件 + 错误分类法）。
- **R10**（Track A 发版门）— 版本号双处 0.4.0→0.5.0 + CHANGELOG 提升（含 compare-link）+ 全量测试绿（覆盖≥80）+ tag。

**延后（不在本轮）**
- **R5** — 索引性→权益账本桥接。数据定为延后（重采样未达 G1 触发 blocked ≥5 或渠道 ≥10%）；实现要点与 resume-trigger 见 origin。

**Track B（非阻塞治理）**
- **R6–R9** — 归档 ~68 份到既有 `docs/_archive/`（含反向引用门）、状态归一（含本计划自身）、referral 墓碑、单一现役索引。

## Scope Boundaries

- 本轮是收敛，不开新战线；Track A 之外不增功能。
- **R1 不写新平台引擎、不做渠道发现**——只对*已存在*的 uncertain adapter 翻牌；翻牌=改 `register()` 一行 `dofollow=`。
- R2–R4 **不改后端业务逻辑 / pipeline / 状态 schema**，纯前端换壳 + 一致性。
- **R3/R4 仅覆盖核心流程页 allowlist**（index、settings、发布工作台、监控看板对应模板+CSS）；其余 ~30 个模板/页 fast-follow，**不在 U3 门的扫描范围**（见 U3）。copilot 页归 fast-follow，本轮不强制。
- **light 主题**：本轮只保证深色一致，不做 light parity（现 CSS 本无 light 实现）。
- **R5 不在本轮**（数据定为延后）。
- 不含代码内 TODO/xfail 债务清扫（已知 2 处 false-green：`linkcheck/language.py:73`、`tests/test_e2e_live_publish_ratio.py` xfail——后者恰守 U1 触及的 publish-output seam，U1 后需复核其仍为 xfail）。
- 不引入打包器 / 框架（zero-build ESM）；不做 WS/SSE 硬需求。

## Context & Research

### Relevant Code and Patterns

**R1 — dofollow 翻牌（canary close-out）**
- 候选机制（已验码）：`docs/discovery/canary-pending.md` 的 close-out 程序——graduation = **把现有 `register()` 的 `dofollow='uncertain'` 翻成 `True`**，不是写新 YAML。
- 现有 uncertain adapter（`publishing/adapters/__init__.py:75-99` import、`:124-287` register）：hackmd_api、mataroa_api、gitlabpages、hashnode_graphql、substack_api、hatena_atompub、rentry_api、wordpresscom_api、writeas_api、notesio_api；txtfyi 同时是手写 adapter + 唯一 catalog YAML。
- 验证 CLI：`cli/verify_dofollow.py`（OUR-pipeline canary）；dofollow 权威分类 `docs/solutions/dofollow-platform-shortlist.md`（5 confirmed 全为 API/OAuth/cookie）。
- 序列化 seam：`publishing/adapters/base.py::to_publish_output` 与 `cli/_resume.py::item_to_publish_output` **已共用** `carry_link_attr_verification`；**但 `_resume.py:65-70` 不持久化 `_provider_meta`——resumed publish 不带 verdict，canary 必须跑 fresh（非 resumed）publish**。

**R2 — 空态**：`static/js/ui/states.js:48 renderEmpty(container,{icon,title,message,actionLabel,onAction})`（仅当 actionLabel+onAction 同传才渲染 CTA，addEventListener 绑定）。范例 `monitor_hub.js:75`。模板 `templates/index.html`、`templates/settings.html`（+ `_settings_sidebar.html`、冷启动 banner 现为 server Jinja）。驱动 `static/js/index.js`、`static/js/settings.js`——**均未 import `ui/states.js`**（已验），须加 import + 锁定渠道/站点列表容器。

**R3 — token**：`static/css/tokens.css` 单一 `:root`（按钮/卡片/状态/表面语义变量齐备）。已 token 化范例 `global_nav.css`。**裸 Bootstrap 颜色类分布（已验码）**：33 个模板含裸 `btn-*`/`bg-*`，绝大多数在 fast-follow 页（health.html=20、pipeline_dashboard=5），核心页极少（index=2、settings=1、monitor_hub=0）。裸色 CSS：index.css（~24 hex + ~76 rgba，其中 ~63 是合理的语义表面叠色，非阴影/渐变——见 U3 sizing）。**无现成裸色 CI 门**；最近范式 `tests/test_webui_static_css_served.py`（`__tier__=unit`，Flask test_client，按 `client.get('/static/css/<file>')` 显式逐文件）。

**R4 — 三态**：`ui/states.js renderSkeleton:32 / renderEmpty:48 / renderError:71`；toast 经 `notifications.js getNotificationCenter()` 或 `CustomEvent('app:notify')` → `ui/toast.js` 单订阅。全三态范例 `monitor_hub.js:61-80`（已验）。现仅 2 个错误分类在用（`加载失败`/`聚合不可用`）。

**R10 — 发版**：`pyproject.toml:7`（`[project]`）+ `:125`（`[tool.towncrier]`）两处 `version="0.4.0"`（**仅此两处可改**）；`CHANGELOG.md:19 ## [0.4.0] - 2026-06-12`、`:182` compare-link `v0.3.0...HEAD`。无 release 工具/脚本（手动）。覆盖门 `fail_under=80`（`pyproject.toml:137` + `ci.yml:134`），被 `tests/test_debt_registry_freshness.py:68-76` 反测保护。**勿动**的 v0.4.0 历史引用：`debt_registry.toml:94`、`tests/test_debt_registry_freshness.py:6,85`、`tests/test_webui_lite_origin_guard_coverage.py:129`、任何 `.claude/worktrees/` 副本。

### Institutional Learnings

- **`grep-dofollow-map-before-shipping-adapter-2026-05-20`**：发任何 adapter 前验 **value** 不只验接线——PR #108 ship 3 个、9 分钟后回滚因全 nofollow。**value 验证是门控步骤**。（→ U1）
- **`dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25`**：verdict 须穿过两条序列化路径——helper 已统一，但 resume 路径不持久化 verdict（见上）。（→ U1 测试）
- **`adapter-silent-exceptions-resolution`**：无静默 `except: pass`、具体异常、`from exc`。（→ U1）
- **`lite-accepted-deferrals-2026-06-05`**：收敛轮"主动延后项 + rationale + resume-trigger"格式范例。（→ R5 延后 / U7）

### External References

无（本仓内部约定充分，未做外部研究）。

## Key Technical Decisions

- **R1 = 翻牌而非新建**（plan-review 修正）：扩 dofollow 的真实机制是对现有 uncertain adapter 跑 canary、翻 `register()` 的 `dofollow=True`。写新 catalog YAML 仅适用于"全新、尚无 adapter 的平台"，而本轮无此现成候选（需渠道发现，越界）。
- **R1 可能零产出 → 诚实解耦发版**：none-auth form-POST dofollow 类别可能无成员（5 confirmed 全 API/auth）。故 U5 发版**不硬卡 U1**：U1 翻成 ≥2 → 计入 v0.5.0；翻不出 ≥2 → 记录 0/1 outcome、dofollow 扩充延 **v0.5.1**，v0.5.0 作为「UI 一致性 + 治理 + 已翻牌数」发版。**是否仍把 R1 放本轮，见待决问题（你拍板）。**
- **R3 门 allowlist 化**：token-compliance 门只扫**核心流程页的固定 allowlist**（模板 + CSS），杜绝把 fast-follow 的 ~30 模板判红。复用既有 **budget-ceiling 范式**（仿 `monolith_budget.toml`/`complexity_budget.toml` 的 per-file ceiling + rationale），**不**新造 `/* token-exempt */` 注释语法。
- **R3 截图复核为 advisory**：硬门=自动"核心页裸类=0"；视觉复核是建议性人工步、不卡 tag。
- **Track B 永不阻塞发版**：R10 只 gate 在 R2–R4 + R1-outcome-of-record；R6–R9 任意时刻落，R6 执行前须用户确认归档方式。
- **R5 延后由数据定**：不在本轮；origin 已用 deferrals 格式记 resume-trigger。

## Open Questions

### Resolved During Planning

- **R1 候选从哪来？** → 现有 uncertain adapter 池（hackmd/mataroa/hashnode/substack/hatena/rentry/wordpresscom/writeas/notesio/txtfyi），跑 canary 翻牌；不是写新平台。
- **R3 验收怎么判？** → CI 断言仅扫核心页 allowlist：模板裸 `btn-*`/`bg-*`=0；CSS 裸 hex/rgb 收敛到 per-file ceiling（budget 范式）。
- **R10 改几处？** → pyproject `:7`、`:125` 两处 + CHANGELOG 新 `[0.5.0]` 头 + compare-link 脚注；勿碰历史 v0.4.0 引用；全量测试绿（覆盖≥80）+ tag。
- **归档目录？** → 既有 `docs/_archive/plans/`（170）与 `docs/_archive/brainstorms/`（93），**不**新建 `docs/plans/_archive/`。

### To Be Resolved by Unit Owner（执行时由对应单元决定，非外部阻塞）

- [U1] 翻哪 2+ 个 uncertain adapter、各自 canary 是否真 dofollow=true —— 取决于 live 探测结果。
- [U3] index/settings/copilot.css 的 ~63 处裸 rgba 叠色：逐条判可 token 化 vs 进 per-file ceiling —— 需逐文件看实际用途（U3 是否大重构取决于此，见 sizing 注）。
- [U4] 错误分类法是否本轮全量定、还是先覆盖核心页实际错误源。
- [U7] 两份 active plan 是否真无未合并残留 —— 须逐 unit 核对 git 后才能安全标 shipped。

## High-Level Technical Design

> *以下展示单元依赖与轨道关系，是评审用的方向性指引，非实现规范。*

```mermaid
flowchart TB
  subgraph A["Track A —— 决定发版（ship-blocking）"]
    U1["U1 · R1 dofollow 翻牌<br/>(canary≥2 uncertain adapter)"]
    U2["U2 · R2 空态首次引导 CTA"]
    U3["U3 · R3 token 验收门(allowlist)+核心页收口"]
    U4["U4 · R4 三态一致(分类法+接线)"]
    U5["U5 · R10 发版门"]
    U3 -. CSS 样式待 U3；JS 可并行 .-> U4
    U2 --> U5
    U4 --> U5
    U1 -. outcome-of-record（≥2 翻牌 或 延 v0.5.1）.-> U5
  end
  subgraph B["Track B —— 治理(非阻塞，可任意时刻落)"]
    U6["U6 · R6 归档~68(反向引用门,用户确认,去重)"]
    U7["U7 · R7 状态归一(含本计划)+补勾选框"]
    U8["U8 · R8 referral 墓碑 + R9 单一索引"]
    U6 --> U7 --> U8
  end
  A -.发版 gate 在 U2-U4 + U1-outcome；B 不阻塞.- B
```

## Implementation Units

### Phase 1 — Track A（ship-blocking）

- [ ] **U1: R1 — dofollow 翻牌（canary ≥2 个 uncertain adapter）** ⏭️ 延后 v0.5.1（需 live operator canary + 凭证，本轮未跑；v0.5.0 已诚实解耦发版，候选清单见记忆 [[v050-core-convergence]]）。

**Goal:** 对现有 `uncertain` adapter 跑 OUR-pipeline canary，翻牌 ≥2 个为 `dofollow=true`（或记录 outcome 并延 v0.5.1）。

**Requirements:** R1

**Dependencies:** 无（含外部 live-canary 步，结果非确定）

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/__init__.py`（把翻牌成功的 adapter 的 `register(..., dofollow='uncertain')` 改为 `dofollow=True`，每个一行）
- Modify: `docs/discovery/canary-pending.md`（按 close-out 程序记录翻牌/留存结果）
- Test: `tests/test_adapter_<slug>_api.py`（对应 adapter 的 dofollow 断言更新）+ seam 测试（见下）
- Reference only：`cli/verify_dofollow.py`、`docs/solutions/dofollow-platform-shortlist.md`

**Approach:**
- 从 uncertain 池选 3–4 个**真有可能 dofollow** 的候选（优先 redirect/permalink 形态明确者；注意 none-auth form-POST 类别可能无成员）。
- **canary 必须跑 fresh（非 resumed）publish**——`_resume.py` 不持久化 verdict。逐个 `verify-dofollow` 真人 live 探测。
- 翻牌成功（dofollow 确证 true）→ 改 `register()` 一行 + 更新 canary-pending。**要求 ≥2 翻牌**；不足则记 outcome、走 U5 的 v0.5.1 延后路径。
- 错误处理：具体异常 + `from exc`，无静默 `except: pass`。

**Execution note:** value 翻牌 + live-canary 是 gating 步骤、非 emergent 测试通过；canary 跑 fresh publish；先于改 register()。

**Patterns to follow:** `docs/discovery/canary-pending.md` close-out 程序；现有 `register(..., dofollow=..., rationale=, referral_value=)` 形态。

**Test scenarios:**
- Happy path：翻牌后 adapter 的 dofollow 断言 = true；`registered_platforms()` 仍含该 slug。
- Integration（防漏 seam）：fresh publish 路径（`base.py::to_publish_output`）verdict **present**；resume 路径（`_resume.py::item_to_publish_output`）在 checkpoint 缺 verification key 时 verdict **absent**（断言当前真实行为，**非**"穿透")。
- Edge：canary 判 nofollow/uncertain → **不**翻牌，记录留存于 canary-pending（防 PR #108 式误翻）。
- Error path：canary 探测 5xx/超时 → 具体异常 + 保留 traceback，不静默吞。

**Verification:** ≥2 个 adapter 翻为 dofollow=true 且 canary 证据在案；seam + adapter 测试绿；若 <2，U5 按 v0.5.1 延后路径切版。

---

- [x] **U2: R2 — 空态首次引导 CTA（index + settings）** ✅ 22 新测试绿、1682 webui 无回归。新锚点 `#indexEmptyState`/`#sidebarChannelsEmpty`/`#historyEmptyFiltered`、`__indexBootstrap.has_channels`。

**Goal:** index/settings 无渠道/无站点时用统一 `renderEmpty` 渲染「去配置」CTA，且正确区分三种"空"。

**Requirements:** R2

**Dependencies:** 无

**Files:**
- Modify: `webui_app/static/js/index.js`、`webui_app/static/js/settings.js`（加 `import { renderEmpty, renderError } from './ui/states.js'`，锁定渠道/站点列表容器）
- Modify（按需）：`templates/index.html`、`templates/settings.html`、`_settings_sidebar.html`（容器锚点 + 让位现 server-Jinja 冷启动文案）
- Test: `tests/test_webui_empty_state.py`（新增，unit）

**Approach:**
- 三种"空"分流：真·零配置→`renderEmpty`+去配置 CTA；有配置但本视图无结果→`renderEmpty`「当前条件无结果」+清筛选（**无**去配置 CTA）；请求失败→`renderError`。
- 严守 anti-rot：`data-action` 委托、无内联 `on*`、无 `window.*` API、`el()`/textContent 不碰 `innerHTML`、`readCsrf()` 每次读 `<meta>`。

**Patterns to follow:** `monitor_hub.js:75 renderEmpty`；`ui/states.js` 的 `el()` 约定。

**Test scenarios:**
- Happy path：无渠道 → 去配置 CTA，点击触发 `onAction`（addEventListener，非 inline）。
- Edge：有渠道但筛选无结果 → 「当前条件无结果」，**无**去配置 CTA。
- Error path：列表请求失败 → `renderError` + 重试，而非空态。
- Anti-rot：无内联 `on*`、CTA 文案经 textContent（沿用 `test_webui_index_js_bootstrap.py` 风格）。

**Verification:** index/settings 零配置态出现正确 CTA；三种空成因各走对组件；anti-rot 测试绿。

---

- [x] **U3: R3 — token 验收门（核心页 allowlist）+ 收口** ✅ 新 `test_webui_css_no_raw_colors.py`（allowlist+per-file ceiling，排除 tokens.css/fast-follow，已验证有效）；tokenize 3/3 核心模板类 + ~52 CSS 裸色；10+127 测试绿。

**Goal:** 建立**仅扫核心流程页**的 token 合规门，并把核心页裸 Bootstrap 颜色类/裸色 CSS 收口到 `tokens.css`。

**Requirements:** R3

**Dependencies:** 无

**Files:**
- Create: `tests/test_webui_css_no_raw_colors.py`（`__tier__=unit`；**内含硬编码 `CORE_FLOW` allowlist**——核心模板 [index.html, settings.html, monitor_hub.html, 发布工作台/看板模板] + 核心 CSS [index.css, settings.css]；**不扫** health.html/sites.html/equity_ledger.html/_settings_* 等 fast-follow）
- Create（可选）：核心页裸色 per-file ceiling 表（仿 `monolith_budget.toml` 格式 + rationale），承接暂不可 token 化的合理叠色
- Modify: 核心模板里的裸 `btn-*`/`bg-*` 类 → token 化样式；`index.css`（样板先行）→ `settings.css` 等核心页 CSS
- Reference：`global_nav.css`（已 token 化范例）、`test_webui_static_css_served.py`（逐文件 client.get 范式）

**Approach:**
- **先立门 + 样板**：门只对 allowlist 断言——核心模板裸 `btn-*`/`bg-*`=0；核心 CSS 裸 `#hex`/`rgba()`（非 `var(--)`）收敛到 per-file ceiling（budget 范式，附 rationale），**不**用新造的 `/* token-exempt */` 注释语法。先拿 index 做样板。
- **再批量**：推 settings + 核心模板。
- **截图视觉复核（advisory，不卡 tag）**：改前/改后截图人工看视觉层级未被抹平——防机械 AI-slop；但硬发版判据是自动"裸类=0"门。

**Execution note:** 先写失败的 `test_webui_css_no_raw_colors.py`（红，仅 allowlist 范围）→ 收口至绿，锁死回退。

**Sizing 注（feasibility 揭示）：** index.css ~76 rgba 中 ~63 是合理语义叠色（非阴影）；逐条判"token 化 vs 进 ceiling"是 U3 的主要工作量——若全要新 token，U3 体量显著上升。先样板一页校准实际成本，再定批量范围（见待决问题）。

**Patterns to follow:** `global_nav.css` 的 `var(--…)`；`test_webui_static_css_served.py` 的逐文件 client.get + tier。

**Test scenarios:**
- Happy path：门扫 allowlist → 核心模板裸类=0、核心 CSS 裸色 ≤ ceiling 时通过。
- Edge：故意在核心模板留一个裸 `btn-primary` → 门转红（证明有效）；fast-follow 模板的裸类**不**触发门（证明 allowlist 生效）。
- Integration：渲染核心页（test_client）断言关键元素用 token 化样式、无 `<style>` 内联。

**Verification:** `test_webui_css_no_raw_colors.py` 绿且只覆盖核心页；核心流程页观感统一深色控台、无 Bootstrap 默认违和；fast-follow 页不被误判红。

---

- [x] **U4: R4 — 三态一致（分类法 + 接线）** ✅ 新 `ui/errors.js`（network/permission/server/unknown 固定文案）；monitor_hub/index/settings 错误态统一走 classifyError；40+ 测试绿。

**Goal:** 核心流程页加载/空/错误态统一到 `ui/states.js` + `notifications.js`，并确立错误分类法。

**Requirements:** R4

**Dependencies:** 软依赖 U3——JS 状态结构 + 错误分类法可与 U3 **并行**写；仅错误卡片的 token 化 CSS 样式待 U3 完成。

**Files:**
- Modify: 核心流程页 JS 驱动（`index.js`/`settings.js`/工作台模块）接 `renderSkeleton/renderEmpty/renderError` + toast
- Test: `tests/test_webui_feedback_states.py`（新增，unit）

**Approach:**
- **先定分类法**：错误态有限集（网络/超时、权限/CSRF、5xx、未知）+ 各类文案模板 + 重试入口统一位置（错误卡内联 `renderError` 重试）；瞬时操作反馈用 toast、区域加载失败用内联。
- 接线沿用 `monitor_hub.js:61-80` 全三态范式。

**Patterns to follow:** `monitor_hub.js` 三态范式；`notifications.js` / `app:notify` 事件总线。

**Test scenarios:**
- Happy path：加载中 skeleton；加载完渲染数据。
- Error path：fetch 抛错 → `renderError` + 重试触发重载；`data.ok===false` → 对应分类文案。
- Edge：空结果 → `renderEmpty`（与 U2 区分成因一致）。
- Integration：失败→重试成功完整序列（skeleton→error→重试→数据）。

**Verification:** 核心页三态长一个样；错误分类一致、有重试；`test_webui_feedback_states.py` 绿。

---

- [x] **U5: R10 — 发版门（0.4.0 → 0.5.0，诚实解耦 U1）** ✅ v0.5.0 已发布（PR #44 → 20855fe6；pyproject :7/:125→0.5.0，历史引用未动；CHANGELOG `[0.5.0]`；annotated tag `v0.5.0`（这仓首个真 tag）；GitHub Release 非 draft）。预飞 11561 passed、`test_e2e_live_publish_ratio` 仍 xfail（U1 延后未碰 publish-output seam，符合预期）。

**Goal:** 定义并执行"可切版本"：版本号、CHANGELOG、全量测试、tag——gate 在 U2–U4 + U1-outcome-of-record，不硬卡 U1。

**Requirements:** R10

**Dependencies:** U2–U4 完成 + U1 有明确 outcome（≥2 翻牌 **或** 记录 0/1 并延 v0.5.1）

**Files:**
- Modify: `pyproject.toml`（**仅** `:7` 与 `:125` → `0.5.0`；**勿** grep-replace 碰历史 v0.4.0 引用）
- Modify: `CHANGELOG.md`（`[Unreleased]` 提升为 `## [0.5.0] - 2026-06-18`，归整 R1–R4 条目；加 `[0.5.0]: …/compare/v0.4.0...v0.5.0` 并把 `[Unreleased]` 重指 `v0.5.0...HEAD`）
- Verify only：`tests/test_debt_registry_freshness.py:68-76`（覆盖门反测须保持绿）

**Approach:**
- **预飞（也作 U1 前置）**：先在 base commit 跑 `PYTHONPATH=src pytest tests/` 记录绿基线 + xfail/xpass 数；U1 触及 publish-output seam，落地后复核 `test_e2e_live_publish_ratio` 的 xfail 仍为 xfail（未 xpass）。
- 三处文本改动（pyproject 双处 + CHANGELOG 头）+ compare-link 脚注；全量测试绿且覆盖≥80；打 tag `v0.5.0`。
- CHANGELOG 须如实记 R5 延后 + resume-trigger，以及（若 U1<2）dofollow 扩充延 v0.5.1。

**Execution note:** 发版动作（tag/推送）属不可逆对外操作，执行前向用户确认。

**Test scenarios:** `Test expectation: none -- 纯版本/文档变更`；唯一断言是既有全量套件 + 覆盖门保持绿（含 `test_debt_registry_freshness` 不被破坏、xfail 计数不变）。

**Verification:** pyproject 两处=0.5.0、历史引用未动；CHANGELOG 有 `[0.5.0]` 条目 + compare-link；全量测试绿（覆盖≥80）；tag 待用户确认后打。

### Phase 2 — Track B（治理，非阻塞发版）

- [x] **U6: R6 — 归档 ~68 份旧文档（反向引用门 + 用户确认 + 去重）** ✅ PR #41：归档 67 份到既有 `docs/_archive/`（34 git mv + 33 git rm 去重前次遗留），反向引用 0 断链，活跃面收敛至保留集。

**Goal:** 把已发布/被取代的 ~68 份文档移入既有 `docs/_archive/`，无断链、无重复。

**Requirements:** R6

**Dependencies:** 无（执行前须用户确认归档方式）

**Files:**
- Move: 可归档项 → `docs/_archive/plans/`、`docs/_archive/brainstorms/`（**不**新建 `docs/plans/_archive/`）
- Touch（按需）：`AGENTS.md` 等——把指向被归档文件的链接改指 `_archive`（含 Markdown-link 与裸 basename 两种形式）

**Approach:**
- **保留清单**：本计划、origin 文档、2 份 active plan、referral 墓碑、config-driven-adapters brainstorm。其余归档。
- **去重**：`config-driven-lightweight-adapters-requirements.md` 现于 `docs/brainstorms/` 与 `docs/brainstorms/_archive/` **均存在**——保留 live 版、删/合并 archived 重复，明确哪份留存。
- **反向引用门（必须）**：每个候选 `grep -rIl <basename> AGENTS.md ARCHITECTURE.md CLAUDE.md docs/ .claude/`；有活引用者保留或同 commit 改指 `_archive`。
- *移动*（git mv）非硬删；**执行方式（移动/硬删/仅标注）先经用户确认**；归档 commit 与代码 commit 分开。

**Execution note:** 不可逆批量动作——执行前用户确认。

**Test scenarios:** `Test expectation: none -- 文档移动`；门为脚本断言：归档后现役引用无指向失效路径（inbound-reference clean）。

**Verification:** 活跃面只剩保留清单；无断链、无重复；其余入 `docs/_archive/`。

---

- [x] **U7: R7 — 状态归一（含本计划）+ 补勾选框** ✅ 本计划 → shipped（U1 延 v0.5.1）；按 git 逐 unit 核对后 `2026-06-16-004`（9/10 unit 合并，Unit 6=R1 延 v0.5.1）与 `2026-06-17-001`（7/7 unit）→ shipped；勾选框补齐。

**Goal:** 归一已完成但仍标 active 的 plan 状态，补漏打的勾选框，并明确本计划自身的终态。

**Requirements:** R7

**Dependencies:** U1/U2 落地后（两份 plan 尾部工作随之 shipped）

**Files:**
- Modify: `docs/plans/2026-06-16-004-...-v050-convergence-...plan.md`、`docs/plans/2026-06-17-001-...-webui-console-redesign-plan.md`（status→shipped/completed）
- Modify: **本计划 `2026-06-18-001`**——Track A 完成后归一为 shipped/completed（避免成为新的孤儿 active；现役共 3 个 active 含本计划）
- Modify: `docs/plans/2026-06-15-004-...`、`docs/plans/2026-06-16-001-...`（这两份 status 已是 completed，仅**补正文漏打的勾选框**，非改 status）

**Approach:** 归一前**逐 unit 核对 git** 确认无真未合并残留（避免把活工作误标 shipped）；用 `lite-accepted-deferrals` 格式确保 R5 延后带 resume-trigger 离场。归一后现役 active 文档收敛到预期集（"5 份保留"须把本计划终态算清）。

**Test scenarios:** `Test expectation: none -- plan 状态元数据`。

**Verification:** 无"完成却标 active"漂移（含本计划已定终态）；勾选框与 git 现实一致。

---

- [x] **U8: R8 + R9 — referral 墓碑 + 单一现役索引** ✅ PR #41：referral-302 plan+brainstorm 加 `<!-- TOMBSTONE -->` 勿复活标记；`docs/active-docs.md` 单一扁平现役索引。

**Goal:** 给 referral-302 plan 加勿复活墓碑；产出一份**扁平、有上限**的现役文档索引。

**Requirements:** R8, R9

**Dependencies:** U6（归档后才知最终现役集）

**Files:**
- Modify: `docs/plans/2026-06-15-003-...-referral-attribution-loop-plan.md`（顶部加 `<!-- TOMBSTONE: do-not-revive, see PR #6 -->`）
- Modify: **在 origin 文档维护"现役清单"**（定为单一产物，不另建 README 导航工具）

**Approach:** 墓碑标记防误复活（302 摧毁 dofollow）；索引=`{文件名, status, 一行说明}` 的保留集扁平列表，**一屏上限、无导航、无逐档详情**——R9 体量锁到与 R8 同级。

**Test scenarios:** `Test expectation: none -- 文档标记/索引`。

**Verification:** 墓碑就位；现役索引一屏内一眼可见"现在还有什么在做"。

## System-Wide Impact

- **Interaction graph:** U1 翻 `register()` 的 dofollow 影响 registry/signals/ledger 对该渠道的 dofollow 判定——翻牌前须 canary 确证，防 PR #108 式误翻。U2/U4 经 `app:notify` 事件总线 + toast 交互。
- **Error propagation:** U1 适配器错误须具体异常 + `from exc`；U4 错误态须分类透传而非吞掉。
- **State lifecycle risks:** U1 的 dofollow verdict 在 resume 路径不持久化——canary 必须 fresh publish，否则 verdict 静默丢失。
- **API surface parity:** R2 空态/CTA 模式应可被 fast-follow 页复用（U2 即范式）。
- **Unchanged invariants:** 后端业务逻辑 / pipeline / 状态 schema / events.db 不变；adapter 注册**机制**不变（U1 只改单个 `dofollow=` 实参值）；R5（live_dofollow 语义）本轮不动。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| **U1 类别可能无成员**（none-auth form-POST dofollow 经验上不存在），翻牌产出 0 | 诚实解耦：U5 不硬卡 U1；<2 则记 outcome、dofollow 扩充延 v0.5.1，v0.5.0 仍可切；是否保 R1 在本轮见待决问题 |
| U1 误把 nofollow 渠道翻成 dofollow（PR #108 重演） | canary 确证 true 才翻；judge 偏保守；翻牌即改单行可快速回退 |
| U1 verdict 漏穿 resume seam | canary 跑 fresh publish；seam 测试断言 resume 路径 verdict **absent**（当前真实行为）|
| **U3 门误判 fast-follow 页为红、阻塞 CI** | 门**硬编 allowlist**只扫核心页；fast-follow 显式排除 + 后续单元再拓宽 |
| U3 实际是大重构（~63 rgba 逐条判） | 先样板一页校准成本；用 per-file ceiling 承接暂不可 token 化者；批量范围按样板成本再定 |
| U3 截图复核拖发版 | 复核为 advisory，硬门=自动裸类=0 |
| 本计划 / plan-claims 门 | 已加 `claims: {}` opt-out（plan-check exit 0）|
| R10 grep-replace 碰历史 v0.4.0 引用 | 仅改 pyproject :7/:125，列出勿动清单；用定点行编辑 |
| R10 改动破坏覆盖门反测 / xfail 翻 xpass | 预飞记绿基线 + xfail 数；U1 后复核 xfail 仍为 xfail；`test_debt_registry_freshness` 保持绿 |
| R6 批量归档断链/误删/重复 | 反向引用门（含两种链接形式）+ 去重 config-driven dup + 用户确认 + git mv 可恢复 + 独立 commit |
| 本计划自身留成孤儿 active | U7 显式把本计划归一终态 |

## Documentation / Operational Notes

- CHANGELOG `[0.5.0]` 须如实反映本轮范围（已翻牌 dofollow 数 + UI 一致性 + 治理），显式记 R5 延后 + resume-trigger；若 U1<2，记 dofollow 扩充延 v0.5.1。
- 发版 tag/推送、R6 归档方式均为需用户确认的动作。

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-18-v050-core-convergence-requirements.md](docs/brainstorms/2026-06-18-v050-core-convergence-requirements.md)
- dofollow 翻牌：`publishing/adapters/__init__.py`、`cli/verify_dofollow.py`、`docs/discovery/canary-pending.md`、`docs/solutions/dofollow-platform-shortlist.md`
- 前端：`static/js/ui/states.js`、`notifications.js`、`static/css/tokens.css`
- Learnings：`grep-dofollow-map-before-shipping-adapter-2026-05-20`、`dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25`、`lite-accepted-deferrals-2026-06-05`
- 关联 PR：#108（adapter value 回滚教训）、#6（referral channel-level MVP，取代 302）
