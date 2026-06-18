---
date: 2026-06-15
topic: reliability-observe-to-enforce-hardening
---

# Reliability: Observe → Enforce (Measure-First Thin Slice)

承接 `docs/plans/2026-06-15-001-feat-publish-reliability-iteration-plan.md`（status: completed）。
上一轮把可靠性执行层的机器**造好并接上 observe 模式**；本轮**先回答「enforce 到底会拦下多少
坏发佈？值不值得开？」**，用数据回答，再**安全地、按数据**决定要不要真正翻转一条频道。

> **范围演进（2026-06-15，两轮 document-review 后）**
> - **Pass-1 → 薄切片**：5 个 persona 中 4 个独立指出第一个 enforce 胜利不需要 per-adapter 熔断
>   与 fallback 白名单扩张（全系统当前**只有 1 条 fallback transition**：MediumAPI→MediumBrave），
>   已降为 Follow-up。
> - **Pass-2 → 测量与翻转切开**：评审进一步指出初稿仍把 enforce 当成「默认终点」，且在 ~1–10
>   backlinks/run 的低流量下，最可能的诚实结论是「enforce 几乎不触发」。故本轮重构为
>   **Phase 0（廉价先验）→ Phase A（测量 + observe 期收益，无条件）→ Phase B（enforce 翻转，
>   gated on 数据判定值得）**。Phase B 不会在没有数据支撑前建造。

## Problem Frame

可靠性执行层（40 个 adapter、熔断器、错误分类、fallback、per-channel metric）已建好，
`BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED` 停在 **`observe`** 模式：跑闸门/熔断检查、
发出 `would_skip_policy` / `would_skip_circuit` 事件、做 trip 记帐，**但发佈照常**。

**今天具体出什么错？诚实答案：还量不出来。** `would_skip_*` 只 `log.info` 到 stderr，
**没进 `events.db`**（`scorecard/success_rate.py` header 自己写明）。连锁两个问题：

1. **量不出 enforce 的价值**：不知道「过去 N 天，enforce 本来会拦下几次徒劳发佈」。
2. **operator 对退化频道无主动感知**：频道被 ban / 选择器漂移后，observe 仍照发，只能肉眼看
   run 才发现——这正是单人流水线最想摆脱的「保姆式盯梢」。

**主线 = 测量 → （观察期就先拿一个收益）→ 用数据决定是否 enforce。** 不预设 enforce 一定值得开。

> **do-nothing 基线**：留在 observe、肉眼盯 run、失败手动重跑。本轮若量化后发现 enforce 触发率
> 极低，就是**有价值的负结论**——Phase 0/A 的收益不依赖「enforce 值得开」这个前提。
> ⚠️ 并且 enforce 会引入一个 observe **没有**的新失败模式（见 Resolve-Before-Planning 的
> fail-CLOSED 项），所以「该不该 enforce」必须连这个新风险一起算。

## 两个 enforce 开关必须区分（pass-1 P0，已修）

| 开关 | 子系统 | 管什么 | 本轮关系 |
|---|---|---|---|
| `RELIABILITY_POLICY_ENABLED` | `reliability/policy.py` | 闸门+熔断 → 该不该 **skip** 一次发佈 | **本轮主角** |
| `DEDUP_ENFORCE` | `cli/_dedup_gate.py`（fail-closed） | 防 **重复发佈** | **非本轮**；不可回退前置约束 |

> 重复发佈安全归 **dedup gate**，不是 reliability enforce 的产物。成功判据据此不拿「无重复发佈」
> 当功劳。

## 三种模式（已有机制）

| 模式 | 闸门+熔断 | `would_skip_*` | trip 记帐 | 实际发佈 | 现状 |
|---|---|---|---|---|---|
| `off` | 不跑 | 无 | 无 | 照常 | 历史默认 |
| `observe` | 跑 | 发出（**仅 stderr，未持久化**） | 跑 | 照常 | **现在停在这** |
| `enforce` | 跑 | — | 跑 | 命中即 **真 skip** | Phase B 目标（gated） |

## Rollout 流程（measure → decide →（若值得）enforce）

```
Phase 0  R0a 廉价先验：grep 现有 stderr/WebUI 日志，数 would_skip_* 数量级（~1h）
              │
       触发信号够多吗？──否──► 终止：记录负结论（enforce 几乎不触发），不建 R0
              │是
              ▼
Phase A  R0 持久化 would_skip_*/skipped_* → events.db（去重 policy_skip↔failed）
         R2 per-channel 面板（模式/would-skip/readiness，源=events.db）
         R5a 退化频道【主动外推】告警（observe 也发，不依赖 enforce）★独立收益
         R1 用真实数据判 readiness（含预先承诺的 kill 数字）
              │
       readiness 判定值得 enforce？──否──► 留 observe；R5a 已交付收益，本轮收工
              │是
              ▼
Phase B  R6 选无-fallback 频道（按所选频道可达 gate 收窄成功判据）
         R3 最小 enforce-allowlist  ·  R4 一键回滚  ·  R7 enforce skip 响亮外推
         （损坏态→降级回 observe+告警〔已定案〕；告警读 events.db 不读故障源；首次拦截须自然发生）
```

