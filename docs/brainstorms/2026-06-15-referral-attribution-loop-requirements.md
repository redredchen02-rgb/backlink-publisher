---
date: 2026-06-15
topic: referral-attribution-loop
---

# Referral 归因闭环（Close the Referral Attribution Loop）

## Problem Frame

系统目前能**发布**外链、能定期**复查链接死活**（keepalive 五步闭环、recheck 5 类判决），但**无法在产品内确认链接是否真的带来了 referral 流量**。

GA4 数据摄入在项目内是**零代码**——`cli/channel_scorecard.py` 自注释 `GA4 referral / GSC discovery / AI-retrievability axes are deferred (Wave-0 DESCOPE)`，归因完全外包给外部 `gsearch-radar` CLI。

这一个缺口同时卡住三处下游：
- **g3 gate**（`gates/g3_referer.py`）GA4 部分无代码，只接受操作员手填 `referral_sessions`，否则 `BLOCKED`
- **channel scorecard** 的 referral 维度永远渲染 `inert:not-landed`
- **keepalive「该不该复投」决策** 缺流量信号，只能按死活猜

后果：运营者决定「哪个渠道值得再投一轮」时是**半盲**的。补齐 GA4 摄入 = 三个子系统同时解锁。

## Requirements（渠道级 MVP，2026-06-15 收敛）

**核心机制：纯读取归因，零发布管道改动，dofollow 完整保留。** 只读 GA4 referral 数据 + 按 referrer host 映射到渠道，绝不改外链 URL。

**GA4 渠道级摄入**
- R1. 复用既有 `click_track`（已用 `google-analytics-data` 查 GA4 Data API、按 `sessionSource/sessionMedium` 拉 referral session）查询渠道级 referral，输出 clean JSONL / stderr 诊断。**单一 GA4 property**，不需 property 路由。
- R2. 将 GA4 `sessionSource`（referrer host）映射回**渠道**（platform）。注意 GA4 会对 source 做规整（如 `m.facebook.com`→`facebook`），需建 source↔渠道 映射表。
- R3. 把渠道级 referral 落库进 events store（新 event kind，按 channel keyed），使 `events/history_query.py` 能重建归因历史。

**归因产出（解锁下游）**
- R4. `channel_scorecard` 用真实渠道 referral sessions 替换 `inert:not-landed`，按渠道展示带流量能力。
- R7. g3 gate 消费产品内 GA4 渠道 referral 计数，从 `BLOCKED`/手填 变为真实 verdict。

## Success Criteria
- `gate-probe --gate g3` 在**无需手填** `referral_sessions` 下返回真实 verdict（非 BLOCKED）。
- `channel_scorecard` 对至少 1 个渠道展示**非 inert** referral 列。
- 全程走 CLI 管道、可被外部排程器调度（守护进程本身不在本轮）。
- **发布管道零改动；任一外链的 dofollow 链接保持不变**（回归测试守护）。

## Scope Boundaries
- **🚫 链接级归因（原 R5/R6）移出 MVP**：渠道级已满足决策需求（用户确认）。链接级若未来要做，只能用"保 dofollow"的真链打标记 + 自有日志，另开 brainstorm。
- **🚫 不碰发布管道 / adapter / 外链 URL**：这是保住 dofollow + 避免短链灾难的硬边界。
- **GSC discovery / AI-retrievability** 维持 deferred（Wave-0 DESCOPE）。
- **不**自建排程守护（CLI 可被排程即可）。
- **不**新增 GA4 认证 UI（复用 click_track 凭证机制）。
- **不**做内容质量评分（方向 C）。

## Key Decisions
- **轴心 = 产品成效（SEO 结果）**，不是代码可维护性或运营自主性 —— 用户已确认。
- **GA4 referral 是最高杠杆缺口**：它是 g3、scorecard、keepalive 复投决策三者共同的卡点，补一处解锁三处。
- **🔒 硬约束（本轮血泪习得，不可违反）：任何归因方案必须保住到 money page 的直接 dofollow 链接。** 产品的命根子是传递链接权重（adapter 强制 `dofollow=True`）；任何把外链改指向中转/重定向、导致 money page 拿不到直接 dofollow 的方案，都用毁掉被测量物的方式完成测量，否决。
- **被否决的方案 ① UTM join**（2026-06-15 计划期研究否决）：GA4 标准版高基数 `(other)` 聚合吃掉 article_id 级细粒度；外链场景 UTM strip 率高 + 幸存者偏差。UTM 顶多渠道级。
- **被否决的方案 ② 自有短链 302**（2026-06-15 document-review 五persona一致否决，两个 P0）：毁 dofollow 本意；打断 g5 + 6 个发布后校验器；每条发布实为 3 条独立 body 链接（main/list/work）单 URL 模型套不上；单点风险（域名过期=全量死链/可劫持）。详见 `docs/plans/2026-06-15-003-*-plan.md`（PARKED）。
- **现实约束（feasibility 习得）**：每条发布 payload 含 3 条独立链接（main_domain/list/work），任何链接级方案都要处理"3 链 → 1 文章/渠道"的归因映射。
- **✅ 已定方向（2026-06-15 用户确认）：渠道级 MVP**——复用既有 `click_track`（已能查 GA4 referral）+ referrer host→渠道映射，**不动发布管道、保住 dofollow、纯读取、可逆**。解锁 g3 / scorecard（皆渠道级）。
- **归因精度 = 渠道级足够**（用户确认）：三个下游消费者本就渠道级运作；链接级 R5/R6 移出 MVP。

## Dependencies / Assumptions
- 既有 `click_track` 子包已配 GA4 凭证（`config/types.py:ClickTrackConfig.credential_path`，`[click_track]` TOML）—— 复用，规划期确认。
- 现有 events store 可加新 kind（需 REQUIRED_FIELDS floor，过 R2 契约门）—— 规划期确认。
- 与 `2026-06-15-002` 计划零重叠（已核实：001 发布硬化 completed、002 文档债清理）。
- 短链方案 `2026-06-15-003` 已 PARKED 作废。

## Outstanding Questions

### Resolve Before Planning
_（已全部解决 —— 渠道级方向已定，无 blocking）_

### Deferred to Planning
- [Affects R1][Technical] 复用 `click_track.engine.query_site` 的具体接入方式（GA4 凭证/配额/日期窗口）—— 规划期读 click_track 实现确认。
- [Affects R2][Needs research] GA4 `sessionSource` 规整规则 → 渠道映射表如何建（哪些 source 对应哪个 adapter）—— 规划期定。
- [Affects R3][Technical] 新 referral event kind 的 schema 与 REQUIRED_FIELDS floor —— 规划期定。
- [Affects R7][Needs research] g3 `referral_sessions` 接口无破坏切到 events 数据源 —— 读 `gates/g3_referer.py` + `cli/gate_probe.py` 确认。

## Next Steps
→ /ce:plan —— 渠道级方向已定、零 blocking、范围干净可逆。新计划另起序号（003 已 PARKED）。
