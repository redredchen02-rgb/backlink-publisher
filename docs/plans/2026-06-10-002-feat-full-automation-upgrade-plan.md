---
title: "feat: 全链路自动化升级计划"
type: feat
status: active
date: 2026-06-10
origin: workspace-root operator request
claims:
  paths:
    - src/backlink_publisher/publishing/registry.py
    - src/backlink_publisher/optimization/
    - src/backlink_publisher/cli/weights.py
    - src/backlink_publisher/cli/optimize_weights.py
    - src/backlink_publisher/cli/collect_signals.py
    - src/backlink_publisher/cli/plan_backlinks/
    - webui_store/campaign_store.py
    - webui_app/campaign_worker.py
    - webui_app/routes/
    - webui_app/templates/
    - scripts/run-full-pipeline.sh
    - scripts/com.dex.bp-*.plist
  shas:
    - HEAD
---

# 全链路自动化升级计划

> 将 backlink-publisher 从「半自动脚本工具」迭代为「闭环自动化发布系统」。
> 基于六个维度全面升级：优化闭环 → 智能调度 → 批量战役 → 故障自愈 → 运营可视化 → 双语运营体系化。

---

## 0. 现状全景

### 0.1 已实现的自动化

| 组件 | 状态 | 描述 |
|---|---|---|
| `run-full-pipeline.sh gap` | ✅ 生产 | launchd 每日 4:00 触发：equity-ledger → plan-gap → plan → validate → publish |
| `run-recheck-periodic.sh --probe` | ✅ 生产 | launchd 每周一 4:30 触发：recheck-backlinks 存活率探针 |
| `run-optimization.sh` | ⚠️ dry-run 模式 | launchd 每 6 小时触发 collect-signals + optimize-weights，**从未实际写入权重** |
| `com.dex.bp-keepalive` | ✅ 生产 | WebUI keepalive + 健康检查 |
| weights CLI | ✅ 已实现 | `weights collect` / `optimize` / `show` 三个子命令均已完成 |

### 0.2 已设计但未实现的系统

| 计划 | 复杂度 | 当前状态 |
|---|---|---|
| CampaignStore + CampaignWorker（批量战役） | 中等 | 设计已完成（482 行 plan，6 units），**零代码实现** |
| continuous-optimization rules engine（Rule 3+） | 中等 | CLI 骨架完成，Rule 1/2 已实现，但未接入 plan-backlinks 的 `preferred_dispatch()` |
| 双语权重分离 | 新设计 | 从未设计或实现 |
| 运营 Dashboard | 新设计 | `/health` 有 canary / publish-path 卡片，但无管线健康总览 |

### 0.3 当前运营参数

| 参数 | 值 |
|---|---|
| 发布频率 | 每日 4:00 一次（约 3-5 行 seed） |
| 平台数 | 20 注册，实际活跃 ~5-8 |
| 语言 | zh-CN（BP_LANG=zh-CN 硬编码） |
| 发布模式 | draft（暂存草稿，非直接 publish） |
| 调度方式 | launchd plist（macOS 原生定时器） |
| 日志 | 纯文本文件，无结构化日志 |
| 故障处理 | bash 脚本 `set -euo pipefail`，失败就失败，无重试 |

---

## 1. 优化目标

将当前「定时跑脚本 → 出结果 → 人工判断」的模式转变为：

```
定时检测 gap
  → 有 gap? 自动跑管线
    → 发布完成 → 自动优化权重
      → 权重影响下次发布决策
        → 反馈循环闭合

无 gap? 跳过（不浪费资源）
```

**关键指标**：

| 指标 | 当前 | 目标 |
|---|---|---|
| 人工介入频率 | ~每周回看 weights + 检查发布状态 | 零日常介入（仅异常告警） |
| 发布决策依据 | 固定平台顺序 | 动态权重（存活率/成功率/语言适配度） |
| 调度粒度 | 每日 1 次 | 自动按 gap 密度调整频次 |
| 故障恢复 | 人工重跑（检查日志 → 定位问题 → 重试） | 自动重试 + 断点续跑 |
| 运营可见性 | 翻 logs + events.db 查询 | WebUI 仪表盘实时可见 |

---

## 2. 阶段一：关闭优化循环（Phase 0 — 立即可做）

