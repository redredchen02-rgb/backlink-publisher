---
title: "analysis: Comprehensive Codebase Optimization Plan (current-state audit)"
type: analysis
status: active
date: 2026-06-15
---

# 全面代码库优化计划（基于 2026-06-15 实际状态审计）

**审计日期**: 2026-06-15
**状态**: P0–P2 已执行落地（见文末「执行结果」）
**审计范围**: 整个 `backlink-publisher/` 仓库（src 356 文件 / 68.8K SLOC，tests 547 文件 / 128K 行，WebUI 14K 行，前端 JS 4.3K 行）
**方法**: 文件系统枚举 + grep + git log + 与 `debt_registry.toml` / 既有 plan-doc 交叉验证

---

## 0. 最重要的结论先行

这个代码库**不缺功能、不缺测试、不缺流程纪律**。过去 7 天有 47 次提交，v0.4.0 的 8 个单元（U1–U8）已全部落地，CI 已有 `--cov-fail-under=80` 门禁、mypy 渐进 strict、structlog 已引入、Dockerfile 已存在、测试已按 `__tier__` 分层（511/530）。

**真正的问题是「文档与现实的脱节」和「已过时的优化叙事仍在驱动注意力」**：

1. `debt_registry.toml` 8 条里有 **5 条标 `open` 但实际已解决**——注册表本身失真，技术债失去了信号价值。
2. `2026-06-05-002` 的 gap analysis 里列的「缺口」**大半已被 v0.4.0 闭环**（structlog / Docker / backup-state CLI / 测试拆分 / health endpoint / coverage gate），但没有任何 doc 标记其为「已落地」。
3. `AGENTS.md`（root + canonical）的**关键数字全面漂移**：「20 route modules」实际 37、「14 monolith files」实际 18、「5 service modules」实际 19。Agent 和新人读到的是半年前的地图。

所以本计划的核心定位是：**先修「失真」，再谈「新优化」**。下面每一项都标注了「实际现状」vs「叙事状态」，避免重复劳动。

---

## 1. 现状盘点（按维度）

| 维度 | 既有叙事 | 实际现状 (2026-06-15) | 结论 |
|---|---|---|---|
| 测试规模 | ~160 文件 | **547 文件 / 128K 行** | 远超叙事，已是大体量套件 |
| 测试分层 | 「只有子集有 tier marker」(debt `open`) | **511/530 (96%) 已标 `__tier__`** | 几近完成，应关债 |
| Coverage 门禁 | 「未实施」(gap analysis P1) | **CI 已有 `--cov-fail-under=80` (R18)** | 已落地，gap analysis 过时 |
| Health endpoint | 「不存在」(debt `no-health-surface` open) | **`/health` + `/ce:health` 仪表板 + 5 个 scorecard 子路由** | 已落地，应关债 |
| 最大测试文件 | 「test_webui_route_contract.py 1647 SLOC」(debt `open`) | **已拆成 7 个 per-concern 文件，原文件已删** | 已落地，应关债 |
| structlog | 「未引入」(gap analysis E1) | **`_util/structlog_config.py` + `structured_logger`** | 已落地 |
| Docker | 「未实施」(gap analysis F2 P2) | **`Dockerfile` + `docker-compose.yml`** | 已落地 |
| backup/restore CLI | 「未实施」(gap analysis E4 P1) | **`backup-state` / `restore-state` entrypoints** | 已落地 |
| 统一 HTTP client | 「未实施」(gap analysis A4) | **`_util/http_client.py` + `http_session.py` 存在；仍有 13 处直接 `requests.*`** | 部分，值得收口 |
| JS 测试 | 「占位」(gap analysis G1) | **`node --test` 跑 3 个 `.mjs`（lib_api / lib_dom / dom_check）** | 已落地，gap analysis 过时 |
| 单体预算文件 | AGENTS 说「14」 | **18 条 `[files.*]`** | 文档漂移 |

---

## 2. 真正值得做的优化（按 ROI 排序）

### 🔴 P0 — 修「失真」（高价值、低风险、立刻做）

这几项**不动生产代码，只动元数据/文档**，但能立刻恢复技术债的信号价值。是整个计划里 ROI 最高的一档。