## Requirements

### Phase 0 — 廉价先验（先 grep，再决定建不建持久化层）
- R0a. 先对现有 stderr / WebUI 捕获的日志做一次 `would_skip_*` 计数（约 1 小时），得出「可见历史
  里 enforce 本来会触发几次」的数量级。若「几乎不触发」，本轮在此终止并记录负结论，**不建 R0**。
  仅当信号足够、值得可查询历史时才进 Phase A 的 R0。（理由：低流量 + 39/40 频道熔断本就诚实，
  最可能结论是 near-null；先花 1 小时验证，别先建持久化层。）

### Phase A — 测量 + observe 期收益（无条件；不依赖 enforce 决策）
- R0. 持久化 `would_skip_policy` / `would_skip_circuit` 及实际 `skipped_policy` /
  `skipped_circuit_open` 进 `events.db`（新 event kind + projector）。
  - **去重（feasibility 强约束）**：enforce skip 目前经 `_engine` 的 `checkpoint.POLICY_SKIP`
    投影成 `PUBLISH_FAILED`，会被 `success_rate.py` 当 failure。R0 必须特判 `error_class=policy_skip`，
    避免一次 skip **既算 failure 又算新 skip kind**（否则与「skips 不计入成功度量」自相矛盾）。
  - per-channel 归组是 `payload_json` 读取（events.db 无 platform 栏）；新 kind 的 REQUIRED_FIELDS
    须含 `platform`。
  - 历史从 R0 上线起累积；**决定是否从日志回填**（否则 R1/R2 上线后要等 D 天才有数据，且单机
    睡眠会在 observe 流里留洞）。
- R2. per-channel 面板（挂 `/health` 旁）：当前模式、observe 期 `would_skip_*` 次数（源=R0）、
  readiness 状态。
- R5a. **退化频道主动外推告警（observe 模式也发，独立于 enforce 决策）**：频道被 ban / 选择器漂移
  / 熔断跳闸时，**主动推播**（operator 无需开任何面板）。这条是本轮**保底的 operator 收益**——
  即使最终判定不值得 enforce，它也独立兑现「不必肉眼盯退化频道」。
  - 走 operator 既有**外部 TG-bot 告警栈**（读 events.db）；**本仓库内的范围仅限发出结构化
    event/信号，不在仓内造通知子系统**（cross-repo 边界要写清）。
  - 必须是**外推（interrupt-driven）**，不可降级成「面板红点要 operator 自己来看」（否则只是把
    保姆式盯梢换个界面）。
  - **去重/冷却/ack 契约**：同频道同原因冷却窗内只推一次（首次推、后续静默累计、恢复或新原因再推）
    + ack/snooze 入口。防单维护者因每 run 重复推播而整条静音。
- R1. 用 R0 数据定义 per-channel enforce-readiness。**框架在本轮范围内**；数值阈值（N attempts /
  D days）延到规划按真实数据校准；低流量下退化为 operator 质性判断。
  - **预先承诺一个 kill 数字**：触发率低于此即接受负结论、不 enforce（避免「机器都建了就硬开」）。

### Phase B — enforce 翻转（gated on R1 判定「值得」；否则整段不做）
- R3. 最小 **enforce-allowlist**（一组被 enforce 的频道名，其余默认 observe/off），穿过
  `policy_mode()` / `policy_enabled()` 呼叫点（已确认 src dispatch 仅 `_resume` + `_engine` 两处
  + `publish_with_policy` chokepoint）。不建完整 per-channel 模式矩阵。
- R4. 可逆：单一安全操作切回 observe/off；enforce 不在坏结果后静默续留。
- R6. 首个目标 = **无-fallback 频道**（per-platform 熔断本就诚实，无需 per-adapter 改造）。
  - **gate 可达性（feasibility）**：健康闸门（→`skipped_policy`）只对 browser-tier
    `{medium,velog,devto,mastodon}` 触发；无-fallback 中唯一 browser-tier 是 **mastodon**。其余
    无-fallback 频道（API-tier）只可能触发 `skipped_circuit_open`。成功判据须按所选频道**实际可达
    的 gate** 收窄（想要 `skipped_policy` 证据就选 mastodon）。
  - **局限声明**：无-fallback 频道的胜利只验证 rollout 机制（allowlist / 告警 / 回滚），**不能
    推广**到 fallback 频道（Medium）或广泛 enforce——泛化性是 Follow-up 的明确开放问题。