**目标**：让 `optimize-weights` 真正写入权重，并且 `plan-backlinks` 的 `preferred_dispatch()` 读取这些权重。

**现状评估**：
- `weights collect` ✓ 已实现 — 从 recheck/canary/equity 收集信号
- `weights optimize` ✓ 已实现 — Rule 1（canary drift → 0.5^strikes）和 Rule 2（recheck survival → 1.2x cap 3.0）均已完成
- `weights show` ✓ 已实现
- `publishing/registry.py` 的 `preferred_dispatch()` **未读取** `optimization_state.json` — 这是单行代码缺口

### U1.1 `preferred_dispatch()` 接入动态权重

**文件**：`publishing/registry.py`

修改 `preferred_dispatch()`，在排序前加载 `optimization_state.json`，用 `current_weight` 代替 `base_weight` 排序。

```python
def preferred_dispatch(adapter_names, ...):
    # Existing: sorted(adapter_names, key=lambda x: -dispatch_weight(x))
    # New:
    state = _load_optimization_state()
    def sort_key(name):
        base = dispatch_weight(name)
        dyn = state.get_weight(name, base)
        return -dyn
    return sorted(adapter_names, key=sort_key)
```

- `state.get_weight()` 返回 `current_weight` 存在时用它，否则返回 `base_weight`
- `optimization_state.json` 不存在或损坏 → 静默 fallback 到 base_weight（日志 WARN）
- 日志 INFO 当 weight 偏离 base 超过 10% 时输出

**验收**：设置一个测试权重 → `plan-backlinks` dry-run → 平台顺序反映权重

### U1.2 `optimize-weights` 移除 `--dry-run` 默认

**文件**：`scripts/run-optimization.sh`、`cli/optimize_weights.py`

当前 `run-optimization.sh` 中对 `collect-signals` 和 `optimize-weights` **不传参数**——这意味着它们用的是 CLI 默认值。需要确认默认行为：

- `collect-signals` 默认行为：读取 recheck/canary/equity 数据 → 合并到 `optimization_state.json`
- `optimize-weights` 默认行为：`--dry-run` 为 False 时写入，True 时预览

**操作**：
1. 修改 `run-optimization.sh`：默认移除 `--dry-run`（生产模式写入）
2. 保留 `--dry-run` 在 CLI flag 中供调试
3. 新增 `--safety-gate`：写入前做合理性检查（权重不应全为 0，不应突变 > 5x）

**安全门（safety gate）**：
```
[optimize-weights] safety check:
  - 如果 >50% 的平台 current_weight = 0 → ABORT（可能是全平台故障）
  - 如果某个平台 weight 相比上次变化 > 5x → WARN + 跳过该平台
  - 如果 total published < 10 → 数据量太少，WARN 但不阻止
```
所有安全检查可被 `--force` 跳过。

### U1.3 新增 Rule 3: 存活率统计阈值

**文件**：`optimization/rules.py`

Rule 3 利用累积的 `stats`（published_count / alive_count / dofollow_count）对平台进行渐进优化：

```python
class SurvivalThresholdRule(BaseRule):
    """基于统计阈值的权重调整。
    
    条件: total_published >= min_samples (默认 5)
    
    调整:
      - survival_rate (alive/published) < 30% → weight *= 0.3
      - dofollow_rate (dofollow/alive) < 20%  → weight *= 0.4
      - survival_rate > 80% AND dofollow_rate > 80% → weight *= 1.15 (cap 3.0)
    """
```

**验收**：mock stats 测试三种子场景（低于阈值 / 高于阈值 / 数据不足）

### U1.4 Canary cooldown auto-recovery

**文件**：`optimization/rules.py`

当前 Rule 1（CanaryDriftRule）将 weight 设为 0.0 后永久保持。新增 cooldown 逻辑：

```
max_strikes (默认 3) → weight = 0
cooldown_days (默认 7) → 此期间不调整
cooldown 到期后 → weight 恢复为 base_weight * 0.3（慢启动，不是瞬间回到 1.0）
```

**验收**：mock 7 天前的 weight=0 条目 → 恢复后 weight = 0.3 * base

### U1.5 双语权重分离（Phase 1 基础）

**文件**：`optimization/state.py`、`optimization/models.py`

