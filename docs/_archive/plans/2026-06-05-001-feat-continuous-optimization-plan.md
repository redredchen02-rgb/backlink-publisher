---
date: 2026-06-05
type: feat
topic: continuous-optimization
status: parked
origin: workspace-root (canonical-repo external)
archived_by: plan 2026-06-10-001 (docs consolidation)
notes: superseded by weights CLI subsystem
---

# Backlink Continuous Optimization Plan

> Rules engine + adaptive dispatch weights for closed-loop backlink publishing optimization.
> MVP: Rule 1 (canary drift → circuit-break), Rule 2 (recheck survival → boost). Phase 2: aggregated statistics thresholds (survival rate, dofollow rate).

## Problem Frame

Backlink Publisher's dispatch weights are **static constants** hardcoded in adapter modules. Publishing outcomes (link survival, dofollow status, account sandboxing) are detected by existing quality gates (`canary_targets`, `recheck-backlinks`, `link_attr_verifier`, `equity_ledger`) but **never fed back into dispatch decisions**.

- A platform whose links consistently die → still selected at the same rate
- A platform with 100% dofollow survival → never prioritized higher
- A platform whose account gets sandboxed (canary forward_path_drift) → still dispatched until operator manually disables

**Scale**: ~25+ platforms, 1-3 batches/day, 5-25 links/batch. Manual oversight doesn't scale.

## Scope Boundaries

**In scope:**
- `optimization_state.json` read/write module (persistent weight storage)
- `collect-signals` CLI — gather signals from recheck-backlinks, canary_targets, equity_ledger
- `optimize-weights` CLI — rules engine applying Rule 1 (canary drift) and Rule 2 (recheck survival)
- Weight Reader — modify `plan-backlinks` / `preferred_dispatch()` to read dynamic weights
- `show-optimization-state` CLI — print current state summary
- WebUI optimization status card (read-only view of weight changes)
- Full `--dry-run` support on all modifying commands

**Deferred to follow-up:**
- Rule 3 (aggregated statistical thresholds: survival rate < 30%, dofollow rate < 20%) — needs 1+ week of data accumulation
- WebUI manual weight override — read-only view ships first; override requires auth considerations
- Scheduled automatic optimization run (cron/launchd integration)
- Phase 2 dimensions: referral traffic, index rate, content quality

**Explicitly not in scope:**
- Modifying `publish-backlinks` core logic
- Modifying `recheck-backlinks`, `canary_targets`, `equity_ledger` behavior (signals consumed as-is)
- New background daemon process
- A/B testing framework

## Summary

Adds a closed-loop optimization layer alongside the existing publishing pipeline. Signal collector gathers outcome data from existing quality gates; rules engine applies configurable adjustments to dispatch weights; weight reader makes `plan-backlinks` aware of dynamic weights. All state lives in `~/.backlink-publisher/optimization_state.json`, separate from user config. `--dry-run` everywhere for safe preview.

---

## Key Technical Decisions

### Decision 1: optimization_state.json — separate from config.toml

**Context**: The original requirements specify this. Review confirms: config.toml expresses user intent; optimization_state expresses system-learned signals. Different lifecycles, different write patterns, different ownership.

**Choice**: Persistent state in `~/.backlink-publisher/optimization_state.json`. Read/write via a dedicated `OptimizationState` class. Config directory resolved via same `data_dir` lookup used by other stores.

**Trade-off**: Two files to manage instead of one. Justified because (a) config reads are pure reads, optimization_state is read-write, (b) avoiding config corruption from concurrent writes, (c) clear separation of user intent vs system inference.

### Decision 2: CLI-driven, not event-driven

**Context**: Could trigger optimization on every publish event. Or on a schedule.

**Choice**: CLI commands that the operator (or scheduler) runs at their chosen cadence. No in-process event hooks in the publishing pipeline. `optimize-weights` is designed to be safe to run at any time.

**Trade-off**: Weight updates are not real-time. Acceptable because (a) the feedback loop operates on hours/days timeframes, not seconds, (b) avoids coupling optimization logic into the hot publish path, (c) `--dry-run` lets operators preview before applying.

### Decision 3: Weight application at plan time, not registry time

**Context**: Dispatch weights are used in `preferred_dispatch()` during `plan-backlinks`. The question is when to override.

**Choice**: Override weights at plan-backlinks runtime by reading `optimization_state.json` in the planner, not by mutating the adapter registry. Registry's `dispatch_weight()` remains the static base truth.

