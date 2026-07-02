---
title: 外链发布平台切换评估（dev.to / hashnode 候选）
date: <填入启用日>
status: draft
trigger_condition: "Phase 0 G1 fail (indexed < 7/10) 或 relative_underperformance=true 或 G2 fail 选 Option A"
origin_plan: docs/plans/2026-05-15-004-feat-telegraph-adapter-plan.md
predraft_source: docs/plans/2026-05-18-002-refactor-phase0-unblock-actions-plan.md (Unit 5)
---

> **Archived (E1, 2026-07-02).** Never activated (trigger date placeholder
> left unfilled). `origin_plan` (`2026-05-15-004`) is already archived in
> `docs/_archive/plans/`; the gate condition was never hit.

# 外链发布平台切换评估（dev.to / hashnode 候选）

## Problem Statement (条件式)

**前提（启用时必须先 verify）** —— 触发场景之一：

1. **G1 索引 fail**: Phase 0 T+14 `indexed_pages_at_day14 < 7`,telegra.ph 在 Google 索引可达性上不达标
2. **相对劣势 (soft fail)**: `relative_underperformance=true`,即 dev.to/hashnode baseline 14 天索引率 ≥ telegraph + 15pp,运营 sign-off 倾向换平台
3. **G2 dofollow 回归** + dofollow-regression-followup 选 Option A,转走 dev.to/hashnode

不论触发场景，本 brainstorm 评估 **dev.to / hashnode 作为 telegra.ph 替代平台** 的可行性,产出 plan 候选。

## Pre-planning Inputs（启用前必填）

| 字段 | 值 | 来源 |
|---|---|---|
| 触发场景 | G1 fail / relative_underperformance / G2 fail Option A | 启用方填写 |
| telegraph T+14 indexed | __ / 10 | Phase 0 §1 / §3 |
| telegraph T+14 GSC referring | __ | Phase 0 §3 |
| dev.to/hashnode baseline T+14 indexed | __ / __ | Phase 0 §4 |
| dev.to/hashnode baseline T+14 dofollow 保持率 | __ / __ | Phase 0 §4 |
| 运营对 dev.to 注册门槛的实测体验 | 简单 / 中等 / 困难 | 运营反馈 |
| 运营对 hashnode 注册门槛的实测体验 | 简单 / 中等 / 困难 | 运营反馈 |

## Candidates 对比

| 候选 | dofollow | API 类型 | 内容审核 | 索引速度 | 注册门槛 | 64KB 类似上限 |
|---|---|---|---|---|---|---|
| dev.to | 历史上 dofollow，社区写作平台 | REST + token | 自动 + 社区 flag | 通常 24-72h | 邮箱注册 | 无明确上限 |
| hashnode | 历史上 dofollow | GraphQL | 自动 | 通常 24-48h | 邮箱注册 / 社交登录 | 无明确上限 |
| Medium (已实现) | 引入 nofollow 多年 | OAuth + Browser | 严格 | 较快 | 高 | 无 |
| Telegraph (已实验) | <填 G1/G2 结果> | REST + token | 无 | <填> | 无注册 | 64KB |

## Open Questions

1. **dev.to / hashnode 二选一还是同时做？**
   - 单平台先做 → 节省工程时间,但单点故障
   - 同时做 → 工程时间 ×2,但有 A/B 对照可选
2. **dev.to 是否对外链有自动 nofollow 策略？**（需实测,2024 后有传闻部分模式回填 ugc）
3. **hashnode 的 GraphQL API 是否复杂度 >> Telegraph REST？**（如果是,工程预算需重估）
4. **velog spike (PR #38) 的硬阻塞 (社交登录) 在 dev.to / hashnode 是否同样存在？**
   - dev.to: 支持邮箱注册 → 不阻塞
   - hashnode: 仍需社交登录或邮箱 → 视实测
5. **从 Telegraph plan unit 复用率？**
   - 适配器层 (`base.AdapterResult`、`retry.py`、`verify_publish.py`、`link_attr_verifier.py`) 完全复用
   - Unit 3 Markdown→Node 转换器是 Telegraph 专属 → 新平台需重新评估渲染契约
   - 复用率粗估 60-70%（与 Blogger/Medium 适配器同形度类似）
6. **若 Phase 0 telegraph T+21 G2 仍 Pass 但 G1 fail（罕见组合）**：是否保留 Telegraph 作为低索引但高 dofollow 的辅助渠道？

## Scope Boundaries

- **不做** 重启 velog 推进（PR #38 在本 brainstorm 启用时显式转 `cancelled`）
- **不做** 自建外链平台（owned media）—— 那是更大的 brainstorm，单独发起
- **不做** 在不实测 baseline dofollow + 索引前就承诺平台

## Followup Options（候选 plan 方向）

| Option | 描述 | 工程预算粗估 |
|---|---|---|
| A. dev.to 适配器 V1 | 单平台、REST/token，Telegraph plan 同形度高 | 4-6 工作日 |
| B. hashnode 适配器 V1 | 单平台、GraphQL | 6-8 工作日 |
| C. dev.to + hashnode 并行 V1 | A + B | 10-14 工作日 |
| D. dev.to V1 + Telegraph 残值保留 | 主推 dev.to，Telegraph 已发布 10 页留作 brand mention | 4-6 工作日（与 A 同） |
| E. 暂停外链扩量，回顾整体策略 | 整体 retreat，重新 brainstorm 项目目标 | N/A |

## Resolve Before Planning

- [ ] Pre-planning Inputs 全部填齐
- [ ] 运营完成 dev.to / hashnode 各自的真实账号注册尝试（≤2 小时），反馈门槛体验
- [ ] 工程方完成 dev.to / hashnode API 文档阅读 + 错误码清单核对
- [ ] sign-off 选定 Option A-E

## Success Criteria

- 选定 Option，产出对应 plan（若 A → `feat: dev.to adapter`）
- 决定 Telegraph plan `2026-05-15-004` 最终状态（`paused` / `superseded` / `cancelled`）
- 决定 velog PR #38 状态（默认 `cancelled`）

## Sources & References

- **触发依据**: Phase 0 报告（§1 G1 / §4 baseline 数据）
- **原 plan**: docs/plans/2026-05-15-004-feat-telegraph-adapter-plan.md
- **平行模板**: `_drafts/dofollow-regression-followup.md`、`_drafts/indexation-failure-followup.md`
- **复用基础**: `src/backlink_publisher/adapters/blogger_api.py`、`src/backlink_publisher/adapters/medium_api.py`（适配器同形度参考）
- **velog spike (rejected)**: `docs/phase0/2026-05-15-velog-spike-report.md`（PR #38）