当前 `optimization_state.json` 的 schema 是扁平的 per-platform 权重。双语运营下，同一平台在 zh-CN 和 en 场景下的表现可能不同（比如 dev.to 英文文章存活率高、中文存活率低）。

```json
{
  "version": 2,
  "weights": {
    "zh-CN": {
      "blogger": { "base": 1.0, "current": 0.8, ... }
    },
    "en": {
      "devto": { "base": 1.0, "current": 1.2, ... }
    }
  }
}
```

- `collect-signals` 需要按语言收集（当前 recheck-backlinks 已经有 language 字段）
- `optimize-weights` 按语言分别评估规则
- `preferred_dispatch()` 接收 `language` 参数，加载对应语言的权重

**向后兼容**：如果 `optimization_state.json` 是旧版 flat schema → 自动包装为 `{"default": {...}}`，所有语言共享。

### U1.6 阶段一验证

```bash
# 1. 设置测试权重
echo '{"version":1,"weights":{"blogger":{"base":1.0,"current":0.1}}}' > optimization_state.json

# 2. plan-backlinks dry-run 验证顺序反映权重
cat fixtures/seed.jsonl | plan-backlinks --dry-run 2>&1 | grep "preferred_dispatch"

# 3. 关闭 dry-run
bash scripts/run-optimization.sh

# 4. 验证权重已写入
weights show
```

---

## 3. 阶段二：智能调度系统

**目标**：从「固定每日 4:00」进化为「按 gap 检测频率自动调度 + 节流控制」。

### U2.1 Pipeline Orchestrator (Python)

**文件**：
- 创建：`cli/pipeline_orchestrator.py`
- 修改：`scripts/run-full-pipeline.sh`（瘦身成调用 orchestrator 的 thin wrapper）

现状的 `run-full-pipeline.sh` 是 166 行 bash，管道控制流在 shell 层面。将其核心逻辑迁移到 Python：

```python
# cli/pipeline_orchestrator.py
def run_pipeline(config: PipelineConfig) -> PipelineResult:
    """执行一次完整管线，返回每步的状态。"""
    steps = [
        ("equity-ledger", _run_equity_ledger),
        ("plan-gap", _run_plan_gap),
        ("plan-backlinks", _run_plan_backlinks),
        ("validate-backlinks", _run_validate_backlinks),
        ("publish-backlinks", _run_publish_backlinks),
        ("recheck-backlinks", _run_recheck_backlinks),
        ("optimize-weights", _run_optimize_weights),
    ]
    results = []
    for name, fn in steps:
        result = fn(config)
        results.append(result)
        if not result.success and result.fatal:
            break  # 致命错误停止管线
    return PipelineResult(steps=results, ...)
```

关键设计：
- 每步可单独 **跳过**、**重试**、**标记 fatal/non-fatal**
- `publish-backlinks` 失败是 non-fatal（不影响其他步骤）
- `plan-gap` 失败是 fatal（无种子可发）
- 输出为 JSONL + PipelineResult（结构化，便于 WebUI 消费）

`run-full-pipeline.sh` 瘦身成：

```bash
#!/bin/bash
cd "$REPO_DIR"
"$VENV/bin/python" -m backlink_publisher.cli.pipeline_orchestrator "$@"
```

### U2.2 智能节流引擎

**文件**：
- 创建：`publishing/_throttle.py`

当前每个 adapter 有自己的 `PUBLISH_DELAY_S`（环境变量控制）。这些是静态值。智能节流：

```python
class ThrottleEngine:
    def get_delay(self, platform: str, history: list[PublishRecord]) -> float:
        """根据发布历史和平台状态计算推荐延迟。"""
        # 基线：环境变量或 adapter 默认
        base = self._base_delay(platform)
        
        # 如果最近有 429 → 延迟 * 2
        if self._recent_throttle(platform, history):
            base *= 2
        
        # 如果上次发布失败 → 延迟 * 1.5
        if self._last_publish_failed(platform, history):
            base *= 1.5
        
        # 添加 jitter（±20%）
        jitter = uniform(-0.2, 0.2) * base
        return round(base + jitter, 1)
```

输入来源：`events.db` 中的 `publish.failed` 事件、`dedup.db` 中的发布记录。

### U2.3 动态调度频率

**文件**：`cli/pipeline_orchestrator.py`（新增 scheduler 模式）

当前：每日 4:00 固定触发。