**Trade-off**: Each `plan-backlinks` run reads the state file. Acceptable because (a) plan-backlinks is already multi-second, a JSON read is negligible, (b) the registry stays clean as the source of truth.

### Decision 4: Flat rule definitions in state JSON (no TOML/YAML DSL)

**Context**: The requirements deferred the "TOML vs YAML" decision.

**Choice**: Rule parameters live in `optimization_state.json` under `rules` key. Simple JSON object, no separate DSL file. Rule parameters are: `enabled`, `multiplier`, `max_strikes`, `cooldown_days`, `min_confirmations`, `max_cap`.

**Trade-off**: Changing rule parameters requires editing optimization_state.json (not a clean config file). Acceptable because (a) these are optimization params being tuned, not user-facing config, (b) adding a TOML/YAML parser adds dependency weight for 6 fields, (c) --dry-run shows what rules would do with current params.

---

## Implementation Units

### U1. OptimizationState — state persistence module

**Goal**: Read/write `optimization_state.json` with thread-safe access, schema validation, and fallback behavior.

**Requirements**: R1 (state file format), R4 (fallback to static weights)

**Dependencies**: None

**Files**:
- Create: `src/backlink_publisher/optimization/__init__.py` (package init, public API)
- Create: `src/backlink_publisher/optimization/state.py` (OptimizationState class)
- Create: `src/backlink_publisher/optimization/models.py` (dataclasses/types)
- Test: `tests/test_optimization_state.py`

**Approach**:
- `OptimizationState` class:
  ```python
  class OptimizationState:
      def __init__(self, data_dir: Path | None = None):
          # data_dir defaults to ~/.backlink-publisher/
          self.path = data_dir / "optimization_state.json"

      def load(self) -> dict:
          # Returns empty default state if file doesn't exist or is corrupt
          # Logs warning on corrupt state, returns defaults

      def save(self, state: dict) -> None:
          # Atomic write via tempfile + rename (same pattern as drafts_store)

      def get_weight(self, adapter_name: str, default: float) -> float:
          # Returns current_weight if exists, else default

      def set_weight(self, adapter_name: str, weight: float, rule: str, reason: str) -> None:
          # Updates current_weight, records adjustment entry

      def update_stats(self, adapter_name: str, stats_update: dict) -> None:
          # Merges stats_update into adapter's stats

      def get_rules_config(self) -> dict:
          # Returns rules section (or defaults)

      def reset(self) -> None:
          # Clears weights and adjustments back to defaults (keeps stats)

      def to_summary(self) -> dict:
          # Compact summary for show-optimization-state
  ```
- State schema (from requirements):
  ```json
  {
    "version": 1,
    "weights": { "platform_name": { "base": 1.0, "current": 0.5, "updated_at": "...", "adjustments": [...] } },
    "stats": { "platform_name": { "total_published": 12, "alive_count": 8, ... } },
    "rules": { "canary_drift": { "enabled": true, "multiplier": 0.5, ... } }
  }
  ```
- Default state: `{"version": 1, "weights": {}, "stats": {}, "rules": {}}`
- Thread safety: threading.Lock for write operations
- Corrupt file: try/except on json.load, log warning, return default state

**Patterns to follow**: `webui_store/drafts.py` — same JSON persistence + atomic write pattern. Config directory resolution follows existing `data_dir` / config path logic in the codebase.

**Test scenarios**:
- Load from non-existing file returns default state (not error)
- Save then load returns identical data (round-trip)
- get_weight returns current_weight when adapter exists, default when it doesn't
- set_weight creates entry if adapter doesn't exist, appends adjustment
- update_stats merges correctly without overwriting other fields
- Corrupt JSON file loads as default state with warning
- Concurrent reads don't block; concurrent writes are serialized
- to_summary returns compact view without full adjustment history
- reset clears weights but preserves stats

**Verification**: `pytest tests/test_optimization_state.py` green; manual: inspect created JSON file

---

### U2. Signal Collector — collect-signals CLI

**Goal**: Gather publishing outcome signals from existing quality gates and write aggregated stats into optimization_state.json.

**Requirements**: R2 (signal collection), R6 (dry-run support)

**Dependencies**: U1 (OptimizationState)

