---
title: "refactor: Reconcile diverged GitHub/GitLab main histories"
type: refactor
status: completed
date: 2026-07-06
claims: {}
---

# refactor: Reconcile diverged GitHub/GitLab main histories

## Overview

Reconciled `origin/main` and `gitlab/main` histories which had independently diverged due to parallel work on two remotes. PRs #55, #56 landed. Branch protection enabled. GitLab exited scope per operator decision.

## Implementation Units

- [x] **U1: 分歧分析** — 確認 `origin/main` 與 `gitlab/main` 的 fork 範圍(~1061 檔 blob-level divergence)、識別獨立執行的 U5–U8 CLI 解耦重構。

- [x] **U2: 合併策略** — 決定以 `origin/main` 為正統基底,`gitlab/main` 的淨新增內容逐 commit cherry-pick/merge。

- [x] **U3: 衝突解決** — 三輪合併:webui 檔(批次操作/路由)、`spec.py`(OpenAPI 契約增量)、`cli/` shim 區。

- [x] **U4: 閘門驗證** — 全套件 pytest + ruff + mypy + import-linter + SLOC/CC 預算 + frontend typecheck/build 全綠。

- [x] **U5: 分支保護** — GitHub repo 啟用 branch protection rules(required PR review、status checks)。

- [x] **U6: GitLab 退出** — 確認 gitlab remote 無獨佔內容;記錄 GitLab 退出 scope 為 operator 決策;`.gitlab-ci.yml` 停用或標記 legacy。
