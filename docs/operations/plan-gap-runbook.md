# plan-gap Weekly Runbook

每週日 02:00 自動執行：`equity-ledger | plan-gap → logs/plan-gap-latest.json`

## 安裝排程

```bash
cp scripts/com.dex.bp-plan-gap.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.dex.bp-plan-gap.plist
```

## 移除排程

```bash
launchctl unload ~/Library/LaunchAgents/com.dex.bp-plan-gap.plist
rm ~/Library/LaunchAgents/com.dex.bp-plan-gap.plist
```

## 手動執行

```bash
bash scripts/run-plan-gap-weekly.sh
```

## 環境變數調整

| 變數 | 預設 | 說明 |
|------|------|------|
| `BP_PLAN_GAP_DESIRED` | `3` | 每個目標頁面期望的 dofollow 外鏈數量 |
| `BP_PLAN_GAP_LANGUAGE` | `zh-CN` | 種子語言（en / ko / ru / zh-CN） |

臨時調整：
```bash
BP_PLAN_GAP_DESIRED=5 BP_PLAN_GAP_LANGUAGE=en bash scripts/run-plan-gap-weekly.sh
```

或修改 plist 中的 `EnvironmentVariables` 後重新 load。

## 查看結果

```bash
# 最新 plan-gap seed 建議（JSONL）
cat logs/plan-gap-latest.json | head -20

# 計算補鏈候選數
wc -l logs/plan-gap-latest.json

# 查看排程執行日誌
tail -50 logs/plan-gap.log
```

## 驗收排程已安裝

```bash
launchctl list | grep bp-plan-gap
# 應出現 com.dex.bp-plan-gap，status 欄為 -（等待觸發）
```

## 注意事項

- `logs/plan-gap-latest.json` 寫入使用 tmp → rename 原子操作，讀取永遠是完整結果
- `logs/*.json` 已加入 `.gitignore`，不會被提交
- 輸出是 `plan-backlinks` 相容 seed JSONL，只生成建議，不發佈，安全
- 若需實際補鏈，人工審查後再執行 `cat logs/plan-gap-latest.json | plan-backlinks | validate-backlinks | publish-backlinks`