**Files**:
- Create: `src/backlink_publisher/optimization/collector.py` (signal collection logic)
- Create: `src/backlink_publisher/cli/collect_signals.py` (CLI entry point)
- Modify: `src/backlink_publisher/cli/__init__.py` (register command)
- Test: `tests/test_collect_signals.py`

**Approach**:
- Signal sources:
  1. **recheck-backlinks**: Parse recheck-backlinks output (JSONL stdout or exit code). Need recheck to output machine-readable format.
     - If `recheck-backlinks --json-summary` exists, parse that. Otherwise parse stdout.
  2. **canary_targets**: Read canary verdicts. Canary stores drift status — read directly from its state.
  3. **equity_ledger**: Read equity_ledger aggregated stats. If `equity_ledger --summary` exists, parse that.
- Architecture:
  ```python
  def collect_all_signals(state: OptimizationState, dry_run: bool = False) -> dict:
      """Run all collectors and return aggregated stats without writing."""
      signals = {}
      # 1. Collect from recheck
      recheck_data = collect_recheck_signals()
      signals["recheck"] = recheck_data
      # 2. Collect from canary
      canary_data = collect_canary_signals()
      signals["canary"] = canary_data
      # 3. Collect from equity_ledger
      equity_data = collect_equity_signals()
      signals["equity"] = equity_data
      # Merge into per-platform stats
      merged = merge_signals(signals)
      if not dry_run:
          for platform, stats in merged.items():
              state.update_stats(platform, stats)
          state.save(...)
      return {"raw": signals, "merged": merged}
  ```
- recheck signal extraction: Run `backlink-publisher recheck-backlinks` (or call its internal API) for pending rechecks. Parse verdict lines.
- canary signal extraction: Read canary targets drift state directly if stored as JSON, or run canary_targets command.
- CLI flags:
  - `--dry-run`: Print collected signals without writing
  - `--source recheck|canary|equity`: Collect from specific source only

**Important note on recheck-backlinks output**: If recheck-backlinks currently only outputs human-readable text, we need its data in machine-readable form. Approach (choose one during implementation):
  A. Add `--json-summary` flag to recheck-backlinks that outputs structured JSON
  B. Parse the existing stdout with regex
  C. Call recheck-backlinks' internal Python API directly

**Patterns to follow**: `cli/recheck_backlinks.py` CLI pattern (click commands), `cli/equity_ledger.py` structure.

**Test scenarios**:
- collect_signals with no data source returns empty merged dict
- collect_signals populates per-platform stats when signals present
- --dry-run prints collected signals, does NOT write state file
- --source recheck collects only recheck signals
- --source canary collects only canary signals
- All three sources combined merge correctly under per-platform keys
- Signal collector handles missing recheck-backlinks gracefully (no crash)
- Signal collector handles corrupt canary state gracefully

**Verification**: `pytest tests/test_collect_signals.py` green; manual: run `backlink-publisher collect-signals --dry-run` and inspect output

---

### U3. Rules Engine — optimize-weights CLI

**Goal**: Apply Rule 1 (canary drift → circuit-break) and Rule 2 (recheck survival → boost) to compute new dispatch weights.

**Requirements**: R3 (rules engine), R6 (dry-run), Rule 1, Rule 2 definitions

**Dependencies**: U1 (OptimizationState), U2 (Signal Collector: signals must exist in stats)

**Files**:
- Create: `src/backlink_publisher/optimization/rules.py` (rule definitions)
- Create: `src/backlink_publisher/cli/optimize_weights.py` (CLI entry point)
- Modify: `src/backlink_publisher/cli/__init__.py` (register command)
- Test: `tests/test_optimize_weights.py`

**Approach**:
- Rule interface:
  ```python
  @dataclass
  class RuleResult:
      platform: str
      rule_name: str
      old_weight: float
      new_weight: float
      multiplier: float
      reason: str
      applied: bool  # False if rule conditions not met

  class BaseRule(ABC):
      def __init__(self, config: dict):
          self.enabled = config.get("enabled", True)

      @abstractmethod
      def evaluate(self, platform: str, base_weight: float, stats: dict) -> RuleResult | None:
          ...
  ```
- Rule 1: CanaryDriftRule
  ```python
  class CanaryDriftRule(BaseRule):
      def evaluate(self, platform, base_weight, stats):
          drift_count = stats.get("drift_count", 0)
          if drift_count <= 0:
              return RuleResult(applied=False, ...)
          multiplier = self.config.get("multiplier", 0.5)
          max_strikes = self.config.get("max_strikes", 3)
          strikes = min(drift_count, max_strikes)
          new_weight = base_weight * (multiplier ** strikes)
          if strikes >= max_strikes:
              new_weight = 0.0
          return RuleResult(applied=True, ..., new_weight=new_weight)
  ```
