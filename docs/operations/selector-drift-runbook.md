# selector-drift — operations runbook

Plan: `docs/plans/2026-06-15-007-feat-signal-freshness-plan.md`

`selector-drift` 靜態比對已知 CSS/XPath selector 清單與 live DOM，偵測平台 selector 漂移。
每日 05:00 自動執行（靜態 manifest 比對，無需 browser），攔截到漂移時寫 stderr + exit 非零。

## 排程安裝（Plan 2026-06-15-007 Unit 2）

plist 已在 `scripts/com.dex.bp-selector-drift.plist` committed。安裝步驟：

```bash
# 1. 從 canonical repo 複製 plist
cp scripts/com.dex.bp-selector-drift.plist ~/Library/LaunchAgents/com.dex.bp-selector-drift.plist

# 2. 載入（RunAtLoad=false，不立刻執行）
launchctl load ~/Library/LaunchAgents/com.dex.bp-selector-drift.plist

# 3. 確認已載入
launchctl list | grep bp-selector-drift
```

排程時間：每日 05:00（recheck 04:30 之後）。

回滾：
```bash
launchctl unload ~/Library/LaunchAgents/com.dex.bp-selector-drift.plist
rm ~/Library/LaunchAgents/com.dex.bp-selector-drift.plist
```

## 告警處理

selector-drift 告警（exit 非零）意味著某平台 DOM 結構改變，publish 時 selector 可能失效。

1. 查看 `logs/selector-drift-launchd.log` 確認漂移的 selector 和平台
2. 在對應 adapter 的 selector 設定中更新 CSS/XPath
3. 執行 `make selector-smoke`（需掛 Chrome）做人工 live smoke test 確認
4. Commit 更新後的 selector manifest

## attended live smoke（operator 手動，需 Chrome）

靜態 manifest 比對只是 Phase 1。完整 live smoke 需附掛的 Chrome：

```bash
make selector-smoke
```

此命令不在自動排程中，需 operator 手動執行（適合在平台有大改版後觸發）。