目标：根据历史 gap 密度自动调整触发频率。

```python
def should_run_now() -> tuple[bool, str]:
    """判断现在是否应该跑管线。"""
    
    # 1. 检查 equity-ledger 的 gap 数量
    gap_count = count_gaps()
    if gap_count == 0:
        return (False, "no gaps")
    
    # 2. 检查上次运行时间
    hours_since_last = hours_since_last_run()
    
    # 3. 动态频率
    if gap_count >= 5 and hours_since_last >= 4:
        return (True, f"{gap_count} gaps, {hours_since_last}h since last run")
    if gap_count >= 2 and hours_since_last >= 8:
        return (True, f"{gap_count} gaps, {hours_since_last}h since last run")
    
    return (False, f"next run due in {next_run_in()}h")
```

**launchd 变化**：`com.dex.bp-full-pipeline.plist` 从「每日 4:00 硬跑管线」改为「每 4 小时运行 `pipeline_orchestrator --check`」，orchestrator 判断是否需要执行完整管线。

```xml
<!-- 从 StartCalendarInterval（每日）改为 StartInterval（每 4 小时） -->
<key>StartInterval</key>
<integer>14400</integer>
```

### U2.4 阶段二验证

```bash
# 检查模式（无 gap → 跳过）
python -m backlink_publisher.cli.pipeline_orchestrator --check
# → "no gaps, skipped"

# 执行模式
python -m backlink_publisher.cli.pipeline_orchestrator
# → 6 steps with structured result output
```

---

## 4. 阶段三：批量战役管理

**目标**：实现 `docs/_archive/plans/2026-06-02-001-feat-batch-optimization-plan.md` 的核心设计。

### U3.1 CampaignStore

**文件**：
- 创建：`webui_store/campaign_store.py`
- 修改：`webui_store/__init__.py`（export CampaignStore）

遵循 `drafts_store` 的 JSON file persistence + atomic write 模式。

**Schema**（与已有设计一致，增加 `language` 字段）：

```python
{
    "campaign_id": str(uuid),
    "campaign_name": str,
    "language": "zh-CN" | "en",
    "status": "pending|running|draft_review|completed|failed",
    "mode": "draft|publish",
    "platforms": ["blogger", "medium", ...],
    "cap": int | None,
    "created_at": ISO timestamp,
    "updated_at": ISO timestamp,
    "seeds": [
        {
            "seed_index": int,
            "seed_text": str,
            "target_url": str,
            "status": "idle|processing|success|failed|skipped",
            "error": str | None,
            "draft_count": int,
            "published_count": int,
        }
    ],
    "progress_pct": float,
    "result_summary": dict | None,
}
```

**方法**：`create()` / `get()` / `update_status()` / `update_seed_status()` / `list()` / `cancel()`

**测试**：`tests/test_campaign_store.py`

### U3.2 CampaignWorker

**文件**：
- 创建：`webui_app/campaign_worker.py`
- 修改：`webui_app/__init__.py`（start CampaignWorker on create_app）

```python
class CampaignWorker:
    def __init__(self, max_workers=2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.running: dict[str, Future] = {}
    
    def start_campaign(self, campaign_id, config):
        # 提交到线程池，不阻塞
        future = self.executor.submit(
            _execute_campaign, campaign_id, config
        )
        self.running[campaign_id] = future
    
    def get_status(self, campaign_id):
        # 从 CampaignStore 读取 + running indicator
        ...
    
    def cancel_campaign(self, campaign_id):
        # Future.cancel()
        ...
```

- 每个 seed 独立处理，失败不影响其他 seed
- 每个 seed 发布到所有选择的平台
- CampaignWorker 只控制「战役执行」，发布的具体逻辑复用现有的 `publish-backlinks` 核心

### U3.3 spray-backlinks multi-seed

**文件**：
- 修改：`cli/spray_backlinks/core.py`（移除 single-seed guard `len(rows) != 1` → `len(rows) == 0`）
- 修改：`cli/spray_backlinks/__init__.py`（新增 `--max-seeds` / `--seed-delay` 参数）

核心变化：
```python
# 之前
assert len(rows) == 1, "spray-backlinks accepts exactly one seed"

# 之后
if len(rows) == 0:
    sys.exit("error: no input rows")
if len(rows) > max_seeds:
    sys.exit(f"error: max {max_seeds} seeds, got {len(rows)}")

for i, row in enumerate(rows):
    row["seed_id"] = i
    result = process_seed(row)  # 复用原有逻辑
    output_results.append(result)
```

