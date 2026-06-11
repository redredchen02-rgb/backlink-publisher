---
title: "opt: 全面分析代码优化企划"
type: opt
status: active
date: 2026-06-05
origin: analysis
claims: {}
---

# backlink-publisher 全面分析及优化计划

> 综合系统勘察（AGENTS.md、ARCHITECTURE.md、pyproject.toml、registry.py、adapters/__init__.py、_manifests.py、debt_registry.toml、monolith_budget.toml、complexity_budget.toml、validate/engine.py、publish_backlinks/_engine.py、anchor/lang.py、txtfyi_api.py、livejournal_api.py、http_form_post.py、_validate_payload.py 及 优化企划-2026-06-01.md）。

## 一、项目现状

### ✅ 已做到的（行业水准）

| 维度 | 证据 |
|---|---|
| 架构纪律 | 表驱动 registry + 双预算系统(monolith SLOC + cyclomatic complexity) + plan-claims 门禁 |
| 文档纪律 | AGENTS.md / ARCHITECTURE.md / plans 三位一体，80-char rationale 可审查 |
| 测试隔离 | 4 autouse 夹具，≈160 文件 ~96K 行 |
| CI 门禁 | plan-claims-gate、phase0-seal、budget gates、manifest contract、adapter dofollow gate |
| 凭证安全 | 原子写(0o600)、bind-channel 框架、channel-status 状态机 |
| 发布路径 | 23 CLI、25+ 适配器、20+ WebUI 路由、动态 registry |

### ⚠️ 核心问题（同优化企划-2026-06-01）

**工程精密 vs 真实产出的数量级落差。** `live_dofollow=0`——23 个 CLI、双预算系统守护的是一条从未产出过一条 confirmed 真实 dofollow 链的管线。

---

## 二、六层优化

### Layer 1：RegistryEntry 并行字典合并

**现状**：`registry.py` 有 4 个平行字典（`_UI_META_BY_PLATFORM`、`_BIND_BY_PLATFORM`、`_POLICY_BY_PLATFORM`、`_VISIBILITY_BY_PLATFORM`）+ 单独 `_AUTH_TYPE_BY_PLATFORM`。代码注释行 158-164 明确说"第 3 个平行字典就应该合并为 RegistryEntry"，当前已在第 5 个。3 个 snapshot 夹具必须同步维护。

**优化**：将 `_UI_META_BY_PLATFORM`、`_BIND_BY_PLATFORM`、`_POLICY_BY_PLATFORM`、`_VISIBILITY_BY_PLATFORM` 折叠进 `RegistryEntry.dataclass`。注意 `_AUTH_TYPE_BY_PLATFORM` 是静态常量（不在 register() 中写入），保持独立；`_REFERRAL_VALUE_BY_PLATFORM` 已在 RegistryEntry 中。

**影响范围**：
- `src/backlink_publisher/publishing/registry.py`：删除 4 个平行 dict，从 `RegistryEntry` 的 extras 字段加载
- `tests/conftest.py`：简化 snapshot 夹具（从 5→1 个要被快照的 dict）
- `tests/test_registry_dofollow_kwargs.py`：同
- `tests/test_adapter_dofollow_gate.py`：同

**工作量**：~2 小时（纯机械搬迁 + 夹具调整）

**前提条件**：`live_dofollow ≥ 20`

---

### Layer 2：Manifest 占位符收尾

**现状**：`_manifests.py` 有 25 个 manifest dict，但 8 个是 Phase-2 占位符（hashnode、linkedin、rentry、substack、tumblr、wordpresscom、writeas）——只有最小化 `UiMeta`，没有完整的 `BindDescriptor` + `Policy`。Phase-2 注释行 637-641 明确说 "the manifest authors haven't shipped full metadata yet"。

**未完成的具体占位符**：

