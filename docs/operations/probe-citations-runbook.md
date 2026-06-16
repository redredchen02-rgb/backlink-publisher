# probe-citations — operations runbook

Plan: `docs/plans/2026-06-16-002-feat-comprehensive-optimization-roadmap-plan.md` (Unit 3)

`probe-citations` 每日探測 AI 引用狀況（Perplexity v1），將 `citation.observed` 事件寫入 events.db，供 `/ce:health` 面板展示（Phase 2 Unit 6）。

## 排程安裝

plist 已在 `scripts/com.dex.bp-citations.plist` committed。

```bash
# 1. 複製 plist
cp scripts/com.dex.bp-citations.plist ~/Library/LaunchAgents/com.dex.bp-citations.plist

# 2. 載入（RunAtLoad=false）
launchctl load ~/Library/LaunchAgents/com.dex.bp-citations.plist

# 3. 確認已載入
launchctl list | grep bp-citations
```

排程時間：每日 06:00。

## 配額設定

**安裝前確認 Perplexity v1 API 日配額**，再調整以下 EnvironmentVariables（plist 中）：

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `BP_CITATIONS_MAX_PAIRS` | 5 | 每次執行最多探測的 (target, query) 對數 |
| `BP_CITATIONS_COST_CAP` | 10 | 每次執行最多的 API 呼叫數 |

調整方式：
```bash
# 編輯 plist 中的 EnvironmentVariables，然後 reload
launchctl unload ~/Library/LaunchAgents/com.dex.bp-citations.plist
# 編輯 plist...
launchctl load ~/Library/LaunchAgents/com.dex.bp-citations.plist
```

## 手動執行

```bash
# dry-run（預設，無網路，看選取計畫）
PYTHONPATH=src .venv/bin/probe-citations

# 實際探測（5 對，cost-cap 10）
PYTHONPATH=src .venv/bin/probe-citations --probe --max-pairs 5 --cost-cap 10
```

## 驗收

探測後查 events.db 確認 `citation.observed` 事件存在：

```bash
sqlite3 instance/events.db \
  "SELECT ts, json_extract(payload,'$.target'), json_extract(payload,'$.cited')
   FROM events WHERE kind='citation.observed' ORDER BY ts DESC LIMIT 5"
```

## 回滾

```bash
launchctl unload ~/Library/LaunchAgents/com.dex.bp-citations.plist
rm ~/Library/LaunchAgents/com.dex.bp-citations.plist
```