### U3.4 WebUI 批量任务页面

**文件**：
- 创建：`webui_app/routes/batch_campaign.py`
- 创建：`webui_app/templates/batch_campaign.html`
- 创建：`webui_app/routes/campaign_progress.py`
- 创建：`webui_app/templates/campaign_progress.html`
- 修改：`webui_app/routes/__init__.py`
- 修改：`webui_app/templates/base.html`（导航栏新增「批量任务」）

**表单要素**：
- 种子上传（文件 / textarea 多行 JSONL）
- 语言选择（zh-CN / en）
- 平台多选（从 adapter registry 动态获取）
- Mode: draft / publish
- Cap（可选）

**流程**：
1. 用户在 `/batch-campaign` 创建战役
2. 后端创建 CampaignStore 条目 → 提交给 CampaignWorker
3. 重定向到 `/campaign/<id>`（进度页）
4. 进度页每 2 秒轮询 `/api/campaign/<id>/status`
5. 完成后显示结果摘要 → 链接到草稿审批或返回首页

### U3.5 双语 campaign 扩展

- 每个 campaign 有 `language` 字段
- 种子按语言生成不同模板（`_templates.py` 的 `zh-CN` / `en` 模板）
- plan-gap 阶段按语言分别 run

### U3.6 批量草稿审批流

**文件**：
- 修改：`webui_store/drafts.py`（新增 `get_by_campaign_id()` 和 `bulk_publish_now()`）
- 修改：`webui_app/templates/index.html`（草稿 tab 支持 campaign_id 过滤）
- 修改：`webui_app/static/js/draft_review.js`（批量操作 UI）

- 战役结束后，如果 mode=draft，草稿出现在「草稿&历史」tab 中
- 传入 `?campaign_id=xxx` 只显示该战役的草稿
- 批量操作：全部批准、全部拒绝、发布已批准

---

## 5. 阶段四：故障自愈

### U4.1 Publish 断点续跑增强

**文件**：`cli/publish_backlinks/__init__.py`（checkpoint resume）

当前 checkpoint resume 已存在但只在 `publish-backlinks` 内部。增强：
- 发布前保存 checkpoint（已做）
- 发布中每成功一条更新 checkpoint（已做）
- **发布失败后自动重试 1 次**（新增），再失败才写入 checkpoint-failed
- **重试时使用退避**（backoff）：第 1 次即时重试，第 2 次等待 30s

### U4.2 平台级自动重试

**文件**：`publishing/adapters/base.py` 或 `publishing/retry.py`

当前有 `retry_transient_call` 用于 429/5xx 退避。扩展其作用范围：

```python
@retry(
    max_attempts=3,
    base_delay=5,
    max_delay=60,
    retry_on=(ConnectionError, TimeoutError, ExternalServiceError),
    no_retry_on=(DependencyError, AuthExpiredError),
)
def publish_with_retry(adapter, payload, mode, config):
    return adapter.publish(payload, mode, config)
```

### U4.3 告警系统

**文件**：
- 创建：`webui_app/services/alerting.py`
- 创建：`webui_app/routes/alerts_api.py`

告警层级：

| 级别 | 触发条件 | 通知方式 |
|---|---|---|
| INFO | 管线运行完成 / 无 gap 跳过 | WebUI banner（自动消失） |
| WARN | 某平台存活率 < 30% / publish 失败率 > 20% | WebUI 持久提醒 + 日志标记 |
| ERROR | AuthExpiredError（账号过期） | WebUI 红色 banner + 通知（可选 email/webhook） |
| CRITICAL | 所有平台均不可用 / 配置损坏 | 通知 + 停止调度（防止空转） |

**WebUI 实现**：在 `/health` 页面增加告警卡片，列出当前活跃告警和解决建议。

### U4.4 存储健康检查

**文件**：
- 创建：`cli/health_check.py`
- 修改：`webui_app/routes/health.py`

```python
def storage_health() -> StorageHealth:
    return StorageHealth(
        events_db_size_mb=events_db_size,
        dedup_db_size_mb=dedup_db_size,
        config_dir_items=config_file_count,
        oldest_unreconciled_checkpoint=oldest_checkpoint_age_hours,
        credential_files_0600=credential_count - non_0600_count,
    )
```