- R7. enforce skip 必须「响亮」**且告警与故障源解耦**：
  - 所有告警（R5a）与 enforce skip 的「响亮」一律读 **events.db 里 dispatch seam 当下写入的
    事件**（`skipped_*` / `degraded` / `circuit_state_unreadable`），**绝不即时重读可能损坏的
    `publish-circuit-state.json`**——故状态档损坏不可能让告警变哑（Blocker 2 已定案）。
  - **损坏态降级（Blocker 1 已定案，operator decision 2026-06-15）**：enforce 下区分两种情况——
    (a) **有效 OPEN 跳闸**（`tripped=True` + 有效 `tripped_at_iso`）→ 照常 skip（语义不变）；
    (b) **损坏哨兵**（`tripped=True` 但 `tripped_at_iso is None`，或 `_get_state` 读取抛异常）
    → **不 skip，降级回 observe（这一次照发）+ 发独立 `circuit_state_unreadable` 响亮告警**。
    observe 模式行为完全不变。理由：「读不到 state」≠「平台被 ban」；下行有界（仅放行一次、若真
    被 ban 则下次带有效时间戳重新跳闸、自愈），优于原行为的「无界静默全停 + 无 cooldown 自恢复」。

## Success Criteria

- **量到了（Phase A 保底）**：R0a/R0 后，operator 能查到「过去 N 天，每条频道 enforce 本来会
  skip 几次」——enforce 的价值（或「触发率太低不值得」的负结论）有数据支撑。
- **退化频道不再靠肉眼（Phase A 保底，独立于 enforce）**：一条被 ban/漂移/跳闸的频道会**主动
  推到 operator**，不必开面板才发现。这条即使走负结论路径也成立。
- **第一次被信任的拦截（Phase B，仅当 enforce 翻转）**：reliability enforce 由**自然发生**的 trip
  （真实连续错误 / ban / session 过期）真的 skip 了一次本会徒劳的发佈，有持久化的
  `skipped_*` 事件为证，**且 operator 收到外推告警**。
  - **真实性条款**：fault-injected `trip()` 只验证接线（acceptance test），**不计入**价值判据；
    价值判据须由生产中自然 trip 满足。
  - 证据用所选频道**实际可达的 gate**（mastodon 可有 `skipped_policy`；API-tier 无-fallback 频道
    只有 `skipped_circuit_open`）。
- 面板 per-channel 显示模式 + would-skip 次数 + readiness，数据来自 `events.db`（非日志）。
- **非功劳项**：重复发佈安全由 dedup gate（`DEDUP_ENFORCE`）保证，是非回归前置约束，不计入
  reliability enforce 成功度量。

## Scope Boundaries

- 不新增平台 / adapter；不翻转 `dofollow="uncertain"` 频道。
- **不做 per-adapter 熔断 / 不扩张 fallback 白名单**（见 Follow-up）。
- 不做统一 pooled HTTP client（上一轮已否决）。Medium **active probe 保持 OFF**。
- enforce 是 **operator 确认制**，不自动翻转（见 Key Decisions 的 slice-1 退出条件）。
- 不重设熔断阈值 / cooldown-only 恢复模型；不碰 dedup gate 逻辑。
- **不在仓内造通知子系统**：R5a 只发信号给外部 TG-bot 栈。
- **R8（≥50% liveness cadence）/ R9（selector-drift 排程）移出 enforce 关键路径**：R1 的 enforce
  决策用 R0 的 would-skip 计数，**不用** liveness 覆盖率，故二者不喂 enforce gate。降为
  Follow-up（仅作 `/health` 面板的信号新鲜度支援，非本轮 enforce 前置）。

## Key Decisions

- **测量与翻转切开（pass-2）**：Phase A 无条件交付测量 + R5a observe 期收益；Phase B（enforce）
  gated on R1 数据判定值得。理由：避免在没数据前预建 enforce 路径；让最可能的「负结论」也带一个
  真实 operator 收益（R5a）。
- **廉价先验先行（R0a）**：建 events.db 持久化前先花 ~1h grep 现有日志验证「是否值得建」。
- **首个 enforce 目标 = 无-fallback 频道**：避开「fallback 成功重置计数器」（唯一对 Medium 成立），
  让第一个胜利不被 per-adapter 重构阻塞；但明确其不泛化。
- **Per-channel 用最小 allowlist**：单维护者、确认制、一次一条，最简表示 + R4 一键回滚。
- **operator 确认制是 slice-1 信任手段，非稳态**：退出条件——首条 enforce 频道稳态 ≥D 天且零误跳后，
  评估批量晋升 / 半自动翻转，避免 ~40 频道逐条确认变成新的保姆式盯梢（Follow-up）。