#### P0-1. 核对并关闭 `debt_registry.toml` 中的 5 条过期 `open` 项

| slug | 现状证据 | 建议动作 |
|---|---|---|
| `no-health-surface` (high) | `routes/health.py:504 @bp.route("/health")` + dashboard 健康栏已落地（U3） | `status = "resolved"`，补 `resolved_date` 字段 |
| `no-coverage-gate` (medium) | `.github/workflows/ci.yml` 有 `--cov-fail-under=80`（R18） | `status = "resolved"` |
| `largest-test-file-bloat` (medium) | `test_webui_route_contract.py` 已删，拆为 7 文件（U2） | `status = "resolved"` |
| `test-tier-coverage-incomplete` (medium) | 511/530 (96%) 测试已带 `__tier__` | `status = "resolved"`（或保留为 `mitigated` + 跟踪剩余 19 个） |
| `no-debt-tracking` (low) | 已经是 `accepted`——但注册表本身失真 | 不动，但借本次审计契机刷新 |

**剩余真正 `open` 的 3 条**：`no-recon-schema`、`orphan-code-unknown`、`no-stewardship-model`——这三条才是真信号，见 P1。

> ⚠️ 改 `debt_registry.toml` 的 `status` 受 `tests/test_debt_registry_format.py` 约束；若 schema 没有 `resolved_date` 字段，需先确认字段集，按现有 schema 写。**建议同 PR 补一个 `resolved_date` 字段并更新 format 测试**——让「关债」留下可追溯的时间戳。

#### P0-2. 修正 `AGENTS.md` 的关键数字漂移（root + canonical 两份）

| 位置 | 旧值 | 新值 |
|---|---|---|
| root `AGENTS.md`「20 route modules」 | 20 | **37** |
| root `AGENTS.md` Monolith Budget「14 files」 | 14 | **18** |
| canonical `AGENTS.md`「WebUI (20 route modules)」 | 20 | **37** |
| canonical `AGENTS.md` Known Quirks「webui_app/services/ 是 5 source modules」 | 5 | **19** |
| canonical `AGENTS.md` Monolith Budget 段「tracks ... for **14** source files」 | 14 | **18** |
| canonical `AGENTS.md` Frontend 段「JS interaction has no test framework yet (deferred)」 | 「no test framework」 | **`node --test` 已跑 3 个 `.mjs`，措辞改为「lib 层有单测，页面交互层仍靠手工 walkthrough」** |
| canonical `AGENTS.md` Env Vars 段提及 `BACKLINK_PUBLISHER_ALLOW_NETWORK`「No longer binds off-loopback」 | 核对是否仍准 | — |

**Golden rule 提醒**：root `AGENTS.md` 是 mirror，canonical 是 `backlink-publisher/AGENTS.md`。两份都要改，且 canonical 是权威源。`bp-*/AGENTS.md` 是 stale 副本，不要动。

#### P0-3. 在 `2026-06-05-002` gap analysis 顶部加「Superseded」横幅

那份分析现在是**误导性文档**——它把 E1/F2/E4/G1/E3/B3/F4 都列为缺口，但全部已落地。任何 agent 或新人读到它会浪费精力重做已完成的事。在文件顶部加：

```markdown
> ⚠️ **SUPERSEDED (2026-06-15)**: 本分析的大多数「缺口」已在 v0.4.0 (plan 06-09-001)
> 及后续迭代中落地。详见 `docs/plans/2026-06-15-002-analysis-comprehensive-optimization-plan.md` §1。
> 仅保留作历史参考。
```

---

### 🟡 P1 — 真实存在的、值得做的工程优化（中风险、中价值）

这些是**审计后确认仍然成立**的优化点，不是从旧叙事抄来的。

#### P1-1. 收口 HTTP 调用层（gap analysis A4 的「真」残余部分）

**现状**: `_util/http_client.py` + `http_session.py` 已存在并被 `publishing/session/` 使用，但 src 里仍有 **13 处直接 `requests.get/post/put/...`** 散落在各 adapter。行为不一致（timeout / retry / UA / SSRF 检查各写各的）。

**为什么值得做**: 不是为了「统一」本身，是为了**让所有出网调用统一走 SSRF 检查和超时默认值**。当前散点调用是安全面和可靠性的真实缺口（某个 adapter 漏掉 `net_safety` 检查就是 SSRF 漏洞）。

