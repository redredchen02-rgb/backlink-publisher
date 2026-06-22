---
date: 2026-06-22
topic: embeddable-sdk-extraction
---

# 可嵌入库/SDK 抽取 —— 让别的程序能 `import` 这个管线

> 一句话：把 `plan → validate → publish` 三段管线升级成「能被别的 Python 程序在进程内 `import` 调用、拿到 typed
> 结果」的 SDK。**好消息：plan/validate 内核早已是进程内纯函数**，只有 publish/resume 还起子进程——所以这活约
> **60% 已经做完**，真正的工作集中在「publish 段 + 顶层门面 + 解开核心对 `webui_app` 的反向依赖」。本次**不**扩大受众、
> **不**碰单操作者安全姿态、**不**做多租户。
>
> 本文档已经过 4 视角文档评审（连贯性/可行性/范围守卫/对抗式），评审对着真实代码核实，下方需求已据此校正。

## Problem Frame

`backlink-publisher` 作为「单人内部 CLI 工具」已经成熟（强制复杂度/SLOC 预算、债务登记、80% 覆盖率门禁、分层测试）。
但想在自己程序里驱动这条管线的调用方，今天**只能**去拼 `argv` 起子进程、解析 stdout 的 JSONL。一次 9 维度全量代码
评估 + 4 视角评审确认：挡住「库化」的不是质量问题，而是少数具体结构阻塞点（且范围比初稿想的小）：

1. **没有门面**：根 `src/backlink_publisher/__init__.py` 只有 14 行（docstring + `from __future__`），没有 `__all__`，
   `import backlink_publisher` 什么也拿不到。
2. **依赖方向反了**：唯一的 `PipelineAPI` 困在 `webui_app/api/pipeline_api.py`，而**核心反向 import 上去够它**。这条反向
   依赖经核实有 **5 处边**（不止初稿说的 1 处，见 R4），核心因此无法脱离 `webui_app` 单独发货。
3. **只有 publish 还被 CLI 绑死**：`PipelineAPI.plan()/validate()/report_anchors()` **已经是纯进程内调用**
   （`pipeline_api.py:275-404` 直接调 `plan_rows`/`validate_rows`，无子进程）；唯独 `publish/publish_seed/resume`
   仍**拼 argv 起子进程**（`pipeline_api.py:408-448`）。这个不对称是关键——它指向「publish 段才是真正要做的」。

受影响的人：想内嵌发布管线的调用方（含本项目自己在飞的 `/api/v1` 层——它对 publish 也在拼子进程）。
为什么现在做：把 publish 逻辑下沉到核心，正好让在飞的 `/api/v1` 改为「消费核心 SDK」，两条线互补。

## 目标分层（本次要达成的依赖方向）

```
   现状（要改）          webui_app/api/pipeline_api.py 拥有 PipelineAPI
                         ├─ plan()/validate()  已是进程内 ✅
                         └─ publish()/resume() 拼 argv 起子进程 ❌
   core ──5 处反向依赖──▶ webui_app   ❌（chain.py ×3 + medium_auth + medium_liveness）

   目标（单向向下依赖）
                     host 程序        CLI（薄壳）      webui_app /api/v1（已存在端点）
                         │                │                   │
                         └────────────────┼───────────────────┘
                                          ▼
                     backlink_publisher  ← 顶层门面 __all__:
                     (plan / validate / publish / dispatch / errors)
                                          ▼
                     纯内核（plan/validate kernels、publish engine、registry、
                     schema、typed results）—— 不依赖 webui_*
```

## Requirements

**公共 API 门面**
- R1. 根 `backlink_publisher` 暴露稳定的顶层入口（至少 `plan` / `validate` / `publish` / `dispatch` + 错误类型），
  带显式 `__all__`。`import backlink_publisher` 不触发网络/凭证副作用。**注**：凭证是在 publish **调用时**惰性读取
  （非 import 时），所以「import 无副作用」成立，但这也意味着 SDK 行为绑定进程级配置——可组合性边界见 Scope。
- R2. 全管线（plan + validate + publish）可在**进程内**调用，输入与输出均为 typed 结构（沿用现有 dataclass），
  **不**经 stdin/stdout JSONL、**不**起子进程（浏览器兜底路径例外，见 R5）、**不**伪造 argparse Namespace。
- R3. 导出错误分类（error taxonomy），调用方能按类型 `catch`，类型与现有 CLI 退出码语义一一对应
  （输入校验=2 / 依赖缺失=3 / 外部服务=4 / 内部错误=5）。

