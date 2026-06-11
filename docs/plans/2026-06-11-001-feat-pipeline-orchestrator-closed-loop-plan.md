---
title: "feat: Pipeline Orchestrator — 全鏈路自動化閉環"
type: feat
status: active
date: 2026-06-11
origin: docs/brainstorms/2026-06-11-pipeline-orchestrator-closed-loop-requirements.md
claims:
  paths:
    - src/backlink_publisher/cli/pipeline_orchestrator.py
    - src/backlink_publisher/events/kinds.py
    - src/backlink_publisher/events/_project_reducers.py
    - src/backlink_publisher/events/store.py
    - src/backlink_publisher/cli/weights.py
    - webui_app/routes/pipeline.py
    - webui_app/templates/pipeline.html
    - scripts/com.dex.bp-pipeline.plist
  shas:
    - HEAD
---

# Pipeline Orchestrator — 全鏈路自動化閉環

> 建立一個中央 PipelineOrchestrator（event-driven state machine）來協調已有的 CLI 元件，
> 形成完整閉環：gap detection → plan → validate → publish → recheck → optimize。
> Operator 不再需要手動啟動每個環節或處理散落在多個 cron 裡的半自動任務。

---

## 0. 現狀與設計原則

### 0.1 已存在且被 Orchestrator 調用的 CLI 元件

| CLI 命令 | 套件 | 角色 | 輸出 |
|---|---|---|---|
| `plan-gap` | `cli/plan_gap.py` | 檢測 gap，輸出 seed JSONL | stdout JSONL, exit code |
| `plan-backlinks` | `cli/plan_backlinks/` | 從 seed 生成文章 | stdout JSONL |
| `validate-backlinks` | `cli/validate_backlinks.py` | 驗證 + 豐富 payload | stdout JSONL |
| `publish-backlinks` | `cli/publish_backlinks/` | 發布到平台 | exit code + checkpoint |
| `recheck-backlinks` | `cli/recheck_backlinks.py` | 存活率重新探測 | events.db events |
| `weights` | `cli/weights.py` | collect + optimize + show | exit code + JSON |

### 0.2 設計原則

- **元件獨立性**：Orchestrator 透過 subprocess + stdout JSONL 調用 CLI，不做 Python import 或 SDK refactor
- **State in events.db**：pipeline events 是 events.db 的自然擴張，無需新資料庫
- **Periodic pulse 而非 daemon**：launchd 每 N 小時喚醒 Orchestrator → 檢查 gap → 決定是否跑 pipeline
- **Per-platform circuit breaker**：一個平台故障不影響其他人
- **weights.write_mode 預設 "preview"**：operator 先看 diff 才 opt-in 自動寫入

### 0.3 事件架構對照

現有 events.db 的事件種類 (`events/kinds.py`)：

```
publish.intent / publish.confirmed / publish.unverified / publish.failed
publish.verified / publish.verify_failed
draft.created / draft.scheduled
link.rechecked / reconcile.swallowed
banner.* / image_gen_*
citation.observed
```

Orchestrator 新增的事件種類：

```
pipeline.started          — pipeline 開始執行（攜帶 config / trigger 原因）
pipeline.stage_completed  — 單一 stage 完成（stage name, duration, exit code）
pipeline.completed        — pipeline 全部完成（summary stats）
pipeline.failed           — pipeline 因致命錯誤中止
pipeline.skipped          — gap 為空，pipeline 跳過
circuit.tripped           — circuit breaker 觸發，某 platform 被隔離（platform, consecutive_failures）
circuit.half_open         — 隔離到期，允許一次測試發布
circuit.reset             — 隔離解除，platform 恢復
weights.snapshot          — 權重寫入快照（調整前/後的權重表）
weights.preview           — 權重 preview diff（write_mode=preview 時輸出）
```

---

## 1. 架構概覽