| 平台 | 缺少 BindDescriptor | 缺少 Policy | 注 |
|---|---|---|---|
| hashnode | ✅ | ✅ | browser-only，无 token-paste |
| linkedin | ✅ | ✅ | 已 visibility=experimental |
| rentry | ✅ | ✅ | 匿名发布，bind=[] 即可 |
| substack | ✅ | ✅ | paste_blob auth |
| tumblr | ✅ | ✅ | token_fields auth |
| wordpresscom | ✅ | ✅ | token_fields auth |
| writeas | ✅ | ✅ | 已 visibility=retired |

**优化**：为上述 7 个补齐 BindDescriptor + Policy。每个 ≤20 行声明 + 为 token-paste/cookie 平台添加 `extras`。

**影响范围**：`_manifests.py` 仅

**工作量**：~1 小时

**前提条件**：`live_dofollow ≥ 20`

---

### Layer 3：WebUI 路由瘦身（燃料状态标记）

**现状**：20+ 路由模块覆盖了在 `live_dofollow=0` 时没有真实数据可展示的功能：
- `/survival-dashboard`——R5，需要 live_dofollow 数据
- `/equity-ledger`——在只有 example.com 数据时只有噪音
- `/optimization-status`——优化权重，但燃料为零
- `/health`——健康面板，数据为空

**优化**：在每条燃料相关路由上添加 amber 横幅 "需要实时数据"（CSS class + 条件 Jinja）。不删除功能，只设置期望期望状态。

**新增横幅控件（建议）**：

```html
{% if live_dofollow_count < 20 %}
<div class="alert alert-warning alert-dismissible fade show" role="alert">
  <i class="bi bi-exclamation-triangle"></i>
  此视图需要实时数据（当前 live_dofollow={{ live_dofollow_count }}）。
  在跑通真实 dofollow 发布路径之前，这里显示的是示例数据。
  <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
</div>
{% endif %}
```

**影响范围**：`templates/survival_dashboard.html`、`templates/equity_ledger.html`、`templates/optimization_status.html`、`webui_app/helpers/contexts.py`（添加 `live_dofollow_count` 到模板上下文）

**工作量**：~30 分钟

**前提条件**：无（燃料无关——标记 UI，不改变行为）

---

### Layer 4：测试文件分解

**现状**（debt_registry `largest-test-file-bloat` 已记录）：

| 文件 | SLOC | 问题 |
|---|---|---|
| `test_webui_route_contract.py` | ~1647 | 单个文件，同一参话化模式，合并冲突风险 |
| `test_cli_generate_backlink_text.py` | ~1070 | 单一测试，10+ 参话化 |
| `test_webui_three_url.py` | ~940 | 单一测试，30+ 场景 |

**优化**：按路由领域分解 `test_webui_route_contract.py`：

```text
tests/
  test_webui_route_contract.py          ← 保留（不变：合约检查 + 总览)
  test_routes/
    __init__.py                         ← 共享夹具 + 模块常量
    test_routes_history.py              ← /history 相关
    test_routes_settings.py             ← /settings 相关
    test_routes_sites.py                ← /sites 相关
    test_routes_health.py               ← /health 相关
    test_routes_survival.py             ← /survival-dashboard 相关
    test_routes_equity.py               ← /equity-ledger 相关
    test_routes_batch.py                ← /batch 相关
```

**影响范围**：`tests/`——创建 `test_routes/` 包 + 8-10 个新测试文件

**工作量**：~3 小时（细分参话化、验证覆盖、保持 pytest 共享夹具）

**前提条件**：`live_dofollow ≥ 20`

---

### Layer 5：燃料增益（C0 排障——前提条件）

**这是实际的高优先级工作。** 以下是基于 `events.db` 实证失败模式的具体技术障碍：

#### 5.1 txt.fyi 不跳转（did not redirect after submit）

**源码分析**：`txtfyi_api.py:132-146`——`submit_form()` 返回后检查 `published_url`。如果 `submit_resp.url == _TXTFYI_SUBMIT` 且主体包含 `_TARPIT_MARKER`，则抛 `ExternalServiceError`。

**根本原因候选**：dwell-time 门禁不足——`_DEFAULT_SUBMIT_DELAY_SECONDS = 4.0s` 可能不足以绕过 txt.fyi 的反垃圾门，或者 `form_time` 戳服务器端超时。