- **重复发佈安全归 dedup gate**，成功判据据此改写。
- **损坏态降级（Blocker 1，operator decision 2026-06-15）**：enforce 下「读不到 circuit state」
  （损坏哨兵：`tripped=True` 但无 `tripped_at_iso`，或读取抛异常）**降级回 observe（照发一次）+ 发
  独立响亮告警**，而非静默 skip。区分「有效 OPEN 跳闸（→skip）」与「state 不可读（→降级）」——
  后者是基础设施故障，不是平台被 ban。取「下行有界、自愈」胜过「无界静默全停」。observe 行为不变。
- **告警源解耦（Blocker 2，已定案）**：所有 operator 告警读 events.db 里 dispatch seam 写入的事件，
  不即时重读可能损坏的 `circuit-state.json`——确保故障源损坏时告警仍响（「响亮」不与故障同源）。

## Dependencies / Assumptions

- 建立在 `06-15-001`（completed）：observe 模式、`transient_policy.py` 分类器、
  `reliability/events.py` 的 `would_skip_*`（**仅 stderr**）、B2 成功率 metric、B1 recheck、
  B3 selector-drift 检查均已存在。events/ 包已有「新 kind + projector」成熟范式（如 LINK_RECHECKED /
  REFERRAL_OBSERVED 直接 append），R0 是已知配方而非异类。
- ⚠️ `transient_policy.py` 的 module docstring **已过时**（仍写 NOT yet wired / ships EMPTY），
  实际 dispatch 已调 `classify_transient` 且 Medium transition 已白名单。**规划以代码为准**。
- R5a 依赖 operator 单机的**外部 TG-bot 告警栈**（仓外）；仓内只发信号。
- 单维护者 / 低流量（~1–10 backlinks/run，全库 ~1726 links）。
- 熔断/健康 store 严格 **per-platform** keyed；本轮**刻意不动**（这正是避开 per-adapter 重构的关键）。
- launchd 排程在 operator 单机；睡眠会让排程静默失效（影响 observe 流连续性与任何 cadence）。

## Outstanding Questions

### Resolve Before Planning
（已全部解决，见 Key Decisions 的「损坏态降级」与「告警源解耦」两条；Phase B 无剩余前置 blocker。
规划可直接进行。）

### Deferred to Planning
- [R0a] grep 口径：扫哪些日志、时间范围、判「够多」的阈值。
- [R0] 新 kind 的 schema + projector + 保留窗口；`policy_skip↔PUBLISH_FAILED` 去重的落点；是否回填历史。
- [R1] 临时 readiness 下界数值 + 「低流量→质性」切换条件 + **预先承诺的 kill 数字**——待 R0 数据校准。
- [R3] enforce-allowlist 落地形式（config.toml vs env）与穿过呼叫点的改造范围。
- [R5a] channel-of-record：哪些 event kind 触发外推、推到哪个 TG chat/topic、in-process 直推还是
  外部栈读 events.db、去重/冷却/ack 的具体形式。
- [R6] 「无-fallback 频道」精确判定（`CROSS_MECHANISM_FALLBACK` + registry publishers）+ 首个目标选定
  （想要 `skipped_policy` 证据 → mastodon）。

### Deferred to Follow-up Iteration（明确不在本轮，记录 gate 条件）
- **per-adapter 熔断诚实性**（旧 R5/R6）：当一条**有-fallback 频道**（当前唯一 Medium）成为 enforce
  候选时启动；届时解决「被 fallback 绕过的 primary 如何 recovery/skip」+ per-adapter 计数器落点。
- **cross-mechanism fallback 白名单扩张**（旧 R7/R8）：需先有 **kill/park 判据**——估每条候选
  transition 期望救回数（transient 率 × runs × links/run）对比一次重复发佈的不可逆代价；若期望
  < ~1/月，结论为「保持 Medium-only / FAIL_FAST 是正确稳态」，仅产出 addressable-set 文档。
- **≥50% liveness cadence（旧 R8）/ selector-drift 排程（旧 R9）**：作 `/health` 信号新鲜度支援，
  非 enforce 前置。含 cadence×预算算术（weekly→daily？）与 static-vs-attended 排程职责。
- **enforce 稳态自动化**：confirm-each-channel 的退出（批量晋升 / 半自动翻转）。

## Next Steps

→ `/ce:plan` for structured implementation planning（建议 plan 按 Phase 0 → A → B 分阶，Phase B
作为 gated 段落。两条 Phase B blocker 已定案并并入 R7 / Key Decisions，无剩余前置——规划可直接开始）