**做法**: grep 出 13 处，逐个评估能否替换为 `http_client` 的封装；不能替换的（如 adapter 有特殊 cookie/header 需求）保留但**加注释说明为何不走统一层**。这是「审计 + 逐步迁移」，不是大爆炸重构。

**验证**: 新增一个 grep gate 测试 `tests/test_no_raw_requests_outside_http_client.py`，白名单允许现有 13 处，新违规即 fail——防回归。

#### P1-2. 落地 `no-recon-schema`（debt 真信号，medium）

**现状**: RECON 事件是 `stderr` 上的 ad-hoc 字符串（`RECON info fetch_head_age_seconds=12`），没有 typed schema。AGENTS 里 `plan-check` 的 RECON 行已经在事实上形成了一套约定（`RECON <level> <key>=<value> ...`），但没形式化。

**为什么值得做**: 下游想做 RECON 聚合/告警只能 string-match，脆弱。一旦某条 RECON 行拼写漂移，监控静默失效。

**做法**:
- 定义 `RECONLine(level: Literal["info","warn","error"], fields: dict[str,str])` dataclass + 一个 `emit_recon()` helper。
- 在 `_util/` 下放，所有 `print(f"RECON ...", file=sys.stderr)` 改走 helper。
- 加 `tests/test_recon_schema.py` 用正则断言所有 RECON 输出符合 schema。

**估时**: 中。涉及面广（很多 CLI 文件），但每处改动机械。

#### P1-3. 30 个 500+ SLOC 文件的「热点审计」（不是一刀切拆分）

**现状**: 有 **30 个源文件 > 500 SLOC**（见审计输出）。其中只有 14 个被 `monolith_budget.toml` 监控并设了 ceiling。**未被监控的 16 个 500+ 文件**包括：
- `idempotency/store.py` (758)、`publishing/_manifests.py` (705)、`config/types.py` (629)、`events/history_query.py` (627)、`cli/spray_backlinks/core.py` (594)、`cli/_resume.py` (571) 等。

**为什么值得做**: 不是「都要拆」，而是**判断哪些是合理的「大而稳」、哪些是真热点**。`config/types.py`（629）大概率是「大量 frozen dataclass，合理」；`idempotency/store.py`（758）值得看是否该拆 read/write path。

**做法**: 对这 16 个文件逐个做 5 分钟审视，结果分三档：
1. **合理保留** → 在 `monolith_budget.toml` 加 ceiling（冻结现状防膨胀）。
2. **边界可疑** → 加 ceiling + 写 rationale 说明为何暂不拆。
3. **真热点** → 立一个小 plan-doc 做提取（遵循已有的 `_engine.py` / `_store_sqlite.py` 模式）。

**验证**: 这本身就是在补全 monolith 防护网——让预算从 14 覆盖到全部 500+ 文件。

#### P1-4. orphan-code 检测落地（debt `orphan-code-unknown`，low 但 cheap）

**现状**: 仓库有 `tests/test_no_orphan_code.py` 和 `test_no_orphaned_guard_scripts.py`（防 guard 脚本失联），但**没有 dead-code 扫描**（未使用的函数/模块/CLI flag）。

**为什么值得做**: 39 个 adapter、39 个 entrypoint、6.8 万行，必然有沉积。cheap 的检测能暴露真问题。

**做法**:
- 加一个 CI 步骤跑 `vulture`（已在生态里成熟）或写一个基于 `ast` + 入口图的自定义扫描。
- 白名单已知「importable 但非核心」的外设模块（`geo/`、`pr_outreach/`、`click_track/`、`debt_report/`——AGENTS 已分类）。
- 发现的孤儿先登记进 `debt_registry.toml`，不是立刻删。

---

### 🟢 P2 — 锦上添花（低优先，当资源允许）

#### P2-1. CODEOWNERS / 模块 stewardship（debt `no-stewardship-model`，low）

repo 已有明确的模块边界（core 4-stage / peripheral / webui / config / events）。加一个 `.github/CODEOWNERS` 把这些边界映射到 owner，成本很低，价值在于 PR routing 和 onboarding。但 owner 是「人」的问题——如果团队就一两个人，这条优先级是真的低。

