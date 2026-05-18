---
title: Telegraph dofollow 回归处置（G2 fail followup 模板）
date: <填入启用日,如 2026-06-08>
status: draft
trigger_condition: "Phase 0 T+21 复查时 dofollow_retained_pages_at_day21 < 10"
origin_plan: docs/plans/2026-05-15-004-feat-telegraph-adapter-plan.md
predraft_source: docs/plans/2026-05-18-002-refactor-phase0-unblock-actions-plan.md (Unit 5)
---

# Telegraph dofollow 回归处置

## Problem Statement (条件式)

**前提（启用时必须先 verify）**：Phase 0 报告 §3 / §3.1 T+21 数据显示 10 个页面中有 N 个（N >= 1）的 `rel_t21 != null`，即 telegra.ph 服务端在发布后 21 天内对部分页面回填了 `nofollow` / `ugc` / `sponsored`。

这与 plan §23 / Phase 0 §1 G2 条件 (`dofollow_retained_pages_at_day21 == 10`) 直接冲突，触发：

- Telegraph plan `status: paused`
- Unit 2/4/5/6 已 push 的 PR 挂 `blocked-by-phase0-final`（若 G1 6/01 已 Pass）
- 本 followup brainstorm 进入决策

## Pre-planning Inputs（启用前必填）

| 字段 | 值 | 来源 |
|---|---|---|
| `dofollow_retained_pages_at_day21` | __ / 10 | Phase 0 报告 §1 |
| 回填为 nofollow 的页面 URL 清单 | <填入> | Phase 0 §3 rel_t21 列 |
| 回填发生的时间窗口（T+7/T+14/T+21 哪一段出现） | <填入> | Phase 0 §3 rel_t7 / rel_t14 / rel_t21 比对 |
| 受影响页面的特征（外链数 / 目标域 TLD / velocity 与否） | <填入> | Phase 0 §3 + §3.1 |
| velocity 子实验是否同步回归 | 3/3 / 2/3 / 1/3 / 0/3 | Phase 0 §3.1 |
| baseline 平台（dev.to / hashnode）同期 dofollow 保持率 | __ / __ | Phase 0 §4 |

## Open Questions

1. **回归是全局还是局部？**
   - 全局（10/10 都回归）→ telegra.ph 平台策略变更，不可挽救；plan `status: cancelled`
   - 局部（部分页面）→ 是否存在共性特征？（外链数高 / suspicious TLD / 内容主题）
2. **回归是否可触发？**
   - 是否通过 `editPage` 重新发布能 reset rel？（需 6/08 后实测）
   - 是否通过新账号重发同 slug 能避开？
3. **dev.to / hashnode baseline 是否同样回归？**
   - 若是 → 整个外链生态都在收紧，需重新评估外链策略
   - 若否 → telegra.ph 单独问题，pivot 候选清晰
4. **已发布的 10 个页面是否仍有残值？**
   - 即使 nofollow，是否仍贡献 referrer / brand mention 信号？（GSC referring URL T+14 / T+21 数据）

## Scope Boundaries

- **不做** 尝试逆向 telegra.ph 回填策略（无文档、无可靠探针）
- **不做** 在不达标 Pass 条件下勉强 ship V1
- **不做** 与 Telegraph 团队沟通（无官方支持渠道，且历史报告显示他们对策略变更不响应）

## Followup Options（候选）

| Option | 描述 | 触发条件 |
|---|---|---|
| A. 平台切换（dev.to / hashnode） | 启用 `platform-switch-evaluation-followup` brainstorm | 默认 |
| B. 多平台并行（telegraph 残留 + 新平台主力） | 已发布 10 页保留作为 brand signal，主力切新平台 | 若 GSC referring 显示残值 |
| C. 完全放弃外部平台外链 | 转向 owned media (项目自建 blog / 论坛) | 若 dev.to/hashnode 同步回归 |
| D. 等待 + 重试 | 6 个月后重做 Phase 0 实验 | 若回归被推测为 telegra.ph 临时反垃圾措施 |

## Resolve Before Planning

- [ ] 确认 Pre-planning Inputs 全部填齐
- [ ] 与运营 sign-off 选择 Option A/B/C/D
- [ ] 决定已发布 10 页的处置（保留 / `editPage` 加 disclaimer / `revokeAccessToken` 销毁）
- [ ] 决定 velog spike PR #38 状态（若选 Option A 走 dev.to/hashnode → PR #38 `cancelled`）

## Success Criteria（启用后 brainstorm 完成的标志）

- 选定一个 Option（A-D 之一），有明确 rationale
- 产出新 plan（若 Option A → `feat: dev.to adapter` plan;若 Option B → `feat: multi-platform fallback strategy` plan）
- telegraph plan `2026-05-15-004` 显式标记 `status: superseded` 或 `cancelled`

## Sources & References

- **触发依据**: Phase 0 报告 §3 / §3.1 T+21 数据
- **原 plan**: docs/plans/2026-05-15-004-feat-telegraph-adapter-plan.md（特别是 R3 / Risk 表第 2 行 "dofollow 在 14 天后被服务端回填 nofollow"）
- **平行模板**: `_drafts/platform-switch-evaluation-followup.md`、`_drafts/indexation-failure-followup.md`