**解开嵌入阻塞点**
- R4. 把 `PipelineAPI` 提到核心，**移除核心 → `webui_app` 的全部 5 处反向依赖**，并以守门测试锁死「核心 ∌ webui_app」：
  - `keepalive/chain.py:101` → `webui_app.api.pipeline_api`
  - `keepalive/chain.py:141` → `webui_app.services.keepalive_job._ensure_article`
  - `keepalive/chain.py:270` → `webui_app.services.keepalive_job.RUNTIME_STICKY_PLATFORMS`（在 `run_cycle:338` 主体消费，load-bearing）
  - `publishing/adapters/medium_auth.py`、`publishing/adapters/medium_liveness.py` 中对 `webui_app` 的引用
- R5. `publish` 提供 in-process 引擎入口，但**必须显式声明它替换掉的隔离契约**，不能当成「只是去掉 argparse」：
  - **去掉杀进程路径**：`_publish_one_row` 现在走 `emit_error(..., exit_code=3)` → 在 per-row 循环中 `raise SystemExit`
    （`_engine.py:278`）。进程内调用方必须拿到 **typed 结果/异常**，而非被杀进程。
  - **浏览器兜底保留隔离**：API 类适配器（Blogger API、Telegraph、Medium token、Velog GraphQL、GH/GitLab Pages…）
    进程内直跑；但 Medium 的 Playwright 浏览器兜底用子进程做崩溃隔离 + PID 文件 + `SIGTERM` 清理
    （`browser_publish/_chrome_session_impl.py:319`）——**保留一个可选子进程/隔离边界**，或把 Chrome 生命周期的
    崩溃/清理所有权显式交给调用方。
  - **全局状态危害**：进程内路径已经在刻意回避 `set_log_level()`/`reset_stats()`（`pipeline_api.py:281-284`，会污染
    调度线程 logger 与全局 fetch 统计）；publish 还多带 `PublishRunState` 节流计数与熔断器磁盘锁——这些状态如何在
    进程内调用下隔离/可重入，是 R5 的核心，不是细节。
- R6. registry 增加显式 `register_all_adapters()` 引导（门面内代为调用，调用方无感）。**理由**：24 处 `register(...)`
  靠 `import …adapters` 副作用触发（`adapters/__init__.py:115+`），host 若直接 import 某个子模块而非 adapters 包，
  registry 会是空的——这是真实的进程内失败模式，不是抽象。

**向后兼容（硬约束）**
- R7a. **3 个管线 CLI**（`plan-backlinks` / `validate-backlinks` / `publish-backlinks`）行为零变化，改写为新 SDK 函数的
  薄包装——这 3 个正是成功标准的 dogfood 路径，是硬要求。注意 CLI 壳仍持有真实策略（config 加载容错、`config_echo`
  横幅、退出码纪律，见 `validate_backlinks.py:5-7`「这些留在壳里、不进引擎」），下沉时**必须原样保留**。
- R7b. 其余 ~47 个 CLI 机会主义迁移为薄包装，**不搞大爆炸式重写**；多数（plan/validate/report 系、已拆解的 `spray`）
  本就是共享引擎的薄壳，残余工作量远小于「重写 50 个」。
- R8. **已存在的** `/api/v1` 端点改为消费核心 SDK（不新增端点）。`scheduler.py`、`api/v1/pipeline.py`、
  `services/_keepalive_engine.py` 已在消费 `PipelineAPI`——R4 下沉后主要是重指 import。
- R9. 单进程单配置下，现有 `Config` / `os.environ` 配置解析保持可用，现有运行方式（CLI、WebUI）不被破坏。

**可发现性与契约**
- R10. 提供文档化的 SDK 快速上手示例（README 或 docs），含一个最小可运行程序：`plan → validate → publish(dry-run)`
  全进程内、API 适配器路径零子进程。
- R11. 公共 API 表面标注为受版本约束的契约（0.x 下可演进，但 `__all__` 即承诺面），并加一道守门测试
  （import-linter：开源工具，按规则校验模块间 import 依赖；或等价自测）锁住「核心不依赖 `webui_app`」与「门面入口可解析」。

## Success Criteria

- 一个 ~15 行的宿主程序能 `from backlink_publisher import plan, validate, publish` 跑完整条管线（API 适配器 dry-run），
  **零子进程、零 `webui_app` import**，拿到 typed 结果（由 e2e 冒烟测试守住）。
- import-linter 证明核心子树不再 import `webui_app`——**全部 5 处反向边**消除（R4）。
- publish 作为库调用时，依赖缺失/外部服务错误返回 typed 异常，**不再 `raise SystemExit` 杀进程**（R5）。
- 3 个管线 CLI + WebUI 全套测试在改写为薄包装后仍全绿（R7a/R8 零回归）。
- README/docs 里那段 SDK 示例能照抄即跑通（R10）。

## Scope Boundaries