- Rule 2: RecheckSurvivalRule
  ```python
  class RecheckSurvivalRule(BaseRule):
      def evaluate(self, platform, base_weight, stats):
          min_confirmations = self.config.get("min_confirmations", 2)
          alive = stats.get("alive_count", 0)
          dofollow = stats.get("dofollow_count", 0)
          if alive < min_confirmations or dofollow < min_confirmations:
              return RuleResult(applied=False, ...)
          multiplier = self.config.get("multiplier", 1.2)
          max_cap = self.config.get("max_cap", 3.0)
          new_weight = min(base_weight * multiplier, max_cap)
          return RuleResult(applied=True, ..., new_weight=new_weight)
  ```
- Engine:
  ```python
  def run_rules(state: OptimizationState, rules: list[str] | None = None, dry_run: bool = False) -> list[RuleResult]:
      results = []
      state_data = state.load()
      rule_instances = [CanaryDriftRule(...), RecheckSurvivalRule(...)]
      for platform, weight_data in state_data["weights"].items():
          base = weight_data["base"]
          stats = state_data["stats"].get(platform, {})
          for rule in rule_instances:
              if rules and rule.name not in rules:
                  continue
              result = rule.evaluate(platform, base, stats)
              if result and result.applied:
                  results.append(result)
                  if not dry_run:
                      state.set_weight(platform, result.new_weight, result.rule_name, result.reason)
      state.save(...)
      return results
  ```
- CLI flags:
  - `--dry-run`: Print adjustments without writing
  - `--rule canary_drift|recheck_survival`: Run specific rule only
  - `--all-platforms`: Include platforms not yet in state (process with base weight from registry)
- Output: Table format showing platform | rule | old_weight → new_weight | reason

**Patterns to follow**: `cli/recheck_backlinks.py` CLI patterns, click command structure.

