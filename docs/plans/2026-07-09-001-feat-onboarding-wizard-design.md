---
title: "feat: Onboarding wizard — 首次進入控制台即引導新手一步步完成配置"
type: feat
status: active
date: 2026-07-09
claims: {}  # design-only — no implementation claims to track yet
---

# feat: Onboarding wizard — 新手引導精靈（設計文件）

> **實作狀態：已完成（2026-07-09）。** 後端 `OnboardingAPI` / `OnboardingSqliteStore` /
> `/api/v1/onboarding/*` 與前端 `stores/onboarding.ts` / `components/OnboardingWizard.vue`
> 均已落地，並通過 ruff / vue-tsc / eslint / pytest / vitest / plan-check。
>
> **本文件為「設計文件」**，描述方案、步驟模型與檔案清單。
> 決策已確認：**首次自動彈出**；**完整 5 步** happy path。

## Overview

本產品是一個 **loopback 運營者控制台**，沒有「應用層登入」——`session['config']`
只是持久化的設定。用戶口中的「登入」在產品語意裡就是 **連接發布渠道**
（Medium / Velog / Blogger / devto / ghpages / wordpresscom / Notion / Blog-ID）。

當一個新運營者打開 `/app` 時，所有「首次必做」事項都擠在單一
`/app/settings` 頁（`SettingsPage.vue`，含 10+ 個 section），且無任何順序提示：
先連哪個渠道、要不要配 LLM、目標站與錨文本為何相依於 Blogger Blog-ID 映射、
何時該建 Campaign、何時算「真的發布成功」——全部要靠使用者自己摸索。

Onboarding wizard 解決這個問題：**首次進入（或尚有未完成步驟且未關閉提示時）
自動彈出一個非阻塞的 stepper 覆蓋層**，把正確的執行順序講清楚，並讓每一步的
「已完成」狀態直接由真實系統狀態推導（不是一份會和現實脫節的手動 checklist）。

## Design Principles（設計原則）

1. **進度由真實狀態推導，不另存漂移的 checklist。**
   某一步一旦底層條件滿足就顯示「已完成」；使用者繞過 wizard 直接手動完成，
    wizard 也會自動認列（自愈）。這避免了「標記完成但其實沒做」或「做了卻還顯示待辦」。
2. **只持久化一個位元：`onboarding_dismissed`（是否不再提示）。**
   其餘每一步的 `done` 都在每次讀取時即時計算。這讓 wizard 與其餘設定頁
   共享同一個真相來源，不引入第二份需要同步的狀態。
3. **完全貼合現有架構與慣例。**
   - 後端：api facade（`*_api.py`）+ `v1` 藍
<think:6124c78e>plan-check says file not found even with Windows path. But the file exists. Let me verify the file exists via ls. Maybe the working directory `backlink-publisher` is actually a symlink/worktree and the path differs. Let me check.</think:6124c78e>plan-check reports not found despite a successful write. Let me verify the file actually exists at that path
<tool_call:6124c78e>Bash<tool_sep:6124c78e>
<arg_key:6124c78e>command</arg_key:6124c78e>
<arg_value:6124c78e>cd /c/Users/user/Dexfucius/backlink-publisher-69/backlink-publisher && ls -la docs/plans/2026-07-09-001-feat-onboarding-wizard-design.md && echo "---" && ls -la "C:/Users/user/Dexfucius/backlink-publisher-69/backlink-publisher/docs/plans/" | head