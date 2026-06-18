---
date: 2026-06-18
topic: v050-core-convergence
---

# v0.5.0 核心收敛 —— 一份「真正还要做什么」的清单

> 本文档是对截至 2026-06-18 的 **43 份 brainstorm + 32 份 plan（共 75 份现役文档）** 做一次全量对账后的
> **单一收敛产物**。结论：绝大多数文档是「已发布 / 被取代 / 已废弃」的旧稿，可归档；v0.5.0 真正
> 未完成的工作只有 **少数几条实做 + 一条文档治理**。本文档取代「再生成一份新优化清单」的诱惑——
> 问题从来不是缺想法，而是文档堆积、未收敛成可发布版本。
>
> ⚠️ **对账边界（2026-06-18 review 补）**：本次对账只覆盖 75 份*文档*，**不含代码内 TODO/xfail 债务**。
> 已知 2 处与 R5 同源（false-green 假成功家族）的代码债，记入 backlog 但不在本轮范围：
> `linkcheck/language.py:73 TODO(ko-corpus-calibration)`（阈值 0.30 未校准）、
> `tests/test_e2e_live_publish_ratio.py` 的 xfail `test_empty_live_url_is_not_verified_dofollow`（空 live_url 跳过验证→假绿）。

## Problem Frame

谁受影响：本工具的运营者（盯 pipeline 状态发外链）+ 维护者。

现状：backlink-publisher v0.4.0 已落地、测试成熟（~537 test files）、技术债登记表近乎全清
（10 项 9 项 resolved，0 项 open）。`main` 上 v0.5.0 收敛正在高速推进——HTTP 统一已收口
（#33–#39）、深色控台改版壳+工作台+监控聚合已合并（#20–#29）、Phase 0「激活前验证门」已合并
（#30）、GSC 索引+排名闭环已落地（`4ede3a06`）。

真正的缺口不是「做什么」，而是 **75 份文档与代码现实严重脱节**：多份 brainstorm 自称「0 执行」
但对应工作早已 merge；2 份 active plan 实际已 ~90% 完成；勾选框忘了打✓。**这种漂移本身就是
风险**——它让人无法一眼看出「还剩什么」，也正是 #24（标记完成却静默 no-op）那类 bug 的温床。

本轮目标：**把 75 份收敛成「一份核心 + 一批归档」，把真正剩下的几条做完，切出 v0.5.0。**

## 对账快照（75 份 → 真正待办屈指可数）

| 类别 | 现役总数 | 保留（仍 active / 墓碑） | 可归档（已发布 / 被取代 / 废弃） |
|---|---|---|---|
| Plans | 32 | 3（2 active + referral 墓碑） | 29 |
| Brainstorms | 43 | 4（含本文档前序 3 份 + 本文档） | ~39 |

全量对账无「文档级孤儿待办」逃逸——除 R5 外，每个仍 PENDING 的需求都已被 2 份 active plan
（`v050-convergence-throughput-trust`、`webui-console-redesign`）吸收。R5（索引性桥接）是唯一一条
**不在任何 active plan 内、却仍有真实产品价值**的遗漏，且其是否该现在做需先验证（见 R5 + 待决问题）。

> 归档现状：现役目录外已有三个旧归档根——`docs/_archive/plans/`（168）、`docs/_archive/brainstorms/`（91）、
> `docs/brainstorms/_archive/`（28）。R6 须并入既有 `docs/_archive/`，**不要**新建 `docs/plans/_archive/`。

## Requirements

工作分两轨。**Track A = 决定能否切 v0.5.0 的代码工作；Track B = 治理清理，永不阻塞发版。**

| ID | 待办 | 轨 | 类型 | 阻塞 |
|---|---|---|---|---|
| R1 | ≥2 个 dofollow 平台 catalog YAML | A | 后端·数据 | 真人 live-canary |
| R2 | 统一空态首次引导 CTA | A | 前端 | 无 |
| R3 | UI 一致性收尾（token 收口） | A | 前端 | 无 |
| R4 | 反馈语言一致性（loading/empty/error） | A | 前端 | 依赖 R3 token |
| ~~R5~~ | 索引性 → 权益账本桥接 | **延后** | 后端·正确性 | **2026-06-18 重采样未显示 G1 触发跨过 → 维持延后** |
| R10 | 发版门（版本号 + CHANGELOG + 测试 + tag） | A | 收尾 | 依赖 A 轨完成 |
| R6–R9 | 文档收敛与治理 | B | 治理（非阻塞） | R6 待用户点头执行 |