```
┌─────────────────────────────────────────────────────────┐
│                     launchd                             │
│  com.dex.bp-pipeline (StartInterval=21600, 每 6h)       │
└──────────────┬──────────────────────────────────────────┘
               │ python -m backlink_publisher.cli.pipeline_orchestrator
               ▼
┌─────────────────────────────────────────────────────────┐
│              PipelineOrchestrator                        │
│                                                          │
│  1. Run plan-gap (check for gaps)                        │
│     ├─ stdout empty → emit pipeline.skipped → exit 0     │
│     └─ stdout non-empty → continue                        │
│                                                          │
│  2. Run plan-backlinks (generate articles)               │
│  3. Run validate-backlinks (validate payloads)           │
│  4. Run publish-backlinks (publish to platforms)         │
│     └─ Per-platform circuit breaker check before each    │
│  5. Run recheck-backlinks (probe survival)              │
│  6. Run weights collect + optimize (close feedback loop)│
│     └─ Respect weights.write_mode (preview/always/...  ) │
│                                                          │
│  Each step writes pipeline.stage_completed to events.db  │
│  Final state: pipeline.completed / pipeline.failed       │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Phase 0：基礎建設（Core Orchestrator）

### U0.1 Pipeline 事件種類

**檔案**：`events/kinds.py`

新增 9 個事件種類常量：

```python
PIPELINE_STARTED: Final = "pipeline.started"
PIPELINE_STAGE_COMPLETED: Final = "pipeline.stage_completed"
PIPELINE_COMPLETED: Final = "pipeline.completed"
PIPELINE_FAILED: Final = "pipeline.failed"
PIPELINE_SKIPPED: Final = "pipeline.skipped"
CIRCUIT_TRIPPED: Final = "circuit.tripped"
CIRCUIT_HALF_OPEN: Final = "circuit.half_open"
CIRCUIT_RESET: Final = "circuit.reset"
WEIGHTS_SNAPSHOT: Final = "weights.snapshot"
WEIGHTS_PREVIEW: Final = "weights.preview"
```

更新 `KINDS` frozenset，加入 9 個新常量。

更新 `REQUIRED_FIELDS`，為每個新 kind 定義 floor fields：

```python
PIPELINE_STARTED: frozenset({"trigger_reason"}),
PIPELINE_STAGE_COMPLETED: frozenset({"stage", "exit_code"}),
PIPELINE_COMPLETED: frozenset({"summary_json"}),
PIPELINE_FAILED: frozenset({"failed_stage", "exit_code"}),
PIPELINE_SKIPPED: frozenset({"reason"}),
CIRCUIT_TRIPPED: frozenset({"platform", "consecutive_failures"}),
CIRCUIT_HALF_OPEN: frozenset({"platform"}),
CIRCUIT_RESET: frozenset({"platform"}),
WEIGHTS_SNAPSHOT: frozenset({"weights_before_json", "weights_after_json", "trigger_reason"}),
WEIGHTS_PREVIEW: frozenset({"diff_json"}),
```

**驗收**：
- `EventStore.append("pipeline.started", ...)` 成功寫入 events.db
- `KINDS` 包含 9 個新字串
- 所有 floor fields 檢查通過

---

### U0.2 PipelineOrchestrator 核心模組

**檔案**：`src/backlink_publisher/cli/pipeline_orchestrator.py`（新檔案）

CLI 入口合約：

```
usage: pipeline-orchestrator [-h] [--dry-run] [--skip STAGE] [--only STAGE]
                             [--from-checkpoint RUN_ID]

Trigger gap detection and optionally run the full publish pipeline.

optional arguments:
  --dry-run           Preview mode: print what would run without executing
  --skip STAGE        Skip one or more stages (repeatable)
  --only STAGE        Run only specified stage(s) 
  --from-checkpoint   Resume from a checkpoint run_id
```

**核心邏輯**：

```python
STAGES = [
    StageDef("plan-gap",         _run_plan_gap,         fatal=True),
    StageDef("plan-backlinks",    _run_plan_backlinks,   fatal=True),
    StageDef("validate-backlinks",_run_validate,         fatal=False),
    StageDef("publish-backlinks", _run_publish,          fatal=False),
    StageDef("recheck-backlinks", _run_recheck,          fatal=False),
    StageDef("weights-collect",   _run_weights_collect,  fatal=False),
    StageDef("weights-optimize",  _run_weights_optimize, fatal=False),
]