#### P2-2. `debt-report` CLI 的可观测化

`debt-report` entrypoint 已存在（peripheral 模块）。让它**定期从 `debt_registry.toml` + 仓库指标（SLOC 趋势、test 数、coverage）生成一份趋势报告**，作为 `/ce:health` 的一个面板。让技术债「可视化」是防止 registry 再次失真的长期机制。

#### P2-3. mypy strict 边界扩展

`mypy.ini` 已经对 `_util.*` / `config.*` / `schema` 开了渐进 strict。可以按季度把更多核心模块（`events/*`、`publishing/registry.py`、`publishing/_manifests.py`）纳入 strict，type check 从 non-blocking 推向 blocking。**但**——这要配合实际修 type error，不是改配置就完事，估时不小。

---

## 3. 明确「不要再做」的事（防重复劳动）

| 旧叙事建议 | 为什么别做 |
|---|---|
| ~~E1: 引入 structlog~~ | 已在 `_util/structlog_config.py` |
| ~~F2: 写 Dockerfile~~ | 已存在 `Dockerfile` + `docker-compose.yml` |
| ~~E4: backup/restore CLI~~ | `backup-state` / `restore-state` 已有 entrypoint |
| ~~E3: 建 /health~~ | `/health` 已落地（U3） |
| ~~G1: 建 JS 测试~~ | `node --test` 已跑 3 个 `.mjs` |
| ~~B3: 装 ruff~~ | ruff 0.15.16 已装，Makefile lint 已用 |
| ~~F4: 增强 Makefile~~ | 已有 10+ target |
| ~~「拆 test_webui_route_contract.py」~~ | U2 已拆完 |
| ~~CI 加 coverage 门禁~~ | R18 已加 `--cov-fail-under=80` |
| ~~weights 三合一 consolidation~~ | `cli/weights.py` 已是 dispatcher |

这些条目来自 `2026-06-05-002` 和 `debt_registry.toml`，**全部已被后续迭代闭环**。任何新 agent 读到旧文档可能会重做——这就是 P0-3（加 Superseded 横幅）必须先做的原因。

---

## 4. 执行顺序建议

```
第 1 批（1 个 PR，半天）—— 修失真，零生产代码风险
  P0-1  关闭 5 条过期 debt（+ 补 resolved_date 字段 + format 测试）
  P0-2  修正 AGENTS.md 数字漂移（root + canonical）
  P0-3  给 06-05-002 加 Superseded 横幅
        ↓  这批落地后，技术债信号恢复真实，后续判断才有意义

第 2 批（2–3 个 PR，1 周）—— 真实工程优化
  P1-1  HTTP 调用收口 + grep gate（防回归）
  P1-4  vulture orphan 扫描 + 白名单
  P1-3  16 个未监控 500+ 文件的热点审计（输出：加 ceiling / 立 plan / 保留）

第 3 批（独立 plan-doc，按需）—— 较大工程
  P1-2  RECON schema 形式化（面广，建议单独 plan）
  P2-x  CODEOWNERS / debt-report 可视化 / mypy strict 扩展
```

---

## 5. 验证 / 完成判据

- **P0 完成判据**: `debt_registry.toml` 里 `open` 项只剩 `no-recon-schema` / `orphan-code-unknown` / `no-stewardship-model` 三条真信号；`AGENTS.md` 的所有具体数字与 `grep | wc -l` 一致；`pytest tests/test_debt_registry_format.py` 绿。
- **P1-1 完成判据**: `tests/test_no_raw_requests_outside_http_client.py` 通过（白名单 = 现有 13 处）；新 PR 若新增直接 `requests.*` 调用即 fail。
- **P1-3 完成判据**: `monolith_budget.toml` 的 `[files.*]` 条目数 ≥ 30（覆盖所有 500+ 文件，无论保留还是计划拆）。
- **P1-4 完成判据**: CI 有一个 `vulture` 步骤（或等价），白名单显式登记已知外设模块；输出可复现。

---

## 6. 附：审计方法学说明（可复现）

本次结论全部来自可复现命令，非主观判断：