**A. Throughput —— dofollow catalog 扩充**

- R1. 在既有 catalog 框架（`publishing/adapters/catalog/`，框架已验收 v050 U5/U7）下，从
  `docs/solutions/dofollow-platform-shortlist.md` **选 3–4 个 none-auth form-POST 候选**，各跑真实
  `verify-dofollow`（真人 live 发布），**要求 ≥2 个通过 dofollow 判定**；通过者补 catalog YAML +
  per-platform mock publish 测试。**发版兜底**：若最终少于 2 个通过，v0.5.0 以「实际通过数 + 一条
  记录说明」切版，而非死等固定数量阻塞发版（候选名单的 none-auth vs API/cookie 形态在 planning 阶段标注）。
  注：当前 catalog 仅 1 个生产实例（`txtfyi.yaml`，且本身仍 canary-pending），框架边角用例未充分演练。

**B-UI. UI/UX 一致性**

- R2. 在发布工作台（index）与设置页（settings）接入**统一空态首次引导**：用既有
  `ui/states.js::renderEmpty`（已确认存在）渲染「去配置」CTA，取代散落静态文案。**须区分三种"空"成因**：
  真·零配置→`renderEmpty`+去配置 CTA；有配置但本视图无结果→`renderEmpty`+「当前条件无结果」+清筛选
  （**不**误导去配置）；请求失败→走 `renderError` 而非空态。
- R3. **token 一致性收尾 + 验收门**：把残留裸色值 / 裸 Bootstrap 颜色类页面收口到 `tokens.css` 语义变量。
  已知工作面（2026-06-18 扫描）：**44 个模板中 24 个仍用裸 `btn-*`/`bg-*` 颜色类**；
  `index.css`/`settings.css`/`copilot.css` 各残留约 100/80/62 处裸色值。**验收门（防"token 清零但观感死板"
  的 AI-slop）**：(1) 量化——模板内裸 `btn-*`/`bg-*` 颜色类 = 0；CSS 裸 hex/rgb 仅允许出现在以
  `/* token-exempt: <reason> */` 标记的渐变/阴影/光晕(orb)处；(2) 一条 CI 断言锁死回退；(3) **视觉验证**——
  每个改动页改前/改后截图人工确认视觉层级（主/危险/次要操作可区分、重要卡片仍有权重差）未被抹平。
  先做一页样板确立标记惯例再批量。
- R4. **反馈语言一致性 + 三态规格**：未重做页面的加载 / 空 / 错误态收口到统一组件（`ui/states.js` +
  `notifications.js`）。**须先定一张三态内容规格**（否则各页像现 `monitor_hub.js` 那样各自发明分类）：
  错误态——有限分类集（网络/超时、权限/CSRF、5xx、未知）+ 各类文案模板 + 重试入口统一位置；空态——
  文案语气基线 + 复用 R2 的「去配置」模式；加载态——骨架行数与 `aria-label` 约定。

**C. Metric 正确性（延后 —— 重采样未达 G1 触发）**

> **2026-06-18 重采样结论（决定 R5 去留）**：本机 `~/.config/backlink-publisher/events.db` 仅 11 个发布目标
> （半数为 `example.com` 等测试桩）、recheck 数据停在 2026-06-02、覆盖 8 个链接、最新 `0 blocked`（历史仅 1 次）。
> 这**不是 G1「1/84」测过的真实生产语料**，无法权威重采样；但现有信号**没有任何迹象显示 G1 重启触发
> （blocked ≥5 或任一 dofollow 渠道 ≥10%）被跨过**，方向与 G1 原判一致。**结论：R5 本轮维持延后**（移出
> Track A）。重启条件 = 在**真实生产语料**上重采样显示触发跨过；届时按下方实现要点落地。R5 的实现路径与
> 惰性陷阱分析已验证保留在此，供重启时直接复用。