class PipelineOrchestrator:
    def __init__(self, config, events_store, circuit_store):
        self.config = config
        self.events = events_store
        self.circuit = circuit_store  # per-platform breaker state
        self.run_id: str | None = None

    def run(self, stages=None, dry_run=False) -> int:
        self.run_id = checkpoint.generate_run_id()
        self.events.append("pipeline.started", {
            "trigger_reason": "periodic_pulse",
            "run_id": self.run_id,
        })
        
        for stage in (stages or STAGES):
            if dry_run:
                print(f"[dry-run] {stage.name}")
                continue
            
            # Circuit breaker check (publish stages only)
            if stage.name == "publish-backlinks":
                blocked = self.circuit.get_blocked_platforms()
                if blocked:
                    print(f"  circuit open for: {blocked}", file=stderr)
            
            t0 = time.time()
            result = stage.run(self.config)
            duration = time.time() - t0
            
            self.events.append("pipeline.stage_completed", {
                "stage": stage.name,
                "exit_code": result.exit_code,
                "duration_s": round(duration, 2),
                "output_summary": result.summary,
            })
            
            if result.fatal and result.exit_code != 0:
                self.events.append("pipeline.failed", {
                    "failed_stage": stage.name,
                    "exit_code": result.exit_code,
                })
                return result.exit_code
        
        self.events.append("pipeline.completed", {
            "summary_json": json.dumps(self._build_summary()),
        })
        return 0
```

**Stage 執行包裝器**：每個 stage 對應一個 helper 函數，使用 `subprocess.run()` 調用對應 CLI：

```python
def _run_plan_gap(config) -> StageResult:
    """Run plan-gap, pipe output to temp file for next stage."""
    result = subprocess.run(
        [sys.executable, "-m", "backlink_publisher.cli.plan_gap"],
        capture_output=True, text=True, timeout=300,
    )
    # plan-gap 輸出 seed JSONL 到 stdout
    seeds = result.stdout.strip()
    has_gap = bool(seeds)
    if has_gap:
        # 寫入 temp file 供下一 stage 使用
        _write_stage_artifact("plan-gap", seeds)
    return StageResult(
        exit_code=result.returncode,
        summary={"has_gap": has_gap, "seed_lines": len(seeds.splitlines())},
        artifact=seeds if has_gap else None,
    )
```

```python
def _run_publish(config) -> StageResult:
    """Run publish-backlinks with circuit breaker awareness."""
    blocked = _get_circuit_blocked_platforms()
    cmd = [sys.executable, "-m", "backlink_publisher.cli.publish_backlinks"]
    if blocked:
        cmd.extend(["--skip-platforms", ",".join(blocked)])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return StageResult(exit_code=result.returncode, ...)
