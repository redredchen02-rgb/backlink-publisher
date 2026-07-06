# CLI Decomposition Reconciliation Audit — main vs origin/main

Date: 2026-07-06 · Reconcile plan: `docs/plans/2026-07-06-001-refactor-reconcile-github-gitlab-main-plan.md` (U3 產物)
Scope: `git merge-tree main origin/main` 實測的 **98 個 `src/backlink_publisher/cli/**` 衝突檔**,由三組並行唯讀稽核完成(平面 60 / admin+ops+plan+_bind 23 / publish+reporting+spray+publish_backlinks 15)。

## 跨檔裁決一:shim 機制(適用全部 35 個指令 shim)

**採 origin 的 `sys.modules[__name__] = _real` 別名機制,套在 local 的目的地佈局上**(兩側 35 個 shim 的目的地 100% 相同,可直接取 origin 版本)。實證:local 的 `import *` re-export 機制有三個缺陷——(1) `patch("cli.<old>.foo")` 落在 shim 副本上、真模組讀自己的 globals,patch 無效;(2) 底線名不被 `import *` 匯出,`patch` 私名直接失敗;(3) 無 `__main__` 分支,`python -m` 舊路徑死路。origin 機制三者皆解。此為 reconcile 計畫預決事項的確認。

## 跨檔裁決二:佈局政策

local 的 reorg 是半完成狀態(35 個指令入子目錄、23 個實作留平面);origin 全部 58 個入子目錄。**依計畫預設(local placement wins absent an origin fix):保留 local 的 23 個平面實作原樣**,不採 origin 的統一佈局——逐檔比對顯示 origin 的子目錄副本無任何 local 缺少的修復,且多檔含回退。

## 分類結果(98 檔全數)

### (a) keep local — 59 檔

**23 個平面完整實作([P] 佈局分歧,local 勝;origin 副本為舊快照或含回退):**
`_candidates` `_dedup_gate`(origin 放寬 except,回退)`_dedup_ops` `_footprint_baseline`(同)`_plan_check_format` `_plan_check_git` `_plan_check_schema` `_publish_cli` `_publish_helpers`(origin `.warn` + 放寬 except,回退)`_report_engine`(內容全同)`_resume`(origin 丟 log + 放寬 except,回退)`_seal_init` `click_track` `collect_signals` `comment` `footprint` `optimize_weights` `pipeline_orchestrator`(origin 丟 `encoding="utf-8"`,Windows 回退)`pr_opportunities`(origin 放寬 except)`referral_attribute` `resume` `runs` `validate_backlinks` + `__init__.py`(空白差異)

**22 個 admin/ops/plan 子目錄檔(佈局兩側全同,origin 差異全為機械 codemod;5 檔 local 嚴格更好):**
admin: `__init__` `audit_state` `bind_channel` `frw_login` `medium_login` `phase0_seal` `state_backup` `velog_login`
ops: `__init__` `cull_channels` `gate_probe` `health_check`(origin 加無用 `import stat`)`keepalive_status`(origin 放寬 except)`preflight_targets` `probe_citations` `probe_index` `probe_ranking` `recheck_backlinks`(**此 4 檔 origin 打回裸 `import fcntl`,Windows 直接壞;local 的 `_compat` shim 正確**)
plan: `__init__` `generate_backlink_text`(local 有複雜度拆解,origin 是 `# noqa: C901` монolith)`plan_check`(origin 多的 re-export 經查無測試依賴)`plan_gap`

**12 個 publish/reporting/spray 子目錄檔(佈局全同,差異為 import 排序/現代化語法,local 較新):**
publish: `__init__` `dispatch_backlinks` `publish_metrics`;publish_backlinks: `_engine`(local 拆解更徹底,符合 U5 CC≤10 目標)
reporting: `__init__` `channel_scorecard` `decay_alert` `equity_ledger` `recheck_overlay`
spray: `__init__` `canary_seed` `canary_targets`

### (b) 採 origin — 38 檔

**35 個 shim(機制升級,取 origin 版本;目的地與 local 全同):**
`audit_state` `bind_channel` `canary_seed` `canary_targets` `canonical_expand` `channel_scorecard` `cull_channels` `debt_report` `decay_alert` `dispatch_backlinks` `equity_ledger` `frw_login` `gate_probe` `generate_backlink_text` `health_check` `keepalive_reset_exhausted` `keepalive_run` `keepalive_status` `medium_login` `phase0_seal` `plan_check` `plan_gap` `platform_health` `preflight_targets` `probe_citations` `probe_index` `probe_ranking` `publish_metrics` `recheck_backlinks` `recheck_overlay` `report_anchors` `state_backup`(origin 版無 `main()` 分支,原樣接受)`velog_login` `verify_dofollow` `weights`

**3 個真 bug 修復移植(local 搬目錄後未更新位置相對常數/import,origin 修對;保留 local 的 encoding/typing 現代化):**
1. `cli/publish/report_anchors.py` — 兩處 lazy import `cli.report_engine` → `cli._report_engine`(缺底線 = ModuleNotFoundError;不採 origin 的相對 import,local 的 helper 留平面)
2. `cli/publish/verify_dofollow.py` — `_find_catalog_path` 內建目錄深度 `.parent.parent` → `.parent.parent.parent`(保留 local 的 `open(..., encoding="utf-8")`)
3. `cli/reporting/debt_report.py` — `_REPO_ROOT = parents[3]` → `parents[4]`(local 版永遠找不到 `debt_registry.toml`、恆報零債務;保留 local 的 `read_text(encoding="utf-8")`)

### (c) 連動待決 — 2 檔(預設 keep local,於 U4 解到對應模組時定案)

1. `cli/_validate_payload.py` — 兩側皆為 re-export shim 指向 `validate._payload`,但名單不同(origin +`_check_body_language_gate` / −`_resolve_banner_path`)。以 reconciled tree 中 `validate/_payload.py` 實際定義為準對齊名單。
2. `cli/_bind/channels/__init__.py` — local 從 `_util.constants` 取 `CHANNELS`+本地定義 `EVENTS`;origin 從 `_util.channels` 取兩者。隨 `_util/` 的解法連動:`_util` keep local(constants.py)→ 本檔 keep local 原樣。

## 統計

| 類別 | 數量 |
|---|---|
| (a) keep local | 59 |
| (b) 採 origin(35 shim 機制 + 3 修復移植) | 38 |
| (c) 連動待決(預設 keep local) | 2(計入上方 a/b 之外) |
| 缺漏 | 0(98/98 全數裁決) |

註:appendix 級發現——`probe-citations` 等指令「佈局分歧」的原始情報有一項不準確:兩側其實都以 `cli/ops/probe_citations.py` 為 canonical,分歧只在 shim 機制。