- 集成到 `run-full-pipeline.sh` 的开头检查
- WebUI `/health` 显示存储健康卡片

### U4.5 Credential 权限自动修复

**文件**：
- 修改：`scripts/audit_credential_permissions.py`（已存在，增强）

- 扫描 `config_dir` 下所有 `*-state.json` / `*-token.json` / `*-cookies.json` / `*.key`
- 报告非 0600 文件 + `--fix` flag
- 集成到 `preflight-targets` 和 WebUI 健康卡片

---

## 6. 阶段五：运营可视化

### U5.1 管线健康 Dashboard

**文件**：`webui_app/templates/health.html`

在 `/health` 页面新增卡片：

```
┌─────────────────────────────────────┐
│ 管线健康总览                         │
│                                     │
│ 上次运行: 2026-06-10T04:00:12       │
│ 运行耗时: 12m 34s                   │
│ 发布: 3/5 成功 (60%)                │
│ 活跃渠道: 8/20 bound                │
│ 待处理 queue: 2                     │
│ 最近 recheck: 2026-06-09 T 存活 87% │
│ 优化权重: 3 平台已调整               │
└─────────────────────────────────────┘
```

数据来源：
- 管线运行历史 → `events.db` + `checkpoint` 目录
- 渠道状态 → `channel-status.json`
- 优化状态 → `optimization_state.json`
- 队列 → `queue_store`

### U5.2 渠道存活率趋势

**文件**：
- `webui_app/routes/health.py`（新增 API endpoint `/api/survival/trend`）
- `webui_app/static/js/health.js`（Chart.js 或纯 SVG 渲染）

按周展示每个平台的存活率趋势：

```json
GET /api/survival/trend?platform=blogger
→ [{ "week": "2026-W22", "published": 5, "alive": 4, "dofollow": 3 },
    { "week": "2026-W23", "published": 7, "alive": 6, "dofollow": 5 }]
```

前端使用 `<canvas>` + 内联 Chart.js（CDN 引入）或纯 CSS 柱状图（避免额外依赖）。

### U5.3 管线运行历史

**文件**：`webui_app/templates/history.html`（增加管线运行 tab）

从 `events.db` / `logs/pipeline-*.log` 聚合每次运行记录：

```json
{
    "run_id": "uuid",
    "started_at": "2026-06-10T04:00:00",
    "completed_at": "2026-06-10T04:12:34",
    "steps": [
        {"name": "equity-ledger", "status": "ok", "duration_s": 1.2},
        {"name": "plan-gap", "status": "ok", "duration_s": 0.8},
        ...
    ],
    "result": {"published": 3, "failed": 0, "skipped": 2}
}
```

### U5.4 权重变化时间线

**文件**：`optimization/state.py`（新增 `adjustment_log` 字段），`webui_app/routes/health.py`

`optimization_state.json` 中每个 weight 的 `adjustments` 数组已记录每次调整。新增 endpoint：

```json
GET /api/optimization/timeline
→ [{ "date": "2026-06-08", "platform": "blogger", "old": 1.0, "new": 0.5, "rule": "canary_drift", "reason": "drift_count=3" },
    { "date": "2026-06-09", "platform": "medium", "old": 1.0, "new": 1.2, "rule": "recheck_survival", ... }]
```

### U5.5 双语 Dashboard 支持

- 所有运营指标按语言筛选：`?lang=zh-CN` / `?lang=en` / `?lang=all`
- 存活率趋势可对比中英文线路
- 权重变化分语言展示

---

## 7. 阶段六：架构加固

### U6.1 structlog 结构化日志

**文件**：
- 创建：`_util/structlog_config.py`
- 修改：各 CLI entrypoint 和 WebUI

```python
# 生产模式: JSON 输出
BACKLINK_LOG_FORMAT=json publish-backlinks ...
# → {"event": "publish.succeeded", "platform": "blogger", "duration_ms": 1234, ...}

# 开发模式: 彩色 console（保持人类可读）
publish-backlinks ...
# → [publish.succeeded] platform=blogger duration_ms=1234
```