- ~~R5~~（延后，重启条件见上）. **索引性桥接**：让 `equity-ledger` 把 `blocked`（noindex / X-Robots / robots-disallowed）的链接
  从 `live_dofollow` 计数中**剔除**——一条「还活着但不被收录」的链接传零 SEO 权益，却被当成健康 dofollow
  计入头号指标，造成**假成功**（`alive ≠ indexed`）。
  - **前置验证门（必须先过，见待决问题）**：R5 当初由量化闸门 G1 主动 DEFER——彼时 blocked 仅 1/84≈1.2%，
    判定「ledger-bridge 在 1.2% 下不值得（carrying cost ≫ yield）」，并留硬性重启触发：**blocked ≥5 或
    任一 dofollow 渠道 ≥10%**。复活 R5 前**必须重采样确认触发已被跨过**，否则就是为 1/84 的成本过度建造。
  - **实现要点（已验码）**：`blocked` 不是 verdict，而是 `link.rechecked` 事件 payload 上的独立
    `indexability` 字段；在 `ledger/aggregate.py::_load_recheck_liveness` 里读
    `latest_link_verdicts(...).payload.get("indexability")`，**复用现有 `dofollow_lost` 的"保留 live、移出
    live_dofollow"剥离模式**（aggregate.py，与已合并的 #31 同一文件域）。
  - **⚠️ 惰性陷阱**：检测信号仅在 `recheck-backlinks --probe`（网络门控）且页面可读时才写；现有语料多为
    `indexability=unknown`（fail-open 不扣分）。**光上 ledger 逻辑、不跑全量 re-probe sweep，头号指标一个数
    都不会变**——会复刻"假成功"。故 R5 交付**必须含一次全量 re-probe sweep**（或明确说明只对新链生效）。
  - 补正向积分测试：构造 alive-but-noindex 链接，断言 `live_dofollow` 计数确实下降。

**D-Release. 发版门**

- R10. **定义并执行「可切版本」**（原 Success Criteria 用了「可切版本」却未定义；现显式化）：
  (a) `pyproject.toml` 版本 `0.4.0→0.5.0`（**两处**：第 7、125 行）；(b) `CHANGELOG.md` 的 `[Unreleased]`
  提升为 `[0.5.0] - <date>`，覆盖 R1–R5；(c) 全量 pytest 绿；(d) 打 tag `v0.5.0`。所有权归 R10，不可悬空。

**E. 文档收敛与治理（Track B —— 不阻塞发版）**

- R6. **归档 ~68 份已发布 / 被取代的旧文档**：按既有惯例*移动*而非硬删，目标是**既有的
  `docs/_archive/plans/` 与 `docs/_archive/brainstorms/`**（并把零散的 `docs/brainstorms/_archive/` 28 份一并
  并入，收敛到单一归档根）；**不要**新建 `docs/plans/_archive/`。**归档前安全门（必须）**：对每个候选跑
  `grep -rIl <basename> AGENTS.md ARCHITECTURE.md CLAUDE.md docs/ .claude/`——凡有活引用者，要么保留 active，
  要么在同一 commit 把引用方改指 `_archive` 路径（AGENTS.md 已按名引用 ≥7 份 plan/brainstorm）。此为不可逆
  动作，**执行前须用户确认方式**（移动 / 硬删 / 仅标注）。
- R7. **状态归一**：R1/R2 落地后，把两份 active plan（`2026-06-16-004-v050-convergence`、
  `2026-06-17-001-webui-console-redesign`）状态从 `active` 归一为 `shipped`/`completed`；顺带补
  `2026-06-15-004` 与 `2026-06-16-001` 漏打的勾选框（工作早已 merge，仅 checkbox 遗漏）。**归一前须核实
  两份 plan 无真未合并残留**，避免把活工作误标为 shipped（即本轮要清的反向漂移）。
- R8. **referral 墓碑**：`2026-06-15-003-referral-attribution-loop`（self-hosted 302 短链改写）保留为
  「勿复活」墓碑——302 改写会摧毁 dofollow（产品命根）、破坏 g5 footprint 与发布后验证器，已被 5-persona
  评审否决，并已被 channel-level GA4 referral MVP（PR #6）取代。在该文件顶部加
  `<!-- TOMBSTONE: do-not-revive, see PR #6 -->` 标记，使后续收敛不会误复活。
- R9. **单一现役索引**：归档后保留的现役文档（本文档 + 4 份保留 plan/brainstorm）收敛为一份可读清单。

## Success Criteria