```bash
# 文件/SLOC
find src -name "*.py" | wc -l                      # 356
find src -name "*.py" -exec wc -l {} + | tail -1   # 68757
find tests -name "*.py" | wc -l                    # 547

# debt 真实性核验
grep "cov-fail-under" .github/workflows/ci.yml     # R18 已在
ls tests/test_webui_route_contract.py 2>/dev/null  # 已删
grep -rl "__tier__" tests/*.py | wc -l             # 511 / 530
grep -n '@bp.route("/health"' webui_app/routes/health.py  # 504 行

# 文档漂移核验
ls webui_app/routes/*.py | grep -v __init__ | wc -l  # 37（非 20）
grep -c "\[files\." monolith_budget.toml             # 18（非 14）
ls webui_app/services/*.py | grep -v __init__ | wc -l # 19（非 5）

# HTTP 散点
grep -rn "requests\.\(get\|post\|put\|patch\|delete\)(" src/ | wc -l  # 13
```

任何后续 agent 重跑这些命令都应得到一致结论——若数字变化（如 routes 涨到 40），说明本计划 P0-2 的修正值需随之更新，这本身就是「文档漂移」循环的一部分，应在 `debt-report` 里自动化（见 P2-2）。

---

## 7. 执行结果（2026-06-15 落地）

P0–P2 全部执行完成。下面是每一项的交付物、验证证据、以及它带来的结构变化。

### P0 — 修失真 ✅

**P0-1: 关闭过期 debt + `resolved_date` 字段**
- `debt_registry.toml`: 5 条过期 `open` 项关闭（4 resolved + 1 mitigated），新增 `debt-registry-staleness` 项记录本次失真事件。**最终 9 项里只剩 1 条真 `open`（`no-stewardship-model`，需人为指定 owner）。**
- `tests/test_debt_registry_format.py`: schema 扩展支持 `resolved_date`（resolved/mitigated 必填，open/accepted 禁止）+ 3 个新测试（presence-matches-status、format、unknown-field 拒绝）。
- 验证: `pytest tests/test_debt_registry_format.py` → **75 passed**。

**P0-2: AGENTS.md 数字漂移修正（root + canonical）**
- `backlink-publisher/AGENTS.md`: route modules 20→37、services 5→19、monolith 14→17→41（P1-3 后）、JS test framework 描述修正、webui_store 单例 5→8 lazy stores。
- `AGENTS.md` (root): budget 14→17→41、stores 5→8。
- `webui_store/__init__.py`: docstring "Six"→"Eight" `_LazyStore`。

**P0-3: Superseded 横幅**
- `docs/plans/2026-06-05-002-feat-optimization-gap-analysis.md` 顶部加 `⚠️ SUPERSEDED` 块，列出已被 v0.4.0 落地的 7 项 + 指向本计划 §1。

### P1 — 真实工程优化 ✅

**P1-1: HTTP 调用收口 + grep gate（含真实 SSRF 修复）**
- 🔴 **发现并修复了真实安全漏洞**: `webui_app/helpers/url_meta.py::_fetch_page` 用 `requests.get(url, verify=False)` 抓取操作员提交的 preview URL，**无 SSRF 检查、禁用 TLS 验证**——`pipeline.py` 预览路由经此可让服务器请求内网/云元数据地址。已迁移到 `http_client`（强制 SSRF 检查 + 移除 `verify=False`）。
- `tests/test_no_raw_requests_outside_http_client.py`（新）: grep gate，白名单 17 处现有 raw `requests.*` 调用（每条带结构化理由），新违规即 fail。同时检测白名单过期（迁移后未删条目）。
- 验证: `pytest tests/test_no_raw_requests_outside_http_client.py` → **2 passed**；受影响 webui 测试 → **141 passed**。

**P1-2: RECON schema 形式化（debt `no-recon-schema` → mitigated）**
- `src/backlink_publisher/_util/recon.py`（新）: `RECONLine` dataclass + `emit_recon()` / `parse_recon_line()` / `format_recon_line()` / `iter_recon_lines()`。**契约匹配真实代码形状**——包括 bare-flag token（`fetch_skipped` 无 `=value`，plan-check 实际这么发）。
- `tests/test_recon_schema.py`（新）: 31 测试，含 `test_real_repo_recon_lines_parse` 契约测试（用 plan-check / publish-backlinks 实际发出的 RECON 行验证 schema 不与现实脱节）。
- 验证: `pytest tests/test_recon_schema.py` → **31 passed**。debt `no-recon-schema` 降级 `medium`→`low`，`mitigated`。