**修复建议**：
1. 将默认延时提高到 6.0s
2. 添加重试逻辑：如果检测到 tarpit，自动重试带指数退避（x1.5 乘数，最多 3 次）
3. 日志行添加 `tarpit_retry_count` 以便监控

**相关代码**：`txtfyi_api.py:62-63`、`txtfyi_api.py:127-143`

#### 5.2 LiveJournal faultCode=100

**源码分析**：`livejournal_api.py:283-298`——`Fault` 被捕获，检查 `_is_auth_fault()`（匹配 faultString 中的"invalid password"/"invalid auth"标志）。如果匹配则抛 `DependencyError`，否则抛 `ExternalServiceError(f"faultCode={code}")`。

**根本原因候选**：
1. 凭证过期（hpassword 在服务端已更改/失效）
2. API 端点的变化（LiveJournal XML-RPC 可能已更改）
3. 参数格式——`postevent` 形状可能过时

**排障步骤**：
1. 手动使用 `xmlrpc.client.ServerProxy` 验证凭据
2. 检查 `postevent` 参数形状 vs LiveJournal 当前文档
3. 在 `_AUTH_FAULT_MARKERS` 中添加 `faultCode=100` 或相关标志

**相关代码**：`livejournal_api.py:83-89`、`livejournal_api.py:282-294`

#### 5.3 anchor 缺少 CJK codepoint

**源码分析**：`_validate_payload.py:270-278`——R4 检查每个 `link["anchor"]` 通过 `check_anchor_language()`。`_check_zh_cn` 检查 `_has_cjk()`。

**根本原因候选**：中文目标的 anchor 生成（可能由 LLM 或默认规则生成）只产生 Latin 锚文本——混合语言/品牌名称，不以 CJK 码点为主。

**修复建议（非破坏性）**：
1. 添加 `link["kind"] == "target"` + `row["language"] == "zh-CN"` 时的 anchor 验证宽松化——如果 anchor 是"51acgs.com"或"click here"等受信任的品牌/目标模式，允许通过
2. 在 `check_anchor_language` 中添加 `allowed_latin_url_patterns` 白名单

**相关代码**：`anchor/lang.py:58-62`、`_validate_payload.py:272-278`

#### 5.4 体语言 en != zh-CN

**源码分析**：`_validate_payload.py:256-268`——`_detect_row_body_language()` 将检测到的语言与请求的语言（此时是 `zh-CN`）进行匹配。如果 body 有大量的 en 内容，`language_matches()` 会失败。

**根本原因候选**：中文目标的 backlink 正文混合中英文——标题/引文是英文，backlink 内容是中文。body 检测偏向英文。

**修复建议**：
1. 在 `_detect_row_body_language` 中添加 "zh-CN" 的宽松模式：如果 ≥30% 的字符是 CJK，就通过
2. 将语言匹配从严格的 `language_matches` 降级为宽松的"主要语言必须包含请求语言"
3. 所有宽松化必须记录在 `validation.warnings` 中，而不仅仅是 `errors`

**相关代码**：`_validate_payload.py:192-226`、`linkcheck/language.py::language_matches`

#### 5.5 超时

**源码分析**：全局超时处理：

| 位置 | 超时 | 重试 |
|---|---|---|
| `livejournal_api.py:61` | `_HTTP_TIMEOUT_S = 15` | `retry_transient_call`——未使用 |
| `http_form_post.py:45` | `DEFAULT_TIMEOUT = 15.0` | 无（create-POST 非幂等） |
| `content/fetch.py` | `BACKLINK_FETCH_TIMEOUT = 10` | 2 次 |

**修复建议**：
1. LiveJournal `_TimeoutTransport` 添加 5xx 自动重试（使用 `retry_transient_call`，像其他适配器一样）
2. 为 txt.fyi 添加全局 15s→30s 超时增加，如果这是 transient

---

### Layer 6：debt_registry 治理

**现状**：6 个开放项目（1 高、4 中、1 低），均未分配所有者。

#### 6.1 高：无 Health Surface（`no-health-surface`）