- **收敛**：`docs/plans/` 与 `docs/brainstorms/` 活跃面只剩本文档 + 4 份保留文档；其余移入 `docs/_archive/`；
  无「自称 0 执行实则已 merge」的漂移文档留在活跃面；归档无断链（inbound-reference clean）。
- **R1**：≥2 个新 dofollow 平台有 catalog YAML + 通过真实 `verify-dofollow` + mock 测试绿（或记录实际通过数）。
- **R2/R3/R4**：核心流程页观感统一为深色控台，无 Bootstrap 默认违和；token 验收门（裸类=0 + 截图视觉复核）
  通过；空 / 错误 / 加载态一致；无渠道 / 无站点有正确引导 CTA（且不误导已配置用户）。
- **R5（延后，非本轮发版门）**：仅当真实生产语料重采样跨过 G1 触发才启动；启动后构造 alive-but-noindex
  链接断言 `live_dofollow` 不再计入它 + 全量 re-probe 后指标真实反映 + 积分测试锁死。
- **R10**：`pyproject` 版本 = 0.5.0（两处）、`CHANGELOG` 有 `[0.5.0]` 条目、全量测试绿、tag 已打。

## Scope Boundaries

- **不再生成新的优化清单 / 路线图**——本轮是收敛，不是扩张。R1–R5 之外不开新战线。
- 本轮对账只覆盖文档，**不含代码内 TODO/xfail 债务清扫**（已知 2 处 false-green 代码债记入 backlog，见顶部）。
- 不新增 publishing adapter 引擎，R1 仅是既有 catalog 框架的数据填充（≥2 个 YAML）。
- UI 各条（R2–R4）**不改后端业务逻辑、pipeline 算法、状态存储 schema、渠道适配器**。R5 是有意为之的
  **后端正确性改动**（不受"不改后端逻辑"约束——该约束仅针对 UI 项 R2–R4）。
- 不引入打包器 / 框架，严守 zero-build 原生 ES modules（无 `window.*` API、无内联 `on*`、
  `readCsrf()` 每次读 `<meta>`）。
- **light 主题**：现 CSS 实为 dark-only（无 `[data-theme=light]`/`prefers-color-scheme: light` 实现）。
  本轮 token 收口**默认只保证深色一致、不做 light parity**（Background 历史措辞「亮/深双主题」不作为本轮承诺）；
  是否保留 light 见待决问题（不可逆地影响 24 个模板）。
- R3/R4 **本轮只覆盖核心流程页**（index / settings / plan-validate-publish 工作台 / 监控看板），其余页面靠
  token 级联受益、列为 fast-follow，不在本期逐页重排（边界见待决问题）。
- 不做 WebSocket/SSE 硬需求（轮询即可）。
- R6 默认*移动*归档，不硬删；执行方式待用户确认。不复活 referral 302 路线（R8）。

## Key Decisions

- **本轮 = 收敛而非扩张**：项目瓶颈是文档堆积未收敛，不是缺想法。再生成全面清单会火上浇油（用户明示）。
- **双轨发版**：Track A（R1–R5 + R10）决定能否切 v0.5.0；Track B（R6–R9 治理）随行但**永不阻塞发版**。
- **R5（索引性桥接）延后 —— 数据定的，非拍脑袋**（2026-06-18）：用户曾拍板纳入核心，review 揭示它当初被量化
  闸门 G1 以「blocked 1.2% 不值得」DEFER（触发 = blocked ≥5 或渠道 ≥10%）。遂用户授权重采样定夺——本机
  events.db 仅 11 目标（半数测试桩）、recheck 停 2026-06-02、最新 0 blocked，**非生产语料且未显示触发跨过**。
  故 R5 维持延后，重启条件 = 真实生产语料重采样达 G1 触发。**R5 即便日后启动也是必要但不充分**：修了
  live_dofollow，下游 equity-passes / ranks 仍是盲区，须单独记入 backlog 而非声称"指标已正确"。
- **竞争路线图已被执行消解，非被掩埋**（review 补）：`2026-06-16-comprehensive-optimization-roadmap` 自称
  与本线"分叉、0 執行"，但其 Phase 0 验证门已 ship（#30）、throughput 项（enforce/citation/weights/plan-gap）
  已在 Plan 002 U1–U12 ship。故 R6 归档它是**记录完成**，不是掩埋一个对立决策。
