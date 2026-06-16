# Mastodon Enforce Gate — Runbook

**狀態**: 已啟用（2026-06-16，Plan 2026-06-16-002 Unit 1）

## 背景

mastodon 是首個啟用 enforce 模式的發布頻道。Enforce gate 在以下情況攔截發布：
- channel health gate blocked（ban / selector-drift / 熔斷跳闸）
- circuit breaker open

其他頻道仍在 observe 模式（記錄 would_skip，但不實際攔截）。

## 啟用方式

以下兩個環境變數已寫入 `scripts/com.dex.bp-full-pipeline.plist` 和 `scripts/launcher.command`：

```
BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=enforce
BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS=mastodon
```

launchd plist 需 reload 才生效：
```bash
launchctl unload scripts/com.dex.bp-full-pipeline.plist
launchctl load   scripts/com.dex.bp-full-pipeline.plist
```

## 驗收方式

執行一次 dry-run publish（mastodon channel），確認 `skipped_policy` 事件出現：

```bash
# 1. 觸發一次 mastodon dry-run
BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=enforce \
BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS=mastodon \
  echo '{"url":"https://mastodon.social/@test","platform":"mastodon"}' \
  | PYTHONPATH=src .venv/bin/python -m backlink_publisher.cli.publish_backlinks --mode draft

# 2. 查詢 events.db 確認有記錄
PYTHONPATH=src .venv/bin/python - <<'EOF'
import sqlite3, json, pathlib
db = pathlib.Path("instance/events.db")
if not db.exists():
    print("events.db not found"); exit()
with sqlite3.connect(db) as conn:
    rows = conn.execute(
        "SELECT ts, kind, payload FROM events WHERE kind IN ('skipped_policy','would_skip_policy') "
        "AND json_extract(payload,'$.platform')='mastodon' ORDER BY ts DESC LIMIT 5"
    ).fetchall()
    for r in rows:
        print(r[0], r[1], json.loads(r[2]))
EOF
```

預期輸出：看到 `kind=skipped_policy platform=mastodon` 或 `would_skip_policy` 的事件。

若 mastodon channel 健康（無 ban / circuit open），發布照常進行（enforce 只攔不健康的 channel）。

## 回滾方式

移除 mastodon（或整個設定）並 reload plist：

```bash
# 快速回退到 observe
BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=observe
# 或移除 BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS 整行
```

在 `scripts/com.dex.bp-full-pipeline.plist` 和 `scripts/launcher.command` 中移除兩個 enforce key，並 reload plist。

## 新增第二個 enforce 頻道

確認頻道在 events.db 有足夠的 readiness 資料（`/ce:health` rollout 面板顯示 enforce-readiness 達標），再在 `ENFORCE_CHANNELS` 中加入，逗號分隔：

```
BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS=mastodon,<next_channel>
```