**Test scenarios**:
- CanaryDriftRule with 0 drift: not applied (applied=False)
- CanaryDriftRule with 1 drift: weight *= multiplier (0.5)
- CanaryDriftRule with 3+ drifts: weight = 0.0 (circuit broken)
- CanaryDriftRule with rule disabled: not evaluated
- RecheckSurvivalRule with <2 confirmations: not applied
- RecheckSurvivalRule with >=2 confirmations: weight *= 1.2
- RecheckSurvivalRule capped at max_cap (3.0) even with many confirmations
- Both rules applied to same platform: canary drift takes precedence (applied first, survival can't override if weight=0)
- --dry-run produces same output but does NOT write to state file
- --rule canary_drift runs only drift rule
- Unknown platform (not in state) skipped unless --all-platforms
- Engine handles empty state gracefully

**Verification**: `pytest tests/test_optimize_weights.py` green; manual: `backlink-publisher optimize-weights --dry-run` with populated state

---

### U4. Weight Reader — plan-backlinks integration

**Goal**: Make `plan-backlinks` read dynamic weights from `optimization_state.json` and use them for platform dispatch ordering in `preferred_dispatch()`.

**Requirements**: R4 (weight reading), R1 (state format), backward compatibility

**Dependencies**: U1 (OptimizationState)

**Files**:
- Modify: `src/backlink_publisher/publishing/registry.py` (modify `preferred_dispatch()` to read dynamic weights)
- Test: `tests/test_registry_dynamic_weights.py`

**Approach**:
- In `preferred_dispatch()`:
  ```python
  def preferred_dispatch(adapter_names, ...):
      # Existing: sorted by dispatch_weight(adapter)
      # New:
      state = OptimizationState()
      state_data = state.load()
      def sort_key(name):
          static_weight = dispatch_weight(name)
          dynamic_weight = state.get_weight(name, static_weight)
          return -dynamic_weight  # descending
      return sorted(adapter_names, key=sort_key)
  ```
- If `optimization_state.json` doesn't exist or is corrupt → `state.load()` returns default → `get_weight()` returns default (= static weight) → behavior unchanged
- If adapter name not in state → use static weight (from `dispatch_weight()`)
- The change is in `preferred_dispatch()` only — `dispatch_weight()` itself stays static
- Log at INFO level when dynamic weight differs from base weight: `"platform=%s: dynamic_weight=%.1f (base=%.1f)"`
- No changes to publish-backlinks, spray-backlinks, or any other pipeline stage

**Patterns to follow**: Existing `preferred_dispatch()` in `publishing/registry.py` — minimal change, just the sort key logic.

**Test scenarios**:
- preferred_dispatch with no state file: same order as static weights
- preferred_dispatch with state file but platform not in state: same order as static weights
- preferred_dispatch with state file: platform with higher dynamic weight sorted first
- preferred_dispatch with state file where platform weight=0: sorted last (or excluded if weight=0)
- Corrupt state file: fallback to static weights (no crash)
- Static dispatch_weight() unchanged after dynamic weight changes
- INFO log message emitted when dynamic weight differs

**Verification**: `pytest tests/test_registry_dynamic_weights.py` green; manual: set a test weight in state, run plan-backlinks dry-run, verify platform order changed

---

### U5. show-optimization-state CLI

**Goal**: Print current optimization state summary for debugging and monitoring.

**Requirements**: R6 (observability)

**Dependencies**: U1 (OptimizationState)

**Files**:
- Create: `src/backlink_publisher/cli/show_optimization_state.py`
- Modify: `src/backlink_publisher/cli/__init__.py` (register command)
- Test: `tests/test_show_optimization_state.py`

**Approach**:
```python
@click.command("show-optimization-state")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@click.option("--platform", help="Filter to specific platform")
def cmd_show_optimization_state(as_json, platform):
    """Show current optimization state summary."""
    state = OptimizationState()
    data = state.load()
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    # Table format:
    # Platform     Base  Current  Delta  Adjustments  Stats(pub/alive/dofollow)
    # blogger      1.0   0.5      -50%   1             (12/8/6)
    # medium       1.0   1.2      +20%   1             (5/5/5)
    click.echo(tabulate_table(...))
```

**Patterns to follow**: `cli/equity_ledger.py` for table formatting style. `cli/recheck_backlinks.py` for CLI flags.

**Test scenarios**:
- Empty state prints header-only table
- State with platforms prints correct Base/Current/Delta columns
- --json flag outputs raw JSON
- --platform filter shows only matching platform
- Delta calculation correct: (current - base) / base * 100
- Platform with weight=0 shows "-100%" delta
- No state file exists: shows "No optimization state found" message (not crash)

**Verification**: `pytest tests/test_show_optimization_state.py` green; manual: run `backlink-publisher show-optimization-state` and inspect output

---

### U6. WebUI optimization status card

**Goal**: Display current optimization state on the WebUI dashboard as a read-only card.

**Requirements**: R5 (WebUI card)

**Dependencies**: U1 (OptimizationState), U5 (state data accessible)

**Files**:
- Modify: `webui_app/routes/__init__.py` or add route (serve state data to template)
- Modify: `webui_app/templates/index.html` (add Optimization Status card)
- Test: `tests/test_webui_routes.py` (add route test for state endpoint)

**Approach**:
- API endpoint: `GET /api/optimization/status` returns JSON:
  ```json
  {
      "platforms": [
          {"name": "blogger", "base": 1.0, "current": 0.5, "trend": "down",
           "adjustments": [{"rule": "canary_drift", "applied_at": "...", "reason": "..."}],
           "stats": {"published": 12, "alive": 8, "dofollow": 6}}
      ],
      "last_updated": "2026-06-05T10:30:00Z"
  }
  ```
- Frontend: Dashboard card showing:
  - Table with per-platform row: platform name, base→current weight (with up/down/flat arrow), trend badge
  - Color coding: green (weight increased), red (weight decreased), gray (unchanged)
  - Hover/click: tooltip showing adjustment reason and timestamp
  - Summary: "N platforms optimized, M at reduced weight"
  - Card title: "优化状态 (Optimization Status)"
- Data refresh: On page load (server-side rendered), no real-time polling needed for MVP
- If no state file: card shows "尚未运行优化" (Optimization not yet run)
- Read-only: no manual override controls in MVP

**Patterns to follow**: Existing dashboard cards in `index.html` — same pattern, same style, same data-loading approach.

**Test scenarios**:
- GET /api/optimization/status returns valid JSON with platform list
- GET /api/optimization/status with no state file returns empty platforms list
- Dashboard card renders correctly with platform data
- Trend arrow correct: current > base = up, current < base = down, equal = flat
- Tooltip shows adjustment data on hover
- Card shows "not yet run" state when no state exists

**Verification**: `pytest tests/test_webui_routes.py` green; manual: navigate to WebUI, verify card renders with correct data

---

### U7. E2E integration & edge case hardening

**Goal**: Ensure full pipeline works end-to-end: signal collection → rule application → weight reading → observable in WebUI.

**Requirements**: All requirements, backward compatibility, error handling

**Dependencies**: U1-U6

**Files**:
- Test: `tests/test_optimization_e2e.py`

**Approach**:
- E2E scenario test:
  1. Create mock state with known signals
  2. Run collect-signals (mock external commands)
  3. Run optimize-weights
  4. Verify state file updated correctly
  5. Verify preferred_dispatch returns correct order
  6. Verify WebUI endpoint returns correct data
- Edge case tests:
  - State file with all weights = 0 (everything circuit-broken) → preferred_dispatch returns original order (since all are 0, fallback to static)
  - State file with very old adjustments (days/weeks ago) → rules engine still works correctly
  - Run optimize-weights when no new signals exist → no changes applied (Rule 1: drift_count=0, Rule 2: confirmations < 2)
  - Consecutive optimize-weights runs: second run doesn't compound (weight already adjusted, re-application uses latest stats)
  - State file permissions error → graceful fallback with warning log

**Patterns to follow**: Existing test patterns in `tests/` directory.

**Test scenarios**:
- Full E2E: collect → optimize → dispatch order updated
- All-zeros state: dispatch falls back to static weights (no error)
- No-new-signals: optimize-weights makes no changes
- Consecutive runs without new signals: idempotent (weight stable)
- State file permission error: logged warning, static fallback

**Verification**: `pytest tests/test_optimization_e2e.py` green

---

## System-Wide Impact

| Area | Impact |
|---|---|
| **plan-backlinks CLI** | Platform sort order now reflects dynamic weights. Static `--platform` explicit selection unchanged |
| **publishing/registry.py** | `preferred_dispatch()` reads optimization_state.json. `dispatch_weight()` unchanged |
| **Adapter dispatch_weight()** | Unchanged — remains source of truth for base weight |
| **recheck-backlinks, canary_targets, equity_ledger** | Unchanged — signal collector consumes their output, doesn't modify behavior |
| **optimization_state.json** | New file in `~/.backlink-publisher/`. Separate from config.toml |
| **Existing tests** | All must remain green. Dynamic weight tests are additive |
| **WebUI** | New API endpoint + dashboard card. Existing pages unchanged |

---

## Deferred Questions

| Question | Reason for Deferral |
|---|---|
| Rule 3: aggregated statistical thresholds | Needs 1+ week of data to set meaningful thresholds |
| WebUI manual weight override | Requires auth (who can override?), needs design. Read-only view ships first |
| Canary cooldown auto-recovery (7d → 0.3) | Rule 1 currently sets weight=0. Auto-recovery can be added post-MVP |
| Per-platform cooldown period tuning | Default 7 days. May need per-platform config, but not enough data yet |
| Rule parameter UI (adjust multiplier/cap via WebUI) | Would need form + validation. Defer until operators request it |

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| optimization_state.json concurrent write from parallel CLI | Medium | Threading.Lock on module + atomic write. Document not to run optimize-weights concurrently |
| Corrupt state file from disk full / power loss | Low | Atomic write (tempfile + rename). Corrupt file → fallback to defaults with logged warning |
| Recheck-backlinks output not machine-parseable | Medium | Add --json-summary flag to recheck-backlinks as part of U2, or call internal API directly |
| Operator expects real-time weight updates | Medium | Document that optimize-weights is CLI-triggered. Post-MVP: cron integration |
| Weight=0 platforms excluded but operator wants them occasionally | Low | `--force` flag on publish-backlinks bypasses weight system (existing behavior) |

---

## Verification Plan

1. All existing tests green: `pytest tests/ -x -q`
2. New tests green for all 7 units
3. Manual E2E: collect-signals → optimize-weights → show-optimization-state → verify weights in plan-backlinks dry-run
4. Backward compatibility: plan-backlinks with no state file produces same output as before
5. `--dry-run` safety: run optimize-weights --dry-run, verify state file unchanged
6. WebUI smoke: navigate dashboard, verify card renders with correct data
7. Corrupt state: manually corrupt JSON, verify graceful fallback