- **归档默认「移动到既有 `docs/_archive/`」**（git 可追溯）；硬删 / 仅标注为备选，**执行前确认**。
- **R1 仍需真人 live-canary**：保留人工验证步，但以「选 3–4、要 ≥2 通过、不足则带记录切版」兜底，避免发版日
  被一个外部手动步骤卡死。
- **两份 active plan 待 R1/R2 落地后归一状态**：避免重蹈本轮要清理的「完成却仍标 active」漂移。

## Dependencies / Assumptions

- R1 依赖一次真人 `verify-dofollow`（live 发布）；候选来自 `docs/solutions/dofollow-platform-shortlist.md`（已确认存在）。
- R2 依赖既有 `ui/states.js::renderEmpty` + `notifications.js`（均已确认存在）。
- R5 依赖：(a) `blocked`/noindex 检测信号（#358）——确认仅 `--probe` 时写、否则 unknown；(b) 一次全量
  re-probe sweep 把信号铺进现有语料，否则 ledger 改动惰性 no-op；(c) `#31` 已合并（非在飞），R5 与之复用
  同一剥离模式、无并发冲突。
- R6 假设这些文档均 git-tracked（确认为真），移动 / 删除均可从历史恢复；但 git 可恢复只保内容、不保链接，
  故须 inbound-reference 安全门。
- R10 依赖 A 轨实质完成；版本号现于 `pyproject.toml` 两处（第 7、125 行），无独立 VERSION 文件。
- 假设 generate/publish 后端数据契约不变，R2–R4 仅前端换壳。

## Outstanding Questions

- [Affects R3/R4][User decision] **UI 一致性的本轮边界**：R3/R4 已默认锁「核心流程页」、其余 fast-follow——
  是否符合你的"保有一致性"预期？还是要本期就铺满全部 ~19 页（代价：开放式打磨、可能拖发版）？（默认已采，可覆盖）
- [Affects R3][User decision] **light 主题去留**：已默认正式放弃 light parity（现本无实现）；若要保需双值 token、
  不可逆地影响 24 个模板。（默认已采，可覆盖）
- *（已解决）R5 重采样门：2026-06-18 用本机数据重采样，未显示 G1 触发跨过 → R5 延后。见 Key Decisions / R5。*

### Deferred to Planning

- [Affects R1][Technical] 从 shortlist 选哪 3–4 个？各自 form-POST 形态 / 字段映射、是否真 none-auth。
- [Affects R3][Technical] `index.css`/`settings.css`/`copilot.css` 裸色值逐文件分流：哪些可 token 化、哪些是
  合理 rgba（渐变/阴影/orb，标 `token-exempt`）；24 模板哪些只需删类名（components.css 级联已带新观感）。
- [Affects R4][Technical] 错误态有限分类集（taxonomy）由本轮定还是 planning 首个交付物；toast vs 内联
  `renderError` 的职责边界。
- [Affects R2/R3/R4][Technical] 被触及页面的响应式：CSS 中查无「表格卡片化」实现，须核实是否真已落地；
  R2 空态 CTA / R4 错误卡片的窄屏行为（单列堆叠、触摸目标 ≥44px）。
- [Affects R5][Technical] R5 语义确认走「保留 live、移出 live_dofollow」（与 #31 dofollow_lost 一致）；
  确认 `live_dofollow` 下游消费者（gates/ 内疑似无）及对 g3/decay 计数的连带影响。
- [Affects R6][Technical] 列出 ~68 候选中被 AGENTS.md / 技能 / 现役 plan 引用者，同 commit 改指 `_archive`。
- [Affects R5][监控] **R5 重启触发监控**：在真实生产语料上定期重采样 blocked 计数 / 渠道率；一旦跨过
  G1 触发（≥5 或 ≥10%），按 R5 实现要点启动桥接。

## Next Steps

R5 已由数据定夺为延后；R3/R4 边界与 light 主题均已采用推荐默认（可覆盖）。**`Resolve Before Planning`
无强阻塞项**，可直接 `/ce:plan docs/brainstorms/2026-06-18-v050-core-convergence-requirements.md`，把
**Track A（R1–R4 + R10）**拆成可执行单元，Track B（R6–R9 治理）并入同一 plan 的非阻塞收尾 milestone。
**R6 归档执行前需用户确认方式**。