关键事件：`publish.started` / `publish.succeeded` / `publish.failed` / `adapter.dispatched` / `throttle.waiting` / `optimize.adjusted` / `pipeline.step_completed`

### U6.2 Prometheus Metrics

**文件**：
- 创建：`_util/metrics.py`
- 修改：`webui_app/routes/`（新增 `/metrics` endpoint）

```python
# 指标定义
publish_total = Counter("publish_total", "Total publishes", ["platform", "status"])
publish_duration = Histogram("publish_duration_seconds", "Publish duration", ["platform"])
optimize_adjustments = Counter("optimize_adjustments", "Weight adjustments", ["platform", "rule"])
url_check_total = Counter("url_check_total", "URL checks", ["result"])
```

WebUI `/metrics` 返回 Prometheus 格式文本：

```
publish_total{platform="blogger",status="success"} 42
publish_duration_seconds{platform="blogger"}_bucket{le="1.0"} 30
optimize_adjustments{platform="blogger",rule="canary_drift"} 2
```

### U6.3 Rate Limiting

**文件**：
- 修改：`webui_app/__init__.py`（添加 flask-limiter 或自实现 token bucket）

```python
limiter = Limiter(
    app,
    key_func=lambda: request.remote_addr,
    default_limits=["30 per minute"],
)

# LLM 端点更严格
@limiter.limit("5 per minute")
def copilot_ask():
    ...
```

- POST/PUT/PATCH/DELETE ≤ 30 req/min per IP
- `/copilot/ask` ≤ 5 req/min
- 超限返回 429 + `Retry-After` header

### U6.4 JSONL 输入大小限制

**文件**：
- 修改：`cli/plan_backlinks/__init__.py` / `cli/validate_backlinks/__init__.py`

当前 `--max-rows` 已存在但默认可能是 None。设默认值 1000，并添加 `--no-limit` 跳过检查。

```python
parser.add_argument("--max-rows", type=int, default=1000, help="Max input rows (default: 1000)")
```

### U6.5 依赖更新

| 依赖 | 操作 | 理由 |
|---|---|---|
| `tomli>=2.0; python_version<'3.11'` | 删除 | requires-python ≥ 3.11，内置 tomllib |
| `structlog` | 新增 | 结构化日志（阶段六） |
| `flask-limiter` | 新增 | Rate limiting（阶段六） |
| `prometheus-client` | 新增 | Prometheus metrics（阶段六） |

---

## 8. 不做清单

| 不做 | 理由 |
|---|---|
| 新 publisher adapter | 聚焦自动化基建，adapter 扩展走 AGENTS.md 标准流程 |
| async/await 重写 | Flask 同步模型足够；ThreadPoolExecutor 解决并发瓶颈 |
| 新存储后端 (Redis/PostgreSQL) | local-first 架构，JSON + SQLite 足够 |
| i18n / 国际化 UI | 单运营商工具，中英双语 UI 可接受 |
| 完整的 A/B 测试框架 | 会大幅增加复杂度，当前 Rule 3 的渐进调整足够 |
| Git 集成 / CI 扩展 | 不属于「发布自动化」范畴 |
| WebUI 手动权重覆写 | 需认证机制；当前 CLI `--force` 已满足紧急需求 |

---

## 9. 执行路线图

### Phase 0：关闭优化循环（预计 1-2 天）

| # | 任务 | 依赖 | 规模 |
|---|---|---|---|
| U1.1 | preferred_dispatch() 接入动态权重 | 无 | S |
| U1.2 | optimize-weights 移除 dry-run + safety gate | U1.1 | S |
| U1.3 | Rule 3: 存活率统计阈值 | U1.2 | M |
| U1.4 | Canary cooldown auto-recovery | U1.3 | S |
| U1.5 | 双语权重分离基础 | U1.1 | M |
| U1.6 | Phase 0 测试和验证 | 上述全部 | S |

**Phase 0 后状态**：优化循环第一次关闭。weights 开始真正影响发布决策。

### Phase 1：智能调度 + 故障自愈（预计 2-3 天）

| # | 任务 | 依赖 | 规模 |
|---|---|---|---|
| U2.1 | Pipeline Orchestrator (Python) | 无 | M |
| U2.2 | 智能节流引擎 | 无 | M |
| U2.3 | 动态调度频率 | U2.1 | M |
| U2.4 | launchd plist 更新 + 验证 | U2.3 | S |
| U4.1 | Publish 断点续跑增强 | 无 | S |
| U4.2 | 平台级自动重试 | 无 | S |
| U4.3 | 告警系统基础 | U2.1 | M |
| U4.5 | Credential 权限审计增强 | 无 | S |

