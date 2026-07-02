---
title: Telegraph 索引失败根因排查与后续走向（G1 fail followup 模板）
date: <填入启用日,如 2026-06-01>
status: draft
trigger_condition: "Phase 0 T+14 索引判定 indexed_pages_at_day14 < 7"
origin_plan: docs/plans/2026-05-15-004-feat-telegraph-adapter-plan.md
predraft_source: docs/plans/2026-05-18-002-refactor-phase0-unblock-actions-plan.md (Unit 5)
---

# Telegraph 索引失败根因排查与后续走向

## Problem Statement (条件式)

**前提（启用时必须先 verify）**：Phase 0 T+14 (2026-06-01) 复查时 `indexed_pages_at_day14 < 7`，即 10 个 telegra.ph 页面中被 Google 索引的数量未达硬门槛 7。

这是 Phase 0 G1 主判定 fail，直接导致：

- Telegraph plan `2026-05-15-004` 立即 `status: paused`
- 本 plan (`2026-05-18-002`) Unit 4 runbook Fail 分支启动
- Unit 2/4/5/6 任何已 push 的内容（本 plan 严格遵守 §194 → 不应有任何 push,但留兜底）撤回

**与 dofollow regression 的关键区别**: G1 fail 是"不被 Google 看见",G2 fail 是"被看见但被标 nofollow"。本模板专注前者。

## Pre-planning Inputs（启用前必填）

| 字段 | 值 | 来源 |
|---|---|---|
| `indexed_pages_at_day14` | __ / 10 | Phase 0 §1 |
| 未被索引的具体页面 URL 清单 | <填入> | Phase 0 §3 indexed_t14=no |
| 未索引页面的共性（外链数 / TLD / velocity / 内容长度） | <填入> | Phase 0 §3 |
| Google `site:telegra.ph/<slug>` 实测返回 | yes/no/captcha 分布 | recheck.py t14 输出 |
| GSC referring URL 注册数 | __ | 运营 GSC Top linking sites 复核 |
| baseline 平台（dev.to/hashnode）同期索引率 | __ / __ | Phase 0 §4 |
| baseline 是否同样不达标？ | 是 / 否 | 对比 |

## Open Questions（根因假设清单）

按概率从高到低：

1. **telegra.ph 域整体在 Google 索引层级偏低**
   - 验证：与 dev.to/hashnode baseline 14 天索引率对比
   - 若同样不达标 → 不是 telegra.ph 问题，是项目目标域 51acgs.com 太新 / 太弱
   - 若 baseline 正常 → telegra.ph 单独问题
2. **页面内容质量被 Google 视为 thin / boilerplate**
   - 验证：10 篇内容主题相似度、字数、外链密度
   - 若 C 组（外链 5 个）索引明显差于 A 组（1 个）→ 链接密度即索引惩罚
3. **suspicious TLD 拖累索引**
   - 验证：C1-C4（含 `.xyz`/`.top`）vs A 组（仅主域）索引差
4. **velocity 子实验造成集中发布惩罚**
   - 验证：V1/V2/V3 (24h 内连发) vs 非 velocity 页面索引差
5. **Google 对 telegra.ph 平台施加 nofollow-by-default 之外的更广泛 demote 信号**（最坏情形）
   - 验证：GSC referring 0 注册 + `site:` 探针全 no
6. **GSC 探针失效（captcha）导致测量误差**
   - 验证：recheck.py t14 是否大量 captcha → 隐身窗口手工 verify

## Scope Boundaries

- **不做** 在根因未明前盲目 pivot 平台
- **不做** 重复 Phase 0 实验（21 天成本太高，先用现有数据归因）
- **不做** 修改 Phase 0 报告本身的数据（如有 captcha 误差，单独标注，不抹掉原数据）

## Followup Options（候选）

| Option | 描述 | 触发条件 |
|---|---|---|
| A. 启用 `platform-switch-evaluation-followup` | 切 dev.to/hashnode | 根因 #1 (telegra.ph 单独问题) 或 #5 (平台 demote) |
| B. 等待 + T+21 复查 | 6 月 8 日 T+21 时索引率可能爬升（Google 抓取延迟） | 若 indexed_t14 = 5-6（边界值，G1 fail 但接近） |
| C. 内容改造重做 Phase 0 | 改用更长内容、更分散主题、更少 suspicious TLD | 根因 #2 或 #3 |
| D. 全停外链扩量项目 | 整体 retreat | baseline 同样不达标 + 项目目标域底子太弱 |

## Resolve Before Planning

- [ ] Pre-planning Inputs 全部填齐
- [ ] 完成 6 个根因假设的快速验证（多数可在 1 天内通过对比数据完成）
- [ ] sign-off 选定 Option A-D

## Success Criteria

- 选定 Option,产出对应行动（Option A → `platform-switch-evaluation-followup` 启用；Option B → 延迟 7 天再判；Option C → 新 brainstorm `content-redesign-for-indexation`；Option D → 项目层 retro brainstorm）
- 决定 Telegraph plan `2026-05-15-004` 最终状态
- 决定本 plan `2026-05-18-002` 状态（同步 telegraph plan）

## Sources & References

- **触发依据**: Phase 0 报告 §1 / §3 T+14 indexed 列
- **原 plan**: docs/plans/2026-05-15-004-feat-telegraph-adapter-plan.md（特别是 Success Criteria 主指标 ≥70% 索引）
- **平行模板**: `_drafts/dofollow-regression-followup.md`、`_drafts/platform-switch-evaluation-followup.md`
- **recheck 工具**: `scripts/telegraph_spike/recheck.py --day t14 --check-indexation`