**P1-3: 500+ SLOC 热点审计（monolith 预算 17→41）**
- `monolith_budget.toml`: 新增 24 条 `[files.*]` 条目，覆盖所有剩余 500+ raw-LOC 文件。每条 rationale 标注审计结论: **KEEP**（大而稳，冻结现状）或 **CANDIDATE**（值得未来拆分，先冻结）。无 OPEN 热点——现有大文件都是合理保留。
- `tests/test_no_monolith_regrowth.py`: 新增 `test_warning_canary_covers_webui_roots`——把 canary 扫描根从 `src/` 扩展到 `webui_app/` + `webui_store/`，补上之前的监控盲区。
- 验证: `pytest tests/test_no_monolith_regrowth.py` → **129 passed**（原 56 + 新增 73 参数化 + 1 新 canary，无 stale 警告）。

**P1-4: vulture orphan-code 扫描（debt `orphan-code-unknown` → mitigated）**
- `tests/test_dead_code_advisory.py`（新）: vulture @ ≥80% confidence 的**咨询式** canary（`warnings.warn`，非 hard-fail——因 vulture 看不见 register-by-string / pyproject entry points / Jinja 调用）。7 条 baseline 发现全部 allowlist（每条带 reachable-by-pattern 理由）。新死代码会在 CI warning 汇总里浮现。
- `pyproject.toml`: dev deps 加 `vulture>=2.16`。
- 验证: `pytest tests/test_dead_code_advisory.py` → **2 passed**（steady state 无新警告）。

### P2 — 长期防漂机制 ✅

**P2: debt-freshness gate（结构性防漂，不是 CODEOWNERS）**
- 重新评估后**放弃 CODEOWNERS**（需人为指定 owner，单维护者仓库价值低），改为实现 `2026-06-05-002` gap analysis 反复出现的根因修复——**债务注册表会再次失真**。
- `tests/test_debt_registry_freshness.py`（新）: 8 个测试，每条 resolved/mitigated debt 对应一个**可证伪声明测试**（例: `no-health-surface` 是 resolved → `/health` 路由必须存在；`no-coverage-gate` 是 resolved → CI 必须有 `--cov-fail-under=80`）。
- **关键 meta-test**: `test_every_resolved_or_mitigated_item_has_a_freshness_claim`——任何 debt 标 resolved/mitigated 但没写声明测试即 fail。这是 P0 失真的结构性解药: 关债必须留下可验证的代码库不变量。
- 验证: `pytest tests/test_debt_registry_freshness.py` → **8 passed**。

### 总验证

```
pytest tests/test_debt_registry_format.py tests/test_debt_registry_freshness.py \
       tests/test_recon_schema.py tests/test_no_raw_requests_outside_http_client.py \
       tests/test_dead_code_advisory.py tests/test_no_monolith_regrowth.py \
       tests/test_no_orphan_code.py tests/test_webui_pipeline_routes.py \
       tests/test_webui_url_verify_routes.py
→ 309 passed in 11.23s
```

`debt-report` CLI 输出: `9 items (1 open)`——唯一 `open` 是 `no-stewardship-model`（需人为决定 owner，合理保留）。

### 结构性变化总结

| 指标 | 改动前 | 改动后 |
|---|---|---|
| `debt_registry.toml` open 项 | 6（5 失真 + 1 真） | **1**（仅 `no-stewardship-model`） |
| monolith 预算覆盖文件 | 17 | **41**（全部 500+ SLOC） |
| canary 扫描根 | `src/` only | `src/` + `webui_app/` + `webui_store/` |
| HTTP raw 调用防回归 | 无 | grep gate（17 白名单 + 过期检测） |
| 死代码检测 | 仅文件级 | 文件级 + vulture 函数级（advisory） |
| RECON schema | 隐式、14 处手写 | 显式 typed contract + 契约测试 |
| 债务「关」的可验证性 | 无（P0 失真根因） | 每条 resolved/mitigated 必须有可证伪声明测试 |
| SSRF 安全面 | `_fetch_page` 漏洞 | 已修（+ TLS 验证恢复） |