```

**關鍵設計**：
- 每個 stage 可單獨 skip/only（對應 CLI `--skip` / `--only`）
- `publish-backlinks` 在調用前檢查 circuit breaker，傳入 `--skip-platforms`
- Stage 之間透過 temp JSONL 檔案傳遞資料（`_stage_artifact()`）
- 每個 stage 有 timeout，預設 600s（publish 最長）
- 非致命 failure（validate / recheck / weights）不中止 pipeline

**驗收**：
- `pipeline-orchestrator --dry-run` 列出所有 stage 但不執行
- `plan-gap` 輸出非空 → pipeline 繼續；輸出空 → `pipeline.skipped` + exit 0
- 每個 stage 完成後 events.db 有對應 `pipeline.stage_completed` 事件

---

### U0.3 Pipeline 事件 projector

**檔案**：`events/_project_reducers.py`

新增 `_project_pipeline` reducer 將 pipeline stage events 投影到 events.db。

但由於 Orchestrator 直接使用 `EventStore.append()`（不走 project checkpoint 機制），此 unit 實際上不需要新增 reducer——pipeline events 從 Orchestrator 端已直接寫入 events.db。

**實際只需要**：確認 events.db schema 的 `events` 表 column 可承載 pipeline event 的 payload 欄位（`payload_json` 是 TEXT，已足夠）。

**驗收**：
- Pipeline event 寫入後，可用 `EventStore.query("SELECT * FROM events WHERE kind LIKE 'pipeline.%'")` 查詢到

---

### U0.4 launchd 整合

**檔案**：`scripts/com.dex.bp-pipeline.plist`（新檔案）

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dex.bp-pipeline</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/dex/.local/share/backlink-publisher/venv/bin/python</string>
        <string>-m</string>
        <string>backlink_publisher.cli.pipeline_orchestrator</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/dex/YDEX/INPORTANT WORK/外链/backlink-publisher-69/backlink-publisher</string>
    <key>StartInterval</key>
    <integer>21600</integer>   <!-- 每 6 小時 -->
    <key>StandardOutPath</key>
    <string>/Users/dex/.cache/backlink-publisher/logs/pipeline-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/dex/.cache/backlink-publisher/logs/pipeline-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

**重要**：此 plist 與現有 `com.dex.bp-full-pipeline` **共存**。Orchestrator 逐步取代老 bash script，但在完全驗證前保留既有排程作為 fallback。

**驗收**：
- `launchctl load scripts/com.dex.bp-pipeline.plist` 成功
- `launchctl list | grep bp-pipeline` 顯示 process

---

## 3. Phase 1：循環閉合

### U1.1 Weights Write Mode 支援

**檔案**：`cli/weights.py`（修改）、`config/config.py`（可能新增 config 欄位）

在 `config.toml` 或環境變數中新增：

```toml
[orchestrator]
weights_write_mode = "preview"   # "preview" | "always" | "threshold"
```

`weights optimize` 行為變化：

- **preview**（預設）：Orchestrator 調用 `weights optimize --dry-run`，將 diff 輸出作為 `weights.preview` 事件寫入 events.db。不自動寫入。
- **always**：Orchestrator 調用 `weights optimize`（不傳 `--dry-run`），將 snapshot 作為 `weights.snapshot` 事件寫入。
- **threshold**：只有當權重變化幅度超過 N%（可配置）時才寫入。Orchestrator 先 dry-run 比較，決定是否再跑一次真實寫入。

Orchestrator 端的邏輯：

```python
def _run_weights_optimize(config) -> StageResult:
    write_mode = config.get("orchestrator", {}).get("weights_write_mode", "preview")
    
    if write_mode == "always":
        cmd = [sys.executable, "-m", "backlink_publisher.cli.weights", "optimize"]
    elif write_mode == "preview":
        cmd = [sys.executable, "-m", "backlink_publisher.cli.weights", "optimize", "--dry-run"]
    elif write_mode == "threshold":
        # 先 dry-run，比對變化
        dry_run = _run_weights_dry_run()
        if _weight_change_exceeds_threshold(dry_run, config):
            cmd = [sys.executable, "-m", "backlink_publisher.cli.weights", "optimize"]
        else:
            return StageResult(exit_code=0, summary={"write_skipped": "threshold_not_met"})
    
    result = subprocess.run(cmd, ...)
    # 記錄 snapshot 或 preview
    events.append(
        WEIGHTS_SNAPSHOT if write_mode == "always" else WEIGHTS_PREVIEW,
        {"diff_json": result.stdout or "{}"},
    )