**优化**：创建 `/ce:health` 纯 JSON 端点（非 HTML），聚合：
- `events.db` 最后操作时间戳
- `canary-store` 状态
- `channel-status` 汇总

**不需要** Kubernetes 就绪探针——只是一个 cron 友好的端点。

**工作量**：~2 小时

#### 6.2 中：无覆盖率门禁（`no-coverage-gate`）

**优化**：在 CI 中添加 pytest-cov `--fail-under=50` 门禁。现有覆盖率未知——先运行 `pytest --cov` 建立基线。

**工作量**：~30 分钟（CI 配置 + 基线）

#### 6.3 中：测试层级标记不完整（`test-tier-coverage-incomplete`）

**优化**：为 ~160 个测试文件添加 `unit`/`integration`/`e2e` 标记。按层级添加 CI 矩阵：`pytest -m "unit"` 推送到 push，`pytest -m "integration"` 到 PR，`pytest -m "e2e"` 每晚/手动。

**工作量**：~4 小时（标记 ~160 个文件 + 贡献文档）

#### 6.4 中：无 RECON 模式

**优化**：为当前 ~10 个 RECON 事件类型添加形式化类型模式。每个类型获得一个 `dataclass` + `json.dumps()` 序列化器。

**工作量**：~3 小时

---

## 三、路线图

```
阶段 1（今天——最高优先级）：C0 排障 + 燃料增益
  [P0] txt.fyi 默认延时 4.0→6.0s + tarpit 重试（最多 3 次指数退避）
  [P0] LiveJournal faultCode=100 诊断（验证凭据 + 更新 AUTH_MARKERS）
  [P1] zh-CN anchor 宽松：品牌/URL 模式白名单通过 R4
  [P1] zh-CN body 语言降级：CJK ≥30% 通过而非严格匹配
  [P1] 超时保护：LiveJournal 5xx 自动重试，txt.fyi 超时 15→30s
  [P0] 从 draft→live 切换 campaign 模式
  [P0] 运行 recheck-backlinks 闭环 publish.unverified → confirmed

阶段 2（fuel ≥ 20 后）：架构治理
  [P2] Layer 1：Registry 并行 dict 折叠
  [P2] Layer 2：Manifest 占位符收尾
  [P2] Layer 4：test_webui_route_contract.py 分解

阶段 3（低优先在线）：监控 + 治理
  [P3] Layer 6.1：/ce:health JSON 端点
  [P3] Layer 6.2：覆盖率门禁（--fail-under=50）
  [P3] Layer 6.3：测试层级标记
  [P3] Layer 6.4：RECON 形式化模式

阶段 4（持续）：Layer 3 WebUI 燃料状态标记
  [P4] amber 横幅组件 + 模板上下文注入
```

---

## 四、资产目录更新

### Complexity Budget 变更

为新的重试逻辑添加函数条目（`_publish_with_retry` ~CC 12）：

```toml
[functions."src/backlink_publisher/cli/_publish_helpers.py::_publish_with_retry"]
ceiling = 12
rationale = "txt.fyi tarpit retry with exponential backoff (max 3 attempts). Extracted from TxtfyiFormPostAdapter.publish to keep the adapter's CC under backstop."
```

### Debt Registry 更新

添加 txt.fyi retry 衰减条目：

```toml
[[items]]
slug = "txtfyi-tarpit-retry-decay"
severity = "low"
rationale = "txt.fyi tarpit retry uses a fixed exponential backoff with no adaptive learning across publishes. An adaptive model would tune the delay per-session, but Phase 0's 4-hour window is too short to collect enough samples to train one."
discovered = "2026-06-05"
owner = "unassigned"
status = "accepted"
```

---

## 五、不做清单

以上，与 010/011 收敛工作不冲突：
- 🔴 不创建第 24 个 CLI
- 🔴 不添加新 gate
- 🔴 不创建新 brainstorm
- 🔴 不修改现有的 plan-claims 门禁
- 🔴 不重启 geo (A5) / history 迁移 (A4)
- 🔴 不修改 010 (convergence) 或 011 (decision surface) 的范围