- **单配置嵌入，非可组合多目标**：本次交付的是「单进程单配置」嵌入（够本项目自己的 `/api/v1` 这个唯一已知调用方用）。
  同进程并发驱动两个账号/目标会撞上进程级 `os.environ` 共享——**多配置/多租户（88 处 env 注入式改造）明确不做**（XL，YAGNI）。
- **不引入新运行时依赖**（如 pydantic）；typed 结果沿用现有 dataclass / `schema.py`。
- **不**做多用户/登录/审计/联网产品化：LITE 单操作者安全姿态（仅回环、无登录、拒绝网络暴露）**原封不动**。
- **不**强行去隔离化 publish 的浏览器兜底路径：崩溃隔离边界刻意保留（R5）。
- **不**改 CLI 的 stdin/stdout JSONL 对外契约本身：CLI 仍是 JSONL 管线，只是内部实现改走 SDK。
- **不**做 PyPI 发布 / `bp init` 打包收尾 / `bp` 总入口收敛——那属于「可重复部署」方向，本次不含。
- **不**强行收尾 Vue 前后端分离重构——但 R4 的 `api/__init__.py` 触点需与之协调排期（见 Dependencies）。

## Key Decisions

- **选「全管线·单配置」而非「只 plan+validate」**：只暴露生成+校验是半个 SDK，调用方仍得自己拼 CLI 发布。
- **publish 全进程内，但浏览器兜底保留隔离边界**：评审证实 publish 的子进程是作者**刻意**选的崩溃隔离，不能盲拆；
  API 适配器进程内、浏览器兜底留隔离，是兼顾「可嵌入」与「不回归稳定性」的折中。
- **CLI/WebUI 改写为 SDK 薄包装，而非另起平行 API**：防漂移 + 强制 dogfood；但硬要求只压在 3 个管线 CLI（R7a），其余机会主义。
- **单进程单配置下保留 `os.environ` 配置解析**：刻意不做注入式 `Config` 改造（YAGNI），把工作量压在 L 而非 XL；
  代价是「单配置嵌入」而非「可组合 SDK」，已在 Scope 诚实标注。

## Dependencies / Assumptions

- **前置闸门（Step 0）**：**64 项**未提交改动落库到干净检查点——含 `webui_app/api/*.py`（oauth/bind/channel_bind/llm/
  image_gen/sites/campaign 等凭证写入后端）、`webui_app/api/v1/*.py`、前端 Sites/Schedule/BatchCampaign/Profiles 页面、
  配套测试。最后一次提交 2026-06-18，悬在工作树已 4 天，**有丢失风险**，SDK 工作不应在它落库前开始。
- **排期精修（评审更正）**：「先落库再并行」整体成立，但落库**不是**冲突防火墙——R4 真正的碰撞点是
  `webui_app/api/__init__.py`（已被改动，是 pipeline_api 的注册接线处），它正与 Vue `/api/v1` 工作同片churn。
  因此：R4 中「提 `PipelineAPI` + 改 `api/__init__.py`」这一步应**等 Vue `/api/v1` 工作到一个检查点后**再做；而 SDK 其余工作
  （R1 门面、R5 在 `src/` 内的 publish 引擎、R6 registry、R7a 管线 CLI 包装）位于 `src/`，可真正并行。
- 假设 Vue 重构继续推进，且接受让已存在的 `/api/v1` 端点改为消费核心 SDK（与已拍板的 plan 2026-06-18-002 方向一致）。

## Outstanding Questions

### Resolve Before Planning
- （空）方向、范围、排期均已与用户确认，无剩余阻塞性产品决策。R5 的浏览器兜底隔离折中已作为默认工程取向纳入，
  用户如不认同可在规划前推翻。

### Deferred to Planning
- [Affects R5][Technical] publish 在进程内的副作用接口形态：节流（throttle）、熔断器磁盘锁、`PublishRunState` 计数器
  如何暴露/可注入/可重入；浏览器兜底的隔离边界是「可选子进程」还是「Chrome 生命周期所有权交调用方」。
- [Affects R4/R9][Technical] `PipelineAPI` 下沉后，`webui_store` 的 5 个状态单例（history/drafts/schedule/queue/profiles）
  哪些算核心、哪些留 `webui_app`？这直接决定 SDK 是有状态还是无状态（连贯性评审标的 P0）。
- [Affects R6][Technical] `register_all_adapters()` 与现有 import 副作用注册的过渡兼容，不破坏 50 个 entry-point 触发路径。
- [Affects R7b][Needs research] 其余 ~47 个 CLI 的薄壳化工作量盘点：从「已抽出的共享引擎」起步，而非假设 greenfield。

## Next Steps

→ `/ce:plan`（Resolve Before Planning 为空，可直接进入结构化实现规划）。第一阶段应为 **Step 0：64 项未提交改动落库**；
R4 的 `api/__init__.py` 触点排在 Vue `/api/v1` 检查点之后，其余 SDK 工作并行。