```

**驗收**：
- `weights_write_mode = "preview"` → Orchestrator 跑 dry-run，events.db 有 `weights.preview`，權重不變
- `weights_write_mode = "always"` → Orchestrator 真實寫入，events.db 有 `weights.snapshot`
- 切換模式不需重啟 launchd——由 Orchestrator 每次啟動重新讀 config

---

### U1.2 Gap-Driven Pipeline 整合

**檔案**：`cli/pipeline_orchestrator.py`（U0.2 的完整實作）

已在 U0.2 涵蓋。關鍵流程設定：

1. Orchestrator 被 launchd 喚醒
2. 執行 `plan-gap` 檢測 gap
3. `plan-gap` stdout 非空 → pipeline 繼續（plan → validate → publish）
4. `plan-gap` stdout 空 → `pipeline.skipped` + exit 0

**publish-backlinks 的 gap-aware 調用**：publish stage 直接 pipe plan-backlinks 的 stdout 作為 publish-backlinks 的 stdin——保持現有 stdout JSONL pipeline 契約。

---

### U1.3 Optimization 閉合

**檔案**：`cli/pipeline_orchestrator.py`（新增 recheck + weights stage）

在 STAGES 清單末尾加入：

```python
StageDef("recheck-backlinks", _run_recheck, fatal=False),
StageDef("weights-collect",   _run_weights_collect, fatal=False),
StageDef("weights-optimize",  _run_weights_optimize, fatal=False),
```

**recheck stage**：使用 `--probe` flag（現有 recheck CLI 需要 `--probe` 才真正發起網路請求）：

```python
def _run_recheck(config) -> StageResult:
    cmd = [sys.executable, "-m", "backlink_publisher.cli.recheck_backlinks", "--probe"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return StageResult(exit_code=result.returncode, ...)
```

**weights collect stage**：

```python
def _run_weights_collect(config) -> StageResult:
    cmd = [sys.executable, "-m", "backlink_publisher.cli.weights", "collect"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return StageResult(exit_code=result.returncode, ...)
```

---

### U1.4 Circuit Breaker（Per-Platform）

**檔案**：`cli/pipeline_orchestrator.py`（新增 `_CircuitBreakerStore`）

Circuit breaker state 存放在 `~/.cache/backlink-publisher/circuit_state.json`（簡單 JSON 檔案，atomic write）。

```python
@dataclass
class CircuitState:
    platform: str
    consecutive_failures: int = 0
    tripped_at: str | None = None       # ISO timestamp
    half_open_at: str | None = None
    reset_at: str | None = None

class CircuitBreakerStore:
    def __init__(self, path: Path, events: EventStore):
        self.path = path
        self.events = events
        self._lock = threading.Lock()
    
    def record_failure(self, platform: str) -> bool:
        """記錄一次失敗。回傳 True 表示 breaker 剛 trip。
        
        threshold: 預設 5 次連續失敗後 trip。
        """
        with self._lock:
            state = self._load()
            entry = state.setdefault(platform, CircuitState(platform))
            entry.consecutive_failures += 1
            if entry.consecutive_failures >= 5 and not entry.tripped_at:
                entry.tripped_at = datetime.now(timezone.utc).isoformat()
                self.events.append("circuit.tripped", {
                    "platform": platform,
                    "consecutive_failures": entry.consecutive_failures,
                })
                self._save(state)
                return True  # just tripped
            self._save(state)
            return False
    
    def record_success(self, platform: str):
        """記錄一次成功。若 breaker 在 half-open 狀態，reset。
        
        Half-open 邏輯：
        - tripped 後等待 configurable cooldown（預設 24h）
        - cooldown 到期後 → half-open（允許一次發布）
        - 該次成功 → reset（清除 failures counter）
        - 該次失敗 → tripped 再度關閉（failure counter 延續而非從 0 開始）
        """
        with self._lock:
            state = self._load()
            entry = state.get(platform)
            if not entry:
                return
            if entry.half_open_at:
                # Half-open 狀態下的成功 → reset
                entry.consecutive_failures = 0
                entry.tripped_at = None
                entry.half_open_at = None
                entry.reset_at = datetime.now(timezone.utc).isoformat()
                self.events.append("circuit.reset", {"platform": platform})
            else:
                # 一般成功 → reset failure counter
                entry.consecutive_failures = 0
            self._save(state)
    
    def get_blocked_platforms(self) -> list[str]:
        """回傳當前被隔離的平台列表。
        
        Half-open transition：tripped 後超過 cooldown → 自動轉 half-open。
        """
        state = self._load()
        blocked = []
        now = datetime.now(timezone.utc)
        for platform, entry in state.items():
            if not entry.tripped_at:
                continue
            tripped = datetime.fromisoformat(entry.tripped_at)
            cooldown_hours = self._get_cooldown_hours(platform)
            if (now - tripped).total_seconds() > cooldown_hours * 3600:
                # Cooldown 到期 → half-open
                if not entry.half_open_at:
                    entry.half_open_at = now.isoformat()
                    self.events.append("circuit.half_open", {"platform": platform})
                    self._save(state)
                # Half-open: 不列入 blocked（允許一次發布嘗試）
                continue
            blocked.append(platform)
        return blocked
```

**threshold 可配置**（config.toml）：

```toml
[orchestrator.circuit_breaker]
error_threshold = 5       # 連續失敗次數
cooldown_hours = 24       # 隔離持續時間
```

**驗收**：
- 模擬 5 次 publish 失敗 → `circuit.tripped` 事件寫入 → `get_blocked_platforms()` 回傳該平台
- 24h 後（或 mock time）→ `circuit.half_open` → 平台不再被 blocked
- half-open 下的成功 publish → `circuit.reset` → failure counter 歸零
- half-open 下再度失敗 → 維持 tripped 狀態（counter 延續）

---

## 4. Phase 2：通知 + WebUI

### U2.1 Pipeline 完成摘要

**檔案**：`cli/pipeline_orchestrator.py`

pipeline 完成時輸出 JSONL 到 stdout + events.db：

```json
{"run_id": "20260611T040000-abcdef01", "started_at": "...", "completed_at": "...",
 "stages": [{"name": "plan-gap", "exit_code": 0, "duration_s": 1.2}, ...],
 "summary": {"has_gap": true, "seeds": 3, "published": 2, "failed": 0, "rechecked": 5,
              "weights_adjusted": 1},
 "circuit_events": [{"platform": "blogger", "event": "circuit.tripped", ...}]
}
```

此摘要也作為 `pipeline.completed` 事件的 payload 寫入 events.db。

---

### U2.2 WebUI `/ce:pipeline` 儀表板

**檔案**：
- `webui_app/routes/pipeline.py`（新檔案）
- `webui_app/templates/pipeline.html`（新檔案）
- 修改 `webui_app/__init__.py`（註冊 blueprint）
- 修改 `webui_app/templates/base.html`（導航欄新增「Pipeline」）

**路由**：

| Route | Method | 功能 |
|---|---|---|
| `/ce:pipeline` | GET | 儀表板主頁 |
| `/api/pipeline/status` | GET | 目前 pipeline state（idle/running/paused/degraded） |
| `/api/pipeline/history` | GET | 最近 N 次 pipeline 摘要 |
| `/api/pipeline/trigger` | POST | 手動觸發一次完整 pipeline |
| `/api/pipeline/pause` | POST | 暫停排程（完成當前 stage 後停止觸發） |
| `/api/pipeline/resume` | POST | 恢復排程 |

**儀表板元件**：

```
┌──────────────────────────────────────────────────┐
│  Pipeline State: ● Idle                          │
│  Last run: 2026-06-11 04:00 (12m 34s, 3 published)│
│  Next run: ~10:00 (auto, 6h interval)            │
│  [Trigger Now] [Pause]                            │
├──────────────────────────────────────────────────┤
│  Stage Summary                                    │
│  ✅ plan-gap (1.2s)    ✅ plan-backlinks (8.3s)   │
│  ✅ validate (2.1s)    ✅ publish (5m 12s, 3/3)   │
│  ✅ recheck (45.2s)    ✅ weights (3.1s)          │
├──────────────────────────────────────────────────┤
│  Circuit Breaker                                  │
│  ⚠ blogger — tripped (5 failures, 12h remaining) │
├──────────────────────────────────────────────────┤
│  Recent Runs                                      │
│  ...                                              │
└──────────────────────────────────────────────────┘
```

**資料來源**：events.db 查詢 `pipeline.*` 和 `circuit.*` 事件。

---

### U2.3 WebUI Banner 通知

**檔案**：
- 修改 `webui_app/templates/base.html`（Banner 區域）
- `webui_app/routes/pipeline.py`（新增 banner 資料 API）

Banner 顯示條件：

| 事件 | Banner 類型 | 內容 |
|---|---|---|
| `circuit.tripped` | ⚠ amber | "平台 {platform} 已被隔離 ({n} failures)，{remaining}h 後恢復" |
| `pipeline.failed` | 🔴 red | "Pipeline 在 {stage} 失敗 (exit {code})，請檢查 logs" |
| `pipeline.completed` with failures | 🟡 yellow | "Pipeline 完成，{n} 個 platform 發布失敗" |
| `pipeline.skipped` | 🟢 green（自動消失） | "Pipeline 跳過：無 gap" |

實作：在 `/ce:pipeline` 頁面的 API response 中同時回傳活躍警示列表。每個 alert 有 `type`（success/warning/danger/info）和 `message`。

---

### U2.4 Operator Override 按鈕

**檔案**：`webui_app/routes/pipeline.py`

**Pause 機制**：Orchestrator 啟動時檢查 `~/.cache/backlink-publisher/pipeline_paused` flag 檔案。WebUI 點擊 Pause 時建立此檔案；Orchestrator 看到 flag 存在 → 跳過本次執行。

```python
def _is_paused() -> bool:
    paused_flag = _cache_dir() / "pipeline_paused"
    return paused_flag.exists()

def _set_paused(paused: bool):
    flag = _cache_dir() / "pipeline_paused"
    if paused:
        flag.touch()
    else:
        flag.unlink(missing_ok=True)
```

**Trigger 機制**：WebUI 點擊 Trigger 時建立 `~/.cache/backlink-publisher/pipeline_trigger` flag 檔案，Orchestrator 下次啟動時（可能在 launchd 週期之前）看到此 flag → 立即執行完整 pipeline。

或者更直接：WebUI 透過 `subprocess` 或 `os.system` 直接執行一次 `pipeline-orchestrator`（類似 `launchctl start com.dex.bp-pipeline`）。

後者更簡單且與 launchd 整合更好：

```python
# webui_app/routes/pipeline.py
@bp.post("/api/pipeline/trigger")
@csrf_guard
def trigger_pipeline():
    import subprocess
    # 以 background process 觸發（不阻塞 HTTP request）
    subprocess.Popen(
        [sys.executable, "-m", "backlink_publisher.cli.pipeline_orchestrator"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"status": "triggered"}
```

---

## 5. 不做清單（與 requirements doc 一致）

| 不做 | 理由 |
|---|---|
| 重寫現有 CLI 元件 | Orchestrator 透過 subprocess + stdout JSONL 調用，不做 SDK refactor |
| 新增 platform adapter | 已有 20 註冊平台，本次不擴充 |
| 新資料庫或儲存 | 使用 events.db + 現有 stores |
| 取代現有 launchd plist | Orchestrator 與 `com.dex.bp-full-pipeline` 共存互為 fallback |
| Redesign WebUI | 僅新增 `/ce:pipeline` 頁面和 banner，不改動現有 UI |
| RAG/LLM 整合 | copilot Q&A 已有，本次不擴充 |
| 跨機器分散式調度 | 單機 process，同當前架構 |

---

## 6. 執行路線圖

```
Phase 0: Foundation (Core Orchestrator)
  U0.1  Pipeline 事件種類追加     S    -           events/kinds.py
  U0.2  PipelineOrchestrator 核心  L    U0.1       cli/pipeline_orchestrator.py
  U0.3  Pipeline 事件確認          S    U0.1       events/store.py
  U0.4  launchd plist              S    U0.2       scripts/com.dex.bp-pipeline.plist

Phase 1: Loop Closure
  U1.1  Weights write mode         M    U0.2       cli/weights.py, config
  U1.2  Gap-driven 整合            S    U0.2       cli/pipeline_orchestrator.py
  U1.3  Optimization 閉合          S    U1.1       cli/pipeline_orchestrator.py
  U1.4  Circuit Breaker            M    U0.2       cli/pipeline_orchestrator.py

Phase 2: Notification + WebUI
  U2.1  Pipeline 完成摘要          S    U0.2       cli/pipeline_orchestrator.py
  U2.2  WebUI /ce:pipeline         M    U0.3       webui_app/routes/pipeline.py
  U2.3  WebUI Banner               S    U2.2       webui_app/templates/base.html
  U2.4  Operator 按鈕              S    U2.2       webui_app/routes/pipeline.py

Phase 3: Verification + Deployment
  U3.1  Integration tests           M    U0.2-U2.4  tests/
  U3.2  End-to-end dry run          S    U3.1       manual
  U3.3  Promote to production       S    U3.2       launchd, docs update
```

規模代碼：S ≤ 半天，M ≤ 1 天，L ≤ 2 天

所有 Phase 0 units 可並行開發（U0.4 依賴 U0.2 的 CLI 入口存在，但 `.plist` 可預先撰寫）。

---

## 7. 檔案變更總覽

| 操作 | 檔案 |
|---|---|
| **新增** | `cli/pipeline_orchestrator.py` |
| **新增** | `scripts/com.dex.bp-pipeline.plist` |
| **新增** | `webui_app/routes/pipeline.py` |
| **新增** | `webui_app/templates/pipeline.html` |
| **修改** | `events/kinds.py` — 追加 9 個新 kind |
| **修改** | `webui_app/__init__.py` — 註冊 pipeline blueprint |
| **修改** | `webui_app/templates/base.html` — 導航欄 + banner 區域 |
| **修改** | `cli/weights.py` — 支援 config-driven write mode（preview/always/threshold） |
| **修改** | `pyproject.toml` — 無新增依賴（使用 stdlib 的 subprocess/threading/sqlite3） |

---

## 8. 風險與緩解

| 風險 | 概率 | 影響 | 緩解 |
|---|---|---|---|
| Orchestrator 與並行的 launchd bp-full-pipeline 衝突 | 中 | 低 | `flock`（文件鎖）確保同一時間只有一個 pipeline 實例 |
| Circuit breaker JSON 檔案 concurrent write | 低 | 低 | `threading.Lock` + atomic write（tempfile + rename） |
| Subprocess timeout 導致 zombie process | 低 | 中 | `subprocess.run(timeout=...)` + `Popen.communicate()` 確保 cleanup |
| Pipeline stage 輸出 JSONL 過大導致 memory OOM | 低 | 低 | `--max-rows` 已在 CLI 層限制；Orchestrator 傳遞同一限制 |
| WebUI trigger 啟動多個重疊 pipeline | 低 | 低 | 檢查 `_is_running()` flag 或 `flock` 
| 新增 event kinds 導致 CI 的 R8a gate 失敗 | 低 | 低 | 同步更新 `tests/` 中的 `KINDS` 預期值 assertion |

---

## 9. 驗收總標準

1. **所有現有測試保持綠色**：`pytest tests/ -x -q`
2. **新增事件種類通過 R8a gate**：`KINDS` 更新後 CI 不會因 unknown kind 失敗
3. **CLI 合約不變**：既有 bash pipeline（`run-full-pipeline.sh`）仍可獨立運作
4. **events.db 無 schema migration 需求**：pipeline events 使用現有 `events` table 的 `payload_json` TEXT column
5. **`/ce:pipeline` 顯示正確的 pipeline state**
6. **Circuit breaker 可 trip、half-open、reset**
7. **weights.write_mode 三種模式皆可運作**
8. **AE1–AE5 全數通過**（requirements doc 定義）

---

## 10. 執行紀律

1. 每個 U 編號是一個獨立 PR，可獨立 review / merge / revert
2. Phase 內任務按依賴順序；無依賴的可並行
3. 每個 U 攜帶測試：新功能 → 新測試；重構 → 現有測試保持綠色
4. 不綁運營變更：本計劃的 PR 不包含 seed / config / campaign 數據變更
5. Phase 0 完成後即可讓 PipelineOrchestrator 在 preview/write_mode=preview 模式運轉；Phase 1-2 逐步疊加

---

*本計畫從 Requirements Document（`docs/brainstorms/2026-06-11-pipeline-orchestrator-closed-loop-requirements.md`）出發，
將 backlink-publisher 從「半連結元件集合」升級為「全閉環自動化發布系統」。*