**Phase 1 后状态**：调度不再死板；故障开始自愈。

### Phase 2：批量战役 + 运营可视化（预计 3-4 天）

| # | 任务 | 依赖 | 规模 |
|---|---|---|---|
| U3.1 | CampaignStore | 无 | M |
| U3.2 | CampaignWorker | U3.1 | M |
| U3.3 | spray-backlinks multi-seed | 无 | M |
| U3.4 | WebUI 批量任务页面 | U3.1+U3.2+U3.3 | L |
| U3.6 | 批量草稿审批流 | U3.1 | M |
| U5.1 | 管线健康 Dashboard | U2.1 | M |
| U5.2 | 渠道存活率趋势 | 无 | M |
| U5.3 | 管线运行历史 | U2.1 | S |
| U5.4 | 权重变化时间线 | U1.1 | S |
| U5.5 | 双语 Dashboard 支持 | U1.5 | S |

**Phase 2 后状态**：Operator 可以在 WebUI 管理战役和观看运营数据。

### Phase 3：架构加固（预计 1-2 天，可穿插在其他 Phase）

| # | 任务 | 依赖 | 规模 |
|---|---|---|---|
| U6.1 | structlog 结构化日志 | 无 | M |
| U6.2 | Prometheus Metrics | 无 | M |
| U6.3 | Rate Limiting | 无 | M |
| U6.4 | JSONL 输入大小限制 | 无 | S |
| U6.5 | 依赖更新清理 | 无 | S |

**Phase 3 后状态**：可观测性建立，安全加固完成。

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| optimize-weights 写入后导致某平台权重过低，从未被选中 | 中 | 中 | safety gate 阻止全 0 / 突变 >5x；`--force` 可跳过 |
| CampaignStore JSON 文件并发写入损坏 | 低 | 高 | atomic write（tempfile + rename）+ threading.Lock |
| 双语 weights 分离导致管理复杂度翻倍 | 中 | 中 | 向后兼容 flat schema；WebUI 自动汇总 |
| PipelineOrchestrator 引入的 Python 依赖比 bash 脚本更容易出错 | 中 | 中 | 保留 `run-full-pipeline.sh` 作为 fallback；新系统逐步切换 |
| rate limiting 误伤正常操作 | 低 | 中 | 默认 30/min 宽松限制；可通过环境变量调高 |
| structlog 切换到 JSON 格式破坏日志分析习惯 | 中 | 低 | 保留人类可读模式作为默认；JSON 模式由环境变量开启 |

---

## 11. 验收总标准

1. **所有现有测试保持绿色**：`pytest tests/ -x -q`
2. **SLOC 天花板不升**：新增模块纳入 `monolith_budget.toml`
3. **无新增 orphaned guard**：`tests/test_no_orphaned_guard_scripts.py` 绿色
4. **CI 全绿**
5. **WebUI 功能完整**：手动 walkthrough 所有路由无 regression
6. **优化循环闭合**：设置 mock 权重 → plan-backlinks 使用动态权重 → publish → 验证
7. **双语管线可独立运行**：`BP_LANG=zh-CN` 和 `BP_LANG=en` 分别测试
8. **文档同步**：AGENTS.md / ARCHITECTURE.md / CHANGELOG.md 更新

---

## 12. 执行纪律

1. 每个 U 编号是一个独立 PR，可独立 review / merge / revert
2. Phase 内任务按优先级顺序，同级别可并行
3. 每个 PR 携带测试：新功能 → 新测试；重构 → 现有测试保持绿色
4. 每个 PR 标注对 budget 文件的影响
5. 不捆绑运营工作：本计划的 PR 不包含 seed / config / campaign 数据变更
6. Phase 0 完成后立即让优化循环在生产环境运行；Phase 1-3 逐步叠加

---

*本计划将 backlink-publisher 从「定时脚本工具」升级为「全闭环自动化发布系统」。*  
*Phase 0 在 1-2 天内完成最关键的优化闭环；Phase 1-3 在 1-2 周内完成全面自动化。*